"""Chat por texto no terminal.

Le linhas do teclado e as entrega ao assistente. Pode rodar como interface
principal (`roboteye chat`) ou em segundo plano, ao lado da face (`roboteye run`).
"""

from __future__ import annotations

import threading

from roboteye.core.assistant import Assistant
from roboteye.core.events import (
    AssistantReply,
    ErrorOccurred,
    Event,
    EventBus,
    Notice,
    Shutdown,
    SpeechHeard,
    SpeechStarted,
    ThinkingStarted,
    UserMessage,
)
from roboteye.loggingSetup import getLogger

logger = getLogger(__name__)

PROMPT = "\033[36mvoce\033[0m> "
REPLY_PREFIX = "\033[35mAtlas\033[0m> "
ERROR_PREFIX = "\033[31m  !\033[0m "
#: Aviso: amarelo, nao vermelho. Nada quebrou, mas mudou.
NOTICE_PREFIX = "\033[33m  ~\033[0m "
#: Escuta pelo microfone: o que o robo ouviu, para depurar o STT.
HEARD_PREFIX = "\033[36m🎤\033[0m "
DIM = "\033[90m"
RESET = "\033[0m"

HELP = """\
Comandos:
  /ajuda              mostra esta ajuda
  /limpar             esquece o historico da conversa
  /parar              interrompe a fala atual
  /sair               encerra o programa

Ensinar (fica salvo entre execucoes):
  /lembrar <fato>     ensina algo que ela deve saber para sempre
  /esquecer <trecho>  apaga os fatos que contenham esse trecho
  /memoria            lista tudo que ela aprendeu
  /recarregar         rele o arquivo de persona do disco

Qualquer outra linha e enviada para a Atlas.\
"""


class ConsoleChat:
    """Laco de leitura do teclado."""

    def __init__(self, assistant: Assistant, bus: EventBus, *, echoReplies: bool = True) -> None:
        self.assistant = assistant
        self.bus = bus
        self.running = False
        self.thread: threading.Thread | None = None
        self.echo = echoReplies

        #: Instante da mensagem do usuario aguardando a 1a fala da resposta. Serve
        #: so para medir o tempo ate o robo comecar a responder; a 1a `SpeechStarted`
        #: consome e zera, para o numero sair uma vez por turno.
        self.aguardandoDesde: float | None = None

        if echoReplies:
            bus.subscribe(self.printEvent)
        bus.subscribe(self.onShutdown, eventType=Shutdown)

    # -- execucao ----------------------------------------------------------
    def run(self) -> None:
        """Le do teclado ate `/sair` ou EOF. Bloqueante."""
        self.running = True
        print(HELP)
        print()

        while self.running:
            try:
                line = input(PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue
            if line.startswith("/"):
                if not self.handleCommand(line):
                    break
                continue

            self.assistant.submit(line)

        self.running = False
        self.bus.publish(Shutdown())

    def startBackground(self) -> None:
        """Roda o chat numa thread, para conviver com a face na thread principal."""
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self.run, name="console-chat", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False

    # -- comandos ----------------------------------------------------------
    def handleCommand(self, line: str) -> bool:
        """Executa um comando. Devolve False quando o chat deve encerrar."""
        command, _, argumento = line.partition(" ")
        command = command.lower()
        argumento = argumento.strip()

        match command:
            case "/ajuda" | "/help":
                print(HELP)
            case "/limpar" | "/clear":
                self.assistant.memory.clear()
                print("  historico apagado.")
            case "/parar" | "/stop":
                self.assistant.interrupt()
                print("  silencio.")
            case "/lembrar" | "/remember":
                self.remember(argumento)
            case "/esquecer" | "/forget":
                self.forget(argumento)
            case "/memoria" | "/memory":
                self.showMemory()
            case "/recarregar" | "/reload":
                self.assistant.reloadPersona()
                print("  persona recarregada do disco.")
            case "/sair" | "/quit" | "/exit":
                return False
            case _:
                print(f"  comando desconhecido: {command} (tente /ajuda)")
        return True

    # -- ensinar -----------------------------------------------------------
    def remember(self, fato: str) -> None:
        if not fato:
            print("  uso: /lembrar meu nome e Kerlon")
            return
        if self.assistant.teach(fato):
            print(f"  guardado: {fato}")
        else:
            print("  ela ja sabia disso.")

    def forget(self, trecho: str) -> None:
        if not trecho:
            print("  uso: /esquecer nome")
            return
        removidos = self.assistant.forget(trecho)
        if removidos:
            print(f"  {removidos} fato(s) esquecido(s).")
        else:
            print("  nada correspondia.")

    def showMemory(self) -> None:
        fatos = self.assistant.facts()
        if not fatos:
            print("  ela ainda nao aprendeu nada. Use /lembrar <fato>.")
            return
        print(f"  ela sabe {len(fatos)} coisa(s):")
        for fato in fatos:
            print(f"    - {fato}")

    # -- saida -------------------------------------------------------------
    def printEvent(self, event: Event) -> None:
        match event:
            case SpeechHeard():
                self.printHeard(event)
            case UserMessage():
                # So marca o inicio do turno para cronometrar a resposta. Nao
                # imprime: o texto digitado ja esta na tela, e o falado saiu no
                # bloco do `SpeechHeard` acima.
                self.aguardandoDesde = event.timestamp
            case ThinkingStarted():
                print(f"  {DIM}…pensando{RESET}")
            case SpeechStarted():
                if self.aguardandoDesde is not None:
                    ms = (event.timestamp - self.aguardandoDesde) * 1000.0
                    print(f"   {DIM}⏱ 1a fala em {ms:.0f} ms (LLM + TTS){RESET}")
                    self.aguardandoDesde = None
            case AssistantReply(text=text):
                print(f"{REPLY_PREFIX}{text}")
            case ErrorOccurred(message=message, source=source):
                print(f"{ERROR_PREFIX}[{source}] {message}")
            case Notice(message=message, source=source):
                print(f"{NOTICE_PREFIX}[{source}] {message}")

    def printHeard(self, event: SpeechHeard) -> None:
        """Mostra o que o microfone entendeu, com as medidas do reconhecimento."""
        medidas = [f"STT {event.ms:.0f} ms"]
        if event.confidence is not None:
            medidas.append(f"conf {event.confidence:.2f}")
        if event.noSpeech is not None and event.noSpeech > 0.5:
            # So aparece quando e alto: e o sinal de que o trecho era mais
            # silencio ou ruido que fala — a pista mais util quando o STT inventa.
            medidas.append(f"silencio {event.noSpeech:.0%}")
        selo = f"{DIM}[{' · '.join(medidas)}]{RESET}"

        if event.accepted is None:
            # Ouvido, mas nao era com o robo (faltou o nome, ou a janela fechou).
            print(f'{HEARD_PREFIX}{DIM}ignorado:{RESET} "{event.raw}"  {selo}')
            return

        print(f'{HEARD_PREFIX}ouvi: "{event.raw}"  {selo}')
        if event.accepted != event.raw:
            # O nome e os restos foram tirados: mostra o que virou a pergunta.
            print(f'   {DIM}→ entendi:{RESET} "{event.accepted}"')

    def onShutdown(self, _: Event) -> None:
        self.running = False
