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


class _AssistantFake:
    """So o suficiente para montar o console; a saida nao usa o assistente."""


@pytest.fixture
def console(bus: EventBus) -> ConsoleChat:
    return ConsoleChat(_AssistantFake(), bus)


class TestEscutaNoTerminal:
    def test_dirigido_mostra_cru_entendido_e_medidas(self, bus, console, capsys) -> None:
        bus.publish(
            SpeechHeard(
                raw="Atlas, quanto e dois?",
                accepted="quanto e dois",
                ms=780,
                confidence=-0.31,
                no_speech=0.02,
            )
        )
        saida = capsys.readouterr().out
        assert "Atlas, quanto e dois?" in saida  # transcricao crua
        assert "quanto e dois" in saida  # pergunta apos tirar o nome
        assert "STT 780 ms" in saida
        assert "conf -0.31" in saida

    def test_sem_o_nome_aparece_como_ignorado(self, bus, console, capsys) -> None:
        bus.publish(SpeechHeard(raw="conversa de fundo", accepted=None, ms=100))
        saida = capsys.readouterr().out
        assert "ignorado" in saida
        assert "conversa de fundo" in saida

    def test_silencio_alto_e_sinalizado(self, bus, console, capsys) -> None:
        bus.publish(SpeechHeard(raw="aa", accepted=None, ms=90, confidence=-0.9, no_speech=0.8))
        assert "silencio" in capsys.readouterr().out

    def test_confianca_ausente_nao_quebra(self, bus, console, capsys) -> None:
        # Vosk nao mede confianca: a linha sai so com o tempo.
        bus.publish(SpeechHeard(raw="atlas oi", accepted="oi", ms=120))
        saida = capsys.readouterr().out
        assert "STT 120 ms" in saida
        assert "conf" not in saida


class TestTempoDeResposta:
    def test_mede_ate_a_primeira_fala(self, bus, console, capsys) -> None:
        bus.publish(UserMessage(text="oi", timestamp=1000.0))
        bus.publish(SpeechStarted(text="ola", timestamp=1000.5))
        assert "1a fala em 500 ms" in capsys.readouterr().out

    def test_so_a_primeira_fala_do_turno_cronometra(self, bus, console, capsys) -> None:
        bus.publish(UserMessage(text="oi", timestamp=1000.0))
        bus.publish(SpeechStarted(text="ola", timestamp=1000.5))
        bus.publish(SpeechStarted(text="tudo bem?", timestamp=1001.0))
        assert capsys.readouterr().out.count("1a fala") == 1

    def test_fala_sem_pergunta_nao_cronometra(self, bus, console, capsys) -> None:
        # Saudacao: fala sem uma mensagem do usuario antes nao mede nada.
        bus.publish(SpeechStarted(text="bom dia", timestamp=1000.0))
        assert "1a fala" not in capsys.readouterr().out
