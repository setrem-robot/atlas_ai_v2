"""Gera uma folha de contato com as expressoes da face.

Serve para ajustar a estetica sem precisar rodar o robo inteiro e esperar a hora
de cada expressao aparecer: mexeu num parametro, roda `roboteye preview` e olha.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from roboteye.config import FaceSettings
from roboteye.face.animator import DEFAULT_BACKGROUND, DEFAULT_EYE_COLOR, EyeFrame, closeLids
from roboteye.face.expressions import Expression
from roboteye.face.layout import EyeLayout
from roboteye.face.shapes import (
    HIDDEN_MOUTH,
    Color,
    EyeShape,
    MouthShape,
    accentFor,
    mouthFor,
    presetFor,
)
from roboteye.face.theme import Theme

COLUMNS = 3
LABEL_MARGIN = 14


@dataclass(frozen=True, slots=True)
class Panel:
    """Um quadro da folha de contato, com tudo o que o renderizador precisa."""

    label: str
    left: EyeShape
    right: EyeShape
    mouth: MouthShape = HIDDEN_MOUTH
    eye: Color = DEFAULT_EYE_COLOR
    background: Color = DEFAULT_BACKGROUND
    swirl: float = 0.0
    swirlPhase: float = 0.0


def panelFor(label: str, expression: Expression, left: EyeShape, right: EyeShape, **extra) -> Panel:
    """Monta um painel ja com a boca e as cores de acento da expressao."""
    accent = accentFor(expression)
    return Panel(
        label=label,
        left=left,
        right=right,
        mouth=mouthFor(expression),
        eye=accent.eye if accent.eye is not None else DEFAULT_EYE_COLOR,
        background=accent.background if accent.background is not None else DEFAULT_BACKGROUND,
        **extra,
    )


def montarPaineis() -> list[Panel]:
    """Os quadros da folha: expressoes de repouso e instantes de movimento."""
    neutral = presetFor(Expression.NEUTRAL)
    thinking = presetFor(Expression.THINKING)

    panels: list[Panel] = []
    for expression in (
        Expression.NEUTRAL,
        Expression.HAPPY,
        Expression.ANGRY,
        Expression.RAGE,
        Expression.TIRED,
        Expression.LAUGH,
        Expression.SLEEP,
    ):
        shape = presetFor(expression)
        label = "MALUCO DE BRABO" if expression is Expression.RAGE else expression.value.upper()
        panels.append(panelFor(label, expression, shape, shape))

    dizzy = presetFor(Expression.DIZZY)
    panels += [
        panelFor(
            "PENSANDO",
            Expression.THINKING,
            replace(thinking, topLid=0.09, offsetX=-115, offsetY=-78),
            replace(thinking, topLid=0.21, offsetX=-115, offsetY=-78),
        ),
        panelFor(
            "FALANDO (pico)",
            Expression.SPEAKING,
            replace(neutral, height=1.055, width=0.972, offsetY=-6),
            replace(neutral, height=1.055, width=0.972, offsetY=-6),
        ),
        panelFor("TONTO (vortice)", Expression.DIZZY, dizzy, dizzy, swirl=1.0, swirlPhase=1.2),
        panelFor(
            "CURIOSO",
            Expression.NEUTRAL,
            replace(neutral, height=0.94, offsetX=380),
            replace(neutral, height=1.16, offsetX=380),
        ),
        Panel(
            "BRAVO -> FELIZ (meio)",
            presetFor(Expression.ANGRY).lerp(presetFor(Expression.HAPPY), 0.5),
            presetFor(Expression.ANGRY).lerp(presetFor(Expression.HAPPY), 0.5),
            mouth=mouthFor(Expression.ANGRY).lerp(mouthFor(Expression.HAPPY), 0.5),
        ),
        Panel("PISCANDO (fundo)", closeLids(neutral, 1.0), closeLids(neutral, 1.0)),
    ]
    return panels


def renderSheet(
    settings: FaceSettings,
    destination: Path,
    *,
    panelWidth: int = 640,
    panelHeight: int = 360,
) -> Path:
    """Desenha todas as expressoes num unico PNG e devolve o caminho salvo."""
    # O driver dummy permite gerar a folha sem abrir janela nenhuma.
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    import pygame

    from roboteye.face.renderer import EyeRenderer, qualityFor

    pygame.init()
    pygame.display.set_mode((64, 64))

    # A folha e estatica: nao ha orcamento de quadro a respeitar, entao ela sai
    # sempre no nivel mais alto, independente do que o robo usaria em execucao.
    quality = qualityFor("high")
    panels = montarPaineis()
    rows = (len(panels) + COLUMNS - 1) // COLUMNS
    theme = Theme.fromSettings(settings)

    sheet = pygame.Surface((panelWidth * COLUMNS, panelHeight * rows))
    sheet.fill(theme.background)
    font = pygame.font.Font(None, max(16, panelHeight // 16))

    layout = EyeLayout.forScreen(panelWidth, panelHeight)
    for index, p in enumerate(panels):
        panel = pygame.Surface((panelWidth, panelHeight))
        renderer = EyeRenderer(
            panel,
            layout,
            theme,
            quality=quality,
            cornerRadius=settings.cornerRadius,
            mouthEnabled=settings.mouthEnabled,
        )
        renderer.draw(
            EyeFrame(
                expression=Expression.NEUTRAL,
                left=p.left,
                right=p.right,
                eyeColor=p.eye,
                backgroundColor=p.background,
                mouth=p.mouth,
                swirl=p.swirl,
                swirlPhase=p.swirlPhase,
            )
        )

        panel.blit(font.render(p.label, True, theme.caption), (LABEL_MARGIN, LABEL_MARGIN))
        pygame.draw.rect(panel, theme.caption, (0, 0, panelWidth, panelHeight), 1)
        sheet.blit(panel, ((index % COLUMNS) * panelWidth, (index // COLUMNS) * panelHeight))

    destination.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, str(destination))
    pygame.quit()
    return destination
