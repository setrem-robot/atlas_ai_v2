"""Barramento de eventos.

Os subsistemas (chat, LLM, voz, face) nao se conhecem: eles publicam e assinam
eventos. Isso permite, por exemplo, rodar o assistente sem a face, ou trocar o
chat de texto por reconhecimento de fala sem tocar em mais nada.

O barramento e seguro para uso entre threads. Os assinantes sao chamados na
thread de quem publica, entao handlers devem ser rapidos; a face usa
`queue_subscriber` para apenas enfileirar e processar no seu proprio loop.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from time import time
from typing import TypeVar

from roboteye.logging_setup import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Eventos
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Event:
    """Evento base. Todo evento carrega o instante em que foi criado."""

    timestamp: float = field(default_factory=time, kw_only=True)


@dataclass(frozen=True, slots=True)
class UserMessage(Event):
    """O usuario enviou uma mensagem (texto digitado, transcricao de voz, ...)."""

    text: str


@dataclass(frozen=True, slots=True)
class SpeechHeard(Event):
    """O microfone transcreveu algo — dirigido ao robo ou nao.

    Existe so para depurar a escuta: carrega o texto exato que o motor entendeu
    (`raw`), o que sobrou depois do filtro do nome (`accepted`, `None` quando nao
    era com o robo) e as medidas que ajudam a entender um erro de reconhecimento
    — quanto a transcricao demorou e o quanto o modelo confiou nela. Quem escuta
    e a interface de debug; o resto do sistema segue reagindo a `UserMessage`.
    """

    raw: str
    accepted: str | None
    ms: float
    #: Media do log-prob do Whisper: perto de 0 e confianca alta, -1 ja e baixa.
    #: `None` nos motores que nao expoem isso (Vosk).
    confidence: float | None = None
    #: Probabilidade de o trecho ser silencio/ruido, tambem do Whisper.
    no_speech: float | None = None


@dataclass(frozen=True, slots=True)
class ListeningChanged(Event):
    """O robo passou a ouvir alguem, ou parou.

    Existe para a face mostrar isso. Sem sinal nenhum, quem fala com o robo nao
    tem como saber se foi ouvido — e a duvida faz a pessoa repetir a pergunta
    por cima da resposta que ja estava vindo.
    """

    active: bool


@dataclass(frozen=True, slots=True)
class ThinkingStarted(Event):
    """O LLM comecou a processar uma mensagem."""


@dataclass(frozen=True, slots=True)
class AssistantReply(Event):
    """Resposta completa do assistente, ja pronta para exibicao."""

    text: str


@dataclass(frozen=True, slots=True)
class SpeechStarted(Event):
    """O audio de um trecho comecou a tocar."""

    text: str


@dataclass(frozen=True, slots=True)
class SpeechFinished(Event):
    """Todo o audio da resposta terminou de tocar."""


@dataclass(frozen=True, slots=True)
class ErrorOccurred(Event):
    """Algo falhou em um subsistema, sem derrubar a aplicacao."""

    message: str
    source: str = "app"


@dataclass(frozen=True, slots=True)
class Notice(Event):
    """Algo que o usuario precisa saber, sem que nada tenha quebrado.

    Existe para separar "mudou de comportamento" de "deu erro". Uma voz online
    que cai para a reserva offline continua funcionando — a face nao deve ficar
    brava nem interromper a fala por causa disso —, mas quem ouve precisa saber,
    porque uma reserva do mesmo idioma passa por "a voz configurada, so que
    errada" e manda a pessoa procurar o problema na configuracao.
    """

    message: str
    source: str = "app"


@dataclass(frozen=True, slots=True)
class Shutdown(Event):
    """Pedido de encerramento da aplicacao."""


E = TypeVar("E", bound=Event)
Handler = Callable[[Event], None]


# ---------------------------------------------------------------------------
# Barramento
# ---------------------------------------------------------------------------
class EventBus:
    """Publicador/assinante simples e thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._handlers: list[tuple[type[Event] | None, Handler]] = []

    def subscribe(self, handler: Handler, *, event_type: type[Event] | None = None) -> None:
        """Registra `handler`. Sem `event_type`, recebe todos os eventos."""
        with self._lock:
            self._handlers.append((event_type, handler))

    def unsubscribe(self, handler: Handler) -> None:
        # Comparacao por igualdade, e nao por identidade: metodos ligados
        # (`obj.metodo`) sao objetos novos a cada acesso, mas comparam iguais.
        with self._lock:
            self._handlers = [entry for entry in self._handlers if entry[1] != handler]

    def publish(self, event: Event) -> None:
        """Entrega o evento aos assinantes.

        Um handler que levanta excecao e registrado no log e ignorado: um
        subsistema com defeito nao pode derrubar os outros.
        """
        with self._lock:
            targets = [
                handler
                for event_type, handler in self._handlers
                if event_type is None or isinstance(event, event_type)
            ]

        logger.debug("evento: %s", type(event).__name__)
        for handler in targets:
            try:
                handler(event)
            except Exception:
                logger.exception("handler de evento falhou para %s", type(event).__name__)


def queue_subscriber(sink: queue.Queue[Event]) -> Handler:
    """Handler que apenas enfileira eventos, para consumo em outra thread.

    Usado pela face: o barramento e publicado por threads de trabalho, mas o
    pygame so pode ser tocado pela thread principal.
    """

    def _handler(event: Event) -> None:
        sink.put(event)

    return _handler
