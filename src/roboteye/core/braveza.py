"""Braveza: xingou, ela responde brava, sem passar pelo modelo.

A face ja fica brava ao ouvir um xingamento (`face/app.py`), mas a resposta
vinha do modelo, que nao foi treinado para isso: medido no Pi, "voce e burra"
deu "ainda estou aprendendo, mas prometo melhorar". Cara brava com fala
humilde nao convence. Aqui a fala acompanha a cara: firme, curta, sem xingar
de volta, e com variacao para nao soar gravada. Pediu desculpa logo depois,
ela aceita.
"""

from __future__ import annotations

import random
import re

from roboteye.core.humor import simplificar, xingou

_BRAVA = (
    "Ei, não gostei disso. Me trata com respeito.",
    "Opa, mais respeito comigo! Eu não te xinguei.",
    "Que grosseria. Estou aqui para ajudar, não para ser xingada.",
    "Isso foi feio. Se quiser conversar, fala direito comigo.",
    "Não precisa ofender. Educação não custa nada.",
    "Fiquei chateada com isso. Vamos manter o respeito?",
)
#: Do terceiro xingamento seguido em diante: a face vira "monstro", a fala sobe o tom.
_MUITO_BRAVA = (
    "Chega! Já pedi respeito. Assim eu não converso.",
    "De novo? Agora fiquei brava de verdade. Respeito, por favor!",
    "Para com isso! Xingar não vai te levar a lugar nenhum comigo.",
)
_PERDOA = (
    "Tudo bem, desculpas aceitas. Vamos recomeçar?",
    "Está desculpado. Em que posso ajudar?",
    "Ok, passou. Agora me pergunta algo legal!",
)
_DESCULPA = re.compile(r"\b(desculp\w*|perdao|foi mal|sinto muito)\b")


class Braveza:
    """Lembra quantos xingamentos seguidos vieram, para subir o tom e perdoar."""

    def __init__(self) -> None:
        self.seguidos = 0

    def responder(self, fala: str) -> str | None:
        """Resposta pronta para xingamento ou desculpa; None deixa para o modelo."""
        if xingou(fala):
            self.seguidos += 1
            return random.choice(_BRAVA if self.seguidos < 3 else _MUITO_BRAVA)
        perdoou = self.seguidos and _DESCULPA.search(simplificar(fala))
        self.seguidos = 0
        return random.choice(_PERDOA) if perdoou else None
