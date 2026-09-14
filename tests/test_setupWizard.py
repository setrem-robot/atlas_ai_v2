"""Testes do assistente de primeira configuração."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from roboteye import setupWizard
from roboteye.config import Settings
from roboteye.llm.probe import ProbeResult
from roboteye.setupWizard import Answers, Prompt, runSetup
from roboteye.web import envfile

EXEMPLO = """\
# Comentário que explica a chave abaixo.
ROBOTEYE_LLM_BACKEND=ollama
ROBOTEYE_OLLAMA_HOST=http://localhost:11434
ROBOTEYE_LLM_MODEL=llama3.2:1b

# Voz
ROBOTEYE_VOICE=francisca
ROBOTEYE_PERSONA=atlas
"""


@pytest.fixture
def projeto(tmp_path: Path) -> Path:
    """Um repositório recém-clonado: tem o exemplo, não tem o `.env`."""
    (tmp_path / ".env.example").write_text(EXEMPLO, encoding="utf-8")
    persona = tmp_path / "persona"
    persona.mkdir()
    (persona / "atlas.md").write_text(
        "<!-- comentário do arquivo -->\n# Quem você é\nVocê é a Atlas, da Setrem.\n",
        encoding="utf-8",
    )
    (persona / "iris.md").write_text(
        "# Quem você é\nVocê é a Íris, uma IA de bordo.\n", encoding="utf-8"
    )
    (persona / "atlas.memoria.md").write_text("fato\n", encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def semRedeNemDownload(monkeypatch: pytest.MonkeyPatch) -> None:
    """O assistente nunca toca na rede durante os testes."""
    monkeypatch.setattr(
        setupWizard,
        "probeOllama",
        lambda host, **_: ProbeResult(
            ok=True,
            host=setupWizard.normalizeHost(host),
            latencyMs=7,
            models=("llama3.2:1b", "qwen3:8b"),
        ),
    )
    monkeypatch.setattr(
        "roboteye.voices.downloadVoice",
        lambda chave, **_: Path(f"/models/{chave}.onnx"),
    )


def falas(respostas: list[str]) -> Iterator[str]:
    return iter(respostas)


def promptCom(respostas: list[str], saida: list[str] | None = None) -> Prompt:
    """Um terminal dublê: lê de uma fila e guarda o que foi impresso."""
    fila = falas(respostas)
    registro = saida if saida is not None else []
    return Prompt(read=lambda _: next(fila, ""), write=registro.append, interactive=True)


class TestPrompt:
    def testEnterAceitaOPadrao(self) -> None:
        assert promptCom([""]).text("modelo", "qwen3:8b") == "qwen3:8b"

    def testEscolhaPorNumero(self) -> None:
        prompt = promptCom(["2"])
        opcoes = [("a", ""), ("b", ""), ("c", "")]
        assert prompt.choice("qual", opcoes, default="a") == "b"

    def testEscolhaPeloProprioNome(self) -> None:
        prompt = promptCom(["c"])
        assert prompt.choice("qual", [("a", ""), ("c", "")], default="a") == "c"

    def testRespostaInvalidaPerguntaDeNovo(self) -> None:
        saida: list[str] = []
        prompt = promptCom(["9", "1"], saida)
        assert prompt.choice("qual", [("a", ""), ("b", "")], default="a") == "a"
        assert any("nao entendi" in linha for linha in saida)

    def testSemTerminalDevolveOPadraoSemPerguntar(self) -> None:
        def explode(_: str) -> str:
            raise AssertionError("nao deveria ter perguntado")

        prompt = Prompt(read=explode, write=lambda _: None, interactive=False)
        assert prompt.text("modelo", "llama3.2:1b") == "llama3.2:1b"
        assert prompt.choice("qual", [("a", "")], default="a") == "a"
        assert prompt.yesNo("baixar?", default=False) is False

    @pytest.mark.parametrize(
        ("resposta", "esperado"), [("s", True), ("sim", True), ("n", False), ("", True)]
    )
    def testSimOuNao(self, resposta: str, esperado: bool) -> None:
        assert promptCom([resposta]).yesNo("baixar?", default=True) is esperado


class TestGravacao:
    def testCriaOEnvAPartirDoExemplo(self, projeto: Path) -> None:
        runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(ollama="1.2.3.4", model="qwen3:8b", voice="dii", persona="iris"),
            Prompt(write=lambda _: None, interactive=False),
            envPath=projeto / ".env",
            projectRoot=projeto,
        )

        conteudo = (projeto / ".env").read_text(encoding="utf-8")
        # O comentário do exemplo é a documentação que fica na máquina: editar o
        # arquivo não pode apagá-lo.
        assert "# Comentário que explica a chave abaixo." in conteudo

        valores = envfile.read(projeto / ".env")
        assert valores["ROBOTEYE_OLLAMA_HOST"] == "http://1.2.3.4:11434"
        assert valores["ROBOTEYE_LLM_MODEL"] == "qwen3:8b"
        assert valores["ROBOTEYE_VOICE"] == "dii"
        assert valores["ROBOTEYE_PERSONA"] == "iris"

    def testSemIaConfiguraOModoEcho(self, projeto: Path) -> None:
        plano = runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(noLlm=True, voice="dii", persona="atlas"),
            Prompt(write=lambda _: None, interactive=False),
            envPath=projeto / ".env",
            projectRoot=projeto,
        )

        assert plano.values["ROBOTEYE_LLM_BACKEND"] == "echo"
        # Sem IA não se grava endereço nenhum: o que estava lá continua valendo
        # para quando a máquina da IA voltar.
        assert "ROBOTEYE_OLLAMA_HOST" not in plano.values

    def testBaixaAVozEscolhidaEAReserva(
        self, projeto: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pedidas: list[str] = []
        monkeypatch.setattr(
            "roboteye.voices.downloadVoice",
            lambda chave, **_: pedidas.append(chave) or Path("x"),
        )
        monkeypatch.setattr(setupWizard.voiceCatalog, "needsDownload", lambda _: True)

        plano = runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(noLlm=True, voice="francisca", persona="atlas"),
            Prompt(write=lambda _: None, interactive=False),
            envPath=projeto / ".env",
            projectRoot=projeto,
        )

        # `francisca` fala pela nuvem; a reserva offline é o arquivo que precisa
        # estar no disco antes de a internet cair.
        assert pedidas[0] == "francisca"
        assert len(pedidas) == 2
        assert plano.downloads == tuple(pedidas)

    def testSkipDownloadNaoBaixaNada(
        self, projeto: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "roboteye.voices.downloadVoice",
            lambda *_, **__: pytest.fail("não deveria baixar"),
        )
        plano = runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(noLlm=True, voice="dii", skipDownload=True),
            Prompt(write=lambda _: None, interactive=False),
            envPath=projeto / ".env",
            projectRoot=projeto,
        )
        assert plano.downloads == ()


class TestDialogo:
    def testFluxoCompletoEscolhendoPelosNumeros(self, projeto: Path) -> None:
        saida: list[str] = []
        # onde=1 (local), modelo=2 (qwen3:8b), voz=1, persona=2
        prompt = promptCom(["1", "2", "1", "2"], saida)

        plano = runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(skipDownload=True),
            prompt,
            envPath=projeto / ".env",
            projectRoot=projeto,
        )

        assert plano.values["ROBOTEYE_OLLAMA_HOST"] == "http://localhost:11434"
        assert plano.values["ROBOTEYE_LLM_MODEL"] == "qwen3:8b"
        assert plano.values["ROBOTEYE_PERSONA"] == "iris"
        assert any("respondeu em 7 ms" in linha for linha in saida)

    def testEscolherNenhumaIaNaoTestaEndereco(
        self, projeto: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            setupWizard,
            "probeOllama",
            lambda *_, **__: pytest.fail("não deveria sondar sem IA"),
        )
        # onde=3 (nenhuma), voz=1, persona=1
        plano = runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(skipDownload=True),
            promptCom(["3", "1", "1"]),
            envPath=projeto / ".env",
            projectRoot=projeto,
        )
        assert plano.values["ROBOTEYE_LLM_BACKEND"] == "echo"

    def testEnderecoQueFalhaPodeSerCorrigidoNaHora(
        self, projeto: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tentativas: list[str] = []

        def sonda(host: str, **_: object) -> ProbeResult:
            tentativas.append(host)
            if "9.9.9.9" in host:
                return ProbeResult(ok=False, host=host, error="conexao recusada")
            return ProbeResult(ok=True, host=setupWizard.normalizeHost(host), models=("m:1b",))

        monkeypatch.setattr(setupWizard, "probeOllama", sonda)
        saida: list[str] = []
        # onde=2 (rede) -> endereço errado -> corrige -> modelo -> voz -> persona
        prompt = promptCom(["2", "9.9.9.9", "192.168.0.7", "1", "1", "1"], saida)

        plano = runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(skipDownload=True),
            prompt,
            envPath=projeto / ".env",
            projectRoot=projeto,
        )

        assert tentativas == ["9.9.9.9", "192.168.0.7"]
        assert plano.values["ROBOTEYE_OLLAMA_HOST"] == "http://192.168.0.7:11434"
        assert any("falhou: conexao recusada" in linha for linha in saida)

    def testMaquinaSemModeloSugereEEnsinaOPull(
        self, projeto: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            setupWizard,
            "probeOllama",
            lambda host, **_: ProbeResult(ok=True, host=setupWizard.normalizeHost(host)),
        )
        # Sem `ollama` nesta máquina, o assistente ensina o comando em vez de tentar.
        monkeypatch.setattr(setupWizard.shutil, "which", lambda _: None)
        saida: list[str] = []
        prompt = promptCom(["1", "1", "1", "1"], saida)

        plano = runSetup(
            Settings.fromEnv(envFile=projeto / ".nao-existe"),
            Answers(skipDownload=True),
            prompt,
            envPath=projeto / ".env",
            projectRoot=projeto,
        )

        assert plano.values["ROBOTEYE_LLM_MODEL"] == setupWizard.MODEL_SUGGESTIONS[0][0]
        assert any("ollama pull" in linha for linha in saida)


class TestPersonas:
    def testListaIgnoraOsArquivosDeMemoria(self, projeto: Path) -> None:
        encontradas = setupWizard.availablePersonas(projeto / "persona")
        assert [nome for nome, _ in encontradas] == ["atlas", "iris"]
        # O título é o mesmo nas duas ("Quem você é"); o que distingue uma da
        # outra é a primeira frase, e é ela que a lista mostra.
        assert encontradas[0][1] == "Você é a Atlas, da Setrem."
        assert encontradas[1][1] == "Você é a Íris, uma IA de bordo."

    def testDiretorioVazioNaoQuebra(self, tmp_path: Path) -> None:
        assert setupWizard.availablePersonas(tmp_path) == []
