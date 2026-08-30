"""Testes da queda da IA de rede para o modelo local."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import pytest

from roboteye.config import LLMSettings
from roboteye.llm.base import ChatMessage, LLMError
from roboteye.llm.factory import create_llm_client
from roboteye.llm.fallback import FallbackLLMClient
from roboteye.llm.ollama import OllamaClient

PERGUNTA = (ChatMessage(role="user", content="ola"),)


class IAFalsa:
    """Cliente de mentira que grava o que lhe perguntaram."""

    def __init__(self, name: str, *, falha_em: int | None = None, pedacos: int = 2) -> None:
        self.name = name
        self.perguntas: list[str] = []
        self.aquecido = False
        #: Com que mensagens foi aquecido — a persona deve chegar ate aqui.
        self.aquecido_com: list[ChatMessage] = []
        self.disponivel = True
        self.fechado = False
        #: Em qual pedaco levantar erro (0 = ja no primeiro), ou None para nunca.
        self._falha_em = falha_em
        self._pedacos = pedacos

    def warm_up(self, messages: Sequence[ChatMessage] = ()) -> None:
        self.aquecido = True
        self.aquecido_com = list(messages)

    def close(self) -> None:
        self.fechado = True

    def is_available(self) -> bool:
        return self.disponivel

    def stream_reply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        self.perguntas.append(messages[-1].content)
        for indice in range(self._pedacos):
            if indice == self._falha_em:
                raise LLMError(f"{self.name} caiu no pedaco {indice}")
            yield self.name


def montar(rede: IAFalsa, local: IAFalsa) -> FallbackLLMClient:
    # `probe_interval=0` desliga a thread de vigia: os testes controlam o
    # estado na mao, e uma thread so tornaria o resultado dependente do relogio.
    return FallbackLLMClient(rede, local, probe_interval=0.0)


def responder(cliente: FallbackLLMClient) -> list[str]:
    return list(cliente.stream_reply(PERGUNTA))


class TestCaminhoFeliz:
    def test_usa_a_ia_de_rede_quando_ela_responde(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        assert responder(montar(rede, local)) == ["rede", "rede"]
        assert local.perguntas == []

    def test_o_nome_diz_que_ha_duas(self) -> None:
        assert montar(IAFalsa("rede"), IAFalsa("local")).name == "rede+local"


class TestQueda:
    def test_falha_no_primeiro_pedaco_troca_de_modelo(self) -> None:
        rede, local = IAFalsa("rede", falha_em=0), IAFalsa("local")
        assert responder(montar(rede, local)) == ["local", "local"]

    def test_depois_de_cair_vai_direto_ao_local(self) -> None:
        rede, local = IAFalsa("rede", falha_em=0), IAFalsa("local")
        cliente = montar(rede, local)
        responder(cliente)
        responder(cliente)
        # A rede so foi tentada na primeira pergunta.
        assert len(rede.perguntas) == 1
        assert len(local.perguntas) == 2

    def test_queda_no_meio_da_resposta_sobe_o_erro(self) -> None:
        # Ja falamos a primeira frase: refazer no outro modelo faria a Atlas
        # recomecar em voz alta.
        rede, local = IAFalsa("rede", falha_em=1), IAFalsa("local")
        cliente = montar(rede, local)
        with pytest.raises(LLMError):
            responder(cliente)
        assert local.perguntas == []
        # Mas a proxima pergunta ja nasce no local.
        assert responder(cliente) == ["local", "local"]

    def test_avisa_quem_estiver_ouvindo(self) -> None:
        avisos: list[str] = []
        cliente = FallbackLLMClient(
            IAFalsa("rede", falha_em=0),
            IAFalsa("local"),
            probe_interval=0.0,
            on_switch=avisos.append,
        )
        responder(cliente)
        assert avisos and "local" in avisos[0]


class TestAquecimento:
    def test_aquece_quem_vai_responder(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        montar(rede, local).warm_up()
        assert rede.aquecido
        # O local nao: um reserva que ocupa memoria nao deve ocupa-la enquanto
        # nao e ele quem responde. Ver `TestMemoriaDaReserva`.
        assert not local.aquecido

    def test_a_persona_chega_a_quem_foi_aquecido(self) -> None:
        # E o que faz o modelo responder em 2 s em vez de 12 na primeira
        # pergunta: o prefixo ja processado fica guardado no servidor.
        persona = (ChatMessage(role="system", content="voce e a Atlas"),)
        rede, local = IAFalsa("rede"), IAFalsa("local")
        montar(rede, local).warm_up(persona)
        assert rede.aquecido_com == list(persona)

    def test_nao_espera_por_uma_rede_que_nao_existe(self) -> None:
        # Aquecer o que ja se sabe fora do ar custa o tempo limite inteiro.
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.disponivel = False
        montar(rede, local).warm_up()
        assert local.aquecido
        assert not rede.aquecido

    def test_rede_fora_no_arranque_ja_comeca_no_local(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.disponivel = False
        cliente = montar(rede, local)
        cliente.warm_up()
        assert responder(cliente) == ["local", "local"]
        assert rede.perguntas == []

    def test_aquecer_nao_derruba_o_arranque(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.warm_up = _explodir  # type: ignore[method-assign]
        cliente = montar(rede, local)
        cliente.warm_up()  # nao levanta
        # E o robo continua sabendo com quem falar.
        assert responder(cliente) == ["rede", "rede"]

    def test_fechar_fecha_os_dois(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        montar(rede, local).close()
        assert rede.fechado and local.fechado


class IAResidente(IAFalsa):
    """Reserva que ocupa memoria desta maquina — e sabe devolve-la."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.keep_alive = "0"
        self.descarregou = 0

    def set_keep_alive(self, valor: str) -> None:
        self.keep_alive = valor

    def unload(self) -> bool:
        self.descarregou += 1
        return True


