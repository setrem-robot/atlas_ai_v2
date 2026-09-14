"""Testes de quando o robo entende que falaram com ele."""

from __future__ import annotations

import pytest

from roboteye.hearing.gatilho import Conversa, dirigidoAoRobo


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
    def testDevolveAPerguntaSemONome(self, ouvido: str, esperado: str) -> None:
        assert dirigidoAoRobo(ouvido, "atlas") == esperado

    def testONomeNoMeioCortaOQueVeioAntes(self) -> None:
        # "...e ai a gente pergunta, Atlas, que horas sao?" — o comeco e outra
        # conversa, nao parte da pergunta.
        ouvido = "e ai a gente pergunta atlas que horas sao"
        assert dirigidoAoRobo(ouvido, "atlas") == "que horas sao"

    def testSoONomeContaComoChamado(self) -> None:
        # Sem janela, alguem que chama merece resposta em vez de silencio.
        assert dirigidoAoRobo("atlas", "atlas") == "atlas"


class TestNaoEraComEle:
    def testConversaAlheiaEIgnorada(self) -> None:
        assert dirigidoAoRobo("quantos alunos tem o curso", "atlas") is None

    def testSilencioEIgnorado(self) -> None:
        assert dirigidoAoRobo("", "atlas") is None
        assert dirigidoAoRobo("   ", "atlas") is None

    def testNomeDentroDeOutraPalavraNaoConta(self) -> None:
        # "atlasse" nao e o nome dela; comparar por pedaco de texto acharia.
        assert dirigidoAoRobo("o atlasse do mapa", "atlas") is None


class TestSemPalavraDeAtivacao:
    def testTudoPassa(self) -> None:
        # Modo de teste, ou robo em sala silenciosa.
        assert dirigidoAoRobo("que horas sao", "") == "que horas sao"

    def testMasSilencioContinuaSilencio(self) -> None:
        assert dirigidoAoRobo("  ", "") is None


class TestJanelaDeConversa:
    """Chamar o nome deixa a Atlas ouvindo a frase seguinte.

    E assim que as pessoas falam — e como uma crianca fala: chama, espera o robo
    olhar, e so entao pergunta.
    """

    def testChamarEPerguntarDepoisFunciona(self) -> None:
        conversa = Conversa(janelaS=8.0)
        # "Atlas!" — so o chamado; ela fica esperando, sem responder nada.
        assert dirigidoAoRobo("atlas", "atlas", conversa=conversa, agora=0.0) is None
        # "quanto e dois mais dois?" — sem o nome, e vale.
        assert (
            dirigidoAoRobo("quanto e dois mais dois", "atlas", conversa=conversa, agora=2.0)
            == "quanto e dois mais dois"
        )

    def testAJanelaFechaSozinha(self) -> None:
        conversa = Conversa(janelaS=8.0)
        dirigidoAoRobo("atlas", "atlas", conversa=conversa, agora=0.0)
        # Passou da janela: e a sala conversando de novo, nao a pergunta.
        assert dirigidoAoRobo("que horas sao", "atlas", conversa=conversa, agora=20.0) is None

    def testResponderFechaAJanela(self) -> None:
        # Senao a conversa ao lado emendaria na frase seguinte.
        conversa = Conversa(janelaS=8.0)
        dirigidoAoRobo("atlas", "atlas", conversa=conversa, agora=0.0)
        assert dirigidoAoRobo("que horas sao", "atlas", conversa=conversa, agora=1.0)
        assert dirigidoAoRobo("e amanha", "atlas", conversa=conversa, agora=2.0) is None

    def testAPerguntaCompletaTambemAbreAJanela(self) -> None:
        # "Atlas, que horas sao?" responde e deixa a porta aberta para o
        # complemento — "e amanha?" — sem precisar chamar de novo.
        conversa = Conversa(janelaS=8.0)
        assert dirigidoAoRobo("atlas que horas sao", "atlas", conversa=conversa, agora=0.0)
        assert dirigidoAoRobo("e amanha", "atlas", conversa=conversa, agora=1.0) == "e amanha"

    def testSemSerChamadaContinuaIgnorando(self) -> None:
        conversa = Conversa(janelaS=8.0)
        assert dirigidoAoRobo("que horas sao", "atlas", conversa=conversa, agora=0.0) is None
