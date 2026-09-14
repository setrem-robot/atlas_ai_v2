"""Testes da queda da IA de rede para o modelo local."""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

import pytest

from roboteye.config import LLMSettings
from roboteye.llm.base import ChatMessage, LLMError
from roboteye.llm.factory import createLlmClient
from roboteye.llm.fallback import KEEP_ALIVE_EM_USO, FallbackLLMClient
from roboteye.llm.ollama import OllamaClient

PERGUNTA = (ChatMessage(role="user", content="ola"),)


class IAFalsa:
    """Cliente de mentira que grava o que lhe perguntaram."""

    def __init__(self, name: str, *, falhaEm: int | None = None, pedacos: int = 2) -> None:
        self.name = name
        self.perguntas: list[str] = []
        self.aquecido = False
        #: Com que mensagens foi aquecido — a persona deve chegar ate aqui.
        self.aquecidoCom: list[ChatMessage] = []
        self.disponivel = True
        self.fechado = False
        #: Em qual pedaco levantar erro (0 = ja no primeiro), ou None para nunca.
        self.falhaEm = falhaEm
        self.pedacos = pedacos

    def warmUp(self, messages: Sequence[ChatMessage] = ()) -> None:
        self.aquecido = True
        self.aquecidoCom = list(messages)

    def close(self) -> None:
        self.fechado = True

    def isAvailable(self) -> bool:
        return self.disponivel

    def streamReply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        self.perguntas.append(messages[-1].content)
        for indice in range(self.pedacos):
            if indice == self.falhaEm:
                raise LLMError(f"{self.name} caiu no pedaco {indice}")
            yield self.name


def montar(rede: IAFalsa, local: IAFalsa) -> FallbackLLMClient:
    # `probe_interval=0` desliga a thread de vigia: os testes controlam o
    # estado na mao, e uma thread so tornaria o resultado dependente do relogio.
    return FallbackLLMClient(rede, local, probeInterval=0.0)


def responder(cliente: FallbackLLMClient) -> list[str]:
    return list(cliente.streamReply(PERGUNTA))


