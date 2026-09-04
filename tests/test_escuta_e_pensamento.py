"""Pensar e transcrever não cabem juntos em quatro núcleos.

O Ollama usa todos os núcleos que encontra e o reconhecimento pede três;
somando a face, são oito threads disputando quatro. Medido no Pi de produção,
a mesma pergunta ao mesmo modelo:

    sozinho       primeiro token   200 ms   resposta inteira   1,4 s
    disputando    primeiro token  3300 ms   resposta inteira  24,6 s

Dez vezes mais lento. Foi assim que uma resposta real estourou o teto de 60 s e
o robô não respondeu nada:

    23:17:19  ouvi: qual seu nome
    23:18:19  ERROR  o modelo demorou demais para responder: timed out

A escuta agora para enquanto ela pensa. O risco que isso cria é o oposto e é
pior — um microfone que fica pausado é um robô surdo —, e é ele que estes
testes cercam.
"""

from __future__ import annotations

import threading

import pytest

from roboteye.app import Application
from roboteye.core.events import (
    ErrorOccurred,
    EventBus,
    SpeechFinished,
    SpeechStarted,
    ThinkingStarted,
)


class OuvidoFalso:
    """Conta as pausas e retomadas, como um `Ouvido` de verdade faria."""

    name = "falso"

    def __init__(self) -> None:
        self.pausado = False
        self.pausas = 0
        self.retomadas = 0

    def escutar(self):  # pragma: no cover - não é exercitado aqui
        return iter(())

    def pausar(self) -> None:
        self.pausado = True
        self.pausas += 1

    def retomar(self) -> None:
        self.pausado = False
        self.retomadas += 1

    def warm_up(self) -> None: ...

    def close(self) -> None: ...


class LocutorFalso:
    def sinalizar(self, chunks) -> None: ...


@pytest.fixture
def app(bus: EventBus):
    """Uma `Application` com só o que estes testes tocam.

    `object.__new__` em vez de `build()`: montar a aplicação inteira carregaria
    modelo de voz, de escuta e cliente de LLM para exercitar quatro assinaturas
    de evento.
    """
    from roboteye.config import Settings

    aplicacao = object.__new__(Application)
    aplicacao.settings = Settings.from_env(env_file=None)
    aplicacao.bus = bus
    aplicacao.ears = OuvidoFalso()
    aplicacao.speaker = LocutorFalso()  # type: ignore[assignment]
    aplicacao._ouvindo = None
    aplicacao._chamado = None
    aplicacao._conversa = None
    aplicacao._avisei_do_fim = False
    aplicacao._destravar_escuta = None
    aplicacao._abrir_ouvidos()
    yield aplicacao
    aplicacao._cancelar_destravamento()


class TestAEscutaParaEnquantoElaPensa:
    def test_pensar_cala_o_microfone(self, app, bus: EventBus) -> None:
        bus.publish(ThinkingStarted())
        assert app.ears.pausado, "o reconhecimento continuaria roubando os núcleos"

    def test_falar_tambem_cala(self, app, bus: EventBus) -> None:
        """Já era assim: ela não pode transcrever a própria voz."""
        bus.publish(SpeechStarted(text="oi"))
        assert app.ears.pausado

    def test_terminar_de_falar_devolve_a_escuta(self, app, bus: EventBus) -> None:
        bus.publish(ThinkingStarted())
        bus.publish(SpeechFinished())
        assert not app.ears.pausado


class TestONuncaFicarSurdo:
    """Um microfone pausado para sempre é pior que um robô lento.

    O caminho feliz devolve a escuta no `SpeechFinished`. Estes testes cercam
    os outros caminhos — porque o defeito que eles evitam não aparece num teste
    de conversa que deu certo.
    """

    def test_um_turno_que_falha_devolve_a_escuta(self, app, bus: EventBus) -> None:
        """Um turno com erro nunca chega a `SpeechFinished`.

        O modelo estourar o tempo limite é exatamente este caminho — e sem esta
        assinatura o robô ficaria surdo justo depois de já ter falhado uma vez.
        """
        bus.publish(ThinkingStarted())
        assert app.ears.pausado

        bus.publish(ErrorOccurred(message="o modelo demorou demais", source="llm"))

        assert not app.ears.pausado

    def test_o_relogio_devolve_a_escuta_mesmo_sem_evento_nenhum(
        self, app, bus: EventBus, monkeypatch
    ) -> None:
        """A rede de segurança: nenhum evento chega, e a escuta volta assim mesmo."""
        armados: list[float] = []

        class TimerFalso:
            def __init__(self, prazo, funcao):
                armados.append(prazo)
                self._funcao = funcao
                self.daemon = True

            def start(self) -> None:
                self._funcao()  # dispara na hora, para o teste não esperar

            def cancel(self) -> None: ...

        monkeypatch.setattr(threading, "Timer", TimerFalso)

        bus.publish(ThinkingStarted())

        assert armados, "a rede de segurança não foi armada"
        assert armados[0] > app.settings.llm.timeout, (
            "o prazo tem de ser maior que o do modelo, senão corta uma resposta boa"
        )
        assert not app.ears.pausado

    def test_o_relogio_e_cancelado_quando_o_turno_termina_bem(self, app, bus: EventBus) -> None:
        """Um relógio esquecido devolveria a escuta no meio do turno seguinte."""
        bus.publish(ThinkingStarted())
        assert app._destravar_escuta is not None

        bus.publish(SpeechFinished())

        assert app._destravar_escuta is None


