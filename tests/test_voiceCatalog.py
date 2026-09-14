"""Testes do catálogo de vozes e da troca de voz."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboteye import voiceCatalog
from roboteye.config import (
    ConfigError,
    Settings,
    VoiceSettings,
    modelPathForVoice,
)


class TestReservaConfigurada:
    """`ROBOTEYE_VOICE_FALLBACK` aceita "auto", "off" ou o nome de uma voz."""

    def voz(self, **kwargs) -> VoiceSettings:
        return VoiceSettings(voice="francisca", **kwargs)

    def testAutoDeixaOCatalogoEscolher(self) -> None:
        assert self.voz(fallback="auto").fallbackVoice() in {"dora", "dii"}

    def testOffDesliga(self) -> None:
        assert self.voz(fallback="off").fallbackVoice() is None
        assert self.voz(fallback="false").fallbackVoice() is None

    def testNomeExplicitoManda(self) -> None:
        """A heurística de hardware acerta na maioria, não em todo caso.

        Um mini-PC ARM potente ou um Pi só para a face aguentam a voz pesada;
        fixar o nome é a saída para quando o palpite não serve.
        """
        assert self.voz(fallback="dii").fallbackVoice() == "dii"

    def testNomeInvalidoFalhaNaConfiguracao(self) -> None:
        """Melhor quebrar ao subir do que no meio de uma fala, sem rede."""
        with pytest.raises(ConfigError, match="desconhecida"):
            self.voz(fallback="nao-existe").fallbackVoice()

    def testVozOfflineNaoGanhaReserva(self) -> None:
        assert VoiceSettings(voice="dii", fallback="auto").fallbackVoice() is None


class TestCatalogo:
    def testAVozPadraoExiste(self) -> None:
        assert voiceCatalog.get(voiceCatalog.DEFAULT_VOICE) is not None

    def testTemVozEmPortugues(self) -> None:
        vozesPt = [v for v in voiceCatalog.CATALOG.values() if v.language == "pt"]
        assert vozesPt, "o catálogo deveria oferecer ao menos uma voz em português"

    @pytest.mark.parametrize("key", voiceCatalog.names())
    def testTodaVozEstaCompleta(self, key: str) -> None:
        spec = voiceCatalog.get(key)
        assert spec is not None
        assert spec.description
        assert spec.language
        assert spec.engine in {"piper", "kokoro", "edge"}

        if spec.engine == "piper":
            # No Piper cada voz tem seu par (.onnx, .onnx.json).
            assert spec.modelUrl.endswith(".onnx")
            assert spec.configUrl.endswith(".onnx.json")
            assert spec.speaker is None
        elif spec.engine == "kokoro":
            # No Kokoro o pacote é compartilhado e a voz é escolhida por nome.
            assert spec.modelUrl.endswith(".onnx")
            assert spec.configUrl.endswith(".bin")
            assert spec.speaker
        else:
            # Na nuvem não há arquivo nenhum, só o nome da voz a pedir.
            assert not spec.modelUrl
            assert not spec.configUrl
            assert spec.speaker

    def testTemVozEmCadaMotor(self) -> None:
        motores = {v.engine for v in voiceCatalog.CATALOG.values()}
        assert motores == {"piper", "kokoro", "edge"}

    @pytest.mark.parametrize("key", voiceCatalog.names())
    def testSoVozesOnlinePrecisamDeReserva(self, key: str) -> None:
        """Uma voz offline não precisa de plano B; uma online precisa, e no idioma dela."""
        spec = voiceCatalog.get(key)
        assert spec is not None
        reserva = voiceCatalog.fallbackFor(key)

        if spec.engine != "edge":
            assert reserva is None
            return

        assert reserva is not None, f"{key} roda na nuvem e ficaria muda sem internet"
        alvo = voiceCatalog.get(reserva)
        assert alvo is not None
        assert alvo.engine != "edge", "a reserva de uma voz online tem de rodar offline"
        assert alvo.language == spec.language, "cair para outro idioma não ajuda ninguém"

    def testAReservaELeveEmMaquinaModesta(self) -> None:
        """Num Raspberry Pi, cair numa voz pesada troca um problema por outro.

        As vozes Kokoro soam melhor, mas são 325 MB e sintetizam a ~0,4x do
        tempo real. Num Pi isso transformaria "sem internet" em "fala
        arrastada" — pior que o problema original. Por isso o hardware modesto
        cai nas vozes Piper, oito vezes mais rápidas.
        """
        pesada = voiceCatalog.fallbackFor("francisca", light=False)
        leve = voiceCatalog.fallbackFor("francisca", light=True)

        assert pesada != leve
        assert voiceCatalog.CATALOG[pesada].engine == "kokoro"
        assert voiceCatalog.CATALOG[leve].engine == "piper"
        assert voiceCatalog.CATALOG[leve].language == "pt", "a reserva tem de falar a língua"

    def testVozesOnlineNaoTemOQueBaixar(self) -> None:
        assert not voiceCatalog.needsDownload("thalita")
        assert voiceCatalog.needsDownload("dora")

    def testVozesKokoroCompartilhamOsArquivos(self, tmp_path: Path) -> None:
        """Baixar a segunda voz Kokoro não deve baixar nada de novo."""
        dora = voiceCatalog.CATALOG["dora"].targetPaths(tmp_path)
        heart = voiceCatalog.CATALOG["heart"].targetPaths(tmp_path)
        assert dora == heart

    def testVozesPiperNaoCompartilhamArquivos(self, tmp_path: Path) -> None:
        dii = voiceCatalog.CATALOG["dii"].targetPaths(tmp_path)
        faber = voiceCatalog.CATALOG["faber"].targetPaths(tmp_path)
        assert dii != faber

    def testBuscaIgnoraCaixaEEspacos(self) -> None:
        assert voiceCatalog.get("  DII ") is voiceCatalog.get("dii")

    def testVozDesconhecidaDevolveNone(self) -> None:
        assert voiceCatalog.get("inexistente") is None

    def testIdiomaDeVozDesconhecidaCaiNoPadrao(self) -> None:
        assert voiceCatalog.languageOf("inexistente", default="xx") == "xx"

    def testCaminhosDerivamDoNome(self, tmp_path: Path) -> None:
        modelo, config = voiceCatalog.CATALOG["dii"].targetPaths(tmp_path)
        assert modelo == tmp_path / "dii" / "dii.onnx"
        assert config == tmp_path / "dii" / "dii.onnx.json"


class TestSelecaoDeVoz:
    def testNomeDaVozResolveOCaminho(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)

        settings = VoiceSettings.fromEnv()

        assert settings.voice == "dii"
        assert settings.modelPath.name == "dii.onnx"
        assert settings.language == "pt"

    def testCaminhoExplicitoTemPrecedencia(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        monkeypatch.setenv("ROBOTEYE_VOICE_MODEL", "/tmp/outro/modelo.onnx")

        assert VoiceSettings.fromEnv().modelPath.name == "modelo.onnx"

    def testVozDesconhecidaListaAsOpcoes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "inexistente")
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)

        with pytest.raises(ConfigError, match="dii"):
            VoiceSettings.fromEnv()

    def testNomeDaVozIgnoraCaixa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "DII")
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)

        assert VoiceSettings.fromEnv().voice == "dii"

    def testModelPathForVoiceRejeitaDesconhecida(self) -> None:
        with pytest.raises(ConfigError, match="desconhecida"):
            modelPathForVoice("inexistente")


class TestSelecaoDeMotor:
    """Cada voz sabe em qual motor roda; `auto` respeita isso."""

    def voice(self, monkeypatch: pytest.MonkeyPatch, **env: str) -> VoiceSettings:
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)
        for chave, valor in env.items():
            monkeypatch.setenv(f"ROBOTEYE_{chave}", valor)
        return VoiceSettings.fromEnv()

    def testAutoUsaOMotorDaVozPiper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.voice(monkeypatch, VOICE="dii", TTS_BACKEND="auto").engine == "piper"

    def testAutoUsaOMotorDaVozKokoro(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.voice(monkeypatch, VOICE="dora", TTS_BACKEND="auto").engine == "kokoro"

    def testBackendExplicitoTemAPalavraFinal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Regressão: com TTS_BACKEND=piper no .env, uma voz Kokoro era carregada
        # pelo motor errado e quebrava ao ler o .onnx.
        assert self.voice(monkeypatch, VOICE="dora", TTS_BACKEND="null").engine == "null"

    def testVozKokoroTrazONomeDoFalante(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.voice(monkeypatch, VOICE="dora").speaker == "pf_dora"

    def testVozPiperNaoTemFalante(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert self.voice(monkeypatch, VOICE="dii").speaker is None

    def testFalantePodeSerSobrescrito(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = self.voice(monkeypatch, VOICE="dora", VOICE_SPEAKER="pm_santa")
        assert settings.speaker == "pm_santa"

    def testConfigDoKokoroApontaParaOPacote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = self.voice(monkeypatch, VOICE="dora")
        assert settings.resolvedConfigPath().name == "voices.bin"

    def testConfigDoPiperApontaParaOJson(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = self.voice(monkeypatch, VOICE="dii")
        assert settings.resolvedConfigPath().name == "dii.onnx.json"


class TestFabricaDeMotores:
    def testCriaOMotorCertoParaCadaVoz(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from roboteye.speech.factory import createTtsEngine

        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)
        monkeypatch.setenv("ROBOTEYE_TTS_BACKEND", "auto")

        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        assert createTtsEngine(VoiceSettings.fromEnv()).name == "piper"

        monkeypatch.setenv("ROBOTEYE_VOICE", "dora")
        assert createTtsEngine(VoiceSettings.fromEnv()).name == "kokoro"


class TestIdiomaDerivadoDaVoz:
    """De nada adianta uma voz brasileira se o modelo responde em inglês."""

    def settings(self, tmp_path: Path) -> Settings:
        return Settings.fromEnv(envFile=tmp_path / "inexistente.env")

    def testVozBrasileiraFazResponderEmPortugues(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)
        monkeypatch.delenv("ROBOTEYE_REPLY_LANGUAGE", raising=False)

        assert self.settings(tmp_path).llm.replyLanguage == "pt"

    def testVozInglesaFazResponderEmIngles(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "lessac")
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)
        monkeypatch.delenv("ROBOTEYE_REPLY_LANGUAGE", raising=False)

        assert self.settings(tmp_path).llm.replyLanguage == "en"

    def testEscolhaExplicitaDoUsuarioTemAPalavraFinal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)
        monkeypatch.setenv("ROBOTEYE_REPLY_LANGUAGE", "en")

        assert self.settings(tmp_path).llm.replyLanguage == "en"


class TestPersonalidadePorIdioma:
    def testPromptPedePortuguesDoBrasil(self, tmp_path: Path) -> None:
        from roboteye.llm.persona import PersonaStore

        prompt = PersonaStore(tmp_path, "atlas").load("pt").systemPrompt()
        assert "Brazilian Portuguese" in prompt
