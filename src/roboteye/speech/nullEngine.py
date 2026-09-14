"""Motor de TTS silencioso.

Util em testes, em servidores sem placa de som e quando se quer apenas ler as
respostas no terminal.
"""

from __future__ import annotations

from collections.abc import Iterator

from roboteye.loggingSetup import getLogger
from roboteye.speech.base import SpeechChunk

logger = getLogger(__name__)


class NullEngine:
    """Descarta o texto em vez de sintetiza-lo."""

    name = "null"

    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        logger.debug("TTS desativado, texto nao falado: %s", text)
        return iter(())

    def warmUp(self) -> None:
        return None

    def close(self) -> None:
        return None
