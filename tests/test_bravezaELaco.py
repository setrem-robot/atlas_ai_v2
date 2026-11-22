"""Fala brava sem o modelo e corte do laco em que o modelo pequeno entra."""

from __future__ import annotations

from roboteye.core.braveza import _BRAVA, _MUITO_BRAVA, _PERDOA, Braveza
from roboteye.core.text import cortarLaco, pararNoLaco


def test_xingamento_responde_bravo_e_sobe_o_tom() -> None:
    braveza = Braveza()
    assert braveza.responder("você é burra") in _BRAVA
    assert braveza.responder("sua idiota") in _BRAVA
    assert braveza.responder("cala a boca") in _MUITO_BRAVA


def test_desculpa_depois_do_xingamento_e_aceita() -> None:
    braveza = Braveza()
    braveza.responder("robô inútil")
    assert braveza.responder("desculpa atlas") in _PERDOA
    assert braveza.responder("desculpa atlas") is None  # sem xingamento antes, vai ao modelo


def test_conversa_normal_fica_com_o_modelo() -> None:
    assert Braveza().responder("o que é um bit") is None


def test_cortar_laco_apara_a_repeticao() -> None:
    frase = "Um quilobyte vale mil bytes, como um terço de um terço de um terço de um terço"
    assert cortarLaco(frase) == "Um quilobyte vale mil bytes, como um terço."
    assert cortarLaco("É um bolo de chocolate com um bolo de chocolate dentro.") == (
        "É um bolo de chocolate."
    )


def test_cortar_laco_nao_mexe_em_frase_normal() -> None:
    frase = "A tensão é igual à resistência vezes a corrente."
    assert cortarLaco(frase) == frase


def test_parar_no_laco_fecha_o_stream() -> None:
    lidos: list[str] = []

    def modelo():
        for palavra in ("um terço de " * 50).split(" "):
            lidos.append(palavra)
            yield palavra + " "

    texto = "".join(pararNoLaco(modelo()))
    assert len(lidos) < 20
    assert texto.count("terço") <= 4


def test_parar_no_laco_deixa_duas_citacoes() -> None:
    resposta = (
        "O curso de Engenharia de Computação é ótimo. A Engenharia de Computação forma gente."
    )
    assert "".join(pararNoLaco(iter(resposta.split(" ")))) == "".join(resposta.split(" "))
