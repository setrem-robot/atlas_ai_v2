"""Testes da transcricao do Whisper — a parte que nao precisa do modelo real.

O `faster-whisper` nao entra aqui: um modelo falso devolve segmentos com as
mesmas propriedades que os de verdade (`text`, `avg_logprob`, `no_speech_prob`),
e o que se verifica e como a `WhisperEars` os resume numa `Transcricao`.
"""

from __future__ import annotations

import pytest

from roboteye.hearing.base import Transcricao
from roboteye.hearing.whisper_ears import WhisperEars


class _Segmento:
    def __init__(self, text: str, avg_logprob: float, no_speech_prob: float) -> None:
        self.text = text
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


class _ModeloFalso:
    def transcribe(self, audio, **_kwargs):
        segmentos = [
            _Segmento(" Atlas,", avg_logprob=-0.2, no_speech_prob=0.01),
            _Segmento(" quanto e dois?", avg_logprob=-0.4, no_speech_prob=0.05),
        ]
        return iter(segmentos), object()


class TestTranscrever:
    def test_junta_texto_e_resume_as_medidas(self) -> None:
        ears = WhisperEars("tiny")
        ears._modelo = _ModeloFalso()

        t = ears._transcrever(audio=b"")

        assert isinstance(t, Transcricao)
        assert t.texto == "Atlas, quanto e dois?"
        # Confianca e a media dos log-probs; silencio e o maior dos trechos.
        assert t.confianca == pytest.approx((-0.2 + -0.4) / 2)
        assert t.sem_fala == pytest.approx(0.05)
        assert t.ms >= 0.0

    def test_sem_modelo_devolve_vazio(self) -> None:
        ears = WhisperEars("tiny")
        ears._modelo = None

        t = ears._transcrever(audio=b"")

        assert t.texto == ""
        assert t.confianca is None
