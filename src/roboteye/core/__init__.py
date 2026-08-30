"""Nucleo da aplicacao: eventos, orquestracao e utilitarios de texto."""

from roboteye.core.events import (
    AssistantReply,
    ErrorOccurred,
    Event,
    EventBus,
    Shutdown,
    SpeechFinished,
    SpeechHeard,
    SpeechStarted,
    ThinkingStarted,
    UserMessage,
)

__all__ = [
    "AssistantReply",
    "ErrorOccurred",
    "Event",
    "EventBus",
    "Shutdown",
    "SpeechFinished",
    "SpeechHeard",
    "SpeechStarted",
    "ThinkingStarted",
    "UserMessage",
]
