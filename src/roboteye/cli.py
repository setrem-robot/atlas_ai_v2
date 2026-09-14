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

from roboteye import __version__, voiceCatalog
from roboteye.config import ConfigError, Settings
from roboteye.loggingSetup import configureLogging, getLogger

logger = getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def buildParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="roboteye",
        description="A face animada da Atlas: olhos, IA e voz local.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"roboteye {__version__}")
    parser.add_argument(
        "--log-level",
        dest="logLevel",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="sobrescreve ROBOTEYE_LOG_LEVEL",
    )
    parser.add_argument("--env-file", help="caminho de um .env alternativo")

    subparsers = parser.add_subparsers(dest="command")

    def addVoiceOption(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--voice",
            metavar="NOME",
            help=f"voz do catalogo ({', '.join(voiceCatalog.names())}); "
            "sobrescreve ROBOTEYE_VOICE",
        )

    def addPersonaOption(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--persona",
            metavar="NOME",
            help="personagem a carregar de persona/<nome>.md; sobrescreve ROBOTEYE_PERSONA",
        )

    run = subparsers.add_parser("run", help="face animada + chat de texto (padrao)")
    run.add_argument("--fullscreen", action="store_true", help="abre a face em tela cheia")
    run.add_argument(
        "--no-face", dest="noFace", action="store_true", help="roda apenas o chat"
    )
    addVoiceOption(run)
    addPersonaOption(run)
    run.set_defaults(handler=commandRun)

    chat = subparsers.add_parser("chat", help="apenas o chat de texto no terminal")
    addVoiceOption(chat)
    addPersonaOption(chat)
    chat.set_defaults(handler=commandChat)

    face = subparsers.add_parser("face", help="apenas a face animada")
    face.add_argument("--fullscreen", action="store_true", help="abre a face em tela cheia")
    face.set_defaults(handler=commandFace)

    say = subparsers.add_parser("say", help="sintetiza um texto e sai")
    say.add_argument("text", nargs="+", help="texto a ser falado")
    say.add_argument("--output", help="salva em um arquivo WAV em vez de tocar")
    addVoiceOption(say)
    say.set_defaults(handler=commandSay)

    doctor = subparsers.add_parser("doctor", help="verifica dependencias, voz e LLM")
    doctor.set_defaults(handler=commandDoctor)

    memoria = subparsers.add_parser("memoria", help="mostra onde a RAM do robo esta indo")
    memoria.add_argument("--json", action="store_true", help="saida em JSON, para graficos")
    memoria.set_defaults(handler=commandMemoria)

    radio = subparsers.add_parser(
        "radio", help="diz se o Wi-Fi e o Bluetooth estao brigando pela mesma antena"
    )
    radio.set_defaults(handler=commandRadio)

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
    setup.add_argument(
        "--no-llm", dest="noLlm", action="store_true", help="configura sem IA (modo echo)"
    )
    setup.add_argument(
        "--non-interactive",
        dest="nonInteractive",
        action="store_true",
        help="nao pergunta nada; usa as flags e mantem o resto",
    )
    setup.add_argument(
        "--skip-download",
        dest="skipDownload",
        action="store_true",
        help="nao baixa o modelo de voz ao final",
    )
    addVoiceOption(setup)
    addPersonaOption(setup)
    setup.set_defaults(handler=commandSetup)

    models = subparsers.add_parser("models", help="lista os modelos disponiveis na maquina da IA")
    models.add_argument(
        "--ollama", metavar="IP:PORTA", help="outro endereco, so para esta consulta"
    )
    models.set_defaults(handler=commandModels)

    preview = subparsers.add_parser("preview", help="salva um PNG com todas as expressoes da face")
    preview.add_argument("--output", default="preview.png", help="arquivo de saida")
    preview.set_defaults(handler=commandPreview)

    web = subparsers.add_parser("web", help="pagina de configuracao, para abrir do celular")
    web.add_argument("--port", type=int, help="porta (padrao: 8080)")
    web.set_defaults(handler=commandWeb)

    ble = subparsers.add_parser("ble", help="ponte bluetooth: o celular controla o robo sem ESP32")
    ble.add_argument("--nome", default="Atlas", help="nome que aparece na busca do celular")
    ble.add_argument(
        "--mqtt-host", dest="mqttHost", default="127.0.0.1", help="broker (padrao: 127.0.0.1)"
    )
    ble.add_argument(
        "--mqtt-port", dest="mqttPort", type=int, default=1883, help="porta do broker"
    )
    ble.set_defaults(handler=commandBle)

    voice = subparsers.add_parser("voice", help="gerencia modelos de voz")
    voiceSubparsers = voice.add_subparsers(dest="voiceCommand", required=True)

    voiceList = voiceSubparsers.add_parser("list", help="lista as vozes do catalogo")
    voiceList.set_defaults(handler=commandVoiceList)

    voiceDownload = voiceSubparsers.add_parser("download", help="baixa uma voz")
    voiceDownload.add_argument(
        "key",
        nargs="?",
        default=voiceCatalog.DEFAULT_VOICE,
        help=f"voz (padrao: {voiceCatalog.DEFAULT_VOICE})",
    )
    voiceDownload.add_argument("--force", action="store_true", help="rebaixa mesmo se existir")
    voiceDownload.set_defaults(handler=commandVoiceDownload)

    voiceEnsure = voiceSubparsers.add_parser(
        "ensure",
        help="baixa o que a configuracao atual precisa (voz e reserva offline)",
    )
    voiceEnsure.set_defaults(handler=commandVoiceEnsure)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = buildParser()
    args = parser.parse_args(argv)

    # Sem subcomando, `run` e o padrao.
    if getattr(args, "handler", None) is None:
        args = parser.parse_args([*(argv or []), "run"])

    try:
        settings = Settings.fromEnv(envFile=args.env_file)
    except ConfigError as exc:
        print(f"erro de configuracao: {exc}", file=sys.stderr)
        return EXIT_ERROR

    configureLogging(args.logLevel or settings.logLevel)

    try:
        settings = applyVoiceOverride(args, settings)
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
def configPage(settings: Settings, app: Any = None):
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

    config = buildWebConfig(settings)
    comandos = None
    if settings.web.mostrarComandos:
        from roboteye.web.comandos import ComandosRecebidos

        comandos = ComandosRecebidos()
        comandos.escutar(host=settings.web.mqttHost, port=settings.web.mqttPort)

    if app is not None:
        config = replace(
            config,
            comandos=comandos,
            conversa=conversaDo(app),
            # O atualizador pergunta isto antes de reiniciar o robo: ninguem quer
            # a face sumindo no meio de uma frase.
            ocupado=app.assistant.isBusy,
        )
    server = ConfigServer(config)
    try:
        server.start()
    except OSError as exc:
        logger.warning("pagina de configuracao indisponivel: %s", exc)
        yield None
        return

    print(announceWeb(config), flush=True)
    try:
        yield server
    finally:
        server.stop()


