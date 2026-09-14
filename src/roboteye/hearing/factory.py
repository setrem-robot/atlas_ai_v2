"""Construcao do ouvido a partir da configuracao."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roboteye.hearing.base import Ouvido

if TYPE_CHECKING:
    from roboteye.config import HearingSettings


def createEars(settings: HearingSettings) -> Ouvido | None:
    """Instancia o ouvido pedido, ou None quando a escuta esta desligada."""
    if not settings.enabled or settings.backend == "null":
        return None

    match settings.backend:
        case "whisper":
            from roboteye.hearing.whisperEars import WhisperEars
            from roboteye.speech.devices import resolverEntrada

            return WhisperEars(
                settings.model,
                device=resolverEntrada(settings.device),
                cpuThreads=settings.cpuThreads,
                modelDir=str(settings.modelPath),
                # 0 quer dizer "meça a sala": o microfone entende `None`.
                limiar=settings.limiar or None,
            )
        case "vosk":
            from roboteye.hearing.voskEars import VoskEars
            from roboteye.speech.devices import resolverEntrada

            return VoskEars(
                settings.modelPath / settings.voskModel,
                device=resolverEntrada(settings.device),
            )
        case other:  # pragma: no cover - config.py ja valida
            raise ValueError(f"backend de escuta desconhecido: {other!r}")
