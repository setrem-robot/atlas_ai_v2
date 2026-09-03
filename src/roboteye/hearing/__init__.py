"""Escuta: microfone e reconhecimento de fala."""

from roboteye.hearing.base import AvisaAoFecharFrase, HearingError, Ouvido, Transcricao
from roboteye.hearing.factory import create_ears
from roboteye.hearing.gatilho import dirigido_ao_robo

__all__ = [
    "AvisaAoFecharFrase",
    "HearingError",
    "Ouvido",
    "Transcricao",
    "create_ears",
    "dirigido_ao_robo",
]
