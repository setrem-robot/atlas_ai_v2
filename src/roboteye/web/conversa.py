"""Conversa com a Atlas pela pagina do celular.

O robo instalado sobe sozinho no arranque mostrando so a face: nao ha teclado
nem terminal, e o servico nao tem entrada de texto. Ate aqui, conversar com ela
exigia parar o robo e rodar `roboteye run` por SSH — ou seja, apagar a face na
frente de quem veio ver o robo funcionar.

A pagina de configuracao ja sobe junto, ja e acessivel do celular e ja pede PIN.
Faltava so deixar digitar nela.

Esta classe nao conhece o Assistant nem o barramento de eventos: recebe uma
funcao para entregar o que foi digitado, e alguem de fora anota o que a Atlas
respondeu. Quem liga as duas pontas e quem monta a aplicacao — a mesma regra que
vale para o resto do projeto.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Fala:
    """Uma linha da conversa."""

    quem: str
    texto: str

    def as_dict(self) -> dict[str, str]:
        return {"quem": self.quem, "texto": self.texto}


class ConversaWeb:
    """O que a pagina precisa para conversar com o robo."""

    #: Quantas falas manter. A pagina e um controle remoto, nao um arquivo: o
    #: suficiente para ver a ultima troca sem virar transcricao — e sem crescer
    #: sem limite num processo que fica ligado o dia inteiro.
    LIMITE = 12

    def __init__(self, entregar: Callable[[str], None]) -> None:
        self._entregar = entregar
        self._falas: list[Fala] = []
        # A pagina responde numa thread do servidor HTTP e as respostas chegam
        # na thread do assistente; sem o cadeado, uma leitura pode pegar a lista
        # no meio de uma escrita.
        self._lock = threading.Lock()

    def enviar(self, texto: str) -> str:
        """Entrega o texto ao robo e devolve o que foi realmente enviado."""
        texto = texto.strip()
        if not texto:
            return ""
        self.anotar("voce", texto)
        self._entregar(texto)
        return texto

    def anotar(self, quem: str, texto: str) -> None:
        texto = texto.strip()
        if not texto:
            return
        with self._lock:
            self._falas.append(Fala(quem=quem, texto=texto))
            del self._falas[: -self.LIMITE]

    def falas(self) -> list[dict[str, str]]:
        with self._lock:
            return [fala.as_dict() for fala in self._falas]
