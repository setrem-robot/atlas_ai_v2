"""Construcao do ouvido a partir da configuracao."""

from __future__ import annotations

from typing import TYPE_CHECKING

from roboteye.hearing.base import Ouvido

if TYPE_CHECKING:
    from roboteye.config import HearingSettings


def create_ears(settings: HearingSettings) -> Ouvido | None:
    """Instancia o ouvido pedido, ou None quando a escuta esta desligada."""
    if not settings.enabled or settings.backend == "null":
        return None

    match settings.backend:
        case "whisper":
            from roboteye.hearing.whisper_ears import WhisperEars
            from roboteye.speech.devices import resolver_entrada

            return WhisperEars(
                settings.model,
                device=resolver_entrada(settings.device),
                cpu_threads=settings.cpu_threads,
                model_dir=str(settings.model_path),
                # 0 quer dizer "meça a sala": o microfone entende `None`.
                limiar=settings.limiar or None,
            )
        case "vosk":
            from roboteye.hearing.vosk_ears import VoskEars
            from roboteye.speech.devices import resolver_entrada

            return VoskEars(
                settings.model_path / "vosk-pt",
                device=resolver_entrada(settings.device),
            )
        case other:  # pragma: no cover - config.py ja valida
            raise ValueError(f"backend de escuta desconhecido: {other!r}")
