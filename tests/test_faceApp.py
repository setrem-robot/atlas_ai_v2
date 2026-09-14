"""Teste de integração da janela da face.

Roda o loop de verdade com o driver `dummy` do SDL, para pegar erros que só
aparecem com a janela montada (fonte, redimensionamento, reação a eventos).
"""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

pytest.importorskip("pygame")

from roboteye.config import FaceSettings
from roboteye.core.events import (
    AssistantReply,
    ErrorOccurred,
    EventBus,
    Shutdown,
    SpeechFinished,
    SpeechStarted,
    ThinkingStarted,
    UserMessage,
)
from roboteye.face.app import HINT_TEXT, FaceApp
from roboteye.face.expressions import Expression


@pytest.fixture
def settings() -> FaceSettings:
    return FaceSettings(enabled=True, fullscreen=False, width=640, height=480, fps=60)


def rodarPor(face: FaceApp, segundos: float = 0.4) -> None:
    """Executa o loop da face por um instante e o encerra."""
    parar = threading.Timer(segundos, face.requestStop)
    parar.start()
    try:
        face.run()
    finally:
        parar.cancel()


class TestFaceApp:
    def testLoopRodaEEncerraLimpo(self, settings: FaceSettings, bus: EventBus) -> None:
        rodarPor(FaceApp(settings, bus))

    def testReageAosEventosDoSistema(self, settings: FaceSettings, bus: EventBus) -> None:
        face = FaceApp(settings, bus)

        def publicar() -> None:
            time.sleep(0.05)
            bus.publish(UserMessage(text="olá"))
            bus.publish(ThinkingStarted())
            time.sleep(0.05)
            bus.publish(SpeechStarted(text="uma resposta qualquer"))
            time.sleep(0.05)
            bus.publish(SpeechFinished())
            bus.publish(AssistantReply(text="uma resposta qualquer"))

        threading.Thread(target=publicar, daemon=True).start()
        rodarPor(face, 0.4)

    def testErroDeixaAFaceBrava(self, settings: FaceSettings, bus: EventBus) -> None:
        face = FaceApp(settings, bus)

        threading.Timer(0.05, lambda: bus.publish(ErrorOccurred(message="deu ruim"))).start()
        rodarPor(face, 0.3)

        assert face.animator.currentExpression is Expression.ANGRY

    def testEventoDeEncerramentoParaOLoop(
        self, settings: FaceSettings, bus: EventBus
    ) -> None:
        face = FaceApp(settings, bus)

        inicio = time.perf_counter()
        threading.Timer(0.1, lambda: bus.publish(Shutdown())).start()
        face.run()  # deve retornar sozinho, sem o timer de segurança

        assert time.perf_counter() - inicio < 5.0

    def testAjudaMostraATaxaDeQuadros(self, settings: FaceSettings, bus: EventBus) -> None:
        face = FaceApp(settings, bus)
        rodarPor(face, 0.5)  # tempo de sobra para o Clock formar a media

        assert face.hint().startswith(HINT_TEXT)
        assert face.hint().endswith("FPS")
        assert face.fps > 0.0

    def testAjudaEscondidaNaoMostraNada(self, settings: FaceSettings, bus: EventBus) -> None:
        face = FaceApp(settings, bus, showHint=False)
        rodarPor(face, 0.3)

        assert face.hint() == ""

    def testFaceEmTelaCheiaMonta(self, bus: EventBus) -> None:
        settings = FaceSettings(fullscreen=True, width=640, height=480, fps=60)
        rodarPor(FaceApp(settings, bus), 0.2)
