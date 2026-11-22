"""Humor da face a partir do que se diz.

Xingou, ela fica brava; a resposta é alegre, ela sorri; não entendeu, fica
tonta. Sem modelo nenhum: palavras-chave sobre o texto que já existe (a
transcrição e cada trecho falado), de graça no Pi e sem atrasar a fala.

Devolve o valor das `Expression` da face ("angry", "happy", ...) como texto,
para o núcleo não depender do pacote da face.
"""

from __future__ import annotations

import re

from roboteye.core.palavrasProibidas import xingamentoEm
from roboteye.core.text import simplificar

# Ofensa só conta dita a ela ("você é burra", "sua idiota", "robô inútil") ou
# sozinha ("idiota"): "onde jogo o lixo" não é xingamento.
_OFENSA = (
    r"(burr[ao]|idiota|estupid[ao]|imbecil|otari[ao]|babaca|retardad[ao]|inutil|lixo"
    r"|ridicul[ao]|trouxa|anta|jumenta|cretin[ao]|feia|chata|lerda|lesad[ao]|tapad[ao]|ignorante)"
)
_DIRIGIDA = re.compile(
    rf"\b(voce|vc|tu|ce|sua|seu|robo|robozinho|atlas|que|como|ta|e uma?)\b"
    rf"(\s+\w+){{0,2}}\s+{_OFENSA}\b"
)
_SOZINHA = re.compile(rf"^(\w+\s+)?{_OFENSA}(\s+\w+)?$")


def xingou(texto: str) -> bool:
    """A pessoa xingou ou ofendeu o robô?"""
    s = simplificar(texto)
    # Palavrão, preconceito, ameaça: xingamento em qualquer lugar da frase.
    return xingamentoEm(s) or bool(_DIRIGIDA.search(s) or _SOZINHA.search(s))


#: Uma risada escrita: "haha", "hahaha", "ha ha", "kkkk", "rsrs", "hehe", "rá rá".
#: Sobre o texto cru (com acento e caixa), porque e usada tambem para tirar a
#: risada da fala antes da sintese — ver `trechosDaRisada`.
RISADA = re.compile(
    r"\b(?:k{3,}|(?:h[aá]){2,}h?|(?:he){2,}h?|(?:hi){2,}h?|(?:rs){2,}"
    r"|(?:h[aá][\s,]+){1,}h[aá]|r[aá](?:[\s,]+r[aá])+)\b[!.,]*",
    re.IGNORECASE,
)

_BRAVA = re.compile(
    r"\b(respeito|grosseria|nao gostei|xing\w*|ofens\w*|mal educad[ao]|fiquei chatead[ao])\b"
)
_CONFUSA = re.compile(r"\b(nao entendi|pode repetir|como assim)\b")
_TRISTE = re.compile(
    r"\b(infelizmente|desculp\w*|sinto muito|que pena|triste|cansad[ao]|nao consigo)\b"
)
_ALEGRE = re.compile(
    r"\b(que bom|adoro|adorei|amo|gosto muito|legal|feliz|alegria|obrigad[ao]|agradec\w*"
    r"|de nada|prazer|parabens|bem vind[ao]|oba|otim[ao]|incrivel|bacana|maravilh\w*"
    r"|com certeza|bom dia|boa tarde|boa noite|oi|ola|essa foi boa|engracad[ao])\b"
)
#: Elogio so conta dito a ela, como a ofensa: "voce e linda", "gosto de voce".
_ELOGIO = re.compile(
    r"\b(voce|vc|tu|atlas|robo)\b(\s+\w+){0,2}\s+(linda|lindo|inteligente|legal|incrivel"
    r"|demais|fofa|fofo|engracada|engracado|esperta|esperto|bonita|bonito|maravilhosa"
    r"|sensacional|a melhor|o melhor)\b"
    r"|\b(gosto|gostei|adoro|amo) (muito )?(de )?(voce|vc|tu|te)\b|\bte (amo|adoro)\b"
    r"|\b(parabens|muito bem|mandou bem|boa atlas)\b"
)


