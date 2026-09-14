"""Janela da face.

O pygame so pode ser manipulado pela thread principal, entao `FaceApp.run()` e
bloqueante e roda no processo principal. A comunicacao com o resto do sistema e
feita por uma fila alimentada pelo barramento de eventos.
"""

from __future__ import annotations

import os
import queue
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from roboteye.core.events import (
    AssistantReply,
    ErrorOccurred,
    Event,
    EventBus,
    ListeningChanged,
    Notice,
    Shutdown,
    SpeechFinished,
    SpeechStarted,
    ThinkingStarted,
    UserMessage,
    queueSubscriber,
)
from roboteye.core.text import truncate
from roboteye.face.animator import EyeAnimator
from roboteye.face.expressions import Expression
from roboteye.face.layout import EyeLayout
from roboteye.face.renderer import EyeRenderer, qualityFor
from roboteye.face.theme import Theme
from roboteye.loggingSetup import getLogger
from roboteye.speech.envelope import SpeechEnvelope

if TYPE_CHECKING:
    from roboteye.config import FaceSettings

logger = getLogger(__name__)

HINT_TEXT = "ESC sair · S dormir · ESPACO piscar · H ajuda"

#: De quanto em quanto tempo o numero de FPS na ajuda e reescrito. O `Clock` ja
#: entrega a media dos ultimos quadros; o que falta e nao mostra-la a cada um
#: deles — um numero que muda sessenta vezes por segundo nao chega a ser lido, so
#: pisca. Um quarto de segundo e rapido para acusar um engasgo e lento para o olho.
FPS_REFRESH = 0.25

#: Quanto tempo a legenda fica na tela depois de escrita, e os tempos de
#: aparecimento e desaparecimento suave.
CAPTION_TIMEOUT = 12.0
CAPTION_FADE_IN = 0.25
CAPTION_FADE_OUT = 1.5


