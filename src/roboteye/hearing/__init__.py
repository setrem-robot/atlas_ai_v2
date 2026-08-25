"""Escuta: microfone e reconhecimento de fala."""

from roboteye.hearing.base import HearingError, Ouvido
from roboteye.hearing.factory import create_ears
from roboteye.hearing.gatilho import dirigido_ao_robo

__all__ = ["HearingError", "Ouvido", "create_ears", "dirigido_ao_robo"]
