"""Cliente de LLM falso.

Responde com falas pre-escritas do personagem. Serve para testar a face e a voz
sem depender do Ollama, e para os testes automatizados.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Sequence

from roboteye.llm.base import ChatMessage

_CANNED_REPLIES = (
    "Fascinating. I will pretend that was a useful thing to say.",
    "Noted. Filed under: things that did not need saying.",
    "I could answer that, but watching you wait is more entertaining.",
    "That is a question. Technically.",
    "Your persistence is almost admirable. Almost.",
)


class EchoClient:
    """Devolve uma fala pronta, ignorando o modelo de verdade."""

    name = "echo"

    def __init__(self, *, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def stream_reply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        reply = self._rng.choice(_CANNED_REPLIES)
        # Emite em pedacos para exercitar o mesmo caminho do streaming real.
        for word in reply.split(" "):
            yield word + " "

    def is_available(self) -> bool:
        return True

    def warm_up(self, messages: Sequence[ChatMessage] = ()) -> None:
        return None

    def close(self) -> None:
        return None
