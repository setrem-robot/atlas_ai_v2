"""Motor de TTS local baseado no Kokoro (ONNX).

Um unico modelo de 325 MB que carrega dezenas de vozes, a 24 kHz. A voz sai
audivelmente melhor que a do Piper — em troca de umas oito vezes mais CPU
(RTF ~0,4 contra ~0,05). Numa maquina de mesa a diferenca nem aparece; num
Raspberry Pi, aparece bastante, e por isso o Piper continua sendo o padrao.

Usa `onnxruntime`, a mesma base do Piper: nao arrasta PyTorch para o projeto.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from roboteye.loggingSetup import getLogger
from roboteye.speech.base import AudioFormat, SpeechChunk, SpeechError

if TYPE_CHECKING:
    from roboteye.config import VoiceSettings

logger = getLogger(__name__)

_INSTALL_HINT = 'Kokoro nao esta instalado. Rode: pip install -e ".[kokoro]"'

#: O Kokoro trabalha com codigos de idioma proprios.
_LANGUAGES = {
    "pt": "pt-br",
    "en": "en-us",
    "es": "es",
    "fr": "fr-fr",
    "it": "it",
    "ja": "ja",
    "zh": "cmn",
    "hi": "hi",
}

DEFAULT_SPEAKER = "pf_dora"


class KokoroEngine:
    """Sintetiza voz com o modelo Kokoro local."""

    name = "kokoro"

    def __init__(self, settings: VoiceSettings) -> None:
        self.settings = settings
        self.kokoro: Any | None = None
        self.speaker = settings.speaker or DEFAULT_SPEAKER
        self.language = _LANGUAGES.get(settings.language, "en-us")

    # -- ciclo de vida -----------------------------------------------------
    def warmUp(self) -> None:
        """Carrega o modelo (~1,5 s). Feito no arranque para nao pagar na 1a fala."""
        if self.kokoro is not None:
            return

        try:
            from kokoroOnnx import Kokoro
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise SpeechError(_INSTALL_HINT) from exc

        modelPath = self.settings.modelPath
        voicesPath = self.settings.resolvedConfigPath()
        ensureFiles(modelPath, voicesPath)

        logger.info("carregando voz kokoro: %s", self.speaker)
        try:
            self.kokoro = Kokoro(str(modelPath), str(voicesPath))
        except Exception as exc:
            raise SpeechError(f"falha ao carregar o modelo Kokoro {modelPath}: {exc}") from exc

        available = set(self.kokoro.get_voices())
        if self.speaker not in available:
            raise SpeechError(
                f"voz {self.speaker!r} nao existe no pacote Kokoro "
                f"(ha {len(available)}, por exemplo: {', '.join(sorted(available)[:5])})"
            )

    def close(self) -> None:
        self.kokoro = None

    # -- sintese -----------------------------------------------------------
    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        if not text.strip():
            return

        self.warmUp()
        assert self.kokoro is not None  # garantido por warm_up

        try:
            samples, sampleRate = self.kokoro.create(
                text,
                voice=self.speaker,
                speed=1.0 / self.settings.lengthScale,
                lang=self.language,
            )
        except Exception as exc:
            raise SpeechError(f"falha na sintese Kokoro: {exc}") from exc

        yield SpeechChunk(
            audio=toPcm16(samples),
            format=AudioFormat(sampleRate=sampleRate, channels=1, sampleWidth=2),
        )


def toPcm16(samples: np.ndarray) -> bytes:
    """Converte as amostras de ponto flutuante (-1..1) para PCM de 16 bits."""
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


def ensureFiles(modelPath: Path, voicesPath: Path) -> None:
    if not modelPath.is_file():
        raise SpeechError(
            f"modelo Kokoro nao encontrado em {modelPath}. Baixe com: roboteye voice download dora"
        )
    if not voicesPath.is_file():
        raise SpeechError(
            f"pacote de vozes nao encontrado em {voicesPath}. "
            "Baixe com: roboteye voice download dora --force"
        )
