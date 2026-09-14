"""Construcao do motor de TTS a partir da configuracao."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from roboteye.loggingSetup import getLogger
from roboteye.speech.base import TTSEngine
from roboteye.speech.edgeEngine import EdgeEngine
from roboteye.speech.fallback import FallbackEngine
from roboteye.speech.kokoroEngine import KokoroEngine
from roboteye.speech.nullEngine import NullEngine
from roboteye.speech.piperEngine import PiperEngine

if TYPE_CHECKING:
    from roboteye.config import VoiceSettings

logger = getLogger(__name__)


def createTtsEngine(
    settings: VoiceSettings,
    *,
    onVoiceSwitch: Callable[[str], None] | None = None,
) -> TTSEngine:
    """Instancia o motor pedido na configuracao.

    Com `ROBOTEYE_TTS_BACKEND=auto` (o padrao), quem decide e a voz escolhida:
    cada uma declara no catalogo em qual motor roda.

    Uma voz online ganha automaticamente uma reserva offline, para que ficar sem
    internet troque o timbre em vez de calar o robo. Quem nao quiser isso pode
    desligar com `ROBOTEYE_VOICE_FALLBACK=off`.

    O motor e criado sem carregar modelos; use `warm_up()` para isso.
    """
    engine = build(settings)

    backupVoice = settings.fallbackVoice()
    if backupVoice is None:
        return engine

    logger.debug("voz %s tera %s como reserva offline", settings.voice, backupVoice)
    return FallbackEngine(
        engine,
        build(settings.forVoice(backupVoice)),
        onSwitch=onVoiceSwitch,
    )


def build(settings: VoiceSettings) -> TTSEngine:
    engine = settings.engine
    logger.debug("motor de voz: %s (voz %s)", engine, settings.voice)

    match engine:
        case "piper":
            return PiperEngine(settings)
        case "kokoro":
            return KokoroEngine(settings)
        case "edge":
            return EdgeEngine(settings)
        case "null":
            return NullEngine()
        case other:  # pragma: no cover - config.py ja valida
            raise ValueError(f"motor de TTS desconhecido: {other!r}")
