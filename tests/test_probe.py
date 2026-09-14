"""Testes da sonda que descobre o que a máquina da IA tem."""

from __future__ import annotations

import httpx
import pytest

from roboteye.llm.probe import explain, normalizeHost, probeOllama


class TestNormalizeHost:
    @pytest.mark.parametrize(
        ("digitado", "esperado"),
        [
            ("192.168.1.50", "http://192.168.1.50:11434"),
            ("192.168.1.50:11434", "http://192.168.1.50:11434"),
            ("http://192.168.1.50:11434/", "http://192.168.1.50:11434"),
            ("localhost:1234", "http://localhost:1234"),
            ("https://ia.local:443", "https://ia.local:443"),
        ],
    )
    def testCompletaOQueAPessoaNaoDigita(self, digitado: str, esperado: str) -> None:
        assert normalizeHost(digitado) == esperado

    def testVazioContinuaVazio(self) -> None:
        assert normalizeHost("   ") == ""


class RespostaFake:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class TestProbeOllama:
    def testListaOsModelosEmOrdem(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pedidos: list[str] = []

        def fakeGet(url: str, **_: object) -> RespostaFake:
            pedidos.append(url)
            return RespostaFake({"models": [{"name": "qwen3:8b"}, {"name": "llama3.2:1b"}]})

        monkeypatch.setattr(httpx, "get", fakeGet)
        resultado = probeOllama("192.168.1.50")

        assert pedidos == ["http://192.168.1.50:11434/api/tags"]
        assert resultado.ok
        assert resultado.models == ("llama3.2:1b", "qwen3:8b")

    def testFalhaDeRedeViraExplicacao(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fakeGet(*_: object, **__: object) -> RespostaFake:
            raise httpx.ConnectError("recusado")

        monkeypatch.setattr(httpx, "get", fakeGet)
        resultado = probeOllama("192.168.1.50")

        assert not resultado.ok
        assert "conexao recusada" in resultado.error
        # Mesmo falhando, devolve o endereço já normalizado — é o que a página e
        # o assistente mostram de volta a quem digitou.
        assert resultado.host == "http://192.168.1.50:11434"

    def testEnderecoVazioNaoBateNaRede(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def explode(*_: object, **__: object) -> None:
            raise AssertionError("nao deveria ter tentado a rede")

        monkeypatch.setattr(httpx, "get", explode)
        assert probeOllama("").error == "informe o endereco"


class TestExplain:
    @pytest.mark.parametrize(
        ("erro", "trecho"),
        [
            (httpx.ConnectTimeout("estourou"), "tempo limite"),
            (httpx.ConnectError("recusado"), "conexao recusada"),
            (RuntimeError("Name or service not known"), "nao resolvido"),
        ],
    )
    def testTraduzParaAlgoAcionavel(self, erro: Exception, trecho: str) -> None:
        assert trecho in explain(erro)
