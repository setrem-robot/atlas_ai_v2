"""Motor de TTS local baseado no Piper (ONNX).

E o motor padrao: roda inteiramente offline e sintetiza muito mais rapido que o
tempo real mesmo em CPU modesta, o que elimina a latencia de rede da API remota.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from roboteye.loggingSetup import getLogger
from roboteye.speech.base import AudioFormat, SpeechChunk, SpeechError

if TYPE_CHECKING:
    from roboteye.config import VoiceSettings

logger = getLogger(__name__)

_INSTALL_HINT = (
    'Piper nao esta instalado. Rode: pip install -e ".[tts]" (ou pip install piper-tts sounddevice)'
)


class PiperEngine:
    """Sintetiza voz com um modelo Piper local."""

    name = "piper"

    def __init__(self, settings: VoiceSettings) -> None:
        self.settings = settings
        self.voice: Any | None = None
        self.synConfig: Any | None = None

    # -- ciclo de vida -----------------------------------------------------
    def warmUp(self) -> None:
        """Carrega o modelo ONNX (~2 s). Chamado no arranque para nao pagar isso na 1a fala."""
        if self.voice is not None:
            return

        try:
            from piper import PiperVoice, SynthesisConfig
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise SpeechError(_INSTALL_HINT) from exc

        modelPath = self.settings.modelPath
        configPath = self.settings.resolvedConfigPath()
        ensureModelFiles(modelPath, configPath)

        logger.info("carregando voz: %s", modelPath.name)
        try:
            self.voice = PiperVoice.load(modelPath, configPath=configPath)
        except Exception as exc:
            raise SpeechError(f"falha ao carregar o modelo de voz {modelPath}: {exc}") from exc

        self.synConfig = SynthesisConfig(
            length_scale=self.settings.lengthScale,
            noise_scale=self.settings.noiseScale,
            noise_w_scale=self.settings.noiseW,
        )
        logger.debug("voz carregada")

    def close(self) -> None:
        self.voice = None
        self.synConfig = None

    # -- sintese -----------------------------------------------------------
    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        if not text.strip():
            return

        self.warmUp()
        assert self.voice is not None  # garantido por warm_up

        try:
            for chunk in self.voice.synthesize(text, syn_config=self.synConfig):
                yield SpeechChunk(
                    audio=chunk.audio_int16_bytes,
                    format=AudioFormat(
                        sampleRate=chunk.sampleRate,
                        channels=chunk.sample_channels,
                        sampleWidth=chunk.sampleWidth,
                    ),
                )
        except Exception as exc:
            raise SpeechError(f"falha na sintese: {exc}") from exc


def ensureModelFiles(modelPath: Path, configPath: Path) -> None:
    if not modelPath.is_file():
        raise SpeechError(
            f"modelo de voz nao encontrado em {modelPath}. Baixe com: roboteye voice download"
        )
    if not configPath.is_file():
        raise SpeechError(
            f"configuracao do modelo nao encontrada em {configPath}. "
            "O Piper precisa do arquivo .onnx.json ao lado do modelo."
        )
