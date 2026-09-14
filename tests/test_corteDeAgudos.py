"""O corte de agudos do acabamento.

Nasceu de uma queixa concreta — "a voz da francisca fica meio bugada" — e de
uma medida no robô, a mesma frase em cada voz:

    energia acima de 8 kHz    francisca (online)  15,4%
                              dii (Piper)          0,04%

Quatrocentas vezes mais brilho. Numa caixinha pequena isso sai como chiado.
Antes de chegar aqui foram descartados por medida: taxa de amostragem errada
(o sink reabre quando o formato muda), estouro (pico 0,604, e a `dii` é que
bate 1,000), decodificação em pedaços (o Edge baixa tudo antes) e resampler
ruim do ALSA (já está em `speexrate_medium`).

O risco que o conserto cria é o oposto do que ele resolve: um filtro reiniciado
a cada bloco produz um degrau na emenda — um clique — e este módulo existe
justamente para não haver cliques. É o que a maior parte destes testes cerca.
"""

from __future__ import annotations

import numpy as np
import pytest

from roboteye.speech.base import AudioFormat, SpeechChunk
from roboteye.speech.polish import AudioPolish, toFloat

TAXA = 24000
FORMATO = AudioFormat(sampleRate=TAXA, channels=1, sampleWidth=2)


def tom(hz: float, segundos: float = 0.25, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(TAXA * segundos), dtype=np.float32) / TAXA
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def comoChunk(samples: np.ndarray) -> SpeechChunk:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    return SpeechChunk(audio=pcm, format=FORMATO)


def passar(polish: AudioPolish, *blocos: np.ndarray) -> np.ndarray:
    saida = list(polish.process(iter([comoChunk(b) for b in blocos])))
    pcm = b"".join(c.audio for c in saida)
    return toFloat(pcm)


def energia(x: np.ndarray, acimaDe: float) -> float:
    """Fração da energia do espectro acima de uma frequência."""
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / TAXA)
    return float(X[f > acimaDe].sum() / max(X.sum(), 1e-9))


class TestOQueOFiltroFaz:
    def testUmTomAgudoEAtenuado(self) -> None:
        alto = passar(AudioPolish(trebleHz=6500, tail=0.0), tom(10000))
        assert np.abs(alto).max() < 0.1, "10 kHz passou quase inteiro"

    def testAVozContinuaPassando(self) -> None:
        """Cortar agudo não pode abafar a fala: o que carrega a
        inteligibilidade mora bem abaixo do corte."""
        antes = tom(1000)
        depois = passar(AudioPolish(trebleHz=6500, tail=0.0), antes)
        assert np.abs(depois).max() == pytest.approx(np.abs(antes).max(), rel=0.1)

    def testOVolumeGeralNaoMuda(self) -> None:
        """Os coeficientes são normalizados. Sem isso, trocar o corte mudaria o
        volume junto, e a comparação entre vozes deixaria de valer."""
        fala = tom(300) + tom(700, amplitude=0.3)
        rms = lambda x: float(np.sqrt((x**2).mean()))  # noqa: E731
        assert rms(passar(AudioPolish(trebleHz=6500, tail=0.0), fala)) == pytest.approx(
            rms(fala), rel=0.05
        )

    def testDesligadoPorPadraoNaoTocaNoAudio(self) -> None:
        agudo = tom(10000)
        assert np.abs(passar(AudioPolish(tail=0.0), agudo)).max() == pytest.approx(
            np.abs(agudo).max(), rel=0.05
        )

    def testReproduzAMedidaQueMotivouAMudanca(self) -> None:
        """Ruído branco tem energia em toda a faixa; o corte tem de derrubar a
        parte alta na mesma ordem de grandeza vista no robô (15,4% -> 9,3%)."""
        ruido = np.random.default_rng(7).normal(0, 0.2, TAXA).astype(np.float32)
        antes = energia(ruido, 8000)
        depois = energia(passar(AudioPolish(trebleHz=6500, tail=0.0), ruido), 8000)
        assert depois < antes / 2, f"acima de 8 kHz: {antes:.3f} -> {depois:.3f}"


class TestONaoCriarCliques:
    """Um filtro sem memória produz um degrau em cada emenda de bloco.

    O Edge entrega a fala inteira num bloco só e não sofreria; o Piper entrega
    frase a frase, e é lá que o defeito apareceria — como um estalo entre as
    frases de uma mesma resposta.
    """

    def maiorSalto(self, x: np.ndarray) -> float:
        return float(np.abs(np.diff(x)).max())

    def testAEmendaEntreBlocosNaoEstala(self) -> None:
        onda = tom(400, segundos=0.5)
        meio = len(onda) // 2

        inteiro = passar(AudioPolish(trebleHz=6500, tail=0.0), onda)
        partido = passar(AudioPolish(trebleHz=6500, tail=0.0), onda[:meio], onda[meio:])

        assert self.maiorSalto(partido) == pytest.approx(self.maiorSalto(inteiro), abs=0.02), (
            "a emenda entre os dois blocos criou um degrau"
        )

    def testPartirEmMuitosBlocosDaOMesmoAudio(self) -> None:
        onda = tom(400, segundos=0.3)
        pedacos = np.array_split(onda, 12)

        inteiro = passar(AudioPolish(trebleHz=6500, tail=0.0), onda)
        picado = passar(AudioPolish(trebleHz=6500, tail=0.0), *pedacos)

        assert len(picado) == len(inteiro)
        assert np.abs(picado - inteiro).max() < 0.01

    def testDuasFalasNaoCompartilhamMemoria(self) -> None:
        """Se a cauda vazasse de uma fala para a próxima, o começo da segunda
        traria o fim da primeira — e o mesmo texto soaria diferente."""
        polish = AudioPolish(trebleHz=6500, tail=0.0)
        onda = tom(400)

        primeira = passar(polish, onda)
        segunda = passar(polish, onda)

        assert np.array_equal(primeira, segunda)


class TestOsCasosQueNaoDevemFiltrar:
    def testCorteAcimaDeNyquistNaoFazNada(self) -> None:
        """Não há o que cortar acima de metade da taxa — filtrar só gastaria CPU."""
        onda = tom(1000)
        assert np.array_equal(
            passar(AudioPolish(trebleHz=99000, tail=0.0), onda),
            passar(AudioPolish(tail=0.0), onda),
        )

    def testBlocoVazioNaoQuebra(self) -> None:
        vazio = SpeechChunk(audio=b"", format=FORMATO)
        assert list(AudioPolish(trebleHz=6500, tail=0.0).process(iter([vazio]))) == [vazio]

    def testOComprimentoDoAudioEPreservado(self) -> None:
        """Um filtro que come amostras encurtaria a fala a cada bloco."""
        onda = tom(1000, segundos=0.2)
        assert len(passar(AudioPolish(trebleHz=6500, tail=0.0), onda)) == len(onda)
