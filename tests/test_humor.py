"""Humor da face a partir do texto: xingamento e tom da resposta."""

from __future__ import annotations

import pytest

from roboteye.core.humor import (
    Animo,
    elogiou,
    humorDaFala,
    riu,
    soRiu,
    trechosDaRisada,
    xingou,
)


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
    ("fala", "humor"),
    [
        ("Ei, não gostei disso. Me trata com respeito.", "angry"),
        ("Não entendi. Pode repetir?", "dizzy"),
        ("Hahaha! Essa foi boa!", "laugh"),
        ("Infelizmente não consigo abrir a porta.", "tired"),
        ("Oi! Que bom te ver.", "happy"),
        ("Agradeço, você também!", "happy"),
        ("É a menor unidade de informação.", None),
        # A pergunta da piada e seria: quem ri e a frase da graca.
        ("Por que o computador foi ao médico?", None),
    ],
)
def test_humor_da_fala(fala: str, humor: str | None) -> None:
    assert humorDaFala(fala) == humor


@pytest.mark.parametrize("texto", ["kkkkk", "Hahaha!", "ha ha ha", "rsrs", "hehehe", "rá rá"])
def test_risada(texto: str) -> None:
    assert riu(texto)


@pytest.mark.parametrize("texto", ["há muito tempo", "o rato roeu", "kk", "cara", "hard"])
def test_nao_e_risada(texto: str) -> None:
    assert not riu(texto)


def test_so_riu() -> None:
    assert soRiu("kkkkkk")
    assert soRiu("hahaha!")
    assert not soRiu("kkkk você é engraçada")
    assert not soRiu("")


@pytest.mark.parametrize(
    "texto",
    [
        "você é muito inteligente atlas",
        "gosto de você",
        "te amo",
        "parabéns",
        "atlas você é demais",
    ],
)
def test_elogio(texto: str) -> None:
    assert elogiou(texto)


@pytest.mark.parametrize("texto", ["o que é inteligência artificial", "a prova foi legal"])
def test_nao_e_elogio(texto: str) -> None:
    assert not elogiou(texto)


def test_trechos_da_risada() -> None:
    assert trechosDaRisada("Hahaha! Essa foi boa!") == [
        ("Hahaha!", True),
        (" Essa foi boa!", False),
    ]
    assert trechosDaRisada("Porque estava com vírus! Hahaha!") == [
        ("Porque estava com vírus! ", False),
        ("Hahaha!", True),
    ]
    assert trechosDaRisada("sem graça nenhuma") == [("sem graça nenhuma", False)]


class TestAnimo:
    def test_comeca_neutro(self) -> None:
        assert Animo().repouso(0.0) == "neutral"

    def test_risadas_deixam_alegre(self) -> None:
        animo = Animo()
        animo.sentir("laugh", 0.0)
        animo.sentir("laugh", 1.0)
        assert animo.repouso(2.0) == "happy"

    def test_xingamento_deixa_chateada(self) -> None:
        animo = Animo()
        animo.sentir("xingou", 0.0)
        assert animo.repouso(1.0) == "tired"

    def test_passa_com_o_tempo(self) -> None:
        animo = Animo(meiaVidaS=60.0)
        animo.sentir("elogio", 0.0)
        assert animo.repouso(1.0) == "happy"
        assert animo.repouso(300.0) == "neutral"

    def test_fica_entre_menos_um_e_um(self) -> None:
        animo = Animo()
        for t in range(10):
            animo.sentir("elogio", float(t))
        assert animo.atual(10.0) <= 1.0