def conversaDo(app: Any):
    """Liga a pagina ao robo: ela entrega o texto, ele devolve o que respondeu.

    A ligacao mora aqui, e nao dentro da pagina, pela mesma razao de sempre
    neste projeto: quem monta as pecas e quem as conhece. `ConversaWeb` nao sabe
    o que e um `Assistant`, e o `Assistant` nao sabe que existe uma pagina.
    """
    from roboteye.core.events import AssistantReply, ErrorOccurred
    from roboteye.web.conversa import ConversaWeb

    conversa = ConversaWeb(app.assistant.submit)
    app.bus.subscribe(lambda e: conversa.anotar("atlas", e.text), eventType=AssistantReply)
    app.bus.subscribe(lambda e: conversa.anotar("erro", e.message), eventType=ErrorOccurred)
    return conversa


# A pagina precisa do robo montado para conversar com ele, entao o `Application`
# vem primeiro nos `with` — ao contrario da ordem que estes comandos tinham.
def commandRun(args: argparse.Namespace, settings: Settings) -> int:
    from roboteye.app import Application

    settings = applyFaceOverrides(args, settings)
    with Application.build(settings) as app, configPage(settings, app):
        app.runInteractive()
    return EXIT_OK


def commandChat(_: argparse.Namespace, settings: Settings) -> int:
    from roboteye.app import Application

    with Application.build(settings) as app, configPage(settings, app):
        app.runChat()
    return EXIT_OK


def commandFace(args: argparse.Namespace, settings: Settings) -> int:
    from roboteye.app import Application

    settings = applyFaceOverrides(args, settings)
    with Application.build(settings) as app, configPage(settings, app):
        app.runFace()
    return EXIT_OK


def commandBle(args: argparse.Namespace, settings: Settings) -> int:
    """Poe o robo no ar pelo bluetooth e entrega os comandos aos motores.

    Substitui o par ESP32 + `serial_ingestor`: o celular fala com o Pi direto, e
    o que chega vai para o mesmo topico MQTT de sempre.
    """
    from roboteye.ble import EntregaMqtt, PonteBLE, anunciarPeloKernel

    entrega = EntregaMqtt(host=args.mqttHost, port=args.mqttPort)
    entrega.conectar()

    if not anunciarPeloKernel(args.nome):
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


