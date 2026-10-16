"""Testes da linguagem neutra no que a Atlas diz de si."""

from __future__ import annotations

import pytest

from roboteye.core.neutroPt import neutralize


class TestEstados:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            # As respostas abaixo saíram do gemma3:1b do robô, como vieram.
            ("Sim, estou pronta!", "Sim, estou à disposição!"),
            ("Estou pronta para conversar.", "Estou à disposição para conversar."),
            (
                "Estou aqui, pronto para ajudar com suas perguntas.",
                "Estou aqui, à disposição para ajudar com suas perguntas.",
            ),
            ("Não, não estou cansada.", "Não, não estou sem energia."),
            ("ainda estou um pouquinho cansada", "ainda estou um pouquinho sem energia"),
            ("Fiquei curiosa!", "Fiquei com curiosidade!"),
            ("Estou muito curiosa.", "Estou com muita curiosidade."),
            ("Estou animado com isso!", "Estou contente com isso!"),
            ("Ainda não estou terminada.", "Ainda não estou em versão final."),
            ("Mas estou ótima, a missão continua!", "Mas estou muito bem, a missão continua!"),
            ("me sinto um pouco pesada", "me sinto um pouco sem energia"),
            ("Fiquei muito orgulhosa!", "Fiquei com muito orgulho!"),
        ],
    )
    def testPrimeiraPessoa(self, entrada: str, esperado: str) -> None:
        assert neutralize(entrada) == esperado

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("Pronto pra responder o que precisar.", "À disposição pra responder o que precisar."),
            (
                "Sim, tudo bem por aqui! Pronta para ajudar.",
                "Sim, tudo bem por aqui! À disposição para ajudar.",
            ),
            ("Um robô aqui, pronto para responder.", "Um robô aqui, à disposição para responder."),
        ],
    )
    def testProntoSemVerbo(self, entrada: str, esperado: str) -> None:
        assert neutralize(entrada) == esperado

    @pytest.mark.parametrize(
        "frase",
        [
            "O almoço está pronto para servir.",
            "Ela está pronta para a prova.",
            "O curso ficou pronto em 2018.",
            "Você parece cansado hoje.",
            "A turma está animada.",
        ],
    )
    def testTerceiraPessoaFicaIntacta(self, frase: str) -> None:
        """Sem verbo do próprio robô na frente, a frase fala de outra coisa."""
        assert neutralize(frase) == frase


class TestAutoria:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("Fui construída por alunos da SETREM.", "Sou obra de alunos da SETREM."),
            ("Eu fui criado pelos alunos do curso.", "Eu sou obra dos alunos do curso."),
            ("Fui feita pela turma de 2026.", "Sou obra da turma de 2026."),
            ("Fui criada para conversar.", "Existo para conversar."),
            ("Eu fui criada na SETREM.", "Eu nasci na SETREM."),
            ("Estou sendo construída aos poucos.", "Estou em desenvolvimento aos poucos."),
        ],
    )
    def testParticipios(self, entrada: str, esperado: str) -> None:
        assert neutralize(entrada) == esperado

    def testHistoriaDaInstituicaoFicaIntacta(self) -> None:
        frase = "A SETREM foi criada em 1950 e o curso foi feito por professores."
        assert neutralize(frase) == frase


class TestNomeERobo:
    def testSemArtigoAntesDoNome(self) -> None:
        assert neutralize("Eu sou a Atlas.") == "Eu sou Atlas."
        assert neutralize("Me chamo o Atlas.") == "Me chamo Atlas."

    def testRoboSemArtigo(self) -> None:
        assert neutralize("Eu sou um robô, então não tenho gênero.") == (
            "Eu sou robô, então não tenho gênero."
        )
        assert neutralize("Sou uma robô da SETREM.") == "Sou robô da SETREM."

    def testSaudacaoDoRobo(self) -> None:
        assert (
            neutralize(
                "Oi! Eu sou a Atlas, o robô da Engenharia de Computação da SETREM. Pode perguntar!"
            )
            == "Oi! Eu sou Atlas, robô da Engenharia de Computação da SETREM. Pode perguntar!"
        )

    def testArtigoQueNaoEDoNomeFica(self) -> None:
        assert neutralize("O Atlas da escola é um livro.") == "O Atlas da escola é um livro."


class TestAgradecimento:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("Tudo ótimo, obrigado!", "Tudo ótimo, agradeço!"),
            ("Obrigada!", "Agradeço!"),
            ("Muito obrigada pela pergunta.", "Agradeço muito pela pergunta."),
            ("Obrigado pela visita!", "Agradeço pela visita!"),
        ],
    )
    def testAgradeco(self, entrada: str, esperado: str) -> None:
        assert neutralize(entrada) == esperado

    def testParticipioNaoEAgradecimento(self) -> None:
        """ "Não sou obrigada a" é outra palavra; trocar daria frase sem sentido."""
        frase = "Não sou obrigada a saber tudo."
        assert neutralize(frase) == frase


class TestBoasVindas:
    def testNaoChutaOGeneroDeQuemChega(self) -> None:
        assert neutralize("Seja bem-vindo à SETREM!") == "Boas-vindas à SETREM!"
        assert neutralize("Bem-vinda!") == "Boas-vindas!"


class TestTextoNeutroFicaIntacto:
    @pytest.mark.parametrize(
        "frase",
        [
            "Eu sou Atlas, da Engenharia de Computação da SETREM.",
            "Quem me construiu foram alunos de Engenharia de Computação da SETREM.",
            "A SETREM fica em Três de Maio, no noroeste do Rio Grande do Sul.",
            "Sim, uso inteligência artificial para conversar com as pessoas.",
            "Ainda não me ensinaram isso.",
        ],
    )
    def testNaoMexe(self, frase: str) -> None:
        assert neutralize(frase) == frase