class TestCaminhoFeliz:
    def testUsaAIaDeRedeQuandoElaResponde(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        assert responder(montar(rede, local)) == ["rede", "rede"]
        assert local.perguntas == []

    def testONomeDizQueHaDuas(self) -> None:
        assert montar(IAFalsa("rede"), IAFalsa("local")).name == "rede+local"


class TestQueda:
    def testFalhaNoPrimeiroPedacoTrocaDeModelo(self) -> None:
        rede, local = IAFalsa("rede", falhaEm=0), IAFalsa("local")
        assert responder(montar(rede, local)) == ["local", "local"]

    def testDepoisDeCairVaiDiretoAoLocal(self) -> None:
        rede, local = IAFalsa("rede", falhaEm=0), IAFalsa("local")
        cliente = montar(rede, local)
        responder(cliente)
        responder(cliente)
        # A rede so foi tentada na primeira pergunta.
        assert len(rede.perguntas) == 1
        assert len(local.perguntas) == 2

    def testQuedaNoMeioDaRespostaSobeOErro(self) -> None:
        # Ja falamos a primeira frase: refazer no outro modelo faria a Atlas
        # recomecar em voz alta.
        rede, local = IAFalsa("rede", falhaEm=1), IAFalsa("local")
        cliente = montar(rede, local)
        with pytest.raises(LLMError):
            responder(cliente)
        assert local.perguntas == []
        # Mas a proxima pergunta ja nasce no local.
        assert responder(cliente) == ["local", "local"]

    def testAvisaQuemEstiverOuvindo(self) -> None:
        avisos: list[str] = []
        cliente = FallbackLLMClient(
            IAFalsa("rede", falhaEm=0),
            IAFalsa("local"),
            probeInterval=0.0,
            onSwitch=avisos.append,
        )
        responder(cliente)
        assert avisos and "local" in avisos[0]


class TestAquecimento:
    def testAqueceQuemVaiResponder(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        montar(rede, local).warmUp()
        assert rede.aquecido
        # O local nao: um reserva que ocupa memoria nao deve ocupa-la enquanto
        # nao e ele quem responde. Ver `TestMemoriaDaReserva`.
        assert not local.aquecido

    def testAPersonaChegaAQuemFoiAquecido(self) -> None:
        # E o que faz o modelo responder em 2 s em vez de 12 na primeira
        # pergunta: o prefixo ja processado fica guardado no servidor.
        persona = (ChatMessage(role="system", content="voce e a Atlas"),)
        rede, local = IAFalsa("rede"), IAFalsa("local")
        montar(rede, local).warmUp(persona)
        assert rede.aquecidoCom == list(persona)

    def testNaoEsperaPorUmaRedeQueNaoExiste(self) -> None:
        # Aquecer o que ja se sabe fora do ar custa o tempo limite inteiro.
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.disponivel = False
        montar(rede, local).warmUp()
        assert local.aquecido
        assert not rede.aquecido

    def testRedeForaNoArranqueJaComecaNoLocal(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.disponivel = False
        cliente = montar(rede, local)
        cliente.warmUp()
        assert responder(cliente) == ["local", "local"]
        assert rede.perguntas == []

    def testAquecerNaoDerrubaOArranque(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.warmUp = explodir  # type: ignore[method-assign]
        cliente = montar(rede, local)
        cliente.warmUp()  # nao levanta
        # E o robo continua sabendo com quem falar.
        assert responder(cliente) == ["rede", "rede"]

    def testFecharFechaOsDois(self) -> None:
        rede, local = IAFalsa("rede"), IAFalsa("local")
        montar(rede, local).close()
        assert rede.fechado and local.fechado


class IAResidente(IAFalsa):
    """Reserva que ocupa memoria desta maquina — e sabe devolve-la."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.keepAlive = "0"
        self.descarregou = 0

    def setKeepAlive(self, valor: str) -> None:
        self.keepAlive = valor

    def unload(self) -> bool:
        self.descarregou += 1
        return True


def esperarMemoria(cliente: FallbackLLMClient) -> None:
    """Deixa a troca de memoria terminar antes de conferir o resultado.

    Ela roda em thread de proposito: carregar o modelo do cartao demora
    segundos, e segurar a sondagem por isso atrasaria a descoberta de que a
    rede voltou.
    """
    thread = cliente.memoria
    if thread is not None:
        thread.join(timeout=5.0)


class TestMemoriaDaReserva:
    """O modelo do Pi so ocupa RAM quando e ele quem responde."""

    def testComARedeDePeAReservaFicaForaDaMemoria(self) -> None:
        rede, local = IAFalsa("rede"), IAResidente("local")
        cliente = montar(rede, local)
        cliente.warmUp()
        esperarMemoria(cliente)
        assert not local.aquecido
        assert local.descarregou == 1

    def testAQuedaCarregaAReservaAntesDaPergunta(self) -> None:
        # O momento de ler o modelo do cartao e a queda, e nao a pergunta
        # seguinte: ali ninguem esta esperando resposta.
        persona = (ChatMessage(role="system", content="voce e a Atlas"),)
        rede, local = IAFalsa("rede"), IAResidente("local")
        cliente = montar(rede, local)
        cliente.warmUp(persona)
        esperarMemoria(cliente)

        rede.disponivel = False
        cliente.setPrimary(False)
        esperarMemoria(cliente)

        assert local.aquecidoCom == list(persona)
        # `-1` e "nao descarregue". Cinco minutos jogavam fora justamente o que
        # este aquecimento conquista: descarregar leva junto o cache do prompt,
        # e reler a persona custa mais que responder. Medido no robo, com 1968
        # tokens, o tempo limite de 60 s estourou sem chegar ao primeiro token.
        assert local.keepAlive == KEEP_ALIVE_EM_USO

    def testARedeDeVoltaDevolveAMemoria(self) -> None:
        rede, local = IAFalsa("rede"), IAResidente("local")
        cliente = montar(rede, local)
        cliente.warmUp()
        esperarMemoria(cliente)

        cliente.setPrimary(False)
        esperarMemoria(cliente)
        cliente.setPrimary(True)
        esperarMemoria(cliente)

        assert local.keepAlive == "0"
        # Uma no arranque e outra quando a rede voltou.
        assert local.descarregou == 2

    def testReservaSemMemoriaPropriaContinuaSendoAquecida(self) -> None:
        # `EchoClient` e afins nao ocupam RAM desta maquina: nao ha o que
        # gerenciar, e o comportamento antigo (aquecer) segue valendo.
        rede, local = IAFalsa("rede"), IAFalsa("local")
        rede.disponivel = False
        montar(rede, local).warmUp()
        assert local.aquecido


class TestFactory:
    def testSemReservaConfiguradaDevolveOClienteSimples(self) -> None:
        assert isinstance(createLlmClient(LLMSettings(backend="ollama")), OllamaClient)

    def testComReservaDevolveOPar(self) -> None:
        cliente = createLlmClient(
            LLMSettings(
                backend="ollama",
                host="http://pc-da-sala:11434",
                fallbackHost="http://localhost:11434",
                fallbackModel="llama3.2:1b",
            )
        )
        assert isinstance(cliente, FallbackLLMClient)

    def testReservaNoMesmoEnderecoNaoEReserva(self) -> None:
        cliente = createLlmClient(
            LLMSettings(backend="ollama", fallbackHost="http://localhost:11434")
        )
        assert isinstance(cliente, OllamaClient)


def explodir(messages: Sequence[ChatMessage] = ()) -> None:
    raise RuntimeError("modelo nao carregou")


class TestOFormatoDoKeepAlive:
    """O Ollama le `keep_alive` como duracao do Go, e recusa a requisicao
    inteira quando nao consegue.

    Nao e o campo que falha: e a pergunta. Um valor sem unidade derruba toda
    conversa com 400, e o robo fica sem responder nada — foi o que aconteceu
    com `"-1"`:

        {"error":"time: missing unit in duration \"-1\""}

    Os dubles de HTTP dos outros testes aceitam qualquer coisa, entao o formato
    nao aparece ali. Esta classe cobre o contrato que o Ollama de fato impoe.
    """

    #: A gramatica de `time.ParseDuration`: numero com unidade, opcionalmente
    #: negativo e com casas decimais.
    DURACAO = re.compile(r"^-?\d+(\.\d+)?(ns|us|µs|ms|s|m|h)$")

    def testOValorEmUsoTemUnidade(self) -> None:
        assert self.DURACAO.match(KEEP_ALIVE_EM_USO), (
            f"{KEEP_ALIVE_EM_USO!r} nao e uma duracao que o Ollama aceite"
        )

    def testENegativoParaNaoDescarregar(self) -> None:
        """Duracao negativa e como o Ollama entende "mantenha carregado"."""
        assert KEEP_ALIVE_EM_USO.startswith("-")

    def testOsPadroesDaConfiguracaoTambemTemUnidade(self) -> None:
        from roboteye.config import LLMSettings

        padrao = LLMSettings()
        for valor in (padrao.keepAlive, padrao.fallbackKeepAlive):
            assert self.DURACAO.match(valor) or valor in {"0", ""}, (
                f"{valor!r} nao e uma duracao que o Ollama aceite"
            )