def commandSay(args: argparse.Namespace, settings: Settings) -> int:
    import wave

    from roboteye.speech.base import SpeechError
    from roboteye.speech.factory import createTtsEngine
    from roboteye.speech.player import createAudioSink
    from roboteye.speech.speaker import synthesizePolished

    text = " ".join(args.text)
    engine = createTtsEngine(settings.voice)

    def audio():
        # O mesmo caminho que o robo usa, para que `say` sirva de conferencia:
        # com normalizacao do texto e com o acabamento do audio.
        return synthesizePolished(engine, text, language=settings.voice.language)

    try:
        if args.output:
            writeWav(audio(), args.output, wave)
            print(f"audio salvo em {args.output}")
            return EXIT_OK

        sink = createAudioSink(settings.voice)
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


def writeWav(stream, path: str, waveModule) -> None:
    chunks = list(stream)
    if not chunks:
        raise RuntimeError("nenhum audio foi gerado")

    audioFormat = chunks[0].format
    with waveModule.open(path, "wb") as handle:
        handle.setnchannels(audioFormat.channels)
        handle.setsampwidth(audioFormat.sampleWidth)
        handle.setframerate(audioFormat.sampleRate)
        for chunk in chunks:
            handle.writeframes(chunk.audio)


def commandDoctor(_: argparse.Namespace, settings: Settings) -> int:
    from roboteye.diagnostics import runDiagnostics

    report = runDiagnostics(settings)
    print(report.render())
    return EXIT_OK if report.ok else EXIT_ERROR


def commandMemoria(args: argparse.Namespace, settings: Settings) -> int:
    """Mostra de quem e a memoria que o robo esta gastando."""
    from roboteye.memoria import medir, renderJson

    # O Ollama que interessa e o do proprio Pi: e ele que ocupa RAM aqui. O da
    # maquina de mesa gasta a memoria dela, e nao ha o que otimizar daqui.
    local = settings.llm.fallbackHost or hostSeLocal(settings.llm.host)
    relatorio = medir(ollamaHost=local)
    print(renderJson(relatorio) if args.json else relatorio.render())
    return EXIT_OK if relatorio.folgado or bool(relatorio.erro) else EXIT_ERROR


def commandRadio(_: argparse.Namespace, __: Settings) -> int:
    """Diz se o Wi-Fi e o Bluetooth estao disputando a mesma faixa."""
    from roboteye.radio import aconselhar, medir, render

    estado = medir()
    # Uma conta so: `aconselhar` alimenta tanto o relatorio quanto o codigo de
    # saida. Antes rodava duas vezes — barato, mas repetido a toa.
    conselhos = aconselhar(estado)
    print(render(estado, conselhos))
    return EXIT_OK if not conselhos else EXIT_ERROR


def hostSeLocal(host: str) -> str:
    """O endereco do LLM, mas so quando ele aponta para esta maquina."""
    return host if any(marca in host for marca in ("127.0.0.1", "localhost", "::1")) else ""


def commandSetup(args: argparse.Namespace, settings: Settings) -> int:
    """Assistente de primeira configuracao."""
    from roboteye.config import PROJECT_ROOT
    from roboteye.setupWizard import Answers, Prompt, runSetup

    answers = Answers(
        ollama=args.ollama,
        model=args.model,
        voice=args.voice,
        persona=args.persona,
        noLlm=args.noLlm,
        nonInteractive=args.nonInteractive,
        skipDownload=args.skipDownload,
    )
    # Sem terminal de verdade — num script, num servico — perguntar seria
    # esperar por uma resposta que nunca chega. Ali o assistente so aplica o que
    # veio nas flags.
    prompt = Prompt(interactive=not args.nonInteractive and stdinIsTty())

    envPath = Path(args.env_file) if args.env_file else PROJECT_ROOT / ".env"
    runSetup(settings, answers, prompt, envPath=envPath)
    return EXIT_OK


def stdinIsTty() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (ValueError, OSError):  # stdin fechado
        return False


def commandModels(args: argparse.Namespace, settings: Settings) -> int:
    """Lista o que a maquina da IA tem instalado.

    A alternativa e entrar por SSH na outra maquina para rodar `ollama list` —
    e o robo ja sabe o endereco.
    """
    from roboteye.llm.probe import probeOllama

    resultado = probeOllama(args.ollama or settings.llm.host)
    if not resultado.ok:
        print(f"{resultado.host}: {resultado.error}", file=sys.stderr)
        return EXIT_ERROR

    print(f"\n{resultado.host} respondeu em {resultado.latencyMs} ms\n")
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


def commandPreview(args: argparse.Namespace, settings: Settings) -> int:
    from pathlib import Path

    from roboteye.face.preview import renderSheet

    caminho = renderSheet(settings.face, Path(args.output))
    print(f"folha de expressoes salva em {caminho}")
    return EXIT_OK


