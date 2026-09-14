"""Dublês compartilhados pelos testes, expostos como fixtures.

Nenhum teste toca hardware de áudio, rede ou modelos ONNX: todas as fronteiras
externas do sistema têm um substituto aqui.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from roboteye.core.assistant import Assistant
from roboteye.core.events import Event, EventBus
from roboteye.llm.base import ChatMessage
from roboteye.llm.memory import ConversationMemory
from roboteye.llm.persona import PersonaStore
from roboteye.speech.base import AudioFormat, SpeechChunk
from roboteye.speech.speaker import Speaker

TEST_FORMAT = AudioFormat(sampleRate=22050, channels=1, sampleWidth=2)


# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------
class FakeTTSEngine:
    """Gera um bloco de silêncio proporcional ao tamanho do texto."""

    name = "fake"

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.warmedUp = False
        self.closed = False

    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        self.spoken.append(text)
        # 100 amostras por caractere: suficiente para exercitar o caminho do áudio.
        yield SpeechChunk(audio=b"\x00\x00" * (len(text) * 100), format=TEST_FORMAT)

    def warmUp(self) -> None:
        self.warmedUp = True

    def close(self) -> None:
        self.closed = True


class FakeAudioSink:
    """Registra o que seria reproduzido, sem tocar no dispositivo."""

    name = "fake"

    def __init__(self) -> None:
        self.written = bytearray()
        self.starts: list[AudioFormat] = []
        self.stops = 0
        self.closed = False

    def start(self, audioFormat: AudioFormat) -> None:
        self.starts.append(audioFormat)

    def write(self, audio: bytes) -> None:
        self.written.extend(audio)

    def stop(self) -> None:
        self.stops += 1

    def close(self) -> None:
        self.closed = True


class FakeLLMClient:
    """Devolve uma resposta fixa, pedaço a pedaço, como o streaming real."""

    name = "fake"

    def __init__(self, reply: str = "Hello there. How predictable.") -> None:
        self.reply = reply
        self.prompts: list[Sequence[ChatMessage]] = []
        self.closed = False

    def streamReply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        self.prompts.append(list(messages))
        for word in self.reply.split(" "):
            yield word + " "

    def isAvailable(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class EventRecorder:
    """Coleta os eventos publicados no barramento."""

    def __init__(self, bus: EventBus) -> None:
        self.events: list[Event] = []
        self.lock = threading.Lock()
        bus.subscribe(self.record)

    def record(self, event: Event) -> None:
        with self.lock:
            self.events.append(event)

    def ofType(self, eventType: type[Event]) -> list[Event]:
        with self.lock:
            return [event for event in self.events if isinstance(event, eventType)]

    def typeNames(self) -> list[str]:
        with self.lock:
            return [type(event).__name__ for event in self.events]

    def waitFor(self, eventType: type[Event], timeout: float = 5.0) -> bool:
        """Espera até que um evento do tipo apareça. Devolve False se estourar."""
        clock = threading.Event()
        waited = 0.0
        step = 0.01
        while waited < timeout:
            if self.ofType(eventType):
                return True
            clock.wait(step)
            waited += step
        return False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def ambienteIsolado():
    """Impede que a configuração de um teste vaze para o seguinte.

    A CLI grava em `os.environ` de propósito (é assim que `--voice` reaproveita
    toda a resolução de configuração), então basta um teste escrever ali para
    contaminar os outros. Aqui o ambiente volta ao que era, sempre.
    """
    original = {k: v for k, v in os.environ.items() if k.startswith("ROBOTEYE_")}
    yield
    for chave in [k for k in os.environ if k.startswith("ROBOTEYE_")]:
        del os.environ[chave]
    os.environ.update(original)


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def recorder(bus: EventBus) -> EventRecorder:
    return EventRecorder(bus)


@pytest.fixture
def engine() -> FakeTTSEngine:
    return FakeTTSEngine()


@pytest.fixture
def sink() -> FakeAudioSink:
    return FakeAudioSink()


@pytest.fixture
def makeLlm() -> Callable[..., FakeLLMClient]:
    """Fábrica de clientes de LLM falsos com resposta configurável."""
    return FakeLLMClient


@pytest.fixture
def makeSpeaker(engine: FakeTTSEngine, sink: FakeAudioSink, bus: EventBus):
    """Fábrica de locutores já iniciados, fechados automaticamente no fim."""
    criados: list[Speaker] = []

    def factory(tts=None, *, start: bool = True) -> Speaker:
        speaker = Speaker(tts or engine, sink, bus)
        if start:
            speaker.start()
        criados.append(speaker)
        return speaker

    yield factory

    for speaker in criados:
        speaker.close()


@pytest.fixture
def makeAssistant(makeSpeaker, bus: EventBus):
    """Fábrica de assistentes já iniciados, fechados automaticamente no fim.

    Passe `persona_dir` para exercitar o caminho com persona em arquivo; sem
    ele, o assistente roda com um prompt fixo e sem memória ensinável.
    """
    criados: list[Assistant] = []

    def factory(
        llm,
        *,
        systemPrompt: str = "você é um robô de testes",
        history: int = 6,
        personaDir: Path | None = None,
    ):
        store = PersonaStore(personaDir, "atlas") if personaDir else None
        prompt = store.load().systemPrompt() if store else systemPrompt

        memory = ConversationMemory(prompt, maxMessages=history)
        speaker = makeSpeaker()
        assistant = Assistant(llm=llm, memory=memory, speaker=speaker, bus=bus, persona=store)
        assistant.start()
        criados.append(assistant)
        return assistant, memory

    yield factory

    for assistant in criados:
        assistant.close()
