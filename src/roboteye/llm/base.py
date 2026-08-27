"""Contratos da camada de LLM."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


class LLMError(RuntimeError):
    """Falha ao conversar com o modelo de linguagem."""


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Uma mensagem no formato de chat."""

    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@runtime_checkable
class LLMClient(Protocol):
    """Cliente de modelo de linguagem."""

    name: str

    def stream_reply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Produz a resposta em pedacos, na ordem em que o modelo a gera."""
        ...

    def is_available(self) -> bool:
        """Indica se o backend esta acessivel (usado pelo comando `doctor`)."""
        ...

    def warm_up(self, messages: Sequence[ChatMessage] = ()) -> None:
        """Prepara conexao e modelo. Deve ser idempotente e nunca levantar.

        `messages` sao as mensagens que a conversa vai usar de verdade — na
        pratica, a persona. Quem consegue reaproveitar o prefixo ja processado
        deve fazer isso aqui, no arranque, e nao na primeira pergunta.
        """
        ...

    def close(self) -> None:
        """Libera conexoes. Deve ser idempotente."""
        ...


@runtime_checkable
class ModeloResidente(Protocol):
    """Cliente cujo modelo ocupa memoria desta maquina, e pode devolve-la.

    Separado de `LLMClient` de proposito: o `EchoClient` nao tem modelo nenhum
    e o Ollama da maquina de mesa tem, mas gasta a memoria *dela*. Quem precisa
    liberar RAM aqui pergunta por este protocolo em vez de assumir que todo
    cliente sabe se descarregar.
    """

    def set_keep_alive(self, valor: str) -> None:
        """Muda quanto tempo o modelo fica residente depois de responder."""
        ...

    def unload(self) -> bool:
        """Solta o modelo da memoria agora. Devolve se o pedido foi aceito."""
        ...


def collect(chunks: Iterator[str]) -> str:
    """Consome um fluxo de pedacos e devolve a resposta completa."""
    return "".join(chunks).strip()
