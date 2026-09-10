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
from roboteye.speech.polish import AudioPolish, to_float

TAXA = 24000
FORMATO = AudioFormat(sample_rate=TAXA, channels=1, sample_width=2)


def tom(hz: float, segundos: float = 0.25, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(TAXA * segundos), dtype=np.float32) / TAXA
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def como_chunk(samples: np.ndarray) -> SpeechChunk:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()
    return SpeechChunk(audio=pcm, format=FORMATO)


def passar(polish: AudioPolish, *blocos: np.ndarray) -> np.ndarray:
    saida = list(polish.process(iter([como_chunk(b) for b in blocos])))
    pcm = b"".join(c.audio for c in saida)
    return to_float(pcm)


def energia(x: np.ndarray, acima_de: float) -> float:
    """Fração da energia do espectro acima de uma frequência."""
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / TAXA)
    return float(X[f > acima_de].sum() / max(X.sum(), 1e-9))


class TestOQueOFiltroFaz:
    def test_um_tom_agudo_e_atenuado(self) -> None:
        alto = passar(AudioPolish(treble_hz=6500, tail=0.0), tom(10000))
        assert np.abs(alto).max() < 0.1, "10 kHz passou quase inteiro"

    def test_a_voz_continua_passando(self) -> None:
        """Cortar agudo não pode abafar a fala: o que carrega a
        inteligibilidade mora bem abaixo do corte."""
        antes = tom(1000)
        depois = passar(AudioPolish(treble_hz=6500, tail=0.0), antes)
        assert np.abs(depois).max() == pytest.approx(np.abs(antes).max(), rel=0.1)

    def test_o_volume_geral_nao_muda(self) -> None:
        """Os coeficientes são normalizados. Sem isso, trocar o corte mudaria o
        volume junto, e a comparação entre vozes deixaria de valer."""
        fala = tom(300) + tom(700, amplitude=0.3)
        rms = lambda x: float(np.sqrt((x**2).mean()))  # noqa: E731
        assert rms(passar(AudioPolish(treble_hz=6500, tail=0.0), fala)) == pytest.approx(
            rms(fala), rel=0.05
        )

    def test_desligado_por_padrao_nao_toca_no_audio(self) -> None:
        agudo = tom(10000)
        assert np.abs(passar(AudioPolish(tail=0.0), agudo)).max() == pytest.approx(
            np.abs(agudo).max(), rel=0.05
        )

    def test_reproduz_a_medida_que_motivou_a_mudanca(self) -> None:
        """Ruído branco tem energia em toda a faixa; o corte tem de derrubar a
        parte alta na mesma ordem de grandeza vista no robô (15,4% -> 9,3%)."""
        ruido = np.random.default_rng(7).normal(0, 0.2, TAXA).astype(np.float32)
        antes = energia(ruido, 8000)
        depois = energia(passar(AudioPolish(treble_hz=6500, tail=0.0), ruido), 8000)
        assert depois < antes / 2, f"acima de 8 kHz: {antes:.3f} -> {depois:.3f}"


class TestONaoCriarCliques:
    """Um filtro sem memória produz um degrau em cada emenda de bloco.

    O Edge entrega a fala inteira num bloco só e não sofreria; o Piper entrega
    frase a frase, e é lá que o defeito apareceria — como um estalo entre as
    frases de uma mesma resposta.
    """

    def _maior_salto(self, x: np.ndarray) -> float:
        return float(np.abs(np.diff(x)).max())

    def test_a_emenda_entre_blocos_nao_estala(self) -> None:
        onda = tom(400, segundos=0.5)
        meio = len(onda) // 2

        inteiro = passar(AudioPolish(treble_hz=6500, tail=0.0), onda)
        partido = passar(AudioPolish(treble_hz=6500, tail=0.0), onda[:meio], onda[meio:])

        assert self._maior_salto(partido) == pytest.approx(self._maior_salto(inteiro), abs=0.02), (
            "a emenda entre os dois blocos criou um degrau"
        )

    def test_partir_em_muitos_blocos_da_o_mesmo_audio(self) -> None:
        onda = tom(400, segundos=0.3)
        pedacos = np.array_split(onda, 12)

        inteiro = passar(AudioPolish(treble_hz=6500, tail=0.0), onda)
        picado = passar(AudioPolish(treble_hz=6500, tail=0.0), *pedacos)

        assert len(picado) == len(inteiro)
        assert np.abs(picado - inteiro).max() < 0.01

    def test_duas_falas_nao_compartilham_memoria(self) -> None:
        """Se a cauda vazasse de uma fala para a próxima, o começo da segunda
        traria o fim da primeira — e o mesmo texto soaria diferente."""
        polish = AudioPolish(treble_hz=6500, tail=0.0)
        onda = tom(400)

        primeira = passar(polish, onda)
        segunda = passar(polish, onda)

        assert np.array_equal(primeira, segunda)


class TestOsCasosQueNaoDevemFiltrar:
    def test_corte_acima_de_nyquist_nao_faz_nada(self) -> None:
        """Não há o que cortar acima de metade da taxa — filtrar só gastaria CPU."""
        onda = tom(1000)
        assert np.array_equal(
            passar(AudioPolish(treble_hz=99000, tail=0.0), onda),
            passar(AudioPolish(tail=0.0), onda),
        )

    def test_bloco_vazio_nao_quebra(self) -> None:
        vazio = SpeechChunk(audio=b"", format=FORMATO)
        assert list(AudioPolish(treble_hz=6500, tail=0.0).process(iter([vazio]))) == [vazio]

    def test_o_comprimento_do_audio_e_preservado(self) -> None:
        """Um filtro que come amostras encurtaria a fala a cada bloco."""
        onda = tom(1000, segundos=0.2)
        assert len(passar(AudioPolish(treble_hz=6500, tail=0.0), onda)) == len(onda)
