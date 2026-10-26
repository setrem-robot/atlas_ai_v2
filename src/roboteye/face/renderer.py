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

from roboteye.config import isArm
from roboteye.face import mask
from roboteye.face.animator import EyeFrame
from roboteye.face.layout import EyeLayout
from roboteye.face.mask import MaskGeometry
from roboteye.face.shapes import DEFAULT_RADIUS, EyeShape, MouthShape
from roboteye.face.theme import Theme


@dataclass(frozen=True, slots=True)
class RenderQuality:
    """Quanto se pode gastar para desenhar um quadro."""

    name: str
    #: Maior dimensao da grade do campo, em pixels. 0 remove o teto.
    resolutionCap: int
    #: Intensidade do halo ao redor do olho. 0 desliga.
    glow: float
    #: Se o olho recebe um leve degrade vertical, que sugere volume.
    gradient: bool
    #: Arredondamento das quinas onde as palpebras encontram a borda.
    fillet: float = mask.DEFAULT_FILLET


LOW = RenderQuality(name="low", resolutionCap=200, glow=0.0, gradient=False)
MEDIUM = RenderQuality(name="medium", resolutionCap=340, glow=0.22, gradient=True)
HIGH = RenderQuality(name="high", resolutionCap=560, glow=0.30, gradient=True)

_QUALITIES = {q.name: q for q in (LOW, MEDIUM, HIGH)}

#: Margem ao redor do olho reservada ao halo, em alturas de olho.
GLOW_PADDING = 0.34

#: A grade do halo e propositalmente grosseira: ele e uma mancha suave, e
#: ampliar uma mancha suave nao tem custo visivel. E o que o torna quase de graca.
GLOW_RESOLUTION = 72

#: Quanto o degrade escurece a base do olho.
GRADIENT_DEPTH = 0.16


