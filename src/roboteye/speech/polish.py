"""Acabamento do audio, entre a sintese e o alto-falante.

Um motor de TTS entrega a fala e mais nada: comeca no primeiro sample e termina
no ultimo, sem margem. Mandar isso direto para a placa produz tres incomodos que
somados sao boa parte do que se ouve como "audio estranho":

**Estalo nas pontas.** Se a forma de onda comeca num valor longe de zero, o
alto-falante recebe um degrau — e um degrau e um clique. Umas poucas
milissegundos de rampa em cada ponta resolvem, e sao curtas demais para se
ouvirem como fade.

**Frases coladas.** O texto e sintetizado frase a frase e cada uma vai para a
placa assim que fica pronta, entao a seguinte comeca no exato sample em que a
anterior acabou. Ninguem fala assim: falta o respiro que separa uma frase da
outra. Um rabicho de silencio no fim de cada uma devolve esse respiro.

**Estouro.** Ganho e uma coisa que se quer poder ajustar, mas multiplicar
amostras de 16 bits sem cuidado faz o sinal dar a volta e virar ruido. O
limitador aqui e o piso de seguranca disso.

**Agudo que a caixinha nao da conta.** As vozes nao ocupam a mesma faixa. Medida
a mesma frase neste robo, a energia acima de 8 kHz:

    francisca (online, 24 kHz)   15,4%
    dii (Piper, 22 kHz)           0,04%

Quatrocentas vezes mais brilho. Num alto-falante pequeno ligado a um dongle USB
barato isso nao sai como presenca: sai como chiado, e quem ouve descreve a voz
como "bugada". Nao e defeito de sintese nem de reamostragem — as duas foram
descartadas por medida — e por isso o conserto e aqui, no acabamento, e nao no
motor de voz. Desligado por padrao: numa caixa boa, cortar agudo so abafa.

Tudo neste modulo sao funcoes sobre bytes e sem thread. O filtro precisa de
memoria entre blocos (senao cada emenda vira um clique, que e justamente o que
este modulo existe para evitar), mas essa memoria vive na chamada de `process`,
nao no objeto: duas falas nunca compartilham estado.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from roboteye.speech.base import AudioFormat, SpeechChunk

#: Rampa de entrada. Curta: o suficiente para matar o degrau, nao o bastante
#: para comer o ataque da primeira silaba.
DEFAULT_FADE_IN = 0.006

#: Rampa de saida, um pouco mais longa — cortar o fim e mais audivel que o comeco.
DEFAULT_FADE_OUT = 0.012

#: Silencio no fim de cada frase. E o respiro entre uma e outra.
DEFAULT_TAIL = 0.14

#: Quantos coeficientes o filtro de agudos usa. Impar de proposito: mantem a
#: fase linear, entao o filtro atrasa todas as frequencias igualmente e nao
#: deforma a fala. 63 dao uma transicao de ~1,5 kHz, suave o bastante para nao
#: se ouvir como um corte, e baratos: `np.convolve` resolve uma fala de quatro
#: segundos em poucos milissegundos.
COEFICIENTES = 63


@dataclass(frozen=True, slots=True)
class AudioPolish:
    """Parametros do acabamento aplicado a cada fala."""

    fade_in: float = DEFAULT_FADE_IN
    fade_out: float = DEFAULT_FADE_OUT
    tail: float = DEFAULT_TAIL
    gain: float = 1.0
    #: Acima desta frequencia o audio e atenuado. 0 desliga. Ver o cabecalho.
    treble_hz: float = 0.0

    def process(self, chunks: Iterable[SpeechChunk]) -> Iterator[SpeechChunk]:
        """Aplica o acabamento a uma fala inteira, sem esperar por ela.

        As rampas precisam saber onde a fala comeca e onde termina, mas segurar
        todo o audio para descobrir isso jogaria fora a maior vantagem do
        projeto — comecar a tocar antes de a sintese acabar. A saida e olhar um
        bloco a frente: basta para saber se o bloco atual e o ultimo, e atrasa a
        reproducao em um bloco, nao na fala toda.
        """
        # Nasce e morre aqui: a memoria do filtro atravessa os blocos de uma
        # fala e nunca a fronteira entre duas.
        suave = _Suavizador(self.treble_hz)
        pending: SpeechChunk | None = None
        first = True

        for chunk in chunks:
            if pending is not None:
                yield self._polish(pending, fade_in=first, fade_out=False, suave=suave)
                first = False
            pending = chunk

        if pending is None:
            return

        yield self._polish(pending, fade_in=first, fade_out=True, suave=suave)
        if self.tail > 0.0:
            yield SpeechChunk(audio=silence(pending.format, self.tail), format=pending.format)

    def _polish(
        self, chunk: SpeechChunk, *, fade_in: bool, fade_out: bool, suave: _Suavizador
    ) -> SpeechChunk:
        samples = to_float(chunk.audio)
        if samples.size == 0:
            return chunk

        if self.gain != 1.0:
            samples = samples * self.gain

        # Antes das rampas: elas moldam as pontas do que vai sair, e filtrar
        # depois espalharia a rampa de volta para dentro do audio.
        samples = suave.aplicar(samples, chunk.format.sample_rate)

        rate = chunk.format.sample_rate * chunk.format.channels
        if fade_in:
            _ramp_in(samples, int(self.fade_in * rate))
        if fade_out:
            _ramp_out(samples, int(self.fade_out * rate))

        return SpeechChunk(audio=to_pcm16(samples), format=chunk.format)


class _Suavizador:
    """Tira o brilho que a caixinha do robo nao reproduz — ver o cabecalho.

    Guarda a cauda do bloco anterior porque um filtro reiniciado a cada bloco
    produz um degrau na emenda, e um degrau e um clique. E interno e de vida
    curta: um por fala, criado dentro de `process`.
    """

    def __init__(self, corte_hz: float) -> None:
        self._corte = corte_hz
        self._cauda: np.ndarray | None = None

    def aplicar(self, samples: np.ndarray, taxa: int) -> np.ndarray:
        if self._corte <= 0.0 or samples.size == 0:
            return samples
        # Acima de Nyquist nao ha o que cortar: filtrar seria so gastar CPU e
        # perder as pontas do bloco.
        if self._corte >= taxa / 2.0:
            return samples

        taps = _coeficientes(taxa, self._corte)
        sobra = taps.size - 1
        anterior = self._cauda if self._cauda is not None else np.zeros(sobra, dtype=np.float32)
        entrada = np.concatenate([anterior, samples])
        self._cauda = entrada[-sobra:].copy() if sobra else entrada[:0]
        # "valid" com a cauda na frente devolve exatamente `samples.size`
        # amostras, alinhadas: o atraso do filtro nao vira desencontro.
        return np.convolve(entrada, taps, mode="valid").astype(np.float32)


@lru_cache(maxsize=8)
def _coeficientes(taxa: int, corte_hz: float) -> np.ndarray:
    """Passa-baixa de fase linear, por janelamento de um seno cardinal.

    Em cache porque so ha um punhado de combinacoes de taxa e corte na vida do
    processo, e recalcular a cada bloco custaria mais que filtrar.
    """
    n = np.arange(COEFICIENTES, dtype=np.float64) - (COEFICIENTES - 1) / 2.0
    # `np.sinc` ja e normalizado (sinc(x) = sen(pi x)/(pi x)), entao o corte
    # entra como fracao da taxa de amostragem.
    taps = 2.0 * (corte_hz / taxa) * np.sinc(2.0 * (corte_hz / taxa) * n)
    taps *= np.hamming(COEFICIENTES)
    # Ganho unitario em corrente continua: sem isto o filtro mudaria o volume
    # junto com o brilho, e a comparacao entre vozes deixaria de valer.
    taps /= taps.sum()
    return taps.astype(np.float32)


# ---------------------------------------------------------------------------
# Conversao
# ---------------------------------------------------------------------------
def to_float(pcm: bytes) -> np.ndarray:
    """PCM de 16 bits para ponto flutuante em -1..1."""
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0


def to_pcm16(samples: np.ndarray) -> bytes:
    """Ponto flutuante de volta para PCM de 16 bits, com limite.

    O corte em -1..1 e o que impede um ganho alto de fazer o sinal dar a volta:
    sem ele, um pico estourado vira o valor mais negativo possivel, e isso se
    ouve como um estalo seco no meio da palavra.
    """
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def silence(audio_format: AudioFormat, seconds: float) -> bytes:
    """Um trecho mudo, no formato dado."""
    count = int(max(0.0, seconds) * audio_format.sample_rate) * audio_format.channels
    return np.zeros(count, dtype="<i2").tobytes()


# ---------------------------------------------------------------------------
# Rampas
# ---------------------------------------------------------------------------
def _ramp_in(samples: np.ndarray, length: int) -> None:
    length = min(length, samples.size)
    if length > 1:
        samples[:length] *= np.linspace(0.0, 1.0, length, dtype=np.float32)


def _ramp_out(samples: np.ndarray, length: int) -> None:
    length = min(length, samples.size)
    if length > 1:
        samples[-length:] *= np.linspace(1.0, 0.0, length, dtype=np.float32)
