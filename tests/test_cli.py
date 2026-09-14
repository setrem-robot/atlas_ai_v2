"""Testes da linha de comando e do diagnóstico."""

from __future__ import annotations

import pytest

from roboteye import voiceCatalog
from roboteye.cli import buildParser, main
from roboteye.config import FaceSettings, LLMSettings, Settings, VoiceSettings
from roboteye.diagnostics import Status, runDiagnostics


@pytest.fixture(autouse=True)
def ambienteLimpo(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Isola os testes do `.env` e da configuração real da máquina."""
    monkeypatch.setenv("ROBOTEYE_LLM_BACKEND", "echo")
    monkeypatch.setenv("ROBOTEYE_TTS_BACKEND", "null")
    monkeypatch.setenv("ROBOTEYE_FACE_ENABLED", "false")
    monkeypatch.setenv("ROBOTEYE_VOICE_MODEL", str(tmp_path / "voz.onnx"))


class TestParser:
    @pytest.mark.parametrize(
        "argumentos",
        [
            ["run"],
            ["chat"],
            ["face"],
            ["say", "texto"],
            ["doctor"],
            ["setup"],
            ["setup", "--no-llm", "--non-interactive"],
            ["models"],
            ["voice", "list"],
            ["voice", "download"],
        ],
    )
    def testSubcomandosDisponiveis(self, argumentos: list[str]) -> None:
        assert buildParser().parse_args(argumentos).handler is not None

    def testVoiceExigeUmSubcomando(self) -> None:
        with pytest.raises(SystemExit):
            buildParser().parse_args(["voice"])

    def testSayJuntaAsPalavras(self) -> None:
        args = buildParser().parse_args(["say", "olá", "mundo"])
        assert args.text == ["olá", "mundo"]

    def testFullscreenEOpcional(self) -> None:
        assert buildParser().parse_args(["run"]).fullscreen is False
        assert buildParser().parse_args(["run", "--fullscreen"]).fullscreen is True

    def testVoiceDownloadTemPadrao(self) -> None:
        padrao = buildParser().parse_args(["voice", "download"]).key
        assert padrao == voiceCatalog.DEFAULT_VOICE

    @pytest.mark.parametrize("comando", [["run"], ["chat"], ["say", "oi"]])
    def testVoicePodeSerTrocadaNaLinhaDeComando(self, comando: list[str]) -> None:
        assert buildParser().parse_args([*comando, "--voice", "dii"]).voice == "dii"

    def testComandoInvalidoEncerra(self) -> None:
        with pytest.raises(SystemExit):
            buildParser().parse_args(["inexistente"])


class TestComandos:
    def testVoiceListListaOCatalogo(self, capsys) -> None:
        assert main(["voice", "list"]) == 0
        assert voiceCatalog.DEFAULT_VOICE in capsys.readouterr().out

    def testVoiceDownloadDesconhecidaFalha(self, capsys) -> None:
        assert main(["voice", "download", "inexistente"]) == 1

    def testDoctorRodaSemExplodir(self) -> None:
        # Com backends echo/null e modelo inexistente, deve reportar falha, não travar.
        assert main(["doctor"]) in (0, 1)

    def testSayComTtsMudoAvisaQueNaoGerouAudio(self, tmp_path, capsys) -> None:
        destino = tmp_path / "saida.wav"
        with pytest.raises(RuntimeError, match="nenhum audio"):
            main(["say", "olá", "--output", str(destino)])

    def testConfiguracaoInvalidaRetornaErro(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("ROBOTEYE_FACE_WIDTH", "isso-nao-e-numero")
        assert main(["doctor"]) == 1
        assert "configuracao" in capsys.readouterr().err

    def testVoiceInexistenteNaLinhaDeComandoRetornaErro(self, capsys) -> None:
        assert main(["say", "oi", "--voice", "inexistente"]) == 1
        assert "inexistente" in capsys.readouterr().err

    def testModelsListaOQueAMaquinaDaIaTem(self, monkeypatch, capsys) -> None:
        from roboteye.llm.probe import ProbeResult

        monkeypatch.setattr(
            "roboteye.llm.probe.probeOllama",
            lambda *_, **__: ProbeResult(
                ok=True, host="http://ia:11434", latencyMs=9, models=("a:1b", "b:8b")
            ),
        )
        assert main(["models"]) == 0
        assert "a:1b" in capsys.readouterr().out

    def testModelsComMaquinaForaDoArRetornaErro(self, monkeypatch, capsys) -> None:
        from roboteye.llm.probe import ProbeResult

        monkeypatch.setattr(
            "roboteye.llm.probe.probeOllama",
            lambda *_, **__: ProbeResult(ok=False, host="http://ia:11434", error="recusado"),
        )
        assert main(["models"]) == 1
        assert "recusado" in capsys.readouterr().err

    def testSetupNaoInterativoGravaOEnv(self, tmp_path, monkeypatch, capsys) -> None:
        from roboteye.web import envfile

        env = tmp_path / ".env"
        env.write_text("# meu comentario\nROBOTEYE_VOICE=francisca\n", encoding="utf-8")
        monkeypatch.setattr(
            "roboteye.voices.downloadVoice", lambda *_, **__: tmp_path / "voz.onnx"
        )

        codigo = main(
            [
                "--env-file",
                str(env),
                "setup",
                "--non-interactive",
                "--no-llm",
                "--voice",
                "dii",
                "--skip-download",
            ]
        )

        assert codigo == 0
        valores = envfile.read(env)
        assert valores["ROBOTEYE_VOICE"] == "dii"
        assert valores["ROBOTEYE_LLM_BACKEND"] == "echo"
        assert "# meu comentario" in env.read_text(encoding="utf-8")

    def testVoiceListMarcaAVozEmUso(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        monkeypatch.delenv("ROBOTEYE_VOICE_MODEL", raising=False)

        assert main(["voice", "list"]) == 0

        linhaMarcada = next(
            linha for linha in capsys.readouterr().out.splitlines() if linha.startswith(" *")
        )
        assert "dii" in linhaMarcada


class TestDiagnostics:
    def settings(self, **kwargs) -> Settings:
        base = {
            "llm": LLMSettings(backend="echo"),
            "voice": VoiceSettings(backend="null"),
            "face": FaceSettings(),
        }
        return Settings(**{**base, **kwargs})

    def testRelatorioTemUmaLinhaPorVerificacao(self) -> None:
        relatorio = runDiagnostics(self.settings())
        assert len(relatorio.checks) >= 4
        assert "Diagnostico do RobotEye" in relatorio.render()

    def testBackendMudoGeraAvisoENaoFalha(self) -> None:
        relatorio = runDiagnostics(self.settings())
        voz = [c for c in relatorio.checks if c.name == "motor de voz"]
        assert voz and voz[0].status is Status.WARN
        assert relatorio.ok

    def testModeloAusenteEFalhaComDica(self, tmp_path) -> None:
        settings = self.settings(
            voice=VoiceSettings(backend="piper", modelPath=tmp_path / "nao-existe.onnx")
        )
        relatorio = runDiagnostics(settings)

        modelo = [c for c in relatorio.checks if c.name == "modelo de voz"]
        if modelo:  # só aparece se o piper estiver instalado
            assert modelo[0].status is Status.FAIL
            assert "voice download" in modelo[0].hint
            assert not relatorio.ok