def qualityFor(name: str) -> RenderQuality:
    """Resolve o nome de um nivel de qualidade.

    `auto` decide pela maquina: em ARM (o caso do Raspberry Pi) o orcamento de
    CPU e outro, entao o padrao cai para o nivel baixo.
    """
    key = name.strip().lower()
    if key == "auto":
        return LOW if isArm() else MEDIUM
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
        cornerRadius: float = DEFAULT_RADIUS,
        mouthEnabled: bool = True,
    ) -> None:
        self.surface = surface
        self.layout = layout
        self.theme = theme
        self.quality = quality
        self.mouthEnabled = mouthEnabled
        # Cada forma traz o proprio raio; a configuracao do usuario reescala
        # todos eles de uma vez, preservando as proporcoes entre expressoes.
        self.radiusScale = cornerRadius / DEFAULT_RADIUS
        self.buffers: dict[tuple[int, int], pygame.Surface] = {}
        self.buildFonts()

    def resize(self, surface: pygame.Surface, layout: EyeLayout) -> None:
        """Reajusta o renderizador apos mudanca de resolucao."""
        self.surface = surface
        self.layout = layout
        self.buffers.clear()
        self.buildFonts()

    def buildFonts(self) -> None:
        size = self.layout.captionFontSize
        self.font = pygame.font.Font(None, size)
        self.hintFont = pygame.font.Font(None, max(12, size * 2 // 3))

    # -----------------------------------------------------------------------
    # Desenho
    # -----------------------------------------------------------------------
    def draw(
        self,
        frame: EyeFrame,
        *,
        caption: str = "",
        hint: str = "",
        captionOpacity: float = 1.0,
    ) -> None:
        # A cor e o fundo vem do quadro, nao do tema: a transicao de emocao (o
        # ciano virando branco, o preto virando vermelho) e logica temporal, e
        # mora no animador. O tema segue dono so das cores da legenda.
        self.surface.fill(frame.backgroundColor)

        layout = self.layout
        self.drawEye(
            frame.left,
            layout.leftEyeX,
            innerIsRight=True,
            color=frame.eyeColor,
            swirl=frame.swirl,
            swirlPhase=frame.swirlPhase,
        )
        self.drawEye(
            frame.right,
            layout.rightEyeX,
            innerIsRight=False,
            color=frame.eyeColor,
            swirl=frame.swirl,
            swirlPhase=frame.swirlPhase,
        )

        if self.mouthEnabled and not frame.mouth.isHidden:
            self.drawMouth(frame.mouth, frame.eyeColor)

        if caption and captionOpacity > 0.01:
            self.drawCaption(caption, captionOpacity)
        if hint:
            self.drawHint(hint)

    def drawEye(
        self,
        shape: EyeShape,
        baseX: int,
        *,
        innerIsRight: bool,
        color: tuple[int, int, int] = (4, 201, 253),
        swirl: float = 0.0,
        swirlPhase: float = 0.0,
    ) -> None:
        if shape.isClosed:
            return

        layout = self.layout
        eyeWidth = layout.eyeWidth * shape.width
        eyeHeight = layout.eyeHeight * shape.height
        if eyeWidth < 1.0 or eyeHeight < 1.0:
            return

        # Tudo aqui e ponto flutuante ate o ultimo instante: e a parte
        # fracionaria que faz o movimento lento deslizar em vez de pular.
        centerX = baseX + shape.offsetX * layout.scale
        centerY = layout.eyeCenterY + shape.offsetY * layout.scale

        shape = shape.withRadius(shape.radius * self.radiusScale)

        # Tonto: o olho some aos poucos e a espiral toma o lugar, no mesmo ponto.
        # Um crossfade, nao uma troca seca.
        eyeOpacity = 1.0 - swirl
        if eyeOpacity > 0.003:
            if self.quality.glow > 0.0:
                self.drawGlow(shape, eyeWidth, eyeHeight, centerX, centerY, innerIsRight, color)
            self.blitField(
                shape,
                eyeWidth,
                eyeHeight,
                centerX,
                centerY,
                innerIsRight=innerIsRight,
                padding=1.5,
                cap=self.quality.resolutionCap,
                glow=0.0,
                color=color,
                opacity=eyeOpacity,
            )

        if swirl > 0.003:
            self.drawSpiral(centerX, centerY, eyeWidth, eyeHeight, color, swirl, swirlPhase)

    def drawGlow(
        self,
        shape: EyeShape,
        eyeWidth: float,
        eyeHeight: float,
        centerX: float,
        centerY: float,
        innerIsRight: bool,
        color: tuple[int, int, int],
    ) -> None:
        self.blitField(
            shape,
            eyeWidth,
            eyeHeight,
            centerX,
            centerY,
            innerIsRight=innerIsRight,
            padding=GLOW_PADDING * eyeHeight,
            cap=GLOW_RESOLUTION,
            glow=self.quality.glow,
            color=color,
        )

    def blitField(
        self,
        shape: EyeShape,
        eyeWidth: float,
        eyeHeight: float,
        centerX: float,
        centerY: float,
        *,
        innerIsRight: bool,
        padding: float,
        cap: int,
        glow: float,
        color: tuple[int, int, int] = (4, 201, 253),
        opacity: float = 1.0,
    ) -> None:
        """Amostra o campo, colore e cola na tela. Serve ao olho e ao halo."""
        targetWidth = eyeWidth + 2.0 * padding
        targetHeight = eyeHeight + 2.0 * padding

        # A posicao vira um canto inteiro mais uma fracao; a fracao e assada na
        # amostragem do campo, mais adiante.
        left = centerX - targetWidth / 2.0
        top = centerY - targetHeight / 2.0
        intLeft = math.floor(left)
        intTop = math.floor(top)

        blitWidth = max(1, round(targetWidth))
        blitHeight = max(1, round(targetHeight))

        # Teto de resolucao: a grade encolhe, o olho na grade encolhe junto, e o
        # deslocamento sub-pixel e convertido para pixels da grade.
        largest = max(targetWidth, targetHeight)
        factor = min(1.0, cap / largest) if cap else 1.0

        gridWidth = max(1, round(targetWidth * factor))
        gridHeight = max(1, round(targetHeight * factor))

        geometry = MaskGeometry(
            gridWidth=gridWidth,
            gridHeight=gridHeight,
            eyeWidth=eyeWidth * factor,
            eyeHeight=eyeHeight * factor,
            subpixelX=(left - intLeft) * factor,
            subpixelY=(top - intTop) * factor,
        )

        field = mask.eyeField(
            shape,
            geometry,
            innerIsRight=innerIsRight,
            fillet=self.quality.fillet,
        )

        alpha = mask.fieldToAlpha(field, geometry.pixel)

        if glow > 0.0:
            # O desfoque tem que caber na margem: se o brilho ainda nao zerou na
            # borda da grade, o corte aparece como um retangulo fantasma.
            sigma = padding * factor / mask.GLOW_SIGMAS
            alpha = mask.softGlow(alpha, sigma) * glow

        if opacity < 1.0:
            alpha = alpha * opacity

        if not alpha.any():
            return

        surface = self.paint(alpha, gradient=self.quality.gradient and glow == 0.0, color=color)
        if (gridWidth, gridHeight) != (blitWidth, blitHeight):
            surface = pygame.transform.smoothscale(surface, (blitWidth, blitHeight))

        self.surface.blit(surface, (intLeft, intTop))

    def paint(
        self, alpha: np.ndarray, *, gradient: bool, color: tuple[int, int, int] = (4, 201, 253)
    ) -> pygame.Surface:
        """Transforma a opacidade num retalho RGBA da cor pedida."""
        height, width = alpha.shape
        surface = self.buffer(width, height)

        # O pygame indexa superficies por [x][y]; os campos saem em [y][x].
        rgb = pygame.surfarray.pixels3d(surface)
        opacity = pygame.surfarray.pixels_alpha(surface)

        opacity[:] = (alpha.T * 255.0).astype(np.uint8)

        tint: np.ndarray = np.asarray(color, dtype=np.float32)
        if gradient:
            # Um degrade de cima para baixo sugere uma superficie iluminada de
            # cima. E sutil de proposito: forte demais e o olho vira um botao.
            #
            # A rampa e centrada em 1: o topo clareia tanto quanto a base
            # escurece. Assim o centro do olho sai exatamente na cor pedida, em
            # vez de sempre um pouco mais escuro que ela.
            half = GRADIENT_DEPTH / 2.0
            ramp: np.ndarray = np.linspace(1.0 + half, 1.0 - half, height, dtype=np.float32)
            tinted = ramp[None, :, None] * tint[None, None, :]
            rgb[:] = np.clip(tinted, 0.0, 255.0).astype(np.uint8)
        else:
            rgb[:] = tint.astype(np.uint8)

        del rgb, opacity
        return surface

    # -----------------------------------------------------------------------
    # Boca e vortice
    # -----------------------------------------------------------------------
    def drawMouth(self, mouth: MouthShape, color: tuple[int, int, int]) -> None:
        """Desenha a boca centrada, abaixo dos olhos.

        A boca nao tem halo nem degrade — e um traco limpo, e e tambem o que a
        mantem barata num quadro que ja desenha dois olhos. Segue o mesmo campo
        de distancia dos olhos, entao herda o antialiasing de graca.
        """
        layout = self.layout
        drawWidth = max(1.0, layout.mouthWidth * mouth.width)
        reserve = float(layout.mouthHeight)

        # Margem para as pontas arredondadas e para a curva nao encostar na borda.
        padding = reserve * 0.18
        targetWidth = drawWidth + 2.0 * padding
        targetHeight = reserve

        cap = self.quality.resolutionCap
        largest = max(targetWidth, targetHeight)
        factor = min(1.0, cap / largest) if cap else 1.0

        gridWidth = max(1, round(targetWidth * factor))
        gridHeight = max(1, round(targetHeight * factor))

        geometry = mask.MouthGeometry(
            gridWidth=gridWidth,
            gridHeight=gridHeight,
            mouthWidth=drawWidth * factor,
            mouthHeight=reserve * factor,
        )
        field = mask.mouthField(mouth, geometry)
        alpha = mask.fieldToAlpha(field, geometry.pixel) * mouth.alpha
        if not alpha.any():
            return

        surface = self.paint(alpha, gradient=False, color=color)
        blitWidth = max(1, round(targetWidth))
        blitHeight = max(1, round(targetHeight))
        if (gridWidth, gridHeight) != (blitWidth, blitHeight):
            surface = pygame.transform.smoothscale(surface, (blitWidth, blitHeight))

        left = layout.mouthCenterX - blitWidth // 2
        top = layout.mouthCenterY - blitHeight // 2
        self.surface.blit(surface, (left, top))

    def drawSpiral(
        self,
        centerX: float,
        centerY: float,
        eyeWidth: float,
        eyeHeight: float,
        color: tuple[int, int, int],
        opacity: float,
        phase: float,
    ) -> None:
        """Desenha o vortice do tonto no lugar do olho (so quando ela esta tonta)."""
        cap = self.quality.resolutionCap or 220
        size = min(max(eyeWidth, eyeHeight), float(cap))
        grid = max(1, round(size))

        alpha = mask.spiralField(grid, grid, phase) * opacity
        if not alpha.any():
            return

        surface = self.paint(alpha, gradient=False, color=color)
        blit = max(1, round(max(eyeWidth, eyeHeight)))
        if grid != blit:
            surface = pygame.transform.smoothscale(surface, (blit, blit))

        self.surface.blit(surface, (round(centerX - blit / 2), round(centerY - blit / 2)))

    def buffer(self, width: int, height: int) -> pygame.Surface:
        """Superficie reaproveitada para um tamanho, para nao alocar por quadro."""
        key = (width, height)
        surface = self.buffers.get(key)
        if surface is None:
            surface = pygame.Surface(key, pygame.SRCALPHA)
            # O cache guarda um punhado de tamanhos: os que a respiracao e a
            # piscada percorrem. Um teto evita que ele cresca sem limite quando
            # a janela e redimensionada muitas vezes.
            if len(self.buffers) > 64:
                self.buffers.clear()
            self.buffers[key] = surface
        return surface

    # -----------------------------------------------------------------------
    # Texto
    # -----------------------------------------------------------------------
    def drawCaption(self, caption: str, opacity: float) -> None:
        layout = self.layout
        maxWidth = layout.screenWidth - 2 * layout.captionMargin
        lines = wrap(caption, self.font, maxWidth)[-3:]

        lineHeight = self.font.get_linesize()
        bottom = layout.screenHeight - layout.captionMargin - lineHeight
        alpha = int(255 * min(1.0, max(0.0, opacity)))

        for index, line in enumerate(reversed(lines)):
            text = self.font.render(line, True, self.theme.captionHighlight)
            text.set_alpha(alpha)
            position = text.get_rect(
                centerx=layout.screenWidth // 2,
                top=bottom - index * lineHeight,
            )
            self.surface.blit(text, position)

    def drawHint(self, hint: str) -> None:
        text = self.hintFont.render(hint, True, self.theme.caption)
        self.surface.blit(text, (self.layout.captionMargin, self.layout.captionMargin))


def wrap(text: str, font: pygame.font.Font, maxWidth: int) -> list[str]:
    """Quebra o texto em linhas que caibam em `max_width` pixels."""
    lines: list[str] = []
    current = ""

    for word in text.split():
        candidate = f"{current} {word}".strip()
        if font.size(candidate)[0] <= maxWidth or not current:
            current = candidate
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)
    return lines
