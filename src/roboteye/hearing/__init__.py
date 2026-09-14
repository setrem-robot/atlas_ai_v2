"""Escuta: microfone e reconhecimento de fala."""

from roboteye.hearing.base import AvisaAoFecharFrase, HearingError, Ouvido, Transcricao
from roboteye.hearing.factory import createEars
from roboteye.hearing.gatilho import dirigidoAoRobo

__all__ = [
    "AvisaAoFecharFrase",
    "HearingError",
    "Ouvido",
    "Transcricao",
    "createEars",
    "dirigidoAoRobo",
]
