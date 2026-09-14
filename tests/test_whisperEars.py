"""Testes da transcricao do Whisper — a parte que nao precisa do modelo real.

O `faster-whisper` nao entra aqui: um modelo falso devolve segmentos com as
mesmas propriedades que os de verdade (`text`, `avg_logprob`, `no_speech_prob`),
e o que se verifica e como a `WhisperEars` os resume numa `Transcricao`.
"""

from __future__ import annotations

import pytest

from roboteye.hearing.base import Transcricao
from roboteye.hearing.whisperEars import WhisperEars


class Segmento:
    def __init__(self, text: str, avg_logprob: float, no_speech_prob: float) -> None:
        self.text = text
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


class ModeloFalso:
    def transcribe(self, audio, **kwargs):
        segmentos = [
            Segmento(" Atlas,", avg_logprob=-0.2, no_speech_prob=0.01),
            Segmento(" quanto e dois?", avg_logprob=-0.4, no_speech_prob=0.05),
        ]
        return iter(segmentos), object()


class TestTranscrever:
    def testJuntaTextoEResumeAsMedidas(self) -> None:
        ears = WhisperEars("tiny")
        ears.modelo = ModeloFalso()

        t = ears.transcrever(audio=b"")

        assert isinstance(t, Transcricao)
        assert t.texto == "Atlas, quanto e dois?"
        # Confianca e a media dos log-probs; silencio e o maior dos trechos.
        assert t.confianca == pytest.approx((-0.2 + -0.4) / 2)
        assert t.semFala == pytest.approx(0.05)
        assert t.ms >= 0.0

    def testSemModeloDevolveVazio(self) -> None:
        ears = WhisperEars("tiny")
        ears.modelo = None

        t = ears.transcrever(audio=b"")

        assert t.texto == ""
        assert t.confianca is None
