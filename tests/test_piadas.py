"""Piadas: ela ri das que ouve e conta as dela, sem passar pelo modelo."""

from __future__ import annotations

import random

import pytest

from roboteye.core.humor import riu
from roboteye.core.piadas import ESPERA_DO_FIM_S, NAO_SEI, PIADAS, RISOS, Piadas


@pytest.fixture
def piadas() -> Piadas:
    return Piadas(random.Random(7))


def test_conversa_normal_fica_com_o_modelo(piadas: Piadas) -> None:
    for texto in ("qual é o seu nome", "por que o céu é azul", "o que é um bit"):
        assert piadas.responder(texto, 0.0) is None


def test_adivinha_falada_em_duas_frases(piadas: Piadas) -> None:
    """Pela voz vem sem "?": ela pergunta o que e, e ri da resposta."""
    assert piadas.responder("o que é o que é cai em pé e corre deitado", 0.0) in NAO_SEI
    resposta = piadas.responder("a chuva", 5.0)
    assert resposta in RISOS and riu(resposta)


def test_adivinha_digitada_inteira_ja_faz_rir(piadas: Piadas) -> None:
    assert piadas.responder("o que é o que é: cai em pé e corre deitado? a chuva", 0.0) in RISOS


def test_piada_anunciada(piadas: Piadas) -> None:
    assert piadas.responder("vou te contar uma piada", 0.0) is not None
    pergunta = piadas.responder("por que a galinha atravessou a rua", 3.0)
    assert pergunta is not None and "Por quê" in pergunta
    assert piadas.responder("para chegar do outro lado", 6.0) in RISOS


def test_piada_anunciada_contada_de_uma_vez(piadas: Piadas) -> None:
    piadas.responder("deixa eu te contar uma piada", 0.0)
    assert piadas.responder("um pato entrou na farmácia e pediu um batom", 3.0) in RISOS


def test_cumulo(piadas: Piadas) -> None:
    pergunta = piadas.responder("sabe qual é o cúmulo da paciência", 0.0)
    assert pergunta is not None and "qual" in pergunta.lower()
    assert piadas.responder("esperar o elevador de escada", 2.0) in RISOS


def test_o_fim_da_piada_tem_prazo(piadas: Piadas) -> None:
    """Passou do prazo, a proxima frase e conversa: rir dela seria pior."""
    piadas.responder("o que é o que é tem dente mas não morde", 0.0)
    assert piadas.responder("qual é o seu nome", ESPERA_DO_FIM_S + 1.0) is None


def test_pave(piadas: Piadas) -> None:
    assert riu(piadas.responder("é pavê ou pacomê", 0.0) or "")


def test_ri_junto_quando_a_pessoa_so_ri(piadas: Piadas) -> None:
    assert riu(piadas.responder("kkkkkk", 0.0) or "")
    assert piadas.responder("kkkk você é engraçada", 1.0) is None


def test_conta_piadas_sem_repetir(piadas: Piadas) -> None:
    contadas = [piadas.responder("me conta uma piada", float(i)) for i in range(len(PIADAS))]
    assert sorted(contadas) == sorted(PIADAS)  # um baralho inteiro antes de repetir
    assert all(riu(piada or "") for piada in contadas)  # e ri no fim de cada uma
