"""Utilitarios de texto usados entre o LLM e a sintese de voz."""

from __future__ import annotations

import re
import unicodedata
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


#: Palavras que nao fecham frase: cortado o laco antes delas, a frase acabaria
#: pendurada ("um bolo de chocolate com.").
_PENDURADAS = {
    "a",
    "o",
    "as",
    "os",
    "um",
    "uma",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "e",
    "com",
    "como",
    "que",
    "em",
    "no",
    "na",
    "para",
    "pra",
    "por",
    "mas",
    "ou",
    "se",
    "mais",
}


def _repeticao(texto: str, n: int = 4, vezes: int = 2) -> int | None:
    """Indice da palavra onde um trecho de `n` palavras aparece pela `vezes`-esima vez."""
    palavras = [p.lower() for p in re.findall(r"\w+", texto)]
    contagem: dict[tuple[str, ...], int] = {}
    for i in range(len(palavras) - n + 1):
        trecho = tuple(palavras[i : i + n])
        contagem[trecho] = contagem.get(trecho, 0) + 1
        if contagem[trecho] == vezes:
            return i
    return None


def pararNoLaco(tokens: Iterable[str], *, n: int = 4) -> Iterator[str]:
    """Para de ler o modelo quando ele comeca a repetir um trecho.

    O modelo pequeno as vezes entra em laco ("um terco de um terco de um terco")
    ate o teto de tokens: segundos de fala que nao dizem nada. Parar aqui fecha
    o stream e o Ollama para de gerar; `cortarLaco` apara o que ja veio.
    """
    texto = ""
    for token in tokens:
        yield token
        texto += token
        # Ate o ultimo espaco: palavra pela metade nao conta como repeticao. Tres
        # vezes, nao duas: citar "Engenharia de Computacao" duas vezes e normal.
        if _repeticao(texto[: texto.rfind(" ") + 1], n, vezes=3) is not None:
            fechar = getattr(tokens, "close", None)
            if fechar:
                fechar()
            return


def cortarLaco(frase: str, *, n: int = 4) -> str:
    """A frase ate antes do trecho repetido, fechada com ponto; sem laco, ela mesma."""
    inicio = _repeticao(frase, n)
    if inicio is None:
        return frase
    palavras = list(re.finditer(r"\w+", frase))
    while inicio > 1 and palavras[inicio - 1].group().lower() in _PENDURADAS:
        inicio -= 1
    return frase[: palavras[inicio].start()].rstrip(" ,;:-") + "."


def simplificar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação: o Vosk já entrega assim."""
    semAcento = "".join(
        letra
        for letra in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(letra) != "Mn"
    )
    return " ".join(re.sub(r"[^\w\s]", " ", semAcento).split())