def _esperar_memoria(cliente: FallbackLLMClient) -> None:
    """Deixa a troca de memoria terminar antes de conferir o resultado.

    Ela roda em thread de proposito: carregar o modelo do cartao demora
    segundos, e segurar a sondagem por isso atrasaria a descoberta de que a
    rede voltou.
    """
    thread = cliente._memoria
    if thread is not None:
        thread.join(timeout=5.0)


class TestMemoriaDaReserva:
    """O modelo do Pi so ocupa RAM quando e ele quem responde."""

    def test_com_a_rede_de_pe_a_reserva_fica_fora_da_memoria(self) -> None:
        rede, local = IAFalsa("rede"), IAResidente("local")
        cliente = montar(rede, local)
        cliente.warm_up()
        _esperar_memoria(cliente)
        assert not local.aquecido
        assert local.descarregou == 1

    def test_a_queda_carrega_a_reserva_antes_da_pergunta(self) -> None:
        # O momento de ler o modelo do cartao e a queda, e nao a pergunta
        # seguinte: ali ninguem esta esperando resposta.
        persona = (ChatMessage(role="system", content="voce e a Atlas"),)
        rede, local = IAFalsa("rede"), IAResidente("local")
        cliente = montar(rede, local)
        cliente.warm_up(persona)
        _esperar_memoria(cliente)

        rede.disponivel = False
        cliente._set_primary(False)
        _esperar_memoria(cliente)

        assert local.aquecido_com == list(persona)
        assert local.keep_alive == "5m"

    def test_a_rede_de_volta_devolve_a_memoria(self) -> None:
        rede, local = IAFalsa("rede"), IAResidente("local")
        cliente = montar(rede, local)
        cliente.warm_up()
        _esperar_memoria(cliente)

        cliente._set_primary(False)
        _esperar_memoria(cliente)
        cliente._set_primary(True)
        _esperar_memoria(cliente)

        assert local.keep_alive == "0"
        # Uma no arranque e outra quando a rede voltou.
        assert local.descarregou == 2

    def test_reserva_sem_memoria_propria_continua_sendo_aquecida(self) -> None:
        # `EchoClient` e afins nao ocupam RAM desta maquina: nao ha o que
        # gerenciar, e o comportamento antigo (aquecer) segue valendo.
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.disponivel = False
        montar(rede, local).warm_up()
        assert local.aquecido


class TestFactory:
    def test_sem_reserva_configurada_devolve_o_cliente_simples(self) -> None:
        assert isinstance(create_llm_client(LLMSettings(backend="ollama")), OllamaClient)

    def test_com_reserva_devolve_o_par(self) -> None:
        cliente = create_llm_client(
            LLMSettings(
                backend="ollama",
                host="http://pc-da-sala:11434",
                fallback_host="http://localhost:11434",
                fallback_model="llama3.2:1b",
            )
        )
        assert isinstance(cliente, FallbackLLMClient)

    def test_reserva_no_mesmo_endereco_nao_e_reserva(self) -> None:
        cliente = create_llm_client(
            LLMSettings(backend="ollama", fallback_host="http://localhost:11434")
        )
        assert isinstance(cliente, OllamaClient)


def _explodir(messages: Sequence[ChatMessage] = ()) -> None:
    raise RuntimeError("modelo nao carregou")
