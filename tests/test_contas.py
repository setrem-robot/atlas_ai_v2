"""Contas: ela calcula as perguntas de aritmetica sem passar pelo modelo."""

from __future__ import annotations

import pytest

from roboteye.core.contas import numero, responder


@pytest.mark.parametrize(
    ("texto", "valor"),
    [
        ("dezesseis", 16),
        ("cento e vinte e tres", 123),
        ("dois mil e vinte e seis", 2026),
        ("mil", 1000),
        ("42", 42),
        ("o pao", None),
    ],
)
def test_numero_por_extenso(texto: str, valor: int | None) -> None:
    assert numero(texto) == valor


@pytest.mark.parametrize(
    ("pergunta", "resultado"),
    [
        ("quanto é doze vezes três", "36"),
        ("qual a raiz quadrada de dezesseis", "4"),
        ("um mais sete", "8"),
        ("quanto dá cem dividido por oito", "12,5"),
        ("quanto é dois menos cinco", "menos 3"),
        ("Atlas, quanto é nove ao quadrado?", "81"),
        ("raiz quadrada de dois", "mais ou menos 1,4"),
    ],
)
def test_conta_certa(pergunta: str, resultado: str) -> None:
    resposta = responder(pergunta)
    assert resposta is not None
    assert resposta.rstrip(".").endswith(resultado)


@pytest.mark.parametrize(
    "pergunta",
    [
        "o que é um while",
        "quanto é dois mais dois em binário",
        "eu quero mais tempo",
        "quantos anos tem a setrem",
        "me conta uma piada",
    ],
)
def test_nao_e_conta(pergunta: str) -> None:
    assert responder(pergunta) is None


def test_decimal_exato_nao_e_aproximado() -> None:
    assert "mais ou menos" not in (responder("quanto é cem dividido por oito") or "mais ou menos")


def test_divisao_por_zero() -> None:
    assert "zero" in (responder("quanto é cinco dividido por zero") or "")
