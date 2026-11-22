"""Memoria de conversa.

Mantem uma janela deslizante das ultimas mensagens. Modelos pequenos (como o
llama3.2:1b) degradam rapido com contexto longo, entao o limite e baixo de proposito.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable
from datetime import date

from roboteye.llm.base import ChatMessage

_DIAS = ("segunda-feira", "terca-feira", "quarta-feira", "quinta-feira", "sexta-feira",
         "sabado", "domingo")
_MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")


def hojePorExtenso(dia: date | None = None) -> str:
    """A data dita como gente, sem depender do locale do sistema (o Pi não tem pt_BR)."""
    d = dia or date.today()
    return f"Hoje e {_DIAS[d.weekday()]}, {d.day} de {_MESES[d.month - 1]} de {d.year}."


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
        """Mensagens a enviar ao modelo: prompt de sistema + historico.

        A data entra aqui, e não no prompt guardado: o robô fica semanas ligado,
        e sem ela o modelo inventa o dia com toda a confiança.
        """
        sistema = ChatMessage(role="system", content=f"{self.system.content}\n\n{hojePorExtenso()}")
        with self.lock:
            return [sistema, *self.history]

    def buildNextPrefix(self) -> list[ChatMessage]:
        """O começo do prompt da próxima pergunta, antes de ela chegar.

        Com o histórico cheio, a próxima pergunta empurra a mensagem mais antiga
        para fora da janela. Aquecer o cache com `buildPrompt` daria um prefixo
        que a pergunta seguinte não tem, e o modelo releria tudo depois do system.
        """
        prompt = self.buildPrompt()
        cheio = self.history.maxlen is not None and len(prompt) - 1 >= self.history.maxlen
        return [prompt[0], *prompt[2:]] if cheio else prompt

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
