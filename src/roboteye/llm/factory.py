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


def create_llm_client(settings: LLMSettings) -> LLMClient:
    """Instancia o cliente pedido na configuracao."""
    match settings.backend:
        case "ollama":
            primary = OllamaClient(settings)
            backup = _backup_for(settings)
            if backup is None:
                return primary
            return FallbackLLMClient(primary, backup, probe_interval=settings.probe_interval)
        case "echo":
            return EchoClient()
        case other:  # pragma: no cover - config.py ja valida
            raise ValueError(f"backend de LLM desconhecido: {other!r}")


def _backup_for(settings: LLMSettings) -> LLMClient | None:
    """O Ollama de reserva, se a configuracao pedir um diferente do principal.

    Apontar os dois para o mesmo lugar nao daria reserva nenhuma — so uma
    segunda tentativa contra a mesma maquina que acabou de nao responder.
    """
    if not settings.fallback_host or settings.fallback_host == settings.host:
        return None
    return OllamaClient(
        replace(
            settings,
            host=settings.fallback_host,
            model=settings.fallback_model or settings.model,
        )
    )
