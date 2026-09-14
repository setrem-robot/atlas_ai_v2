"""Testes do cliente Ollama, com transporte HTTP simulado."""

from __future__ import annotations

import json

import httpx
import pytest

from roboteye.config import LLMSettings
from roboteye.llm.base import ChatMessage, LLMError, collect
from roboteye.llm.ollama import OllamaClient

MENSAGENS = [ChatMessage(role="user", content="olá")]


def clienteCom(handler, **ajustes) -> OllamaClient:
    """Cria um cliente cujo transporte é controlado pelo teste."""
    client = OllamaClient(LLMSettings(host="http://fake:11434", model="teste", **ajustes))
    client.client = httpx.Client(
        base_url="http://fake:11434",
        transport=httpx.MockTransport(handler),
    )
    return client


def ndjson(*eventos: dict) -> bytes:
    return "\n".join(json.dumps(evento) for evento in eventos).encode()


class TestStreamReply:
    def testJuntaOsPedacosDaResposta(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=ndjson(
                    {"message": {"content": "Olá"}, "done": False},
                    {"message": {"content": ", humano"}, "done": False},
                    {"message": {"content": "."}, "done": True},
                ),
            )

        client = clienteCom(handler)
        try:
            assert collect(client.streamReply(MENSAGENS)) == "Olá, humano."
        finally:
            client.close()

    def testParaNoDone(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=ndjson(
                    {"message": {"content": "fim"}, "done": True},
                    {"message": {"content": "ignorado"}, "done": False},
                ),
            )

        client = clienteCom(handler)
        try:
            assert collect(client.streamReply(MENSAGENS)) == "fim"
        finally:
            client.close()

    def testLinhasInvalidasSaoIgnoradas(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            content = b"nao e json\n" + ndjson({"message": {"content": "ok"}, "done": True})
            return httpx.Response(200, content=content)

        client = clienteCom(handler)
        try:
            assert collect(client.streamReply(MENSAGENS)) == "ok"
        finally:
            client.close()

    def testErroNoCorpoViraExcecao(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=ndjson({"error": "modelo não carregado"}))

        client = clienteCom(handler)
        try:
            with pytest.raises(LLMError, match="modelo não carregado"):
                collect(client.streamReply(MENSAGENS))
        finally:
            client.close()

    def testModeloAusenteExplicaComoResolver(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "model not found"})

        client = clienteCom(handler)
        try:
            with pytest.raises(LLMError, match="ollama pull"):
                collect(client.streamReply(MENSAGENS))
        finally:
            client.close()

    def testFalhaDeConexaoExplicaOHost(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusada", request=request)

        client = clienteCom(handler)
        try:
            with pytest.raises(LLMError, match="http://fake:11434"):
                collect(client.streamReply(MENSAGENS))
        finally:
            client.close()

    def testEnviaOModeloConfigurado(self) -> None:
        capturado: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            capturado.update(json.loads(request.content))
            return httpx.Response(200, content=ndjson({"message": {"content": "x"}, "done": True}))

        client = clienteCom(handler)
        try:
            collect(client.streamReply(MENSAGENS))
        finally:
            client.close()

        assert capturado["model"] == "teste"
        assert capturado["stream"] is True


class TestDisponibilidade:
    def testServidorNoAr(self) -> None:
        client = clienteCom(lambda _: httpx.Response(200, json={"models": []}))
        try:
            assert client.isAvailable()
        finally:
            client.close()

    def testServidorForaDoAr(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusada", request=request)

        client = clienteCom(handler)
        try:
            assert not client.isAvailable()
        finally:
            client.close()

    def testListaModelos(self) -> None:
        payload = {"models": [{"name": "llama3.2:1b"}, {"name": "qwen2.5:3b"}]}
        client = clienteCom(lambda _: httpx.Response(200, json=payload))
        try:
            assert client.listModels() == ["llama3.2:1b", "qwen2.5:3b"]
        finally:
            client.close()


class TestMemoria:
    """O que o robô pede ao Ollama para não deixar o modelo ocupando RAM."""

    def capturar(self, acao, **kwargs) -> dict:
        capturado: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.content:
                capturado.update(json.loads(request.content))
            return httpx.Response(200, content=ndjson({"message": {"content": "x"}, "done": True}))

        client = OllamaClient(LLMSettings(host="http://fake:11434", model="teste", **kwargs))
        client.client = httpx.Client(
            base_url="http://fake:11434", transport=httpx.MockTransport(handler)
        )
        try:
            acao(client)
        finally:
            client.close()
        return capturado

    def testAConversaDeclaraOContextoEOTempoDeVida(self) -> None:
        # O cache de atenção é reservado pelo tamanho declarado: cada token a
        # mais é memória presa no Pi mesmo numa conversa de duas frases.
        pedido = self.capturar(
            lambda c: collect(c.streamReply(MENSAGENS)), numCtx=1024, keepAlive="30s"
        )
        assert pedido["options"]["num_ctx"] == 1024
        assert pedido["keep_alive"] == "30s"

    def testAquecerComKeepAliveZeroAindaDeixaOModeloResidente(self) -> None:
        # Aquecer pedindo "0" carregaria e descarregaria o modelo antes da
        # primeira pergunta — o oposto do que aquecer significa.
        pedido = self.capturar(lambda c: c.warmUp(), keepAlive="0")
        assert pedido["keep_alive"] == "5m"

    def testDescarregarPedeZero(self) -> None:
        pedido = self.capturar(lambda c: c.unload())
        assert pedido["keep_alive"] == 0
        assert pedido["messages"] == []

    def testDescarregarComOServidorForaDoArNaoLevanta(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("recusada", request=request)

        client = clienteCom(handler)
        try:
            assert client.unload() is False
        finally:
            client.close()

    def testTrocarOTempoDeVidaValeNaProximaPergunta(self) -> None:
        def acao(client: OllamaClient) -> None:
            client.setKeepAlive("5m")
            collect(client.streamReply(MENSAGENS))

        assert self.capturar(acao, keepAlive="0")["keep_alive"] == "5m"


class TestTetoDeNucleos:
    """Quantos nucleos o modelo pode tomar da maquina.

    Num Raspberry Pi os mesmos quatro nucleos desenham a face e reconhecem a
    fala. Medido no robo, a mesma pergunta ao mesmo modelo: sozinho, primeiro
    token em 200 ms; disputando, 3300 ms e a resposta inteira em 24,6 s.
    """

    def opcoesEnviadas(self, **ajustes) -> dict:
        capturado: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            capturado.update(json.loads(request.content))
            return httpx.Response(200, content=ndjson({"message": {"content": "ok"}, "done": True}))

        collect(clienteCom(handler, **ajustes).streamReply(MENSAGENS))
        return capturado["options"]

    def testPorPadraoNaoMandaTeto(self) -> None:
        """Sem numero util, o Ollama decide — e numa maquina de mesa ele acerta."""
        assert "num_thread" not in self.opcoesEnviadas()

    def testOTetoConfiguradoChegaAoModelo(self) -> None:
        assert self.opcoesEnviadas(numThread=3)["num_thread"] == 3
