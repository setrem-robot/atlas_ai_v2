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
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

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

    def __init__(self, assistant: Assistant, bus: EventBus, *, echo_replies: bool = True) -> None:
        self._assistant = assistant
        self._bus = bus
        self._running = False
        self._thread: threading.Thread | None = None
        self._echo = echo_replies

        #: Instante da mensagem do usuario aguardando a 1a fala da resposta. Serve
        #: so para medir o tempo ate o robo comecar a responder; a 1a `SpeechStarted`
        #: consome e zera, para o numero sair uma vez por turno.
        self._aguardando_desde: float | None = None

        if echo_replies:
            bus.subscribe(self._print_event)
        bus.subscribe(self._on_shutdown, event_type=Shutdown)

    # -- execucao ----------------------------------------------------------
    def run(self) -> None:
        """Le do teclado ate `/sair` ou EOF. Bloqueante."""
        self._running = True
        print(HELP)
        print()

        while self._running:
            try:
                line = input(PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not line:
                continue
            if line.startswith("/"):
                if not self._handle_command(line):
                    break
                continue

            self._assistant.submit(line)

        self._running = False
        self._bus.publish(Shutdown())

    def start_background(self) -> None:
        """Roda o chat numa thread, para conviver com a face na thread principal."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self.run, name="console-chat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    # -- comandos ----------------------------------------------------------
    def _handle_command(self, line: str) -> bool:
        """Executa um comando. Devolve False quando o chat deve encerrar."""
        command, _, argumento = line.partition(" ")
        command = command.lower()
        argumento = argumento.strip()

        match command:
            case "/ajuda" | "/help":
                print(HELP)
            case "/limpar" | "/clear":
                self._assistant.memory.clear()
                print("  historico apagado.")
            case "/parar" | "/stop":
                self._assistant.interrupt()
                print("  silencio.")
            case "/lembrar" | "/remember":
                self._remember(argumento)
            case "/esquecer" | "/forget":
                self._forget(argumento)
            case "/memoria" | "/memory":
                self._show_memory()
            case "/recarregar" | "/reload":
                self._assistant.reload_persona()
                print("  persona recarregada do disco.")
            case "/sair" | "/quit" | "/exit":
                return False
            case _:
                print(f"  comando desconhecido: {command} (tente /ajuda)")
        return True

    # -- ensinar -----------------------------------------------------------
    def _remember(self, fato: str) -> None:
        if not fato:
            print("  uso: /lembrar meu nome e Kerlon")
            return
        if self._assistant.teach(fato):
            print(f"  guardado: {fato}")
        else:
            print("  ela ja sabia disso.")

    def _forget(self, trecho: str) -> None:
        if not trecho:
            print("  uso: /esquecer nome")
            return
        removidos = self._assistant.forget(trecho)
        if removidos:
            print(f"  {removidos} fato(s) esquecido(s).")
        else:
            print("  nada correspondia.")

    def _show_memory(self) -> None:
        fatos = self._assistant.facts()
        if not fatos:
            print("  ela ainda nao aprendeu nada. Use /lembrar <fato>.")
            return
        print(f"  ela sabe {len(fatos)} coisa(s):")
        for fato in fatos:
            print(f"    - {fato}")

    # -- saida -------------------------------------------------------------
    def _print_event(self, event: Event) -> None:
        match event:
            case SpeechHeard():
                self._print_heard(event)
            case UserMessage():
                # So marca o inicio do turno para cronometrar a resposta. Nao
                # imprime: o texto digitado ja esta na tela, e o falado saiu no
                # bloco do `SpeechHeard` acima.
                self._aguardando_desde = event.timestamp
            case ThinkingStarted():
                print(f"  {DIM}…pensando{RESET}")
            case SpeechStarted():
                if self._aguardando_desde is not None:
                    ms = (event.timestamp - self._aguardando_desde) * 1000.0
                    print(f"   {DIM}⏱ 1a fala em {ms:.0f} ms (LLM + TTS){RESET}")
                    self._aguardando_desde = None
            case AssistantReply(text=text):
                print(f"{REPLY_PREFIX}{text}")
            case ErrorOccurred(message=message, source=source):
                print(f"{ERROR_PREFIX}[{source}] {message}")
            case Notice(message=message, source=source):
                print(f"{NOTICE_PREFIX}[{source}] {message}")

    def _print_heard(self, event: SpeechHeard) -> None:
        """Mostra o que o microfone entendeu, com as medidas do reconhecimento."""
        medidas = [f"STT {event.ms:.0f} ms"]
        if event.confidence is not None:
            medidas.append(f"conf {event.confidence:.2f}")
        if event.no_speech is not None and event.no_speech > 0.5:
            # So aparece quando e alto: e o sinal de que o trecho era mais
            # silencio ou ruido que fala — a pista mais util quando o STT inventa.
            medidas.append(f"silencio {event.no_speech:.0%}")
        selo = f"{DIM}[{' · '.join(medidas)}]{RESET}"

        if event.accepted is None:
            # Ouvido, mas nao era com o robo (faltou o nome, ou a janela fechou).
            print(f'{HEARD_PREFIX}{DIM}ignorado:{RESET} "{event.raw}"  {selo}')
            return

        print(f'{HEARD_PREFIX}ouvi: "{event.raw}"  {selo}')
        if event.accepted != event.raw:
            # O nome e os restos foram tirados: mostra o que virou a pergunta.
            print(f'   {DIM}→ entendi:{RESET} "{event.accepted}"')

    def _on_shutdown(self, _: Event) -> None:
        self._running = False
