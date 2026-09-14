"""Testes da página de configuração e da edição do `.env`."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from roboteye.config import ConfigError
from roboteye.web import ConfigServer, WebConfig, envfile, generatePin
from roboteye.web.conversa import ConversaWeb
from roboteye.web.server import validate

EXEMPLO = """\
# Comentario que explica a chave
ROBOTEYE_VOICE=dii
# Outro comentario

ROBOTEYE_LLM_MODEL=qwen3:8b
"""


@pytest.fixture
def env(tmp_path: Path) -> Path:
    caminho = tmp_path / ".env"
    caminho.write_text(EXEMPLO, encoding="utf-8")
    return caminho


class TestEnvFile:
    def testLeAsChaves(self, env: Path) -> None:
        assert envfile.read(env) == {
            "ROBOTEYE_VOICE": "dii",
            "ROBOTEYE_LLM_MODEL": "qwen3:8b",
        }

    def testArquivoInexistenteLeVazio(self, tmp_path: Path) -> None:
        assert envfile.read(tmp_path / "nao-existe") == {}

    def testOsComentariosSobrevivem(self, env: Path) -> None:
        """Um `.env` é mais explicação do que configuração.

        Reescrevê-lo a partir de um dicionário deixaria quem o abrisse depois
        com uma lista de chaves sem nenhuma pista do que cada uma faz.
        """
        envfile.update(env, {"ROBOTEYE_VOICE": "francisca"})
        texto = env.read_text(encoding="utf-8")

        assert "# Comentario que explica a chave" in texto
        assert "# Outro comentario" in texto
        assert envfile.read(env)["ROBOTEYE_VOICE"] == "francisca"

    def testAOrdemDasChavesSeMantem(self, env: Path) -> None:
        envfile.update(env, {"ROBOTEYE_VOICE": "dora"})
        linhas = [linha for linha in env.read_text(encoding="utf-8").splitlines() if "=" in linha]
        assert linhas[0].startswith("ROBOTEYE_VOICE")

    def testChaveNovaVaiParaOFim(self, env: Path) -> None:
        envfile.update(env, {"ROBOTEYE_WEB_PIN": "424242"})
        assert envfile.read(env)["ROBOTEYE_WEB_PIN"] == "424242"
        assert "ROBOTEYE_VOICE=dii" in env.read_text(encoding="utf-8")

    def testChavesDesconhecidasFicamOndeEstao(self, env: Path) -> None:
        env.write_text(EXEMPLO + "MINHA_VAR=nao-mexa\n", encoding="utf-8")
        envfile.update(env, {"ROBOTEYE_VOICE": "dii"})
        assert "MINHA_VAR=nao-mexa" in env.read_text(encoding="utf-8")

    def testValorComEspacoOuCerquilhaGanhaAspas(self, env: Path) -> None:
        envfile.update(env, {"ROBOTEYE_EYE_COLOR": "#04C9FD"})
        assert envfile.read(env)["ROBOTEYE_EYE_COLOR"] == "#04C9FD"

    def testChaveRepetidaFicaConsistente(self, env: Path) -> None:
        """Um `.env` editado à mão pode ter a mesma chave duas vezes.

        O que não pode acontecer é o arquivo ficar com dois valores diferentes
        para a mesma chave depois de um salvamento — quem lê pegaria um, quem
        edita depois pegaria outro.
        """
        env.write_text(EXEMPLO + "ROBOTEYE_VOICE=francisca\n", encoding="utf-8")
        envfile.update(env, {"ROBOTEYE_VOICE": "dora"})

        valores = [
            linha.split("=", 1)[1]
            for linha in env.read_text(encoding="utf-8").splitlines()
            if linha.startswith("ROBOTEYE_VOICE=")
        ]
        assert set(valores) == {"dora"}

    def testEscritaEAtomica(self, env: Path, monkeypatch) -> None:
        """Se a energia cair no meio, sobra o arquivo antigo — não meio arquivo."""
        original = env.read_text(encoding="utf-8")

        def explode(*args, **kwargs):
            raise OSError("energia acabou")

        monkeypatch.setattr("os.replace", explode)
        with pytest.raises(OSError):
            envfile.update(env, {"ROBOTEYE_VOICE": "dora"})

        assert env.read_text(encoding="utf-8") == original
        assert not list(env.parent.glob(".*tmp")), "sobrou arquivo temporário"


class TestValidacao:
    def testRecusaConfiguracaoInvalida(self, env: Path) -> None:
        envfile.update(env, {"ROBOTEYE_VOICE": "nao-existe"})
        with pytest.raises(ConfigError, match="desconhecida"):
            validate(env)

    def testEnxergaOArquivoENaoOAmbiente(self, env: Path, monkeypatch) -> None:
        """Regressão: a conferência aprovava qualquer coisa.

        `Settings.from_env` usa `load_dotenv(override=False)`, que respeita o
        que já está no ambiente. Como o robô carrega o `.env` ao subir, os
        valores antigos continuavam em `os.environ` e o arquivo recém-escrito
        era ignorado — inclusive com uma voz que não existe.
        """
        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        envfile.update(env, {"ROBOTEYE_VOICE": "dora"})

        assert validate(env).voice.voice == "dora", "leu o ambiente em vez do arquivo"

    def testDevolveOAmbienteAoQueEra(self, env: Path, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_VOICE", "dii")
        validate(env)
        import os

        assert os.environ["ROBOTEYE_VOICE"] == "dii"


class TestServidor:
    @pytest.fixture
    def servidor(self, env: Path):
        config = WebConfig(host="127.0.0.1", port=0, pin="123456", envPath=env)
        server = ConfigServer(config)
        server.start()
        yield f"http://127.0.0.1:{server.port}"
        server.stop()

    def pedir(self, base: str, rota: str, corpo=None, pin: str = "123456"):
        req = urllib.request.Request(base + rota, method="GET" if corpo is None else "POST")
        req.add_header("X-Pin", pin)
        dados = None
        if corpo is not None:
            req.add_header("Content-Type", "application/json")
            dados = json.dumps(corpo).encode()
        try:
            with urllib.request.urlopen(req, dados, timeout=10) as resposta:
                return resposta.status, json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            return erro.code, json.loads(erro.read())

    def testAPaginaAbreSemPin(self, servidor: str) -> None:
        """O PIN protege o que muda o robô, não a tela de digitar o PIN."""
        with urllib.request.urlopen(servidor + "/", timeout=10) as resposta:
            assert resposta.status == 200
            assert b"RobotEye" in resposta.read()

    def testApiExigePin(self, servidor: str) -> None:
        status, _ = self.pedir(servidor, "/api/state", pin="000000")
        assert status == 401

    def testPinForaDoAsciiERecusadoComResposta(self, servidor: str) -> None:
        """Errar o PIN tem de dar 401, e não deixar o cliente pendurado.

        `secrets.compare_digest` levanta TypeError com texto fora do ASCII, e a
        conferência acontece fora do `try` do handler: a requisição morria sem
        resposta nenhuma, com um traceback no log acusando o lugar errado.
        """
        status, _ = self.pedir(servidor, "/api/state", pin="12345ç")
        assert status == 401

    def testEstadoListaVozesEPersonas(self, servidor: str) -> None:
        status, dados = self.pedir(servidor, "/api/state")
        assert status == 200
        assert dados["config"]["ROBOTEYE_VOICE"] == "dii"
        assert any(v["key"] == "francisca" and v["online"] for v in dados["vozes"])

    def testSalvarGravaNoArquivo(self, servidor: str, env: Path) -> None:
        status, dados = self.pedir(servidor, "/api/config", {"ROBOTEYE_VOICE": "dora"})
        assert status == 200 and dados["salvo"] == 1
        assert envfile.read(env)["ROBOTEYE_VOICE"] == "dora"

    def testConfiguracaoInvalidaEDesfeita(self, servidor: str, env: Path) -> None:
        """Salvar algo inválido só apareceria no próximo arranque, longe daqui."""
        self.pedir(servidor, "/api/config", {"ROBOTEYE_VOICE": "dora"})
        status, _ = self.pedir(servidor, "/api/config", {"ROBOTEYE_VOICE": "nao-existe"})

        assert status == 500
        assert envfile.read(env)["ROBOTEYE_VOICE"] == "dora", "deixou o arquivo quebrado"

    def testOTamanhoDoModeloDeEscutaEEditavelPelaPagina(
        self, servidor: str, env: Path
    ) -> None:
        """Trocar entre rápido e preciso não pode exigir SSH.

        É a mesma ideia que já vale para a voz: o que se troca no dia a dia sai
        do `.env` e vai para a página do celular.
        """
        status, dados = self.pedir(
            servidor, "/api/config", {"ROBOTEYE_HEARING_MODEL_SIZE": "tiny"}
        )
        assert status == 200, dados
        assert envfile.read(env)["ROBOTEYE_HEARING_MODEL_SIZE"] == "tiny"

    def testTamanhoDeModeloInventadoERecusado(self, servidor: str, env: Path) -> None:
        """O `faster-whisper` BAIXA o que pedirem: um erro de digitação viraria
        uma tentativa de download de um modelo inexistente, no arranque, com a
        escuta desligando em silêncio."""
        status, _ = self.pedir(servidor, "/api/config", {"ROBOTEYE_HEARING_MODEL_SIZE": "gigante"})
        assert status == 500
        # O desfazer grava a chave de volta com o valor anterior — aqui, vazio.
        # O que importa é que o valor inventado não ficou.
        assert envfile.read(env).get("ROBOTEYE_HEARING_MODEL_SIZE", "") != "gigante"

    def testSoGravaChavesConhecidas(self, servidor: str, env: Path) -> None:
        """A página não pode virar um editor livre do ambiente do processo."""
        self.pedir(servidor, "/api/config", {"PATH": "/comprometido"})
        assert "PATH" not in envfile.read(env)

    def testTestarIaNumEnderecoMortoExplicaOQueHouve(self, servidor: str) -> None:
        status, dados = self.pedir(servidor, "/api/test/llm", {"host": "127.0.0.1:9"})
        assert status == 200
        assert dados["ok"] is False
        assert dados["erro"], "uma falha sem explicação não ajuda quem está de pé na frente do robô"

    def testTestarIaSemEndereco(self, servidor: str) -> None:
        _, dados = self.pedir(servidor, "/api/test/llm", {"host": "  "})
        assert dados["ok"] is False

    def testRotaDesconhecida(self, servidor: str) -> None:
        status, _ = self.pedir(servidor, "/api/nao-existe", {})
        assert status == 404


def testPinTemSeisDigitos() -> None:
    pin = generatePin()
    assert len(pin) == 6 and pin.isdigit()


class TestConversa:
    """A conversa pela pagina — a unica entrada de texto do robo instalado."""

    def testEntregaOQueFoiDigitado(self) -> None:
        entregues: list[str] = []
        conversa = ConversaWeb(entregues.append)
        conversa.enviar("  oi, tudo bem?  ")
        assert entregues == ["oi, tudo bem?"]

    def testTextoVazioNaoIncomodaORobo(self) -> None:
        entregues: list[str] = []
        conversa = ConversaWeb(entregues.append)
        conversa.enviar("   ")
        assert entregues == []
        assert conversa.falas() == []

    def testGuardaOsDoisLadosDaConversa(self) -> None:
        conversa = ConversaWeb(lambda _: None)
        conversa.enviar("quem e voce?")
        conversa.anotar("atlas", "Sou a Atlas.")
        assert conversa.falas() == [
            {"quem": "voce", "texto": "quem e voce?"},
            {"quem": "atlas", "texto": "Sou a Atlas."},
        ]

    def testNaoCresceSemLimite(self) -> None:
        # O processo fica ligado o dia inteiro; guardar tudo seria vazamento.
        conversa = ConversaWeb(lambda _: None)
        for i in range(ConversaWeb.LIMITE * 3):
            conversa.anotar("voce", f"mensagem {i}")
        falas = conversa.falas()
        assert len(falas) == ConversaWeb.LIMITE
        assert falas[-1]["texto"] == f"mensagem {ConversaWeb.LIMITE * 3 - 1}"

    def testFalasEUmaCopia(self) -> None:
        # Quem le nao pode mexer no historico de quem escreve.
        conversa = ConversaWeb(lambda _: None)
        conversa.anotar("voce", "oi")
        conversa.falas().clear()
        assert len(conversa.falas()) == 1


class TestRotaDeConversa:
    @pytest.fixture
    def entregues(self) -> list[str]:
        return []

    @pytest.fixture
    def servidorComRobo(self, env: Path, entregues: list[str]):
        config = WebConfig(
            host="127.0.0.1",
            port=0,
            pin="123456",
            envPath=env,
            conversa=ConversaWeb(entregues.append),
        )
        server = ConfigServer(config)
        server.start()
        yield f"http://127.0.0.1:{server.port}"
        server.stop()

    @pytest.fixture
    def servidorSozinho(self, env: Path):
        # `roboteye web` sem robo rodando: nao ha com quem conversar.
        config = WebConfig(host="127.0.0.1", port=0, pin="123456", envPath=env)
        server = ConfigServer(config)
        server.start()
        yield f"http://127.0.0.1:{server.port}"
        server.stop()

    def pedir(self, base: str, rota: str, corpo=None, pin: str = "123456"):
        req = urllib.request.Request(base + rota, method="GET" if corpo is None else "POST")
        req.add_header("X-Pin", pin)
        dados = None
        if corpo is not None:
            req.add_header("Content-Type", "application/json")
            dados = json.dumps(corpo).encode()
        try:
            with urllib.request.urlopen(req, dados) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def testMensagemChegaAoRobo(self, servidorComRobo: str, entregues: list[str]) -> None:
        status, corpo = self.pedir(servidorComRobo, "/api/conversar", {"texto": "ola"})
        assert status == 200
        assert corpo == {"enviado": "ola"}
        assert entregues == ["ola"]

    def testOEstadoMostraAConversa(self, servidorComRobo: str) -> None:
        self.pedir(servidorComRobo, "/api/conversar", {"texto": "ola"})
        _, corpo = self.pedir(servidorComRobo, "/api/state")
        assert corpo["conversa"]["disponivel"] is True
        assert corpo["conversa"]["falas"] == [{"quem": "voce", "texto": "ola"}]

    def testSemRoboAPaginaDizIsso(self, servidorSozinho: str) -> None:
        _, corpo = self.pedir(servidorSozinho, "/api/conversar", {"texto": "ola"})
        assert "erro" in corpo

    def testSemRoboOEstadoEscondeAConversa(self, servidorSozinho: str) -> None:
        _, corpo = self.pedir(servidorSozinho, "/api/state")
        assert corpo["conversa"]["disponivel"] is False

    def testConversaTambemExigeOPIN(
        self, servidorComRobo: str, entregues: list[str]
    ) -> None:
        status, _ = self.pedir(servidorComRobo, "/api/conversar", {"texto": "ola"}, pin="000000")
        assert status == 401
        assert entregues == []