class TestOSinalDePerguntaRecebida:
    """Quem pergunta tudo de uma vez também precisa saber que foi ouvido."""

    def test_avisa_quando_o_sinal_ainda_nao_saiu(self, app) -> None:
        tocados: list = []
        app.speaker.sinalizar = tocados.append  # type: ignore[method-assign]

        app._avisar_que_peguei_a_pergunta()

        assert len(tocados) == 1

    def test_nao_avisa_duas_vezes_no_mesmo_turno(self, app) -> None:
        """No caminho de duas etapas o sinal já saiu no fim da captura."""
        tocados: list = []
        app.speaker.sinalizar = tocados.append  # type: ignore[method-assign]
        app._avisei_do_fim = True

        app._avisar_que_peguei_a_pergunta()

        assert tocados == []

    def test_o_turno_seguinte_volta_a_avisar(self, app, bus: EventBus) -> None:
        """Sem o reset, o robô avisaria uma vez e ficaria mudo para sempre."""
        tocados: list = []
        app.speaker.sinalizar = tocados.append  # type: ignore[method-assign]
        app._avisei_do_fim = True

        bus.publish(SpeechFinished())
        app._avisar_que_peguei_a_pergunta()

        assert len(tocados) == 1


class TestOAvisoDaPersonaGrande:
    """Um prompt grande não dá erro: dá lentidão, e de um jeito que não aponta
    para ele.

    Cada vez que o cache do modelo esfria, o prompt inteiro é relido antes de a
    resposta começar — e num Raspberry Pi isso corre a ~35 tokens/s. Medido
    neste robô, com 1968 tokens de persona:

        prompt processing  512/1968   39 tokens/s
        [GIN] 500 | 1m0s | POST "/api/chat"

    Sessenta segundos sem chegar ao primeiro token. Quem investiga olha o
    modelo, a rede e a voz — tudo menos o arquivo de texto da personalidade.
    """

    def _avisos(
        self, caplog, caracteres: int, num_ctx: int = 4096, max_tokens: int = 220, *, no_pi=True
    ) -> list[str]:
        import logging

        from roboteye import app as app_mod
        from roboteye.config import LLMSettings

        # O aviso e sobre tempo, e o tempo depende da maquina: a mesma persona
        # que trava um Pi passa despercebida numa maquina de mesa.
        original = app_mod.is_arm
        app_mod.is_arm = lambda: no_pi
        try:
            with caplog.at_level(logging.WARNING, logger="roboteye.app"):
                app_mod._conferir_o_tamanho_da_persona(
                    "x" * caracteres, LLMSettings(num_ctx=num_ctx, max_tokens=max_tokens)
                )
        finally:
            app_mod.is_arm = original
        return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]

    def test_uma_persona_curta_nao_avisa(self, caplog) -> None:
        # ~500 tokens numa janela de 4096: era a suposição original do projeto.
        assert self._avisos(caplog, caracteres=2000) == []

    def test_a_persona_deste_robo_avisa(self, caplog) -> None:
        """7198 caracteres, medidos no robô: ~1950 tokens, ~55s de leitura fria."""
        avisos = self._avisos(caplog, caracteres=7198)
        assert len(avisos) == 1
        assert "persona" in avisos[0]

    def test_o_aviso_diz_quanto_custa_em_segundos(self, caplog) -> None:
        """Um aviso que só diz "está grande" não faz ninguém agir."""
        aviso = self._avisos(caplog, caracteres=7198)[0]
        assert "s antes da primeira" in aviso, aviso
        assert "encurtar persona/" in aviso, aviso

    def test_avisa_que_nao_cabe_junto_com_a_resposta(self, caplog) -> None:
        """1800 de persona + 220 de resposta não cabem em 2048.

        Era a configuração que travou o robô: o Ollama passa a deslocar a
        janela no meio da geração, que é caro e piora o texto.
        """
        aviso = self._avisos(caplog, caracteres=7198, num_ctx=2048)[0]
        assert "nao cabe junto com a resposta" in aviso, aviso

    def test_numa_maquina_de_mesa_a_mesma_persona_nao_assusta(self, caplog) -> None:
        """Um aviso que aparece onde não dói ensina a ser ignorado."""
        assert self._avisos(caplog, caracteres=7198, no_pi=False) == []
