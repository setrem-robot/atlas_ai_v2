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
    Notice,
    Shutdown,
    SpeechFinished,
    SpeechStarted,
    ThinkingStarted,
    UserMessage,
    queue_subscriber,
)
from roboteye.core.text import truncate
from roboteye.face.animator import EyeAnimator
from roboteye.face.expressions import Expression
from roboteye.face.layout import EyeLayout
from roboteye.face.renderer import EyeRenderer, quality_for
from roboteye.face.theme import Theme
from roboteye.logging_setup import get_logger
from roboteye.speech.envelope import SpeechEnvelope

if TYPE_CHECKING:
    from roboteye.config import FaceSettings

logger = get_logger(__name__)

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
        show_hint: bool = True,
        envelope: SpeechEnvelope | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        #: Amplitude do audio em reproducao, para animar a fala. Sem ele a face
        #: continua funcionando, com o movimento sintetico.
        self._envelope = envelope
        self._events: queue.Queue[Event] = queue.Queue()
        self._running = False
        self._show_hint = show_hint

        self._caption = ""
        self._caption_age = 0.0

        self._fps = 0.0
        self._fps_age = 0.0

        self._animator = EyeAnimator(idle_animations=settings.idle_animations)
        self._screen: pygame.Surface | None = None
        self._renderer: EyeRenderer | None = None
        self._clock: pygame.time.Clock | None = None

        bus.subscribe(queue_subscriber(self._events))

    # -- ciclo de vida -----------------------------------------------------
    def _create_window(self) -> None:
        if os.environ.get("SDL_VIDEODRIVER") is None:
            escolhido = _pick_video_driver()
            if escolhido is not None:
                os.environ["SDL_VIDEODRIVER"] = escolhido

        pygame.init()
        pygame.display.set_caption("RobotEye")

        # Sem desktop nao ha janela: o KMSDRM entrega a tela inteira e ponto. Um
        # `set_mode` de 1280x720 ali dentro nao daria uma janela menor, daria a
        # tela toda com a face desenhada num pedaco dela.
        if self._settings.fullscreen or os.environ.get("SDL_VIDEODRIVER") == "kmsdrm":
            pygame.mouse.set_visible(False)
            self._screen = _open_screen((0, 0), pygame.FULLSCREEN | pygame.DOUBLEBUF)
        else:
            self._screen = _open_screen(
                (self._settings.width, self._settings.height),
                pygame.RESIZABLE | pygame.DOUBLEBUF,
            )

        width, height = self._screen.get_size()
        layout = EyeLayout.for_screen(width, height)
        quality = quality_for(self._settings.quality)
        self._renderer = EyeRenderer(
            self._screen,
            layout,
            Theme.from_settings(self._settings),
            quality=quality,
            corner_radius=self._settings.corner_radius,
        )
        self._clock = pygame.time.Clock()
        logger.info("face iniciada em %dx%d (qualidade %s)", width, height, quality.name)

    def run(self) -> None:
        """Executa o loop ate o usuario fechar a janela. Bloqueante."""
        self._create_window()
        assert self._renderer is not None and self._clock is not None

        self._running = True
        try:
            while self._running:
                dt = self._clock.tick(self._settings.fps) / 1000.0
                self._handle_pygame_events()
                self._handle_bus_events()
                self._age_caption(dt)
                self._track_fps(dt, self._clock)

                if self._envelope is not None:
                    self._animator.set_speech_level(self._envelope.level())

                frame = self._animator.update(dt)
                self._renderer.draw(
                    frame,
                    caption=self._caption,
                    hint=self._hint(),
                    caption_opacity=self._caption_opacity(),
                )
                pygame.display.flip()
        finally:
            pygame.quit()
            logger.info("face encerrada")

    def request_stop(self) -> None:
        """Pede o encerramento do loop (pode ser chamado de outra thread)."""
        self._running = False

    # -- entrada -----------------------------------------------------------
    def _handle_pygame_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._quit()

            elif event.type == pygame.VIDEORESIZE:
                self._resize(event.w, event.h)

            elif event.type == pygame.KEYDOWN:
                self._handle_key(event.key)

    def _handle_key(self, key: int) -> None:
        if key in (pygame.K_ESCAPE, pygame.K_q):
            self._quit()
        elif key == pygame.K_s:
            self._animator.toggle_sleep()
        elif key == pygame.K_SPACE:
            self._animator.blink_now()
        elif key == pygame.K_h:
            self._show_hint = not self._show_hint

    def _resize(self, width: int, height: int) -> None:
        self._screen = pygame.display.set_mode((width, height), pygame.RESIZABLE | pygame.DOUBLEBUF)
        assert self._renderer is not None
        self._renderer.resize(self._screen, EyeLayout.for_screen(width, height))

    def _quit(self) -> None:
        self._running = False
        self._bus.publish(Shutdown())

    # -- reacao aos eventos do sistema -------------------------------------
    def _handle_bus_events(self) -> None:
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                return
            self._apply(event)

    def _apply(self, event: Event) -> None:
        match event:
            case UserMessage():
                self._animator.wake()
                self._set_caption("")

            case ThinkingStarted():
                self._animator.set_activity(Expression.THINKING)

            case SpeechStarted(text=text):
                self._animator.set_activity(Expression.SPEAKING)
                self._set_caption(text)

            case SpeechFinished():
                self._animator.set_activity(None)

            case AssistantReply(text=text):
                self._set_caption(text)

            case ErrorOccurred(message=message):
                self._animator.set_activity(None)
                self._animator.set_mood(Expression.ANGRY)
                self._set_caption(f"[{truncate(message, 90)}]")

            case Notice(message=message):
                # Aviso, nao falha: nada de ficar brava nem de cortar a fala em
                # curso. So aparece escrito, e a animacao segue como estava.
                self._set_caption(f"({truncate(message, 90)})")

            case Shutdown():
                self._running = False

    def _set_caption(self, text: str) -> None:
        self._caption = text
        self._caption_age = 0.0

    def _age_caption(self, dt: float) -> None:
        if not self._caption:
            return
        self._caption_age += dt
        if self._caption_age >= CAPTION_TIMEOUT:
            self._caption = ""

    def _track_fps(self, dt: float, clock: pygame.time.Clock) -> None:
        """Guarda a taxa de quadros que a ajuda mostra."""
        self._fps_age += dt
        if self._fps_age >= FPS_REFRESH:
            self._fps_age = 0.0
            self._fps = clock.get_fps()

    def _hint(self) -> str:
        """Linha de ajuda, com a taxa de quadros no fim.

        O numero fica junto da ajuda de proposito: e informacao de quem esta
        mexendo no robo, nao de quem olha para ele. Some com a mesma tecla.
        """
        if not self._show_hint:
            return ""
        if self._fps < 1.0:
            # Nos primeiros quadros o `Clock` ainda nao tem media: melhor nao
            # mostrar nada do que anunciar 0 FPS logo no arranque.
            return HINT_TEXT
        return f"{HINT_TEXT} · {self._fps:.0f} FPS"

    def _caption_opacity(self) -> float:
        """Legenda aparece rapido e se apaga devagar, em vez de sumir de um golpe."""
        if not self._caption:
            return 0.0
        appearing = min(1.0, self._caption_age / CAPTION_FADE_IN)
        remaining = CAPTION_TIMEOUT - self._caption_age
        vanishing = min(1.0, max(0.0, remaining / CAPTION_FADE_OUT))
        return appearing * vanishing


