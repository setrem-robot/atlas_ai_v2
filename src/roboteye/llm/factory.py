"""Construcao do cliente de LLM a partir da configuracao."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from roboteye.llm.base import LLMClient
from roboteye.llm.echo import EchoClient
from roboteye.llm.fallback import FallbackLLMClient
from roboteye.llm.ollama import OllamaClient

if TYPE_CHECKING:
    from roboteye.config import LLMSettings


def createLlmClient(settings: LLMSettings) -> LLMClient:
    """Instancia o cliente pedido na configuracao."""
    match settings.backend:
        case "ollama":
            primary = OllamaClient(settings)
            backup = backupFor(settings)
            if backup is None:
                return primary
            return FallbackLLMClient(
                primary,
                backup,
                probeInterval=settings.probeInterval,
                keepAliveOcioso=settings.fallbackKeepAlive,
            )
        case "echo":
            return EchoClient()
        case other:  # pragma: no cover - config.py ja valida
            raise ValueError(f"backend de LLM desconhecido: {other!r}")


def backupFor(settings: LLMSettings) -> LLMClient | None:
    """O Ollama de reserva, se a configuracao pedir um diferente do principal.

    Apontar os dois para o mesmo lugar nao daria reserva nenhuma — so uma
    segunda tentativa contra a mesma maquina que acabou de nao responder.
    """
    if not settings.fallbackHost or settings.fallbackHost == settings.host:
        return None
    return OllamaClient(
        replace(
            settings,
            host=settings.fallbackHost,
            model=settings.fallbackModel or settings.model,
        ),
        # O reserva nasce ocioso: enquanto a IA de rede responde, ele nao deve
        # segurar memoria nenhuma do Pi. Quem o promove e o `FallbackLLMClient`,
        # no instante em que a rede cai.
        keepAlive=settings.fallbackKeepAlive,
    )
