"""Geometria da face.

As medidas sao escritas num referencial fixo de 2560x1440 e convertidas para a
resolucao real por um unico fator de escala. Assim a face fica igual num monitor
4K e numa telinha de 800x480 do Raspberry Pi.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Resolucao de referencia em que as medidas abaixo foram desenhadas.
BASE_WIDTH = 2560
BASE_HEIGHT = 1440

# Medidas em unidades base.
EYE_WIDTH = 640
EYE_HEIGHT = 640
EYE_Y_OFFSET = -150
LOOK_RANGE = 380
CAPTION_MARGIN = 40
CAPTION_SIZE = 46


@dataclass(frozen=True, slots=True)
class EyeLayout:
    """Posicoes e tamanhos ja convertidos para pixels."""

    screenWidth: int
    screenHeight: int
    scale: float

    eyeWidth: int
    eyeHeight: int

    leftEyeX: int
    rightEyeX: int
    eyeCenterY: int

    @classmethod
    def forScreen(cls, width: int, height: int) -> EyeLayout:
        """Calcula o layout para uma tela de `width` x `height` pixels."""
        scale = min(width / BASE_WIDTH, height / BASE_HEIGHT)

        def px(value: float) -> int:
            return max(1, int(value * scale))

        return cls(
            screenWidth=width,
            screenHeight=height,
            scale=scale,
            eyeWidth=px(EYE_WIDTH),
            eyeHeight=px(EYE_HEIGHT),
            leftEyeX=width // 3,
            rightEyeX=2 * width // 3,
            eyeCenterY=height // 2 + int(EYE_Y_OFFSET * scale),
        )

    def px(self, baseValue: float) -> int:
        """Converte uma medida do referencial base para pixels."""
        return int(baseValue * self.scale)

    @property
    def captionFontSize(self) -> int:
        return max(12, self.px(CAPTION_SIZE))

    @property
    def captionMargin(self) -> int:
        return max(8, self.px(CAPTION_MARGIN))
