"""Testes de quando o robo entende que falaram com ele."""

from __future__ import annotations

import pytest

from roboteye.hearing.gatilho import dirigido_ao_robo


class TestFalaramComEle:
    @pytest.mark.parametrize(
        ("ouvido", "esperado"),
        [
            ("atlas quantos alunos tem o curso", "quantos alunos tem o curso"),
            ("Atlas, quantos alunos tem o curso?", "quantos alunos tem o curso"),
            # O Vosk transcreve sem acento e sem pontuacao com frequencia; o
            # nome tem de ser reconhecido nas duas formas.
            ("ATLAS me diga as horas", "as horas"),
            ("atlas por favor conte uma piada", "conte uma piada"),
        ],
    )
    def test_devolve_a_pergunta_sem_o_nome(self, ouvido: str, esperado: str) -> None:
        assert dirigido_ao_robo(ouvido, "atlas") == esperado

    def test_o_nome_no_meio_corta_o_que_veio_antes(self) -> None:
        # "...e ai a gente pergunta, Atlas, que horas sao?" — o comeco e outra
        # conversa, nao parte da pergunta.
        ouvido = "e ai a gente pergunta atlas que horas sao"
        assert dirigido_ao_robo(ouvido, "atlas") == "que horas sao"

    def test_so_o_nome_conta_como_chamado(self) -> None:
        # Alguem chamou o robo. Responder qualquer coisa e melhor que ignorar.
        assert dirigido_ao_robo("atlas", "atlas") == "atlas"


class TestNaoEraComEle:
    def test_conversa_alheia_e_ignorada(self) -> None:
        assert dirigido_ao_robo("quantos alunos tem o curso", "atlas") is None

    def test_silencio_e_ignorado(self) -> None:
        assert dirigido_ao_robo("", "atlas") is None
        assert dirigido_ao_robo("   ", "atlas") is None

    def test_nome_dentro_de_outra_palavra_nao_conta(self) -> None:
        # "atlasse" nao e o nome dela; comparar por pedaco de texto acharia.
        assert dirigido_ao_robo("o atlasse do mapa", "atlas") is None


class TestSemPalavraDeAtivacao:
    def test_tudo_passa(self) -> None:
        # Modo de teste, ou robo em sala silenciosa.
        assert dirigido_ao_robo("que horas sao", "") == "que horas sao"

    def test_mas_silencio_continua_silencio(self) -> None:
        assert dirigido_ao_robo("  ", "") is None
