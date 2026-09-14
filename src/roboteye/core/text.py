"""Utilitarios de texto usados entre o LLM e a sintese de voz."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from roboteye.core.normalizePt import normalize as normalizePt

# Fim de frase: pontuacao final, espaco, e algo que nao seja letra minuscula.
# O lookahead evita cortar em reticencias no meio de uma frase ("bem... talvez"),
# que soariam como duas falas separadas.
_SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*\s+(?=[^a-záàâãéêíóôõúüç\s])")

# Ruidos comuns em saidas de LLM que nao devem ser falados.
_MARKDOWN_NOISE = re.compile(r"[*_`#]+")
_EMOJI_AND_SYMBOLS = re.compile(
    "["
    "\U0001f300-\U0001faff"  # pictogramas
    "\U00002600-\U000027bf"  # simbolos diversos
    "\U0001f1e6-\U0001f1ff"  # bandeiras
    "]+",
    flags=re.UNICODE,
)
_WHITESPACE = re.compile(r"\s+")


def cleanForSpeech(text: str, *, language: str = "") -> str:
    """Prepara um texto para a sintese.

    Sempre tira marcacao e emojis, que o TTS soletraria ou leria errado. Em
    portugues faz mais: numeros, horas, dinheiro e abreviacoes viram o que uma
    pessoa diria em voz alta, porque nenhum dos motores de voz usados aqui le
    "R$ 25,90" corretamente.

    A normalizacao e por idioma porque as regras sao: "15:30" vira "quinze e
    trinta" em portugues e outra coisa em qualquer outra lingua.
    """
    cleaned = _MARKDOWN_NOISE.sub("", text)
    cleaned = _EMOJI_AND_SYMBOLS.sub(" ", cleaned)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip()

    if language.lower().startswith("pt"):
        cleaned = normalizePt(cleaned)
    return cleaned


def splitSentences(text: str) -> list[str]:
    """Divide um texto em frases, preservando a pontuacao."""
    sentences: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text + " "):
        sentence = text[start : match.end()].strip()
        if sentence:
            sentences.append(sentence)
        start = match.end()

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def streamSentences(tokens: Iterable[str], *, minChars: int = 24) -> Iterator[str]:
    """Reagrupa um fluxo de tokens do LLM em frases completas.

    E o que permite comecar a falar antes de o modelo terminar de responder:
    assim que uma frase fecha, ela ja pode ir para a sintese.

    `min_chars` evita mandar fragmentos minusculos ("Ok.") para o TTS, que
    soariam picotados; frases curtas sao acumuladas com a seguinte.
    """
    buffer = ""
    for token in tokens:
        buffer += token
        while True:
            match = _SENTENCE_END.search(buffer)
            if match is None:
                break
            candidate = buffer[: match.end()].strip()
            if len(candidate) < minChars:
                break
            buffer = buffer[match.end() :]
            if candidate:
                yield candidate

    tail = buffer.strip()
    if tail:
        yield tail


def truncate(text: str, limit: int = 80) -> str:
    """Encurta um texto para exibicao em log."""
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"
