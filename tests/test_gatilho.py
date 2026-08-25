"""Testes de quando o robo entende que falaram com ele."""

from __future__ import annotations

import pytest

from roboteye.hearing.gatilho import Conversa, dirigido_ao_robo


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
        # Sem janela, alguem que chama merece resposta em vez de silencio.
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


class TestJanelaDeConversa:
    """Chamar o nome deixa a Atlas ouvindo a frase seguinte.

    E assim que as pessoas falam — e como uma crianca fala: chama, espera o robo
    olhar, e so entao pergunta.
    """

    def test_chamar_e_perguntar_depois_funciona(self) -> None:
        conversa = Conversa(janela_s=8.0)
        # "Atlas!" — so o chamado; ela fica esperando, sem responder nada.
        assert dirigido_ao_robo("atlas", "atlas", conversa=conversa, agora=0.0) is None
        # "quanto e dois mais dois?" — sem o nome, e vale.
        assert (
            dirigido_ao_robo("quanto e dois mais dois", "atlas", conversa=conversa, agora=2.0)
            == "quanto e dois mais dois"
        )

    def test_a_janela_fecha_sozinha(self) -> None:
        conversa = Conversa(janela_s=8.0)
        dirigido_ao_robo("atlas", "atlas", conversa=conversa, agora=0.0)
        # Passou da janela: e a sala conversando de novo, nao a pergunta.
        assert dirigido_ao_robo("que horas sao", "atlas", conversa=conversa, agora=20.0) is None

    def test_responder_fecha_a_janela(self) -> None:
        # Senao a conversa ao lado emendaria na frase seguinte.
        conversa = Conversa(janela_s=8.0)
        dirigido_ao_robo("atlas", "atlas", conversa=conversa, agora=0.0)
        assert dirigido_ao_robo("que horas sao", "atlas", conversa=conversa, agora=1.0)
        assert dirigido_ao_robo("e amanha", "atlas", conversa=conversa, agora=2.0) is None

    def test_a_pergunta_completa_tambem_abre_a_janela(self) -> None:
        # "Atlas, que horas sao?" responde e deixa a porta aberta para o
        # complemento — "e amanha?" — sem precisar chamar de novo.
        conversa = Conversa(janela_s=8.0)
        assert dirigido_ao_robo("atlas que horas sao", "atlas", conversa=conversa, agora=0.0)
        assert dirigido_ao_robo("e amanha", "atlas", conversa=conversa, agora=1.0) == "e amanha"

    def test_sem_ser_chamada_continua_ignorando(self) -> None:
        conversa = Conversa(janela_s=8.0)
        assert dirigido_ao_robo("que horas sao", "atlas", conversa=conversa, agora=0.0) is None