def humorDaFala(fala: str) -> str | None:
    """Humor de um trecho que ela vai falar; `None` é neutro (a cara não muda).

    Antes uma pergunta com "piada" fazia rir a resposta inteira, inclusive a
    pergunta da piada, antes da graça. Agora quem ri é a fala que tem risada —
    e as piadas prontas (`core/piadas.py`) poem o "haha" no lugar certo.
    """
    if RISADA.search(fala):
        return "laugh"
    s = simplificar(fala)
    if _BRAVA.search(s):
        return "angry"
    if _CONFUSA.search(s):
        return "dizzy"
    if _TRISTE.search(s):
        return "tired"
    if _ALEGRE.search(s):
        return "happy"
    return None


def riu(texto: str) -> bool:
    """A pessoa riu ("kkkk", "hahaha")? Vale para o que ela digita ou fala."""
    return bool(RISADA.search(texto))


def soRiu(texto: str) -> bool:
    """A mensagem inteira e so risada — nao ha pergunta nenhuma a responder."""
    return bool(texto.strip()) and not simplificar(RISADA.sub(" ", texto))


def elogiou(texto: str) -> bool:
    """A pessoa elogiou o robô?"""
    return bool(_ELOGIO.search(simplificar(texto)))


def trechosDaRisada(texto: str) -> list[tuple[str, bool]]:
    """Corta o texto nos pontos de risada: `(trecho, eRisada)`, na ordem.

    A voz nao sabe rir: lendo "kkkk" ela soletra, lendo "hahaha" sai um "aha"
    seco. O locutor troca cada risada por um som de riso e fala o resto.
    """
    trechos: list[tuple[str, bool]] = []
    inicio = 0
    for achado in RISADA.finditer(texto):
        if texto[inicio : achado.start()].strip():
            trechos.append((texto[inicio : achado.start()], False))
        trechos.append((achado.group(), True))
        inicio = achado.end()
    if texto[inicio:].strip():
        trechos.append((texto[inicio:], False))
    return trechos


# ---------------------------------------------------------------------------
# O ânimo: o humor que dura a conversa
# ---------------------------------------------------------------------------
#: Quanto cada coisa mexe no ânimo, de -1 (chateada) a 1 (alegre).
EMPURRAO: dict[str, float] = {
    "laugh": 0.25,
    "happy": 0.1,
    "elogio": 0.35,
    "tired": -0.1,
    "angry": -0.2,
    "xingou": -0.5,
}

#: A partir de quanto o ânimo muda a cara de repouso.
LIMIAR_DE_HUMOR = 0.3


class Animo:
    """O humor que dura: sobe com riso e carinho, desce com grosseria, e passa.

    A face antes voltava ao neutro a cada pergunta e sorteava caras no ocioso —
    inclusive brava, sem motivo. Era uma face que reagia, nao uma que sentia.
    Aqui cada reacao deixa um resto que decai pela metade a cada `meiaVidaS`:
    depois de umas risadas ela fica alegre por um tempo; depois de um
    xingamento, chateada; e em poucos minutos sem nada, volta ao normal.
    """

    def __init__(self, meiaVidaS: float = 120.0) -> None:
        self.meiaVidaS = meiaVidaS
        self.valor = 0.0
        self.desde = 0.0

    def atual(self, agora: float) -> float:
        passou = max(0.0, agora - self.desde)
        return self.valor * 0.5 ** (passou / self.meiaVidaS)

    def sentir(self, motivo: str, agora: float) -> None:
        """Soma o empurrao de um motivo (`EMPURRAO`); motivo desconhecido nao mexe."""
        self.valor = min(1.0, max(-1.0, self.atual(agora) + EMPURRAO.get(motivo, 0.0)))
        self.desde = agora

    def repouso(self, agora: float) -> str:
        """A cara de quando nada esta acontecendo: valor de uma `Expression`."""
        valor = self.atual(agora)
        if valor >= LIMIAR_DE_HUMOR:
            return "happy"
        if valor <= -LIMIAR_DE_HUMOR:
            return "tired"
        return "neutral"
