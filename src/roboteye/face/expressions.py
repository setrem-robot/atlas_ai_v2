"""Expressoes da face.

Uma expressao e so um rotulo: a forma correspondente vive em `shapes.py`, e a
animacao que leva de uma a outra, em `animator.py`.
"""

from __future__ import annotations

from enum import Enum


class Expression(Enum):
    """O que a face esta demonstrando."""

    # -- humores (o que ela sente) ------------------------------------------
    NEUTRAL = "neutral"
    HAPPY = "happy"
    ANGRY = "angry"
    TIRED = "tired"
    LAUGH = "laugh"
    DIZZY = "dizzy"

    # -- estados (o que ela esta fazendo) -----------------------------------
    SLEEP = "sleep"
    THINKING = "thinking"
    SPEAKING = "speaking"
    LISTENING = "listening"

    @property
    def is_mood(self) -> bool:
        """Se pode ser definida como humor de repouso."""
        return self in _MOODS

    @property
    def is_activity(self) -> bool:
        """Se e imposta pelo assistente, tendo prioridade sobre o humor."""
        return self in _ACTIVITIES

    @property
    def is_transient(self) -> bool:
        """Se volta sozinha ao repouso depois de um tempo."""
        return self in _TRANSIENT


_MOODS = frozenset(
    {
        Expression.NEUTRAL,
        Expression.HAPPY,
        Expression.ANGRY,
        Expression.TIRED,
        Expression.LAUGH,
        Expression.DIZZY,
    }
)

_ACTIVITIES = frozenset({Expression.THINKING, Expression.SPEAKING, Expression.LISTENING})

_TRANSIENT = frozenset({Expression.LAUGH, Expression.DIZZY})

#: Peso de cada humor no sorteio ocioso. O neutro domina de proposito: uma face
#: que troca de expressao o tempo todo parece nervosa, nao viva.
IDLE_WEIGHTS: dict[Expression, int] = {
    Expression.NEUTRAL: 8,
    Expression.HAPPY: 3,
    Expression.TIRED: 2,
    Expression.ANGRY: 2,
    Expression.LAUGH: 1,
    Expression.DIZZY: 1,
}
