"""Gera uma folha de contato com as expressoes da face.

Serve para ajustar a estetica sem precisar rodar o robo inteiro e esperar a hora
de cada expressao aparecer: mexeu num parametro, roda `roboteye preview` e olha.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from roboteye.config import FaceSettings
from roboteye.face.animator import EyeFrame, closeLids
from roboteye.face.expressions import Expression
from roboteye.face.layout import EyeLayout
from roboteye.face.shapes import EyeShape, presetFor
from roboteye.face.theme import Theme

COLUMNS = 3
LABEL_MARGIN = 14


def montarPaineis() -> list[tuple[str, EyeShape, EyeShape]]:
    """Os quadros da folha: expressoes de repouso e instantes de movimento."""
    neutral = presetFor(Expression.NEUTRAL)
    thinking = presetFor(Expression.THINKING)

    panels: list[tuple[str, EyeShape, EyeShape]] = []
    for expression in (
        Expression.NEUTRAL,
        Expression.HAPPY,
        Expression.ANGRY,
        Expression.TIRED,
        Expression.LAUGH,
        Expression.SLEEP,
    ):
        shape = presetFor(expression)
        panels.append((expression.value.upper(), shape, shape))

    panels += [
        (
            "PENSANDO",
            replace(thinking, topLid=0.09, offsetX=-115, offsetY=-78),
            replace(thinking, topLid=0.21, offsetX=-115, offsetY=-78),
        ),
        (
            "FALANDO (pico)",
            replace(neutral, height=1.055, width=0.972, offsetY=-6),
            replace(neutral, height=1.055, width=0.972, offsetY=-6),
        ),
        (
            "PISCANDO (meio)",
            closeLids(neutral, 0.55),
            closeLids(neutral, 0.55),
        ),
        (
            "CURIOSO",
            replace(neutral, height=0.94, offsetX=380),
            replace(neutral, height=1.16, offsetX=380),
        ),
        (
            "BRAVO -> FELIZ (meio)",
            presetFor(Expression.ANGRY).lerp(presetFor(Expression.HAPPY), 0.5),
            presetFor(Expression.ANGRY).lerp(presetFor(Expression.HAPPY), 0.5),
        ),
        (
            "PISCANDO (fundo)",
            closeLids(neutral, 1.0),
            closeLids(neutral, 1.0),
        ),
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
    for index, (label, left, right) in enumerate(panels):
        panel = pygame.Surface((panelWidth, panelHeight))
        renderer = EyeRenderer(
            panel,
            layout,
            theme,
            quality=quality,
            cornerRadius=settings.cornerRadius,
        )
        renderer.draw(EyeFrame(expression=Expression.NEUTRAL, left=left, right=right))

        panel.blit(font.render(label, True, theme.caption), (LABEL_MARGIN, LABEL_MARGIN))
        pygame.draw.rect(panel, theme.caption, (0, 0, panelWidth, panelHeight), 1)
        sheet.blit(panel, ((index % COLUMNS) * panelWidth, (index // COLUMNS) * panelHeight))

    destination.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(sheet, str(destination))
    pygame.quit()
    return destination