class FaceApp:
    """Loop de renderizacao da face."""

    def __init__(
        self,
        settings: FaceSettings,
        bus: EventBus,
        *,
        showHint: bool = True,
        envelope: SpeechEnvelope | None = None,
    ) -> None:
        self.settings = settings
        self.bus = bus
        #: Amplitude do audio em reproducao, para animar a fala. Sem ele a face
        #: continua funcionando, com o movimento sintetico.
        self.envelope = envelope
        self.events: queue.Queue[Event] = queue.Queue()
        self.running = False
        self.showHint = showHint

        self.caption = ""
        self.captionAge = 0.0

        self.fps = 0.0
        self.fpsAge = 0.0

        self.animator = EyeAnimator(idleAnimations=settings.idleAnimations)
        self.screen: pygame.Surface | None = None
        self.renderer: EyeRenderer | None = None
        self.clock: pygame.time.Clock | None = None

        bus.subscribe(queueSubscriber(self.events))

    # -- ciclo de vida -----------------------------------------------------
    def createWindow(self) -> None:
        if os.environ.get("SDL_VIDEODRIVER") is None:
            escolhido = pickVideoDriver()
            if escolhido is not None:
                os.environ["SDL_VIDEODRIVER"] = escolhido

        pygame.init()
        pygame.display.set_caption("RobotEye")

        # Sem desktop nao ha janela: o KMSDRM entrega a tela inteira e ponto. Um
        # `set_mode` de 1280x720 ali dentro nao daria uma janela menor, daria a
        # tela toda com a face desenhada num pedaco dela.
        if self.settings.fullscreen or os.environ.get("SDL_VIDEODRIVER") == "kmsdrm":
            self.screen = openScreen((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF)
            # Depois do `set_mode`, e nao antes: sem tela aberta esta chamada
            # levanta "video system not initialized", e o traceback passa a
            # acusar o mouse quando o problema real e o video que nao subiu.
            pygame.mouse.set_visible(False)
        else:
            self.screen = openScreen(
                (self.settings.width, self.settings.height),
                pygame.RESIZABLE | pygame.DOUBLEBUF,
            )

        width, height = self.screen.get_size()
        layout = EyeLayout.forScreen(width, height)
        quality = qualityFor(self.settings.quality)
        self.renderer = EyeRenderer(
            self.screen,
            layout,
            Theme.fromSettings(self.settings),
            quality=quality,
            cornerRadius=self.settings.cornerRadius,
        )
        self.clock = pygame.time.Clock()
        logger.info("face iniciada em %dx%d (qualidade %s)", width, height, quality.name)

    def run(self) -> None:
        """Executa o loop ate o usuario fechar a janela. Bloqueante."""
        self.createWindow()
        assert self.renderer is not None and self.clock is not None

        self.running = True
        try:
            while self.running:
                dt = self.clock.tick(self.settings.fps) / 1000.0
                self.handlePygameEvents()
                self.handleBusEvents()
                self.ageCaption(dt)
                self.trackFps(dt, self.clock)

                if self.envelope is not None:
                    self.animator.setSpeechLevel(self.envelope.level())

                frame = self.animator.update(dt)
                self.renderer.draw(
                    frame,
                    caption=self.caption,
                    hint=self.hint(),
                    captionOpacity=self.captionOpacity(),
                )
                pygame.display.flip()
        finally:
            pygame.quit()
            logger.info("face encerrada")

    def requestStop(self) -> None:
        """Pede o encerramento do loop (pode ser chamado de outra thread)."""
        self.running = False

    # -- entrada -----------------------------------------------------------
    def handlePygameEvents(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit()

            elif event.type == pygame.VIDEORESIZE:
                self.resize(event.w, event.h)

            elif event.type == pygame.KEYDOWN:
                self.handleKey(event.key)

    def handleKey(self, key: int) -> None:
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self.quit()
        elif key == pygame.K_s:
            self.animator.toggleSleep()
        elif key == pygame.K_SPACE:
            self.animator.blinkNow()
        elif key == pygame.K_h:
            self.showHint = not self.showHint

    def resize(self, width: int, height: int) -> None:
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE | pygame.DOUBLEBUF)
        assert self.renderer is not None
        self.renderer.resize(self.screen, EyeLayout.forScreen(width, height))

    def quit(self) -> None:
        self.running = False
        self.bus.publish(Shutdown())

    # -- reacao aos eventos do sistema -------------------------------------
    def handleBusEvents(self) -> None:
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                return
            self.apply(event)

    def apply(self, event: Event) -> None:
        match event:
            case UserMessage():
                self.animator.wake()
                self.setCaption("")

            case ListeningChanged(active=True):
                self.animator.setActivity(Expression.LISTENING)
            case ListeningChanged(active=False):
                # So volta ao repouso se ainda estiver ouvindo: pensar ou falar
                # ja tomaram a face, e apaga-los aqui piscaria a expressao.
                if self.animator.activity is Expression.LISTENING:
                    self.animator.setActivity(None)
            case ThinkingStarted():
                self.animator.setActivity(Expression.THINKING)

            case SpeechStarted(text=text):
                self.animator.setActivity(Expression.SPEAKING)
                self.setCaption(text)

            case SpeechFinished():
                self.animator.setActivity(None)

            case AssistantReply(text=text):
                self.setCaption(text)

            case ErrorOccurred(message=message):
                self.animator.setActivity(None)
                self.animator.setMood(Expression.ANGRY)
                self.setCaption(f"[{truncate(message, 90)}]")

            case Notice(message=message):
                # Aviso, nao falha: nada de ficar brava nem de cortar a fala em
                # curso. So aparece escrito, e a animacao segue como estava.
                self.setCaption(f"({truncate(message, 90)})")

            case Shutdown():
                self.running = False

    def setCaption(self, text: str) -> None:
        self.caption = text
        self.captionAge = 0.0

    def ageCaption(self, dt: float) -> None:
        if not self.caption:
            return
        self.captionAge += dt
        if self.captionAge >= CAPTION_TIMEOUT:
            self.caption = ""

    def trackFps(self, dt: float, clock: pygame.time.Clock) -> None:
        """Guarda a taxa de quadros que a ajuda mostra."""
        self.fpsAge += dt
        if self.fpsAge >= FPS_REFRESH:
            self.fpsAge = 0.0
            self.fps = clock.get_fps()

    def hint(self) -> str:
        """Linha de ajuda, com a taxa de quadros no fim.

        O numero fica junto da ajuda de proposito: e informacao de quem esta
        mexendo no robo, nao de quem olha para ele. Some com a mesma tecla.
        """
        if not self.showHint:
            return ""
        if self.fps < 1.0:
            # Nos primeiros quadros o `Clock` ainda nao tem media: melhor nao
            # mostrar nada do que anunciar 0 FPS logo no arranque.
            return HINT_TEXT
        return f"{HINT_TEXT} · {self.fps:.0f} FPS"

    def captionOpacity(self) -> float:
        """Legenda aparece rapido e se apaga devagar, em vez de sumir de um golpe."""
        if not self.caption:
            return 0.0
        appearing = min(1.0, self.captionAge / CAPTION_FADE_IN)
        remaining = CAPTION_TIMEOUT - self.captionAge
        vanishing = min(1.0, max(0.0, remaining / CAPTION_FADE_OUT))
        return appearing * vanishing


def hasDisplay() -> bool:
    """Heuristica para detectar ambiente grafico disponivel."""
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def hasKmsConsole() -> bool:
    """Se ha um monitor ligado direto no kernel, sem desktop no meio.

    O `status` de cada conector do DRM diz se tem cabo do outro lado. Ler isso
    e barato e nao abre a tela — quem abre e o SDL, depois.
    """
    try:
        return any(
            conector.read_text().strip() == "connected"
            for conector in Path("/sys/class/drm").glob("card*-*/status")
        )
    except OSError:  # pragma: no cover - sistema sem DRM (Windows, macOS, container)
        return False


def pickVideoDriver() -> str | None:
    """Escolhe o driver de video quando o ambiente nao escolheu por nos.

    Devolve None para deixar o SDL decidir, que e o certo onde ha desktop.

    O alvo de producao e um Pi rodando a imagem Lite: ali nao ha X nem Wayland,
    e `DISPLAY` vazio nao significa "sem tela" — significa "sem desktop". A tela
    existe, e do proprio kernel (KMS/DRM), e o SDL desenha nela direto. Antes
    desta checagem a face caia no driver `dummy` justamente na maquina para a
    qual foi feita: o monitor ficava preto e o log nao dizia por que.
    """
    if hasDisplay():
        return None
    if hasKmsConsole():
        logger.info("sem desktop, mas ha monitor ligado: desenhando direto no KMS/DRM")
        return "kmsdrm"
    logger.warning("nenhum display detectado; a face rodara sem janela visivel")
    return "dummy"


def openScreen(size: tuple[int, int], flags: int) -> pygame.Surface:
    """Abre a tela pedindo sincronismo vertical, se o driver souber dar.

    Onde funciona, o vsync remove o rasgo horizontal sem custar nada. Nem todo
    driver aceita: o `dummy` dos testes reclama levantando, e o KMSDRM do Pi
    aceita sem honrar (medido: 827 quadros/s com e sem, numa tela de 60 Hz).
    Por isso quem limita a taxa continua sendo o `Clock.tick` — o vsync aqui e
    um bonus onde houver, nao a garantia.
    """
    try:
        return pygame.display.set_mode(size, flags, vsync=1)
    except pygame.error:
        logger.debug("driver de video sem vsync; seguindo sem ele")
        return pygame.display.set_mode(size, flags)
