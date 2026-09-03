"""Pagina de configuracao servida pelo proprio robo.

O robo roda de tela cheia, sem teclado e muitas vezes preso atras de um monitor.
Trocar a voz ou apontar para outra maquina de IA exigia abrir um terminal noutro
computador, achar o IP, entrar por SSH e editar um arquivo. Aqui isso vira abrir
o navegador do celular.

**O que ela resolve de verdade.** A IA roda noutra maquina, alcancada por VPN, e
esse endereco muda: troca de rede, troca de servidor, VPN que caiu. O botao que
testa a conexao *antes* de salvar e a razao de existir desta pagina — sem ele,
descobrir que o endereco esta errado exige reiniciar o robo e esperar ele falhar
falando.

**Sobre seguranca.** A pagina mostra e altera enderecos da rede interna, faz o
robo falar e reinicia o servico. Numa rede de faculdade isso nao pode ficar
aberto, entao ha um PIN. Ele nao pretende resistir a um atacante determinado com
acesso a rede — pretende impedir que qualquer um que descubra a porta mexa no
robo. Para valer contra mais que isso, ponha o robo numa VLAN propria.

Nao ha framework aqui de proposito: uma pagina e cinco rotas cabem na biblioteca
padrao, e o robo nao precisa carregar um servidor web inteiro na memoria para
isso.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from roboteye.config import PROJECT_ROOT, Settings
from roboteye.logging_setup import get_logger
from roboteye.web import envfile
from roboteye.web.comandos import ComandosRecebidos
from roboteye.web.conversa import ConversaWeb
from roboteye.web.estado import instantaneo
from roboteye.web.page import PAGE

logger = get_logger(__name__)

DEFAULT_PORT = 8080

#: Depois de tantas tentativas erradas de PIN, o servidor para de responder por
#: um tempo. Um PIN de seis digitos cai rapido a forca bruta sem isto.
MAX_ATTEMPTS = 5
LOCKOUT_SECONDS = 60.0

#: Chaves que a pagina pode escrever. Uma lista fechada e o que impede a pagina
#: de virar um editor arbitrario do ambiente do processo.
EDITABLE = (
    "ROBOTEYE_OLLAMA_HOST",
    "ROBOTEYE_LLM_MODEL",
    "ROBOTEYE_LLM_BACKEND",
    "ROBOTEYE_VOICE",
    "ROBOTEYE_VOICE_FALLBACK",
    "ROBOTEYE_VOICE_GAIN",
    "ROBOTEYE_VOICE_LENGTH_SCALE",
    "ROBOTEYE_PERSONA",
    "ROBOTEYE_REPLY_LANGUAGE",
    "ROBOTEYE_FACE_FULLSCREEN",
    "ROBOTEYE_FACE_QUALITY",
    "ROBOTEYE_EYE_COLOR",
    "ROBOTEYE_LOG_LEVEL",
)


@dataclass(frozen=True, slots=True)
class WebConfig:
    """Como a pagina de configuracao sobe."""

    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    pin: str = ""
    env_path: Path = PROJECT_ROOT / ".env"
    #: Presente quando ha um robo vivo do outro lado para conversar. Ausente
    #: quando a pagina sobe sozinha (`roboteye web`), onde nao ha com quem falar.
    conversa: ConversaWeb | None = None
    #: Diz se a Atlas esta no meio de uma resposta. Quem pergunta e o script de
    #: atualizacao, para nao reiniciar o robo com ela falando.
    ocupado: Callable[[], bool] | None = None
    #: O que o robo esta recebendo do controle. Presente quando ha broker.
    comandos: ComandosRecebidos | None = None


class _Gatekeeper:
    """Confere o PIN e segura quem erra demais."""

    def __init__(self, pin: str) -> None:
        self._pin = pin
        self._lock = threading.Lock()
        self._failures = 0
        self._blocked_until = 0.0

    def allows(self, offered: str | None) -> bool:
        with self._lock:
            if time.monotonic() < self._blocked_until:
                return False
            # Comparacao em tempo constante: um PIN curto comparado com `==`
            # vaza, pelo tempo de resposta, quantos digitos ja estao certos.
            #
            # `isascii()` antes: com texto fora do ASCII o `compare_digest`
            # levanta TypeError em vez de devolver False, e isso acontece fora
            # do `try` de quem chama — a requisicao morre sem resposta e o
            # cliente fica esperando. Um PIN nao-ASCII simplesmente nao confere.
            if offered and offered.isascii() and secrets.compare_digest(offered, self._pin):
                self._failures = 0
                return True

            self._failures += 1
            if self._failures >= MAX_ATTEMPTS:
                self._failures = 0
                self._blocked_until = time.monotonic() + LOCKOUT_SECONDS
                logger.warning(
                    "PIN errado %d vezes; pausando por %ds", MAX_ATTEMPTS, LOCKOUT_SECONDS
                )
            return False


class ConfigServer:
    """Servidor da pagina de configuracao, rodando numa thread propria."""

    def __init__(self, config: WebConfig) -> None:
        self._config = config
        self._gate = _Gatekeeper(config.pin)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else self._config.port

    def start(self) -> None:
        """Sobe o servidor em segundo plano. Idempotente."""
        if self._thread is not None:
            return

        handler = _make_handler(self._config, self._gate)
        self._server = ThreadingHTTPServer((self._config.host, self._config.port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="web", daemon=True)
        self._thread.start()
        logger.info("configuracao em http://%s:%d", _readable_host(self._config.host), self.port)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._thread = None

    def __enter__(self) -> ConfigServer:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def _make_handler(config: WebConfig, gate: _Gatekeeper) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "RobotEye"

        def log_message(self, fmt: str, *args: Any) -> None:
            # O log padrao do http.server escreve em stderr e polui o terminal
            # do chat. Rebaixa para debug.
            logger.debug("web: " + fmt, *args)

        # -- entrada -----------------------------------------------------
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            corpo = self._body()
            if path in {"/", "/index.html"}:
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/state":
                self._guarded(lambda _: _state(config), corpo)
            elif path == "/api/robo":
                # Separado do `/api/state` de proposito: este e consultado a
                # cada poucos segundos por uma pagina aberta, enquanto aquele
                # le o `.env` e o catalogo de vozes, que nao mudam sozinhos.
                self._guarded(lambda _: _robo(config), corpo)
            else:
                self._json(404, {"erro": "rota desconhecida"})

        def do_POST(self) -> None:
            path = urlparse(self.path).path
            # O corpo e lido antes de qualquer decisao, inclusive antes de saber
            # se a rota existe. Responder e fechar deixando bytes por ler no
            # socket faz o sistema mandar um RST em vez do fim limpo, e o
            # cliente recebe "conexao anulada" no lugar do 404 que o servidor
            # escreveu de verdade (WinError 10053 no Windows; no Linux depende
            # do tamanho do corpo e passa batido quase sempre).
            corpo = self._body()
            rotas = {
                "/api/config": lambda body: _save(config, body),
                "/api/test/llm": _test_llm,
                "/api/test/voice": _test_voice,
                "/api/restart": _restart,
                "/api/conversar": lambda body: _conversar(config, body),
                "/api/atualizar": _atualizar,
            }
            handler = rotas.get(path)
            if handler is None:
                self._json(404, {"erro": "rota desconhecida"})
                return
            self._guarded(handler, corpo)

        # -- apoio -------------------------------------------------------
        def _guarded(self, action, corpo: dict[str, Any]) -> None:
            if not gate.allows(self.headers.get("X-Pin")):
                self._json(401, {"erro": "PIN invalido ou tentativas demais"})
                return
            try:
                self._json(200, action(corpo))
            except Exception as exc:
                logger.exception("falha na pagina de configuracao")
                self._json(500, {"erro": str(exc)})

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload).encode("utf-8"), "application/json")

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _state(config: WebConfig) -> dict[str, Any]:
    """Configuracao atual mais o que o catalogo oferece."""
    from roboteye import voice_catalog

    valores = envfile.read(config.env_path)
    vozes = [
        {
            "key": key,
            "descricao": spec.description,
            "idioma": spec.language,
            "online": spec.engine == "edge",
        }
        for key, spec in sorted(voice_catalog.CATALOG.items())
    ]
    personas = sorted(
        p.stem for p in (PROJECT_ROOT / "persona").glob("*.md") if not p.stem.endswith(".memoria")
    )
    return {
        "config": {chave: valores.get(chave, "") for chave in EDITABLE},
        "vozes": vozes,
        "personas": personas,
        "conversa": {
            "disponivel": config.conversa is not None,
            "falas": config.conversa.falas() if config.conversa else [],
        },
        "ocupado": bool(config.ocupado and config.ocupado()),
        "atualizacao": {"disponivel": _atualizacao_instalada()},
    }


def _robo(config: WebConfig) -> dict[str, Any]:
    """Como o robo esta, mais o que ele esta obedecendo."""
    estado = instantaneo(PROJECT_ROOT)
    estado["controle"] = (
        config.comandos.instantaneo()
        if config.comandos is not None
        else {"atual": None, "recebendo": False, "ultimos": [], "total": 0}
    )
    return estado


#: Unidade systemd que traz a versao publicada. Ver `scripts/atualizar.sh`.
UPDATE_UNIT = "roboteye-update.service"


def _atualizacao_instalada() -> bool:
    """Se ha um robo instalado como servico, com o atualizador junto.

    Rodando da arvore de desenvolvimento nao ha unidade nenhuma, e o botao nao
    deve aparecer prometendo o que nao pode cumprir.
    """
    try:
        return (
            subprocess.run(
                ["systemctl", "cat", UPDATE_UNIT],
                capture_output=True,
                timeout=5,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _atualizar(_: dict[str, Any]) -> dict[str, Any]:
    """Dispara a busca pela versao publicada e volta na hora.

    Nao espera o resultado de proposito: a atualizacao reinicia justamente o
    processo que esta respondendo esta requisicao, entao esperar seria esperar a
    propria morte. O `--no-block` entrega ao systemd e devolve; quem quiser
    acompanhar le `journalctl -u roboteye-update`.
    """
    if not _atualizacao_instalada():
        return {"erro": f"{UPDATE_UNIT} nao esta instalado (rode o setup com --service)"}

    try:
        # `sudo -n`: a regra instalada pelo setup permite exatamente este
        # comando, sem senha. Falhar aqui quer dizer que a regra nao esta la.
        pronto = subprocess.run(
            ["sudo", "-n", "systemctl", "start", "--no-block", UPDATE_UNIT],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"erro": f"nao consegui disparar a atualizacao: {exc}"}

    if pronto.returncode != 0:
        detalhe = (pronto.stderr or pronto.stdout).strip()[:200]
        return {"erro": f"nao consegui disparar a atualizacao: {detalhe}"}
    return {"disparado": True}


def _conversar(config: WebConfig, body: dict[str, Any]) -> dict[str, Any]:
    """Entrega ao robo o que foi digitado no celular.

    A resposta desta chamada e so o aceite. O que a Atlas responde sai pela voz
    e pela face — e um robo, nao um chat — e aparece na pagina na proxima
    leitura do estado, que e como ela ja se atualiza.
    """
    if config.conversa is None:
        return {"erro": "nao ha robo rodando para conversar (a pagina subiu sozinha)"}

    texto = str(body.get("texto") or "").strip()
    if not texto:
        return {"erro": "texto vazio"}
    config.conversa.enviar(texto)
    return {"enviado": texto}


def _save(config: WebConfig, body: dict[str, Any]) -> dict[str, Any]:
    """Grava as chaves permitidas e confere que o resultado ainda carrega."""
    changes = {chave: str(body[chave]).strip() for chave in EDITABLE if chave in body}
    if not changes:
        return {"salvo": 0}

    anterior = envfile.read(config.env_path)
    envfile.update(config.env_path, changes)

    # Uma configuracao invalida so apareceria no proximo arranque, quando o robo
    # ja nao teria como avisar. Melhor conferir agora e desfazer.
    try:
        validate(config.env_path)
    except Exception as exc:
        envfile.update(config.env_path, {c: anterior.get(c, "") for c in changes})
        raise ValueError(f"configuracao recusada, nada foi mudado: {exc}") from exc

    return {"salvo": len(changes), "reiniciar": True}


#: `os.environ` e do processo inteiro, e a validacao precisa mexer nele.
#: Duas validacoes ao mesmo tempo se atrapalhariam.
_ENV_LOCK = threading.Lock()


def validate(env_path: Path) -> Settings:
    """Confere se o arquivo, como esta agora, produz uma configuracao valida.

    Nao da para simplesmente chamar `Settings.from_env(env_file=...)`: ela usa
    `load_dotenv(override=False)`, que respeita o que ja esta no ambiente. Como
    o robo carregou o `.env` ao subir, os valores antigos continuam em
    `os.environ` e o arquivo recem-escrito seria ignorado — a conferencia
    aprovaria qualquer coisa, inclusive uma voz que nao existe.

    Entao o ambiente e trocado pelo conteudo do arquivo, a configuracao e
    montada, e o ambiente volta ao que era. O robo em execucao nao percebe:
    ele so le a configuracao ao arrancar.
    """
    valores = envfile.read(env_path)
    anterior = dict(os.environ)

    with _ENV_LOCK:
        try:
            for chave in [c for c in os.environ if c.startswith("ROBOTEYE_")]:
                del os.environ[chave]
            os.environ.update({c: v for c, v in valores.items() if c.startswith("ROBOTEYE_")})
            # Um caminho inexistente impede `from_env` de recarregar o arquivo
            # por cima do ambiente que acabamos de montar.
            return Settings.from_env(env_file=env_path.parent / ".env.nao-existe")
        finally:
            os.environ.clear()
            os.environ.update(anterior)


def _test_llm(body: dict[str, Any]) -> dict[str, Any]:
    """Bate na maquina da IA e diz o que achou — sem precisar salvar antes.

    E o coracao da pagina. O endereco vem por VPN e muda de lugar; poder testar
    um candidato antes de grava-lo evita o ciclo de salvar, reiniciar e esperar
    o robo falhar falando para so entao descobrir que o IP estava errado.
    """
    from roboteye.llm.probe import probe_ollama

    resultado = probe_ollama(str(body.get("host") or ""))
    if not resultado.ok:
        return {"ok": False, "erro": resultado.error, "host": resultado.host}
    return {
        "ok": True,
        "host": resultado.host,
        "ms": resultado.latency_ms,
        "modelos": list(resultado.models),
    }


def _test_voice(body: dict[str, Any]) -> dict[str, Any]:
    """Faz o robo falar uma frase, para conferir voz e alto-falante de uma vez."""
    from roboteye.speech.factory import create_tts_engine
    from roboteye.speech.player import create_audio_sink
    from roboteye.speech.speaker import synthesize_polished

    texto = str(body.get("texto") or "Oi! Estou funcionando.").strip()[:200]
    settings = Settings.from_env()

    engine = create_tts_engine(settings.voice)
    sink = create_audio_sink(settings.voice)
    try:
        blocos = 0
        for chunk in synthesize_polished(engine, texto, language=settings.voice.language):
            sink.start(chunk.format)
            sink.write(chunk.audio)
            blocos += 1
    finally:
        sink.close()
        engine.close()

    return {"ok": blocos > 0, "voz": settings.voice.voice, "motor": settings.voice.engine}


def _restart(_: dict[str, Any]) -> dict[str, Any]:
    """Reinicia o servico para a configuracao nova valer.

    Tenta sem `sudo` primeiro (vale quando a pagina roda como root ou ha sessao
    ativa) e depois com `sudo -n`, que e o caminho no robo instalado: o servico
    roda como o usuario do robo e, sem sessao grafica, o polkit recusa o
    `systemctl restart` — em silencio, com codigo de saida 1 e nada no stderr.
    A regra que libera exatamente este comando e instalada por
    `scripts/setup-raspberry-pi.sh --service`.
    """
    import shutil
    import subprocess

    if shutil.which("systemctl") is None:
        return {"ok": False, "erro": "sem systemd aqui; reinicie o robo a mao"}

    tentativas = (
        ["systemctl", "restart", "roboteye.service"],
        ["sudo", "-n", "systemctl", "restart", "roboteye.service"],
    )
    ultimo = ""
    for comando in tentativas:
        try:
            resultado = subprocess.run(comando, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            ultimo = str(exc)
            continue
        if resultado.returncode == 0:
            return {"ok": True}
        ultimo = (resultado.stderr or resultado.stdout).strip() or "systemctl recusou"

    return {
        "ok": False,
        "erro": f"{ultimo} — rode o setup com --service para liberar o reinicio pela pagina",
    }


def _readable_host(host: str) -> str:
    return "<ip-do-robo>" if host in {"0.0.0.0", ""} else host


def generate_pin() -> str:
    """PIN de seis digitos, sorteado de forma criptografica."""
    return f"{secrets.randbelow(1_000_000):06d}"
