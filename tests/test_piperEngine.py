"""Testes do motor Piper sem o modelo ONNX: a voz e um dublê."""

from __future__ import annotations

from dataclasses import dataclass

from roboteye.config import VoiceSettings
from roboteye.speech.piperEngine import PiperEngine

TAXA = 22050


@dataclass
class BlocoPiper:
    """O que `PiperVoice.synthesize` devolve: um bloco por frase."""

    audio_int16_bytes: bytes
    sample_rate: int = TAXA
    sample_channels: int = 1
    sample_width: int = 2


class VozFalsa:
    def __init__(self, frases: int) -> None:
        self.frases = frases

    def synthesize(self, text: str, syn_config: object = None):
        for _ in range(self.frases):
            yield BlocoPiper(audio_int16_bytes=b"\x01\x00" * 100)


def motor(frases: int, pausa: float) -> PiperEngine:
    engine = PiperEngine(VoiceSettings(sentencePause=pausa))
    engine.voice = VozFalsa(frases)
    return engine


def silencioso(audio: bytes) -> bool:
    return not any(audio)


class TestPausaEntreFrases:
    def testPausaSoEntreAsFrases(self) -> None:
        """Nada antes da primeira nem depois da ultima: o fim ja ganha respiro
        do acabamento, e uma pausa no comeco so atrasaria a fala."""
        blocos = list(motor(3, 0.25).synthesize("Um. Dois. Tres."))

        assert len(blocos) == 5
        assert [silencioso(b.audio) for b in blocos] == [False, True, False, True, False]

    def testDuracaoDaPausa(self) -> None:
        blocos = list(motor(2, 0.25).synthesize("Um. Dois."))

        amostras = len(blocos[1].audio) // 2
        assert amostras == int(0.25 * TAXA)

    def testFraseUnicaNaoGanhaPausa(self) -> None:
        assert len(list(motor(1, 0.25).synthesize("Uma so."))) == 1

    def testZeroDesliga(self) -> None:
        assert len(list(motor(3, 0.0).synthesize("Um. Dois. Tres."))) == 3
