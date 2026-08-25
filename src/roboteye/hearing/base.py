"""Contratos da escuta.

A simetria com `speech/` e proposital: ali um `TTSEngine` transforma texto em som,
aqui um `Ouvido` transforma som em texto. Os dois sao protocolos, os dois tem
`warm_up`/`close`, e trocar a implementacao de qualquer um nao toca em mais nada.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable


class HearingError(RuntimeError):
    """Falha ao escutar."""


@runtime_checkable
class Ouvido(Protocol):
    """Escuta o microfone e entrega frases prontas."""

    name: str

    def escutar(self) -> Iterator[str]:
        """Produz cada frase reconhecida, uma por vez, ate ser fechado.

        Bloqueia esperando alguem falar. Quem chama roda isto numa thread.
        """
        ...

    def pausar(self) -> None:
        """Para de escutar temporariamente. Deve ser idempotente."""
        ...

    def retomar(self) -> None:
        """Volta a escutar. Deve ser idempotente."""
        ...

    def warm_up(self) -> None:
        """Carrega o modelo. Deve ser idempotente e nunca levantar."""
        ...

    def close(self) -> None:
        """Libera o microfone. Deve ser idempotente."""
        ...
