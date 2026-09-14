"""Curvas de aceleracao e interpolacao temporal.

Movimento com velocidade constante e o que faz uma animacao parecer robotica no
mau sentido. Tudo que se move aqui passa por uma curva: comeca devagar, acelera,
freia antes de chegar. E a diferenca entre um olho que desliza e um olho que vive.

Todas as curvas recebem e devolvem um valor normalizado em 0..1.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

Easing = Callable[[float], float]


# ---------------------------------------------------------------------------
# Curvas
# ---------------------------------------------------------------------------
def linear(t: float) -> float:
    return t


def easeInQuad(t: float) -> float:
    """Comeca parado e acelera. Bom para o fechar da palpebra."""
    return t * t


def easeOutQuad(t: float) -> float:
    """Comeca rapido e freia. Bom para o abrir da palpebra."""
    return t * (2.0 - t)


def easeOutCubic(t: float) -> float:
    """Arranque forte com freada longa: o perfil de uma sacada ocular."""
    return 1.0 - (1.0 - t) ** 3


def easeInOutCubic(t: float) -> float:
    """Suave nas duas pontas. O padrao para trocas de expressao."""
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0


def easeOutBack(t: float, overshoot: float = 1.7) -> float:
    """Passa um pouco do alvo e volta. Da um 'pop' de vida a um movimento."""
    c3 = overshoot + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + overshoot * (t - 1.0) ** 2


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------
def lerp(start: float, end: float, t: float) -> float:
    return start + (end - start) * t


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return low if value < low else high if value > high else value


def approach(current: float, target: float, dt: float, rate: float) -> float:
    """Aproximacao exponencial, independente da taxa de quadros.

    Diferente de `current += (target - current) * 0.1`, que anda mais rapido
    quanto maior o FPS, esta versao chega no mesmo lugar no mesmo tempo real.
    `rate` e a velocidade: 10 converge em ~0,3 s, 3 em ~1 s.
    """
    return target + (current - target) * math.exp(-rate * dt)


# ---------------------------------------------------------------------------
# Tween
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Tween:
    """Anima um valor ate um alvo, ao longo de uma duracao, seguindo uma curva.

    Diferente de uma aproximacao exponencial, o tween tem inicio e fim
    definidos — o que importa quando o movimento precisa de tempo exato, como
    uma piscada ou uma sacada.
    """

    value: float = 0.0
    easing: Easing = field(default=easeInOutCubic)

    start: float = field(default=0.0, init=False)
    targetValue: float = field(default=0.0, init=False)
    duration: float = field(default=0.0, init=False)
    elapsed: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self.start = self.value
        self.targetValue = self.value

    def to(self, target: float, duration: float, easing: Easing | None = None) -> None:
        """Inicia um novo movimento a partir de onde o valor esta agora."""
        if easing is not None:
            self.easing = easing
        self.start = self.value
        self.targetValue = target
        self.duration = max(0.0, duration)
        self.elapsed = 0.0

        if self.duration == 0.0:
            self.value = target

    def snap(self, value: float) -> None:
        """Salta para um valor, cancelando o movimento em curso."""
        self.value = value
        self.start = value
        self.targetValue = value
        self.elapsed = self.duration

    def update(self, dt: float) -> float:
        if self.done:
            return self.value

        self.elapsed = min(self.elapsed + dt, self.duration)
        progress = clamp(self.elapsed / self.duration)
        self.value = lerp(self.start, self.targetValue, self.easing(progress))
        return self.value

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    @property
    def target(self) -> float:
        return self.targetValue
