"""Sintese de voz: motores de TTS, saida de audio e o locutor assincrono."""

from roboteye.speech.base import AudioFormat, SpeechChunk, TTSEngine
from roboteye.speech.factory import createTtsEngine
from roboteye.speech.speaker import Speaker

__all__ = ["AudioFormat", "Speaker", "SpeechChunk", "TTSEngine", "createTtsEngine"]