def _has_display() -> bool:
    """Heuristica para detectar ambiente grafico disponivel."""
    if os.name == "nt" or sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _has_kms_console() -> bool:
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


def _pick_video_driver() -> str | None:
    """Escolhe o driver de video quando o ambiente nao escolheu por nos.

    Devolve None para deixar o SDL decidir, que e o certo onde ha desktop.

    O alvo de producao e um Pi rodando a imagem Lite: ali nao ha X nem Wayland,
    e `DISPLAY` vazio nao significa "sem tela" — significa "sem desktop". A tela
    existe, e do proprio kernel (KMS/DRM), e o SDL desenha nela direto. Antes
    desta checagem a face caia no driver `dummy` justamente na maquina para a
    qual foi feita: o monitor ficava preto e o log nao dizia por que.
    """
    if _has_display():
        return None
    if _has_kms_console():
        logger.info("sem desktop, mas ha monitor ligado: desenhando direto no KMS/DRM")
        return "kmsdrm"
    logger.warning("nenhum display detectado; a face rodara sem janela visivel")
    return "dummy"


def _open_screen(size: tuple[int, int], flags: int) -> pygame.Surface:
    """Abre a tela pedindo sincronismo vertical, se o driver souber dar.

    Com vsync o teto de quadros vem do proprio monitor e o rasgo horizontal
    some, sem custar nada. Nem todo driver aceita — o `dummy` dos testes, por
    exemplo — e o pygame reclama levantando; ai vale a tela sem ele.
    """
    try:
        return pygame.display.set_mode(size, flags, vsync=1)
    except pygame.error:
        logger.debug("driver de video sem vsync; seguindo sem ele")
        return pygame.display.set_mode(size, flags)
