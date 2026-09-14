"""Testes da seleção de backends e da personalidade."""

from __future__ import annotations

import pytest

from roboteye.config import LLMSettings, VoiceSettings
from roboteye.llm.echo import EchoClient
from roboteye.llm.factory import createLlmClient
from roboteye.llm.ollama import OllamaClient
from roboteye.llm.persona import PersonaStore
from roboteye.speech.factory import createTtsEngine
from roboteye.speech.nullEngine import NullEngine
from roboteye.speech.piperEngine import PiperEngine
from roboteye.speech.player import NullSink, createAudioSink


class TestLLMFactory:
    def testBackendOllama(self) -> None:
        assert isinstance(createLlmClient(LLMSettings(backend="ollama")), OllamaClient)

    def testBackendEcho(self) -> None:
        assert isinstance(createLlmClient(LLMSettings(backend="echo")), EchoClient)

    def testBackendDesconhecido(self) -> None:
        with pytest.raises(ValueError, match="desconhecido"):
            createLlmClient(LLMSettings(backend="inexistente"))


class TestTTSFactory:
    @pytest.mark.parametrize(
        ("backend", "esperado"),
        [("piper", PiperEngine), ("null", NullEngine)],
    )
    def testBackends(self, backend: str, esperado: type) -> None:
        assert isinstance(createTtsEngine(VoiceSettings(backend=backend)), esperado)

    def testBackendDesconhecido(self) -> None:
        with pytest.raises(ValueError, match="desconhecido"):
            createTtsEngine(VoiceSettings(backend="inexistente"))

    def testMotoresNaoCarregamModeloNaCriacao(self, tmp_path) -> None:
        # Criar o motor com um caminho inexistente não pode falhar: só o warm_up falha.
        createTtsEngine(VoiceSettings(backend="piper", modelPath=tmp_path / "nao-existe.onnx"))


class TestAudioSinkFactory:
    def testBackendNullUsaSaidaMuda(self) -> None:
        assert isinstance(createAudioSink(VoiceSettings(backend="null")), NullSink)

    def testSaidaMudaAceitaTudo(self) -> None:
        sink = NullSink()
        sink.start(None)  # type: ignore[arg-type]
        sink.write(b"\x00\x00")
        sink.stop()
        sink.close()


class TestEchoClient:
    def testDevolveUmaFalaPronta(self) -> None:
        client = EchoClient(seed=1)
        resposta = "".join(client.streamReply([])).strip()
        assert resposta

    def testEDeterministicoComSemente(self) -> None:
        primeira = "".join(EchoClient(seed=7).streamReply([]))
        segunda = "".join(EchoClient(seed=7).streamReply([]))
        assert primeira == segunda

    def testEstaSempreDisponivel(self) -> None:
        assert EchoClient().isAvailable()


class TestNullEngine:
    def testNaoProduzAudio(self) -> None:
        assert list(NullEngine().synthesize("qualquer coisa")) == []


class TestPersona:
    def persona(self, tmp_path, language: str = "en"):
        return PersonaStore(tmp_path, "atlas").load(language)

    def testPromptMencionaOIdiomaPorExtenso(self, tmp_path) -> None:
        assert "English" in self.persona(tmp_path, "en").systemPrompt()
        assert "Brazilian Portuguese" in self.persona(tmp_path, "pt").systemPrompt()

    def testIdiomaDesconhecidoEntraComoVeio(self, tmp_path) -> None:
        assert "xx" in self.persona(tmp_path, "xx").systemPrompt()

    def testProibeMarkdownEEmoji(self, tmp_path) -> None:
        prompt = self.persona(tmp_path).systemPrompt().lower()
        assert "markdown" in prompt
        assert "emoji" in prompt

    def testUsaAPersonaEmbutidaQuandoNaoHaArquivo(self, tmp_path) -> None:
        assert "Atlas" in self.persona(tmp_path).systemPrompt()
