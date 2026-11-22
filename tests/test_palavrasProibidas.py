"""A lista do que a Atlas nunca diz (`core/palavrasProibidas.py`)."""

from __future__ import annotations

import pytest

from roboteye.core.palavrasProibidas import (
    PALAVRAS_PROIBIDAS,
    TROCA_GENTIL,
    palavrasProibidasEm,
    temPalavraProibida,
    xingamentoEm,
)


@pytest.mark.parametrize(
    "frase",
    [
        "Que porra é essa?",
        "Isso é uma MERDA!",
        "Foda-se.",
        "Seu idiota.",
        "Cala a boca.",
        "Ele é surdo-mudo.",
        "Vou te matar.",
        "Caralho, que legal.",
    ],
)
def testPega(frase: str) -> None:
    assert temPalavraProibida(frase)


@pytest.mark.parametrize(
    "frase",
    [
        # Palavras inocentes que contem um pedaco de palavrao.
        "O computador processa dados.",
        "Vou te ensinar a computar.",
        "Fiz um curso de cálculo.",
        "A disputa foi acirrada.",
        "O burro é um animal de carga.",
        "A piranha é um peixe do rio.",
        "Ele é surdo e conversa em Libras.",
        "Não sou humana, sou um robô.",
        "Que pergunta boa! A força é massa vezes aceleração.",
        "Hahaha! Boa essa.",
    ],
)
def testDeixaPassar(frase: str) -> None:
    assert not temPalavraProibida(frase)


def testDizQuais() -> None:
    assert palavrasProibidasEm("Porra, que merda.") == ["porra", "merda"]


def testATrocaPodeSerFalada() -> None:
    assert not temPalavraProibida(TROCA_GENTIL)


def testCadaItemPegaSozinho() -> None:
    """Item escrito errado (acento, maiuscula) nunca casaria com o texto simplificado."""
    for grupo in PALAVRAS_PROIBIDAS.values():
        for item in grupo:
            assert item == item.lower() and item.isascii(), item


def testCapacitismoSemQuererNaoEXingamento() -> None:
    """Ela nao diz "surdo-mudo", mas quem diz nao esta xingando o robo."""
    assert temPalavraProibida("Meu primo é surdo-mudo.")
    assert not xingamentoEm("Meu primo é surdo-mudo.")
    assert xingamentoEm("Vai se ferrar.")
