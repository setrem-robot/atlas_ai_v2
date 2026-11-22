"""Humor da face a partir do que se diz.

Xingou, ela fica brava; a resposta é alegre, ela sorri; não entendeu, fica
tonta. Sem modelo nenhum: palavras-chave sobre o texto que já existe (a
transcrição e cada trecho falado), de graça no Pi e sem atrasar a fala.

Devolve o valor das `Expression` da face ("angry", "happy", ...) como texto,
para o núcleo não depender do pacote da face.
"""

from __future__ import annotations

import re
import unicodedata


def _simples(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação: o Vosk já entrega assim."""
    semAcento = "".join(
        letra
        for letra in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(letra) != "Mn"
    )
    return " ".join(re.sub(r"[^\w\s]", " ", semAcento).split())


# Palavrão é xingamento em qualquer lugar da frase.
_PALAVRAO = re.compile(
    r"\b(porra|caralho|merda|bosta|puta|puto|fdp|desgracad[ao]|arrombad[ao]|vagabund[ao]"
    r"|filh[ao] da puta|vai se (ferrar|foder|lascar)|vai tomar no|cala (a )?boca"
    r"|te odeio|odeio (voce|vc|tu))\b"
)
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
    s = _simples(texto)
    return bool(_PALAVRAO.search(s) or _DIRIGIDA.search(s) or _SOZINHA.search(s))


_BRAVA = re.compile(
    r"\b(respeito|grosseria|nao gostei|xing\w*|ofens\w*|mal educad[ao]|fiquei chatead[ao])\b"
)
_CONFUSA = re.compile(r"\b(nao entendi|pode repetir|como assim)\b")
_RISO = re.compile(r"\b(haha\w*|kkk\w*|hehe\w*|rsrs\w*)\b")
_PIADA = re.compile(r"\b(piada|charada|adivinha|me faz rir|algo engracado)\b")
_TRISTE = re.compile(
    r"\b(infelizmente|desculp\w*|sinto muito|que pena|triste|cansad[ao]|nao consigo)\b"
)
_ALEGRE = re.compile(
    r"\b(que bom|adoro|adorei|amo|gosto muito|legal|feliz|alegria|obrigad[ao]|de nada|prazer"
    r"|parabens|bem vind[ao]|oba|otim[ao]|incrivel|bacana|maravilh\w*|com certeza|bom dia"
    r"|boa tarde|boa noite|oi|ola)\b"
)


def humorDaFala(fala: str, pergunta: str = "") -> str | None:
    """Humor de um trecho que ela vai falar; `None` é neutro (a cara não muda)."""
    s = _simples(fala)
    if _BRAVA.search(s):
        return "angry"
    if _CONFUSA.search(s):
        return "dizzy"
    if _RISO.search(s) or _PIADA.search(_simples(pergunta)):
        return "laugh"
    if _TRISTE.search(s):
        return "tired"
    if _ALEGRE.search(s):
        return "happy"
    return None
