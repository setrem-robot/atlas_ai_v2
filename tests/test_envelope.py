"""Testes do medidor de amplitude que liga a voz a face."""

# ruff: noqa: E402 - numpy e opcional; os imports vem depois do importorskip

from __future__ import annotations

import math
import time

import pytest

np = pytest.importorskip("numpy")

from roboteye.speech.base import AudioFormat
from roboteye.speech.envelope import (
    FRAME_SECONDS,
    MAX_QUEUE_SECONDS,
    SpeechEnvelope,
    rmsFrames,
)

FORMATO = AudioFormat(sampleRate=22050, channels=1, sampleWidth=2)


def tom(segundos: float, amplitude: float = 0.5, taxa: int = 22050) -> bytes:
    """PCM de 16 bits com uma senoide de amplitude conhecida."""
    n = int(taxa * segundos)
    t = np.arange(n, dtype=np.float32) / taxa
    onda = np.sin(2.0 * math.pi * 220.0 * t) * amplitude
    return (onda * 32767.0).astype("<i2").tobytes()


def silencio(segundos: float, taxa: int = 22050) -> bytes:
    return np.zeros(int(taxa * segundos), dtype="<i2").tobytes()


class TestMedicao:
    def testRmsDeUmaSenoideEAAmplitudeSobreRaizDeDois(self) -> None:
        quadros = rmsFrames(tom(0.5, amplitude=0.8), FORMATO)
        assert quadros.size == pytest.approx(0.5 / FRAME_SECONDS, abs=1)
        assert float(quadros.mean()) == pytest.approx(0.8 / math.sqrt(2), rel=0.05)

    def testSilencioMedeZero(self) -> None:
        assert float(rmsFrames(silencio(0.2), FORMATO).max()) == pytest.approx(0.0, abs=1e-6)

    def testEstereoEReduzidoAUmCanal(self) -> None:
        formato = AudioFormat(sampleRate=22050, channels=2, sampleWidth=2)
        mono = rmsFrames(tom(0.4), FORMATO)
        estereo = rmsFrames(np.repeat(np.frombuffer(tom(0.4), dtype="<i2"), 2).tobytes(), formato)
        assert estereo.size == pytest.approx(mono.size, abs=1)

    def testBlocoVazioNaoQuebra(self) -> None:
        assert rmsFrames(b"", FORMATO).size == 0


class TestEstados:
    def testSemFalaNaoHaMedicao(self) -> None:
        """`None` e diferente de zero: significa "ninguem esta medindo".

        A face precisa dessa distincao — em silencio o olho fica parado, mas sem
        medicao ele tem de cair no movimento sintetico, senao uma voz que nao
        produz PCM deixaria a face imovel enquanto fala.
        """
        assert SpeechEnvelope().level() is None

    def testFalandoSemAudioAindaReportaZero(self) -> None:
        envelope = SpeechEnvelope()
        envelope.begin()
        assert envelope.level() == 0.0

    def testEncerrarVoltaParaSemMedicao(self) -> None:
        envelope = SpeechEnvelope(latency=0.0)
        envelope.feed(tom(0.3), FORMATO)
        envelope.end()
        assert envelope.level() is None


class TestSincronizacao:
    def testONivelAcompanhaORelogio(self) -> None:
        """Um bloco alto seguido de silencio deve soar alto e depois calar."""
        envelope = SpeechEnvelope(latency=0.0)
        envelope.feed(tom(0.15, amplitude=0.9) + silencio(0.4), FORMATO)

        agora = envelope.level()
        assert agora is not None and agora > 0.5

        time.sleep(0.25)  # ja passou do trecho com som
        depois = envelope.level()
        assert depois is not None and depois < 0.1

    def testAudioAindaNaoTocadoNaoConta(self) -> None:
        """Com atraso de buffer, o som so comeca depois — o olho tem de esperar."""
        envelope = SpeechEnvelope(latency=0.5)
        envelope.feed(tom(0.3, amplitude=0.9), FORMATO)
        assert envelope.level() == 0.0

    def testBlocosSeguidosEntramNaFilaSemReancorar(self) -> None:
        """Dois blocos consecutivos tocam em sequencia, nao um por cima do outro.

        Se cada bloco reancorasse o relogio no instante da entrega, uma frase
        sintetizada mais rapido que o tempo real (o caso normal) teria o
        envelope inteiro comprimido no comeco, e a face pararia de se mexer no
        meio da fala.
        """
        envelope = SpeechEnvelope(latency=0.0)
        envelope.feed(tom(0.4, amplitude=0.9), FORMATO)
        envelope.feed(tom(0.4, amplitude=0.9), FORMATO)

        # Bem depois do primeiro bloco, mas dentro do segundo.
        time.sleep(0.5)
        nivel = envelope.level()
        assert nivel is not None and nivel > 0.5

    def testOQueJaTocouEDescartado(self) -> None:
        """A fila guarda o futuro, nao o passado.

        Audio ainda nao tocado precisa ficar — e o que a face vai animar daqui a
        pouco. O que ja soou nao serve para mais nada e sai fora, senao uma fala
        longa acumularia a conversa inteira.
        """
        envelope = SpeechEnvelope(latency=0.0)
        envelope.feed(tom(0.5), FORMATO)
        cheio = len(envelope.levels)

        time.sleep(0.3)
        envelope.feed(tom(0.05), FORMATO)  # a poda acontece a cada entrega

        assert len(envelope.levels) < cheio

    def testHaUmTetoParaAudioNaoTocado(self) -> None:
        """Rede de seguranca para destinos que nao bloqueiam na escrita.

        O freio normal e o proprio alto-falante: escrever bloqueia quando o
        buffer enche. Um destino silencioso nao freia nada, e sem teto a fila
        acompanharia a fala inteira.
        """
        envelope = SpeechEnvelope(latency=0.0)
        for _ in range(90):
            envelope.feed(tom(1.0), FORMATO)

        assert len(envelope.levels) <= MAX_QUEUE_SECONDS / FRAME_SECONDS + 1
