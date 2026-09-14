"""Contratos da camada de voz.

Um motor de TTS transforma texto em uma sequencia de blocos PCM. Trabalhar com
blocos (em vez de um WAV inteiro) permite comecar a tocar o audio antes de a
sintese terminar, que e a maior fonte de latencia percebida.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class SpeechError(RuntimeError):
    """Falha ao sintetizar ou reproduzir voz."""


@dataclass(frozen=True, slots=True)
class AudioFormat:
    """Formato do PCM produzido por um motor."""

    sampleRate: int
    channels: int = 1
    sampleWidth: int = 2  # bytes por amostra (2 = int16)

    @property
    def bytesPerSecond(self) -> int:
        return self.sampleRate * self.channels * self.sampleWidth

    def durationOf(self, audio: bytes) -> float:
        """Duracao, em segundos, de um bloco de PCM neste formato."""
        return len(audio) / self.bytesPerSecond


@dataclass(frozen=True, slots=True)
class SpeechChunk:
    """Um bloco de audio PCM assinado, little-endian."""

    audio: bytes
    format: AudioFormat


@runtime_checkable
class TTSEngine(Protocol):
    """Motor de sintese de voz."""

    #: Nome curto para logs e para o comando `doctor`.
    name: str

    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        """Produz o audio de `text`, preferencialmente de forma incremental."""
        ...

    def warmUp(self) -> None:
        """Carrega modelos/conexoes antecipadamente. Deve ser idempotente."""
        ...

    def close(self) -> None:
        """Libera recursos. Deve ser idempotente."""
        ...
