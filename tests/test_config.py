"""Testes da leitura de configuração."""

from __future__ import annotations

import pytest

from roboteye.config import (
    ConfigError,
    FaceSettings,
    LLMSettings,
    Settings,
    VoiceSettings,
    parseColor,
)


class TestParseColor:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("#04C9FD", (4, 201, 253)),
            ("04C9FD", (4, 201, 253)),
            ("255,180,37", (255, 180, 37)),
            ("  #000000  ", (0, 0, 0)),
        ],
    )
    def testFormatosAceitos(self, entrada: str, esperado: tuple[int, int, int]) -> None:
        assert parseColor(entrada) == esperado

    @pytest.mark.parametrize("entrada", ["#GGG", "1,2", "300,0,0", ""])
    def testValoresInvalidos(self, entrada: str) -> None:
        with pytest.raises(ConfigError):
            parseColor(entrada)


class TestLLMSettings:
    def testUsaPadroesSemVariaveis(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ROBOTEYE_LLM_MODEL", raising=False)
        assert LLMSettings.fromEnv().model == "llama3.2:1b"

    def testLeDoAmbiente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_LLM_MODEL", "qwen2.5:3b")
        monkeypatch.setenv("ROBOTEYE_OLLAMA_HOST", "http://10.0.0.5:11434/")
        settings = LLMSettings.fromEnv()
        assert settings.model == "qwen2.5:3b"
        assert settings.host == "http://10.0.0.5:11434"  # barra final removida

    def testBackendInvalidoERejeitado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_LLM_BACKEND", "gpt")
        with pytest.raises(ConfigError, match="invalido"):
            LLMSettings.fromEnv()


class TestVoiceSettings:
    def testConfigDerivadaDoModelo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE_MODEL", "/tmp/voz/personalizada.onnx")
        monkeypatch.delenv("ROBOTEYE_VOICE_CONFIG", raising=False)
        settings = VoiceSettings.fromEnv()
        assert settings.resolvedConfigPath().name == "personalizada.onnx.json"

    def testConfigExplicitaTemPrioridade(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE_MODEL", "/tmp/voz/personalizada.onnx")
        monkeypatch.setenv("ROBOTEYE_VOICE_CONFIG", "/tmp/outro.json")
        assert VoiceSettings.fromEnv().resolvedConfigPath().name == "outro.json"

    def testCaminhoRelativoResolveAPartirDaRaiz(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE_MODEL", "models/x/y.onnx")
        assert VoiceSettings.fromEnv().modelPath.is_absolute()


class TestFaceSettings:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [("true", True), ("1", True), ("yes", True), ("false", False), ("off", False)],
    )
    def testBooleanos(self, monkeypatch: pytest.MonkeyPatch, valor: str, esperado: bool) -> None:
        monkeypatch.setenv("ROBOTEYE_FACE_FULLSCREEN", valor)
        assert FaceSettings.fromEnv().fullscreen is esperado

    def testBooleanoInvalido(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_FACE_ENABLED", "talvez")
        with pytest.raises(ConfigError, match="booleano"):
            FaceSettings.fromEnv()

    def testDimensaoMinima(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_FACE_WIDTH", "10")
        with pytest.raises(ConfigError, match=">="):
            FaceSettings.fromEnv()


class TestSettings:
    def testMontaTodasAsSecoes(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_LOG_LEVEL", "debug")
        settings = Settings.fromEnv(envFile=tmp_path / "inexistente.env")
        assert settings.logLevel == "DEBUG"
        assert isinstance(settings.llm, LLMSettings)
        assert isinstance(settings.voice, VoiceSettings)
        assert isinstance(settings.face, FaceSettings)


class TestOPadraoValeOndeImporta:
    """Um padrão escrito em dois lugares é um padrão que muda pela metade.

    `num_ctx` tinha o valor repetido no campo da dataclass e no `from_env`.
    Mudar só o campo não mudou nada no robô — quem monta a configuração de
    verdade é o `from_env` —, e quem denunciou foi o aviso do arranque, dizendo
    2048 depois de o padrão já ter "virado" 4096.
    """

    def testOPadraoDaClasseEODoAmbienteSaoOMesmo(self, monkeypatch) -> None:
        from roboteye.config import DEFAULT_NUM_CTX, LLMSettings, Settings

        monkeypatch.delenv("ROBOTEYE_LLM_NUM_CTX", raising=False)

        assert LLMSettings().numCtx == DEFAULT_NUM_CTX
        assert Settings.fromEnv(envFile=None).llm.numCtx == DEFAULT_NUM_CTX

    def testAPersonaDesteRoboCabeNoPadrao(self) -> None:
        """~1950 tokens de persona + 220 de resposta precisam caber juntos.

        Com 2048 não cabiam, e o Ollama passava a deslocar a janela no meio da
        geração — caro, e piora o texto.
        """
        from roboteye.config import DEFAULT_NUM_CTX

        personaDesteRobo = 1950
        resposta = 220
        assert personaDesteRobo + resposta < DEFAULT_NUM_CTX
