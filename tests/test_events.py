"""Testes do barramento de eventos."""

from __future__ import annotations

import queue

from roboteye.core.events import (
    AssistantReply,
    Event,
    EventBus,
    SpeechFinished,
    UserMessage,
    queueSubscriber,
)


class TestEventBus:
    def testEntregaATodosOsAssinantes(self, bus: EventBus) -> None:
        recebidos: list[Event] = []
        bus.subscribe(recebidos.append)
        bus.subscribe(recebidos.append)

        bus.publish(UserMessage(text="olá"))

        assert len(recebidos) == 2

    def testFiltraPorTipo(self, bus: EventBus) -> None:
        somenteFalas: list[Event] = []
        bus.subscribe(somenteFalas.append, eventType=SpeechFinished)

        bus.publish(UserMessage(text="olá"))
        bus.publish(SpeechFinished())

        assert len(somenteFalas) == 1

    def testHandlerComErroNaoAfetaOsDemais(self, bus: EventBus) -> None:
        def explode(_: Event) -> None:
            raise RuntimeError("falha proposital")

        recebidos: list[Event] = []
        bus.subscribe(explode)
        bus.subscribe(recebidos.append)

        bus.publish(AssistantReply(text="oi"))

        assert len(recebidos) == 1

    def testUnsubscribeParaDeEntregar(self, bus: EventBus) -> None:
        recebidos: list[Event] = []
        bus.subscribe(recebidos.append)
        bus.unsubscribe(recebidos.append)

        bus.publish(UserMessage(text="olá"))

        assert recebidos == []

    def testQueueSubscriberEnfileira(self, bus: EventBus) -> None:
        fila: queue.Queue[Event] = queue.Queue()
        bus.subscribe(queueSubscriber(fila))

        bus.publish(UserMessage(text="olá"))

        assert isinstance(fila.get_nowait(), UserMessage)


class TestEventos:
    def testCarregamTimestamp(self) -> None:
        assert UserMessage(text="oi").timestamp > 0

    def testSaoImutaveis(self) -> None:
        evento = UserMessage(text="oi")
        try:
            evento.text = "outro"  # type: ignore[misc]
        except (AttributeError, TypeError):
            return
        raise AssertionError("o evento deveria ser imutável")
