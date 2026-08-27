"""Interface de linha de comando.

roboteye run       face + chat de texto (padrao)
roboteye chat      apenas o chat de texto
roboteye face      apenas a face animada
roboteye say TEXT  fala um texto e sai
roboteye setup     configuracao inicial (IA, modelo e voz)
roboteye models    lista os modelos da maquina da IA
roboteye doctor    diagnostico do ambiente
roboteye memoria   onde a RAM do robo esta indo
roboteye radio     Wi-Fi e Bluetooth disputando a mesma antena?
roboteye preview   salva um PNG com todas as expressoes
roboteye voice ... gerencia os modelos de voz
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import threading
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from roboteye import __version__, voice_catalog
from roboteye.config import ConfigError, Settings
from roboteye.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roboteye",
        description="A face animada da Atlas: olhos, IA e voz local.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"roboteye {__version__}")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="sobrescreve ROBOTEYE_LOG_LEVEL",
    )
    parser.add_argument("--env-file", help="caminho de um .env alternativo")

    subparsers = parser.add_subparsers(dest="command")

    def add_voice_option(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--voice",
            metavar="NOME",
            help=f"voz do catalogo ({', '.join(voice_catalog.names())}); "
            "sobrescreve ROBOTEYE_VOICE",
        )

    def add_persona_option(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--persona",
            metavar="NOME",
            help="personagem a carregar de persona/<nome>.md; sobrescreve ROBOTEYE_PERSONA",
        )

    run = subparsers.add_parser("run", help="face animada + chat de texto (padrao)")
    run.add_argument("--fullscreen", action="store_true", help="abre a face em tela cheia")
    run.add_argument("--no-face", action="store_true", help="roda apenas o chat")
    add_voice_option(run)
    add_persona_option(run)
    run.set_defaults(handler=_command_run)

    chat = subparsers.add_parser("chat", help="apenas o chat de texto no terminal")
    add_voice_option(chat)
    add_persona_option(chat)
    chat.set_defaults(handler=_command_chat)

    face = subparsers.add_parser("face", help="apenas a face animada")
    face.add_argument("--fullscreen", action="store_true", help="abre a face em tela cheia")
    face.set_defaults(handler=_command_face)

    say = subparsers.add_parser("say", help="sintetiza um texto e sai")
    say.add_argument("text", nargs="+", help="texto a ser falado")
    say.add_argument("--output", help="salva em um arquivo WAV em vez de tocar")
    add_voice_option(say)
    say.set_defaults(handler=_command_say)

    doctor = subparsers.add_parser("doctor", help="verifica dependencias, voz e LLM")
    doctor.set_defaults(handler=_command_doctor)

    memoria = subparsers.add_parser("memoria", help="mostra onde a RAM do robo esta indo")
    memoria.add_argument("--json", action="store_true", help="saida em JSON, para graficos")
    memoria.set_defaults(handler=_command_memoria)

    radio = subparsers.add_parser(
        "radio", help="diz se o Wi-Fi e o Bluetooth estao brigando pela mesma antena"
    )
    radio.set_defaults(handler=_command_radio)

    setup = subparsers.add_parser(
        "setup",
        help="configuracao inicial: onde roda a IA, qual modelo e qual voz",
        description=(
            "Assistente de primeira configuracao. Pergunta onde roda a IA, testa o "
            "endereco, deixa escolher entre os modelos que a maquina realmente tem, "
            "escolhe a voz e grava tudo no .env sem apagar os comentarios."
        ),
    )
    setup.add_argument("--ollama", metavar="IP:PORTA", help="endereco da maquina com o Ollama")
    setup.add_argument("--model", metavar="NOME", help="modelo de linguagem (ex.: llama3.2:3b)")
    setup.add_argument("--no-llm", action="store_true", help="configura sem IA (modo echo)")
    setup.add_argument(
        "--non-interactive",
        action="store_true",
        help="nao pergunta nada; usa as flags e mantem o resto",
    )
    setup.add_argument(
        "--skip-download", action="store_true", help="nao baixa o modelo de voz ao final"
    )
    add_voice_option(setup)
    add_persona_option(setup)
    setup.set_defaults(handler=_command_setup)

    models = subparsers.add_parser("models", help="lista os modelos disponiveis na maquina da IA")
    models.add_argument(
        "--ollama", metavar="IP:PORTA", help="outro endereco, so para esta consulta"
    )
    models.set_defaults(handler=_command_models)

    preview = subparsers.add_parser("preview", help="salva um PNG com todas as expressoes da face")
    preview.add_argument("--output", default="preview.png", help="arquivo de saida")
    preview.set_defaults(handler=_command_preview)

    web = subparsers.add_parser("web", help="pagina de configuracao, para abrir do celular")
    web.add_argument("--port", type=int, help="porta (padrao: 8080)")
    web.set_defaults(handler=_command_web)

    ble = subparsers.add_parser("ble", help="ponte bluetooth: o celular controla o robo sem ESP32")
    ble.add_argument("--nome", default="Atlas", help="nome que aparece na busca do celular")
    ble.add_argument("--mqtt-host", default="127.0.0.1", help="broker (padrao: 127.0.0.1)")
    ble.add_argument("--mqtt-port", type=int, default=1883, help="porta do broker")
    ble.set_defaults(handler=_command_ble)

    voice = subparsers.add_parser("voice", help="gerencia modelos de voz")
    voice_subparsers = voice.add_subparsers(dest="voice_command", required=True)

    voice_list = voice_subparsers.add_parser("list", help="lista as vozes do catalogo")
    voice_list.set_defaults(handler=_command_voice_list)

    voice_download = voice_subparsers.add_parser("download", help="baixa uma voz")
    voice_download.add_argument(
        "key",
        nargs="?",
        default=voice_catalog.DEFAULT_VOICE,
        help=f"voz (padrao: {voice_catalog.DEFAULT_VOICE})",
    )
    voice_download.add_argument("--force", action="store_true", help="rebaixa mesmo se existir")
    voice_download.set_defaults(handler=_command_voice_download)

    voice_ensure = voice_subparsers.add_parser(
        "ensure",
        help="baixa o que a configuracao atual precisa (voz e reserva offline)",
    )
    voice_ensure.set_defaults(handler=_command_voice_ensure)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Sem subcomando, `run` e o padrao.
    if getattr(args, "handler", None) is None:
        args = parser.parse_args([*(argv or []), "run"])

    try:
        settings = Settings.from_env(env_file=args.env_file)
    except ConfigError as exc:
        print(f"erro de configuracao: {exc}", file=sys.stderr)
        return EXIT_ERROR

    configure_logging(args.log_level or settings.log_level)

    try:
        settings = _apply_voice_override(args, settings)
    except ConfigError as exc:
        print(f"erro de configuracao: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        return int(args.handler(args, settings))
    except KeyboardInterrupt:
        print()
        logger.info("interrompido pelo usuario")
        return EXIT_OK


# ---------------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _config_page(settings: Settings, app: Any = None):
    """Sobe a pagina de configuracao junto com o robo.

    E o modo como ela sera usada de verdade: o robo liga sozinho no arranque, de
    tela cheia e sem teclado, e a unica forma de mexer nele passa a ser o
    navegador do celular. Subir a pagina separado exigiria lembrar de faze-lo —
    exatamente na hora em que ninguem consegue digitar nada no robo.

    Com um `app`, a pagina tambem conversa: e a unica entrada de texto que o robo
    instalado tem, ja que o servico sobe sem terminal. Sem ele — `roboteye web`
    rodando sozinho —, a pagina segue servindo para configurar.

    Falhar aqui nao pode derrubar o robo: uma porta ocupada e um aborrecimento,
    nao um motivo para a face nao acender.
    """
    if not settings.web.enabled:
        yield None
        return

    from roboteye.web import ConfigServer

    config = build_web_config(settings)
    comandos = None
    if settings.web.mostrar_comandos:
        from roboteye.web.comandos import ComandosRecebidos

        comandos = ComandosRecebidos()
        comandos.escutar(host=settings.web.mqtt_host, port=settings.web.mqtt_port)

    if app is not None:
        config = replace(
            config,
            comandos=comandos,
            conversa=_conversa_do(app),
            # O atualizador pergunta isto antes de reiniciar o robo: ninguem quer
            # a face sumindo no meio de uma frase.
            ocupado=app.assistant.is_busy,
        )
    server = ConfigServer(config)
    try:
        server.start()
    except OSError as exc:
        logger.warning("pagina de configuracao indisponivel: %s", exc)
        yield None
        return

    print(announce_web(config), flush=True)
    try:
        yield server
    finally:
        server.stop()


def _conversa_do(app: Any):
    """Liga a pagina ao robo: ela entrega o texto, ele devolve o que respondeu.

    A ligacao mora aqui, e nao dentro da pagina, pela mesma razao de sempre
    neste projeto: quem monta as pecas e quem as conhece. `ConversaWeb` nao sabe
    o que e um `Assistant`, e o `Assistant` nao sabe que existe uma pagina.
    """
    from roboteye.core.events import AssistantReply, ErrorOccurred
    from roboteye.web.conversa import ConversaWeb

    conversa = ConversaWeb(app.assistant.submit)
    app.bus.subscribe(lambda e: conversa.anotar("atlas", e.text), event_type=AssistantReply)
    app.bus.subscribe(lambda e: conversa.anotar("erro", e.message), event_type=ErrorOccurred)
    return conversa


# A pagina precisa do robo montado para conversar com ele, entao o `Application`
# vem primeiro nos `with` — ao contrario da ordem que estes comandos tinham.
def _command_run(args: argparse.Namespace, settings: Settings) -> int:
    from roboteye.app import Application

    settings = _apply_face_overrides(args, settings)
    with Application.build(settings) as app, _config_page(settings, app):
        app.run_interactive()
    return EXIT_OK


def _command_chat(_: argparse.Namespace, settings: Settings) -> int:
    from roboteye.app import Application

    with Application.build(settings) as app, _config_page(settings, app):
        app.run_chat()
    return EXIT_OK


def _command_face(args: argparse.Namespace, settings: Settings) -> int:
    from roboteye.app import Application

    settings = _apply_face_overrides(args, settings)
    with Application.build(settings) as app, _config_page(settings, app):
        app.run_face()
    return EXIT_OK


def _command_ble(args: argparse.Namespace, _settings: Settings) -> int:
    """Poe o robo no ar pelo bluetooth e entrega os comandos aos motores.

    Substitui o par ESP32 + `serial_ingestor`: o celular fala com o Pi direto, e
    o que chega vai para o mesmo topico MQTT de sempre.
    """
    from roboteye.ble import EntregaMqtt, PonteBLE, anunciar_pelo_kernel

    entrega = EntregaMqtt(host=args.mqtt_host, port=args.mqtt_port)
    entrega.conectar()

    if not anunciar_pelo_kernel(args.nome):
        logger.error("sem anuncio no ar, o celular nao vai achar o robo")
        return EXIT_ERROR

    ponte = PonteBLE(entrega, nome=args.nome)
    try:
        # Bloqueia no laco de eventos do D-Bus ate o servico ser encerrado.
        ponte.anunciar()
    except KeyboardInterrupt:
        logger.info("encerrando a ponte bluetooth")
    finally:
        entrega.fechar()
    return EXIT_OK


def _command_say(args: argparse.Namespace, settings: Settings) -> int:
    import wave

    from roboteye.speech.base import SpeechError
    from roboteye.speech.factory import create_tts_engine
    from roboteye.speech.player import create_audio_sink
    from roboteye.speech.speaker import synthesize_polished

    text = " ".join(args.text)
    engine = create_tts_engine(settings.voice)

    def audio():
        # O mesmo caminho que o robo usa, para que `say` sirva de conferencia:
        # com normalizacao do texto e com o acabamento do audio.
        return synthesize_polished(engine, text, language=settings.voice.language)

    try:
        if args.output:
            _write_wav(audio(), args.output, wave)
            print(f"audio salvo em {args.output}")
            return EXIT_OK

        sink = create_audio_sink(settings.voice)
        try:
            for chunk in audio():
                sink.start(chunk.format)
                sink.write(chunk.audio)
        finally:
            sink.close()
    except SpeechError as exc:
        print(f"erro de voz: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        engine.close()

    return EXIT_OK


def _write_wav(stream, path: str, wave_module) -> None:
    chunks = list(stream)
    if not chunks:
        raise RuntimeError("nenhum audio foi gerado")

    audio_format = chunks[0].format
    with wave_module.open(path, "wb") as handle:
        handle.setnchannels(audio_format.channels)
        handle.setsampwidth(audio_format.sample_width)
        handle.setframerate(audio_format.sample_rate)
        for chunk in chunks:
            handle.writeframes(chunk.audio)


def _command_doctor(_: argparse.Namespace, settings: Settings) -> int:
    from roboteye.diagnostics import run_diagnostics

    report = run_diagnostics(settings)
    print(report.render())
    return EXIT_OK if report.ok else EXIT_ERROR


def _command_memoria(args: argparse.Namespace, settings: Settings) -> int:
    """Mostra de quem e a memoria que o robo esta gastando."""
    from roboteye.memoria import medir, render_json

    # O Ollama que interessa e o do proprio Pi: e ele que ocupa RAM aqui. O da
    # maquina de mesa gasta a memoria dela, e nao ha o que otimizar daqui.
    local = settings.llm.fallback_host or _host_se_local(settings.llm.host)
    relatorio = medir(ollama_host=local)
    print(render_json(relatorio) if args.json else relatorio.render())
    return EXIT_OK if relatorio.folgado or bool(relatorio.erro) else EXIT_ERROR


def _command_radio(_: argparse.Namespace, __: Settings) -> int:
    """Diz se o Wi-Fi e o Bluetooth estao disputando a mesma faixa."""
    from roboteye.radio import aconselhar, medir, render

    estado = medir()
    print(render(estado))
    return EXIT_OK if not aconselhar(estado) else EXIT_ERROR


def _host_se_local(host: str) -> str:
    """O endereco do LLM, mas so quando ele aponta para esta maquina."""
    return host if any(marca in host for marca in ("127.0.0.1", "localhost", "::1")) else ""


def _command_setup(args: argparse.Namespace, settings: Settings) -> int:
    """Assistente de primeira configuracao."""
    from roboteye.config import PROJECT_ROOT
    from roboteye.setup_wizard import Answers, Prompt, run_setup

    answers = Answers(
        ollama=args.ollama,
        model=args.model,
        voice=args.voice,
        persona=args.persona,
        no_llm=args.no_llm,
        non_interactive=args.non_interactive,
        skip_download=args.skip_download,
    )
    # Sem terminal de verdade — num script, num servico — perguntar seria
    # esperar por uma resposta que nunca chega. Ali o assistente so aplica o que
    # veio nas flags.
    prompt = Prompt(interactive=not args.non_interactive and _stdin_is_tty())

    env_path = Path(args.env_file) if args.env_file else PROJECT_ROOT / ".env"
    run_setup(settings, answers, prompt, env_path=env_path)
    return EXIT_OK


def _stdin_is_tty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):  # stdin fechado
        return False


def _command_models(args: argparse.Namespace, settings: Settings) -> int:
    """Lista o que a maquina da IA tem instalado.

    A alternativa e entrar por SSH na outra maquina para rodar `ollama list` —
    e o robo ja sabe o endereco.
    """
    from roboteye.llm.probe import probe_ollama

    resultado = probe_ollama(args.ollama or settings.llm.host)
    if not resultado.ok:
        print(f"{resultado.host}: {resultado.error}", file=sys.stderr)
        return EXIT_ERROR

    print(f"\n{resultado.host} respondeu em {resultado.latency_ms} ms\n")
    if not resultado.models:
        print("  nenhum modelo instalado.")
        print("  na maquina da IA: ollama pull llama3.2:3b\n")
        return EXIT_OK

    for nome in resultado.models:
        marca = "*" if nome == settings.llm.model else " "
        print(f" {marca} {nome}")
    print("\n  * = em uso")
    print("  troque com ROBOTEYE_LLM_MODEL no .env, ou com `roboteye setup`\n")
    return EXIT_OK


def _command_preview(args: argparse.Namespace, settings: Settings) -> int:
    from pathlib import Path

    from roboteye.face.preview import render_sheet

    caminho = render_sheet(settings.face, Path(args.output))
    print(f"folha de expressoes salva em {caminho}")
    return EXIT_OK


def _command_voice_list(_: argparse.Namespace, settings: Settings) -> int:
    from roboteye.voices import CATALOG, DEFAULT_MODELS_DIR

    print("\nVozes disponiveis:\n")
    for key, spec in sorted(CATALOG.items()):
        model_path, config_path = spec.target_paths(DEFAULT_MODELS_DIR)
        baixada = model_path.is_file() and config_path.is_file()

        marca = "*" if key == settings.voice.voice else " "
        estado = "baixada" if baixada else "nao baixada"
        print(f" {marca} {key:<8} [{spec.language}] {spec.description}")
        print(f"   {'':<8} {estado}; licenca: {spec.license_note or 'nao informada'}")

    print("\n  * = voz em uso")
    print("\nPara trocar:")
    print("  roboteye voice download <nome>     baixa o modelo")
    print("  roboteye --help                    (ou --voice <nome> em run/chat/say)")
    print("  ROBOTEYE_VOICE=<nome> no .env      torna a troca permanente\n")
    return EXIT_OK


def _command_web(args: argparse.Namespace, settings: Settings) -> int:
    """Sobe so a pagina de configuracao e fica esperando."""
    from roboteye.web import ConfigServer

    config = build_web_config(settings, port=args.port)
    print(announce_web(config))
    print("  Ctrl+C encerra.\n")

    server = ConfigServer(config)
    server.start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("encerrado")
    finally:
        server.stop()
    return EXIT_OK


def build_web_config(settings: Settings, *, port: int | None = None):
    """Monta a configuracao da pagina, sorteando um PIN se nao houver um.

    O PIN sorteado nao e gravado: ele vale enquanto o robo estiver de pe. Quem
    quiser um PIN fixo define ROBOTEYE_WEB_PIN — o que e o normal numa
    instalacao de verdade, para nao precisar olhar o log a cada reinicio.
    """
    from roboteye.web import WebConfig, generate_pin

    return WebConfig(
        host=settings.web.host,
        port=port or settings.web.port,
        pin=settings.web.pin or generate_pin(),
    )


def announce_web(config) -> str:
    """Texto que ensina como chegar na pagina."""
    enderecos = _local_addresses() if config.host in {"0.0.0.0", ""} else [config.host]
    linhas = ["Configuracao pelo navegador:"]
    linhas += [f"  http://{host}:{config.port}" for host in enderecos]
    linhas.append(f"  PIN: {config.pin}")
    return "\n".join(linhas)


def _local_addresses() -> list[str]:
    """IPs pelos quais o robo pode ser alcancado na rede."""
    import socket

    enderecos = []
    try:
        # Nao envia nada: so faz o sistema escolher a interface de saida, que e
        # a que os outros aparelhos da rede conseguem alcancar.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sonda:
            sonda.connect(("8.8.8.8", 80))
            enderecos.append(sonda.getsockname()[0])
    except OSError:
        pass
    enderecos.append("localhost")
    return enderecos


def _command_voice_ensure(_: argparse.Namespace, settings: Settings) -> int:
    """Baixa tudo que a configuracao atual precisa para falar.

    Existe para a instalacao: quem esta implantando sabe qual voz quer, nao quais
    arquivos ela exige. Uma voz da nuvem nao tem modelo para baixar, mas a
    reserva offline dela tem — e e justamente a reserva que precisa estar no
    disco antes de a rede faltar, nao depois.
    """
    from roboteye import voice_catalog
    from roboteye.voices import VoiceDownloadError, console_progress, download_voice

    alvos = [settings.voice.voice]
    reserva = settings.voice.fallback_voice()
    if reserva:
        alvos.append(reserva)

    baixou = False
    for chave in alvos:
        if not voice_catalog.needs_download(chave):
            print(f"{chave}: roda na nuvem, nao ha o que baixar")
            continue
        try:
            download_voice(chave, on_progress=console_progress)
        except VoiceDownloadError as exc:
            print(f"erro ao baixar {chave}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        baixou = True

    if not baixou and not any(voice_catalog.needs_download(c) for c in alvos):
        print("nada a baixar: esta configuracao fala inteiramente pela nuvem")
    return EXIT_OK


def _command_voice_download(args: argparse.Namespace, _: Settings) -> int:
    from roboteye.voices import VoiceDownloadError, console_progress, download_voice

    try:
        path = download_voice(args.key, force=args.force, on_progress=console_progress)
    except VoiceDownloadError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return EXIT_ERROR

    print(f"\nvoz pronta em {path}")
    print(f'Experimente:        roboteye say --voice {args.key} "ola, tudo bem?"')
    print(f"Para fixar no .env: ROBOTEYE_VOICE={args.key}")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _apply_voice_override(args: argparse.Namespace, settings: Settings) -> Settings:
    """Aplica `--voice` e `--persona`, relendo a configuracao.

    Em vez de remendar o objeto ja montado, as flags viram variaveis de ambiente
    e a configuracao e reconstruida: assim tudo que depende delas — o caminho do
    modelo, o motor de voz, o idioma da resposta — e resolvido num lugar so.
    """
    voice = getattr(args, "voice", None)
    persona = getattr(args, "persona", None)
    if not voice and not persona:
        return settings

    if voice:
        os.environ["ROBOTEYE_VOICE"] = voice
        # Um caminho explicito no .env teria prioridade sobre o nome; a flag manda.
        os.environ.pop("ROBOTEYE_VOICE_MODEL", None)
        os.environ.pop("ROBOTEYE_VOICE_CONFIG", None)

    if persona:
        os.environ["ROBOTEYE_PERSONA"] = persona

    return Settings.from_env(env_file=args.env_file)


def _apply_face_overrides(args: argparse.Namespace, settings: Settings) -> Settings:
    """Aplica as flags de linha de comando sobre a configuracao do ambiente."""
    from dataclasses import replace

    face = settings.face
    if getattr(args, "fullscreen", False):
        face = replace(face, fullscreen=True)
    if getattr(args, "no_face", False):
        face = replace(face, enabled=False)
    return replace(settings, face=face)


if __name__ == "__main__":
    raise SystemExit(main())
