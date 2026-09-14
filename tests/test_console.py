"""Testes da saida de debug do chat no terminal.

O foco e o que o `ConsoleChat` imprime ao reagir aos eventos — em especial a
escuta (STT) e o tempo ate a primeira fala —, que e a ferramenta para conferir
reconhecimento e voz por SSH. A leitura do teclado nao entra aqui.
"""

from __future__ import annotations

import pytest

from roboteye.core.events import (
    EventBus,
    SpeechHeard,
    SpeechStarted,
    UserMessage,
)
from roboteye.ui.console import ConsoleChat


class AssistantFake:
    """So o suficiente para montar o console; a saida nao usa o assistente."""


@pytest.fixture
def console(bus: EventBus) -> ConsoleChat:
    return ConsoleChat(AssistantFake(), bus)


class TestEscutaNoTerminal:
    def testDirigidoMostraCruEntendidoEMedidas(self, bus, console, capsys) -> None:
        bus.publish(
            SpeechHeard(
                raw="Atlas, quanto e dois?",
                accepted="quanto e dois",
                ms=780,
                confidence=-0.31,
                noSpeech=0.02,
            )
        )
        saida = capsys.readouterr().out
        assert "Atlas, quanto e dois?" in saida  # transcricao crua
        assert "quanto e dois" in saida  # pergunta apos tirar o nome
        assert "STT 780 ms" in saida
        assert "conf -0.31" in saida

    def testSemONomeApareceComoIgnorado(self, bus, console, capsys) -> None:
        bus.publish(SpeechHeard(raw="conversa de fundo", accepted=None, ms=100))
        saida = capsys.readouterr().out
        assert "ignorado" in saida
        assert "conversa de fundo" in saida

    def testSilencioAltoESinalizado(self, bus, console, capsys) -> None:
        bus.publish(SpeechHeard(raw="aa", accepted=None, ms=90, confidence=-0.9, noSpeech=0.8))
        assert "silencio" in capsys.readouterr().out

    def testConfiancaAusenteNaoQuebra(self, bus, console, capsys) -> None:
        # Vosk nao mede confianca: a linha sai so com o tempo.
        bus.publish(SpeechHeard(raw="atlas oi", accepted="oi", ms=120))
        saida = capsys.readouterr().out
        assert "STT 120 ms" in saida
        assert "conf" not in saida


class TestTempoDeResposta:
    def testMedeAteAPrimeiraFala(self, bus, console, capsys) -> None:
        bus.publish(UserMessage(text="oi", timestamp=1000.0))
        bus.publish(SpeechStarted(text="ola", timestamp=1000.5))
        assert "1a fala em 500 ms" in capsys.readouterr().out

    def testSoAPrimeiraFalaDoTurnoCronometra(self, bus, console, capsys) -> None:
        bus.publish(UserMessage(text="oi", timestamp=1000.0))
        bus.publish(SpeechStarted(text="ola", timestamp=1000.5))
        bus.publish(SpeechStarted(text="tudo bem?", timestamp=1001.0))
        assert capsys.readouterr().out.count("1a fala") == 1

    def testFalaSemPerguntaNaoCronometra(self, bus, console, capsys) -> None:
        # Saudacao: fala sem uma mensagem do usuario antes nao mede nada.
        bus.publish(SpeechStarted(text="bom dia", timestamp=1000.0))
        assert "1a fala" not in capsys.readouterr().out
