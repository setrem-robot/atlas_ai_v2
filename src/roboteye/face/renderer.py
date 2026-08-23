"""Desenho da face com pygame.

O renderizador nao guarda estado de animacao: recebe um `EyeFrame` pronto e o
transforma em pixels. Toda a logica temporal vive em `animator.py`.

A forma de cada olho vem de `mask.py`, como um campo de distancia amostrado no
tamanho final. Isso troca tres coisas em relacao ao desenho por primitivas do
pygame:

**Bordas.** Nao ha superamostragem: a opacidade de cada pixel sai da distancia
ate a borda, entao a curva fica limpa em qualquer tamanho, inclusive nas
diagonais das palpebras — que era onde o serrilhado mais aparecia.

**Sub-pixel.** A posicao do olho e mantida em ponto flutuante e a fracao entra
como deslocamento da amostragem do campo. A respiracao e as microssacadas
passam a deslizar; antes elas andavam de pixel em pixel, o que se via como
tremor nos movimentos lentos.

**Teto de resolucao.** Avaliar o campo custa proporcionalmente a area. Numa tela
grande isso passa do orcamento de um quadro, entao a grade tem um teto e o
resultado e ampliado. Como o campo e suave, ampliar quase nao custa qualidade —
e o deslocamento sub-pixel sobrevive a ampliacao, porque foi assado na
amostragem, nao na posicao final.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pygame

from roboteye.config import is_arm
from roboteye.face import mask
from roboteye.face.animator import EyeFrame
from roboteye.face.layout import EyeLayout
from roboteye.face.mask import MaskGeometry
from roboteye.face.shapes import DEFAULT_RADIUS, EyeShape
from roboteye.face.theme import Theme


@dataclass(frozen=True, slots=True)
class RenderQuality:
    """Quanto se pode gastar para desenhar um quadro."""

    name: str
    #: Maior dimensao da grade do campo, em pixels. 0 remove o teto.
    resolution_cap: int
    #: Intensidade do halo ao redor do olho. 0 desliga.
    glow: float
    #: Se o olho recebe um leve degrade vertical, que sugere volume.
    gradient: bool
    #: Arredondamento das quinas onde as palpebras encontram a borda.
    fillet: float = mask.DEFAULT_FILLET


LOW = RenderQuality(name="low", resolution_cap=200, glow=0.0, gradient=False)
MEDIUM = RenderQuality(name="medium", resolution_cap=340, glow=0.22, gradient=True)
HIGH = RenderQuality(name="high", resolution_cap=560, glow=0.30, gradient=True)

_QUALITIES = {q.name: q for q in (LOW, MEDIUM, HIGH)}

#: Margem ao redor do olho reservada ao halo, em alturas de olho.
GLOW_PADDING = 0.34

#: A grade do halo e propositalmente grosseira: ele e uma mancha suave, e
#: ampliar uma mancha suave nao tem custo visivel. E o que o torna quase de graca.
GLOW_RESOLUTION = 72

#: Quanto o degrade escurece a base do olho.
GRADIENT_DEPTH = 0.16


def quality_for(name: str) -> RenderQuality:
    """Resolve o nome de um nivel de qualidade.

    `auto` decide pela maquina: em ARM (o caso do Raspberry Pi) o orcamento de
    CPU e outro, entao o padrao cai para o nivel baixo.
    """
    key = name.strip().lower()
    if key == "auto":
        return LOW if is_arm() else MEDIUM
    return _QUALITIES.get(key, MEDIUM)


class EyeRenderer:
    """Desenha os olhos e a legenda numa superficie pygame."""

    def __init__(
        self,
        surface: pygame.Surface,
        layout: EyeLayout,
        theme: Theme,
        *,
        quality: RenderQuality = MEDIUM,
        corner_radius: float = DEFAULT_RADIUS,
    ) -> None:
        self._surface = surface
        self._layout = layout
        self._theme = theme
        self._quality = quality
        # Cada forma traz o proprio raio; a configuracao do usuario reescala
        # todos eles de uma vez, preservando as proporcoes entre expressoes.
        self._radius_scale = corner_radius / DEFAULT_RADIUS
        self._buffers: dict[tuple[int, int], pygame.Surface] = {}
        self._build_fonts()

    def resize(self, surface: pygame.Surface, layout: EyeLayout) -> None:
        """Reajusta o renderizador apos mudanca de resolucao."""
        self._surface = surface
        self._layout = layout
        self._buffers.clear()
        self._build_fonts()

    def _build_fonts(self) -> None:
        size = self._layout.caption_font_size
        self._font = pygame.font.Font(None, size)
        self._hint_font = pygame.font.Font(None, max(12, size * 2 // 3))

    # -----------------------------------------------------------------------
    # Desenho
    # -----------------------------------------------------------------------
    def draw(
        self,
        frame: EyeFrame,
        *,
        caption: str = "",
        hint: str = "",
        caption_opacity: float = 1.0,
    ) -> None:
        self._surface.fill(self._theme.background)

        layout = self._layout
        self._draw_eye(frame.left, layout.left_eye_x, inner_is_right=True)
        self._draw_eye(frame.right, layout.right_eye_x, inner_is_right=False)

        if caption and caption_opacity > 0.01:
            self._draw_caption(caption, caption_opacity)
        if hint:
            self._draw_hint(hint)

    def _draw_eye(self, shape: EyeShape, base_x: int, *, inner_is_right: bool) -> None:
        if shape.is_closed:
            return

        layout = self._layout
        eye_width = layout.eye_width * shape.width
        eye_height = layout.eye_height * shape.height
        if eye_width < 1.0 or eye_height < 1.0:
            return

        # Tudo aqui e ponto flutuante ate o ultimo instante: e a parte
        # fracionaria que faz o movimento lento deslizar em vez de pular.
        center_x = base_x + shape.offset_x * layout.scale
        center_y = layout.eye_center_y + shape.offset_y * layout.scale

        shape = shape.with_radius(shape.radius * self._radius_scale)

        if self._quality.glow > 0.0:
            self._draw_glow(shape, eye_width, eye_height, center_x, center_y, inner_is_right)

        self._blit_field(
            shape,
            eye_width,
            eye_height,
            center_x,
            center_y,
            inner_is_right=inner_is_right,
            padding=1.5,
            cap=self._quality.resolution_cap,
            glow=0.0,
        )

    def _draw_glow(
        self,
        shape: EyeShape,
        eye_width: float,
        eye_height: float,
        center_x: float,
        center_y: float,
        inner_is_right: bool,
    ) -> None:
        self._blit_field(
            shape,
            eye_width,
            eye_height,
            center_x,
            center_y,
            inner_is_right=inner_is_right,
            padding=GLOW_PADDING * eye_height,
            cap=GLOW_RESOLUTION,
            glow=self._quality.glow,
        )

    def _blit_field(
        self,
        shape: EyeShape,
        eye_width: float,
        eye_height: float,
        center_x: float,
        center_y: float,
        *,
        inner_is_right: bool,
        padding: float,
        cap: int,
        glow: float,
    ) -> None:
        """Amostra o campo, colore e cola na tela. Serve ao olho e ao halo."""
        target_width = eye_width + 2.0 * padding
        target_height = eye_height + 2.0 * padding

        # A posicao vira um canto inteiro mais uma fracao; a fracao e assada na
        # amostragem do campo, mais adiante.
        left = center_x - target_width / 2.0
        top = center_y - target_height / 2.0
        int_left = math.floor(left)
        int_top = math.floor(top)

        blit_width = max(1, round(target_width))
        blit_height = max(1, round(target_height))

        # Teto de resolucao: a grade encolhe, o olho na grade encolhe junto, e o
        # deslocamento sub-pixel e convertido para pixels da grade.
        largest = max(target_width, target_height)
        factor = min(1.0, cap / largest) if cap else 1.0

        grid_width = max(1, round(target_width * factor))
        grid_height = max(1, round(target_height * factor))

        geometry = MaskGeometry(
            grid_width=grid_width,
            grid_height=grid_height,
            eye_width=eye_width * factor,
            eye_height=eye_height * factor,
            subpixel_x=(left - int_left) * factor,
            subpixel_y=(top - int_top) * factor,
        )

        field = mask.eye_field(
            shape,
            geometry,
            inner_is_right=inner_is_right,
            fillet=self._quality.fillet,
        )

        alpha = mask.field_to_alpha(field, geometry.pixel)

        if glow > 0.0:
            # O desfoque tem que caber na margem: se o brilho ainda nao zerou na
            # borda da grade, o corte aparece como um retangulo fantasma.
            sigma = padding * factor / mask.GLOW_SIGMAS
            alpha = mask.soft_glow(alpha, sigma) * glow

        if not alpha.any():
            return

        surface = self._paint(alpha, gradient=self._quality.gradient and glow == 0.0)
        if (grid_width, grid_height) != (blit_width, blit_height):
            surface = pygame.transform.smoothscale(surface, (blit_width, blit_height))

        self._surface.blit(surface, (int_left, int_top))

    def _paint(self, alpha: np.ndarray, *, gradient: bool) -> pygame.Surface:
        """Transforma a opacidade num retalho RGBA da cor dos olhos."""
        height, width = alpha.shape
        surface = self._buffer(width, height)

        # O pygame indexa superficies por [x][y]; os campos saem em [y][x].
        rgb = pygame.surfarray.pixels3d(surface)
        opacity = pygame.surfarray.pixels_alpha(surface)

        opacity[:] = (alpha.T * 255.0).astype(np.uint8)

        color: np.ndarray = np.asarray(self._theme.eye, dtype=np.float32)
        if gradient:
            # Um degrade de cima para baixo sugere uma superficie iluminada de
            # cima. E sutil de proposito: forte demais e o olho vira um botao.
            #
            # A rampa e centrada em 1: o topo clareia tanto quanto a base
            # escurece. Assim o centro do olho sai exatamente na cor pedida, em
            # vez de sempre um pouco mais escuro que ela.
            half = GRADIENT_DEPTH / 2.0
            ramp: np.ndarray = np.linspace(1.0 + half, 1.0 - half, height, dtype=np.float32)
            tinted = ramp[None, :, None] * color[None, None, :]
            rgb[:] = np.clip(tinted, 0.0, 255.0).astype(np.uint8)
        else:
            rgb[:] = color.astype(np.uint8)

        del rgb, opacity
        return surface

    def _buffer(self, width: int, height: int) -> pygame.Surface:
        """Superficie reaproveitada para um tamanho, para nao alocar por quadro."""
        key = (width, height)
        surface = self._buffers.get(key)
        if surface is None:
            surface = pygame.Surface(key, pygame.SRCALPHA)
            # O cache guarda um punhado de tamanhos: os que a respiracao e a
            # piscada percorrem. Um teto evita que ele cresca sem limite quando
            # a janela e redimensionada muitas vezes.
            if len(self._buffers) > 64:
                self._buffers.clear()
            self._buffers[key] = surface
        return surface

    # -----------------------------------------------------------------------
    # Texto
    # -----------------------------------------------------------------------
    def _draw_caption(self, caption: str, opacity: float) -> None:
        layout = self._layout
        max_width = layout.screen_width - 2 * layout.caption_margin
        lines = _wrap(caption, self._font, max_width)[-3:]

        line_height = self._font.get_linesize()
        bottom = layout.screen_height - layout.caption_margin - line_height
        alpha = int(255 * min(1.0, max(0.0, opacity)))

        for index, line in enumerate(reversed(lines)):
            text = self._font.render(line, True, self._theme.caption_highlight)
            text.set_alpha(alpha)
            position = text.get_rect(
                centerx=layout.screen_width // 2,
                top=bottom - index * line_height,
            )
            self._surface.blit(text, position)

    def _draw_hint(self, hint: str) -> None:
        text = self._hint_font.render(hint, True, self._theme.caption)
        self._surface.blit(text, (self._layout.caption_margin, self._layout.caption_margin))


def _wrap(text: str, font: pygame.font.Font, max_width: int) -> list[str]:
    """Quebra o texto em linhas que caibam em `max_width` pixels."""
    lines: list[str] = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines
