"""Humor da face a partir do texto: xingamento e tom da resposta."""

from __future__ import annotations

import pytest

from roboteye.core.humor import humorDaFala, xingou


@pytest.mark.parametrize(
    "texto",
    [
        "você é burra",
        "Sua idiota!",
        "atlas inútil",
        "cala a boca",
        "vai se ferrar",
        "que porra de robô",
        "idiota",
        "robô lixo",
        "eu te odeio",
    ],
)
def test_xingamento(texto: str) -> None:
    assert xingou(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "onde eu jogo o lixo",
        "qual o seu nome",
        "o que é um bit",
        "você gosta de música",
        "me conta uma piada",
        "a prova foi chata",
    ],
)
def test_nao_e_xingamento(texto: str) -> None:
    assert not xingou(texto)


@pytest.mark.parametrize(
    ("fala", "pergunta", "humor"),
    [
        ("Ei, não gostei disso. Me trata com respeito.", "", "angry"),
        ("Não entendi. Pode repetir?", "", "dizzy"),
        (
            "Por que o computador foi ao médico? Porque estava com vírus.",
            "me conta uma piada",
            "laugh",
        ),
        ("Infelizmente não consigo abrir a porta.", "abre a porta", "tired"),
        ("Oi! Que bom te ver.", "oi", "happy"),
        ("É a menor unidade de informação.", "o que é um bit", None),
    ],
)
def test_humor_da_fala(fala: str, pergunta: str, humor: str | None) -> None:
    assert humorDaFala(fala, pergunta) == humor
