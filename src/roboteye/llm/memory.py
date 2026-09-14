"""Memoria de conversa.

Mantem uma janela deslizante das ultimas mensagens. Modelos pequenos (como o
llama3.2:1b) degradam rapido com contexto longo, entao o limite e baixo de proposito.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable

from roboteye.llm.base import ChatMessage


class ConversationMemory:
    """Historico limitado de mensagens, seguro entre threads."""

    def __init__(self, systemPrompt: str, *, maxMessages: int = 8) -> None:
        self.system = ChatMessage(role="system", content=systemPrompt)
        self.history: deque[ChatMessage] = deque(maxlen=maxMessages)
        self.lock = threading.Lock()

    def addUser(self, text: str) -> None:
        self.append(ChatMessage(role="user", content=text))

    def addAssistant(self, text: str) -> None:
        self.append(ChatMessage(role="assistant", content=text))

    def append(self, message: ChatMessage) -> None:
        if not message.content.strip():
            return
        with self.lock:
            self.history.append(message)

    def buildPrompt(self) -> list[ChatMessage]:
        """Mensagens a enviar ao modelo: prompt de sistema + historico."""
        with self.lock:
            return [self.system, *self.history]

    def clear(self) -> None:
        with self.lock:
            self.history.clear()

    def replaceSystemPrompt(self, prompt: str) -> None:
        with self.lock:
            self.system = ChatMessage(role="system", content=prompt)

    def __len__(self) -> int:
        with self.lock:
            return len(self.history)

    def __iter__(self) -> Iterable[ChatMessage]:
        with self.lock:
            return iter(list(self.history))