def commandVoiceList(_: argparse.Namespace, settings: Settings) -> int:
    from roboteye.voices import CATALOG, DEFAULT_MODELS_DIR

    print("\nVozes disponiveis:\n")
    for key, spec in sorted(CATALOG.items()):
        modelPath, configPath = spec.targetPaths(DEFAULT_MODELS_DIR)
        baixada = modelPath.is_file() and configPath.is_file()

        marca = "*" if key == settings.voice.voice else " "
        estado = "baixada" if baixada else "nao baixada"
        print(f" {marca} {key:<8} [{spec.language}] {spec.description}")
        print(f"   {'':<8} {estado}; licenca: {spec.licenseNote or 'nao informada'}")

    print("\n  * = voz em uso")
    print("\nPara trocar:")
    print("  roboteye voice download <nome>     baixa o modelo")
    print("  roboteye --help                    (ou --voice <nome> em run/chat/say)")
    print("  ROBOTEYE_VOICE=<nome> no .env      torna a troca permanente\n")
    return EXIT_OK


def commandWeb(args: argparse.Namespace, settings: Settings) -> int:
    """Sobe so a pagina de configuracao e fica esperando."""
    from roboteye.web import ConfigServer

    config = buildWebConfig(settings, port=args.port)
    print(announceWeb(config))
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


def buildWebConfig(settings: Settings, *, port: int | None = None):
    """Monta a configuracao da pagina, sorteando um PIN se nao houver um.

    O PIN sorteado nao e gravado: ele vale enquanto o robo estiver de pe. Quem
    quiser um PIN fixo define ROBOTEYE_WEB_PIN — o que e o normal numa
    instalacao de verdade, para nao precisar olhar o log a cada reinicio.
    """
    from roboteye.web import WebConfig, generatePin

    return WebConfig(
        host=settings.web.host,
        port=port or settings.web.port,
        pin=settings.web.pin or generatePin(),
    )


def announceWeb(config) -> str:
    """Texto que ensina como chegar na pagina."""
    enderecos = localAddresses() if config.host in {"0.0.0.0", ""} else [config.host]
    linhas = ["Configuracao pelo navegador:"]
    linhas += [f"  http://{host}:{config.port}" for host in enderecos]
    linhas.append(f"  PIN: {config.pin}")
    return "\n".join(linhas)


def localAddresses() -> list[str]:
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


def commandVoiceEnsure(_: argparse.Namespace, settings: Settings) -> int:
    """Baixa tudo que a configuracao atual precisa para falar.

    Existe para a instalacao: quem esta implantando sabe qual voz quer, nao quais
    arquivos ela exige. Uma voz da nuvem nao tem modelo para baixar, mas a
    reserva offline dela tem — e e justamente a reserva que precisa estar no
    disco antes de a rede faltar, nao depois.
    """
    from roboteye import voiceCatalog
    from roboteye.voices import VoiceDownloadError, consoleProgress, downloadVoice

    alvos = [settings.voice.voice]
    reserva = settings.voice.fallbackVoice()
    if reserva:
        alvos.append(reserva)

    baixou = False
    for chave in alvos:
        if not voiceCatalog.needsDownload(chave):
            print(f"{chave}: roda na nuvem, nao ha o que baixar")
            continue
        try:
            downloadVoice(chave, onProgress=consoleProgress)
        except VoiceDownloadError as exc:
            print(f"erro ao baixar {chave}: {exc}", file=sys.stderr)
            return EXIT_ERROR
        baixou = True

    if not baixou and not any(voiceCatalog.needsDownload(c) for c in alvos):
        print("nada a baixar: esta configuracao fala inteiramente pela nuvem")
    return EXIT_OK


def commandVoiceDownload(args: argparse.Namespace, _: Settings) -> int:
    from roboteye.voices import VoiceDownloadError, consoleProgress, downloadVoice

    try:
        path = downloadVoice(args.key, force=args.force, onProgress=consoleProgress)
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
def applyVoiceOverride(args: argparse.Namespace, settings: Settings) -> Settings:
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

    return Settings.fromEnv(envFile=args.env_file)


def applyFaceOverrides(args: argparse.Namespace, settings: Settings) -> Settings:
    """Aplica as flags de linha de comando sobre a configuracao do ambiente."""
    from dataclasses import replace

    face = settings.face
    if getattr(args, "fullscreen", False):
        face = replace(face, fullscreen=True)
    if getattr(args, "noFace", False):
        face = replace(face, enabled=False)
    return replace(settings, face=face)


if __name__ == "__main__":
    raise SystemExit(main())
