"""Reescreve um texto para que a sintese o leia como gente.

O modelo de linguagem escreve para ser lido com os olhos: "R$ 25,90", "15:30",
"23°C". O modelo de voz nunca viu isso escrito assim em quantidade suficiente e
soletra, erra ou pula. Este modulo faz a ponte, trocando cada forma abreviada
pelo que uma pessoa diria em voz alta.

**A ordem das trocas importa.** "R$ 25,90" tem um numero decimal dentro; se a
regra dos decimais rodar antes da regra do dinheiro, sobra "vinte e cinco
virgula noventa reais", que ninguem fala. As regras mais especificas vem
primeiro, e cada uma consome o que reconheceu.

**Conservador de proposito.** Cada troca aqui e uma chance de estragar um texto
que estava certo — um "m" virando "metros" no meio de uma sigla, um "1.234" que
era numero de versao virando "mil duzentos e trinta e quatro". Quando uma forma
e ambigua, este modulo prefere nao mexer: a voz lendo um simbolo estranho de vez
em quando incomoda menos que uma frase remontada errado.
"""

from __future__ import annotations

import re

from roboteye.core.numbersPt import spell, spellDecimal, spellOrdinal

#: Abreviacoes que aparecem em conversa e que a sintese leria letra por letra.
ABBREVIATIONS = {
    "dr": "doutor",
    "dra": "doutora",
    "sr": "senhor",
    "sra": "senhora",
    "srta": "senhorita",
    "prof": "professor",
    "profa": "professora",
    "etc": "et cetera",
    "obs": "observacao",
    "pag": "pagina",
    "tel": "telefone",
}

#: Unidades seguras de expandir: nao colidem com palavras comuns nem com siglas.
UNITS = {
    "km/h": ("quilometro por hora", "quilometros por hora"),
    "km": ("quilometro", "quilometros"),
    "kg": ("quilo", "quilos"),
    "cm": ("centimetro", "centimetros"),
    "mm": ("milimetro", "milimetros"),
    "ml": ("mililitro", "mililitros"),
    "gb": ("giga", "gigas"),
    "mb": ("mega", "megas"),
}


def normalize(text: str) -> str:
    """Aplica todas as trocas, da forma mais especifica para a mais geral."""
    for rule in _RULES:
        text = rule(text)
    return text


# ---------------------------------------------------------------------------
# Regras, na ordem em que rodam
# ---------------------------------------------------------------------------
def money(text: str) -> str:
    """`R$ 25,90` -> "vinte e cinco reais e noventa centavos"."""

    def replace(match: re.Match[str]) -> str:
        whole = toInt(match.group("whole"))
        cents = int((match.group("cents") or "0").ljust(2, "0")[:2])

        reais = f"{spell(whole)} {'real' if whole == 1 else 'reais'}"
        if cents == 0:
            return reais
        centavos = f"{spell(cents)} {'centavo' if cents == 1 else 'centavos'}"
        return f"{reais} e {centavos}"

    return _MONEY.sub(replace, text)


def percent(text: str) -> str:
    """`35%` -> "trinta e cinco por cento"."""

    def replace(match: re.Match[str]) -> str:
        return f"{spellNumber(match.group('number'))} por cento"

    return _PERCENT.sub(replace, text)


def time(text: str) -> str:
    """`15:30` -> "quinze e trinta"; `15:00` -> "quinze horas"."""

    def replace(match: re.Match[str]) -> str:
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return match.group(0)

        # "hora" e feminino: uma hora, vinte e uma horas. Os minutos nao seguem
        # a hora — dizem-se no masculino.
        spoken = spell(hour, feminine=True)
        if minute == 0:
            return f"{spoken} {'hora' if hour == 1 else 'horas'}"
        return f"{spoken} e {spell(minute)}"

    return _TIME.sub(replace, text)


def temperature(text: str) -> str:
    """`23°C` -> "vinte e tres graus"."""

    def replace(match: re.Match[str]) -> str:
        number = spellNumber(match.group("number"))
        return f"{number} {'grau' if match.group('number') == '1' else 'graus'}"

    return _TEMPERATURE.sub(replace, text)


def units(text: str) -> str:
    """`5 km` -> "cinco quilometros"."""

    def replace(match: re.Match[str]) -> str:
        raw = match.group("number")
        unit = match.group("unit").lower()
        singular, plural = UNITS[unit]
        name = singular if raw in {"1", "-1"} else plural
        return f"{spellNumber(raw)} {name}"

    return _UNIT.sub(replace, text)


def ordinals(text: str) -> str:
    """`1º` -> "primeiro"; `2ª` -> "segunda"."""

    def replace(match: re.Match[str]) -> str:
        marker = match.group("marker")
        return spellOrdinal(int(match.group("number")), feminine=marker in "ªa")

    return _ORDINAL.sub(replace, text)


def abbreviations(text: str) -> str:
    """`Dr.` -> "doutor"."""

    def replace(match: re.Match[str]) -> str:
        return ABBREVIATIONS[match.group(1).lower()]

    return _ABBREV.sub(replace, text)


def numbers(text: str) -> str:
    """O que sobrou de numero solto, incluindo decimais e milhar com ponto."""
    return _NUMBER.sub(lambda m: spellNumber(m.group(0)), text)


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------
def toInt(raw: str) -> int:
    """Le um inteiro que pode vir com ponto de milhar."""
    return int(raw.replace(".", ""))


def spellNumber(raw: str) -> str:
    """Escreve por extenso um numero cru, com ou sem parte decimal."""
    raw = raw.strip()
    negative = raw.startswith("-")
    raw = raw.lstrip("+-")

    whole, _, fraction = raw.partition(",")
    try:
        value = toInt(whole or "0")
    except ValueError:
        return raw

    text = spellDecimal(value, fraction) if fraction else spell(value)
    return f"menos {text}" if negative else text


# Um numero como aparece escrito: milhar com ponto, decimal com virgula.
_RAW = r"\d{1,3}(?:\.\d{3})+|\d+"

_MONEY = re.compile(
    rf"R\$\s*(?P<whole>{_RAW})(?:,(?P<cents>\d{{1,2}}))?",
    re.IGNORECASE,
)
_PERCENT = re.compile(rf"(?P<number>-?(?:{_RAW})(?:,\d+)?)\s*%")
_TIME = re.compile(r"\b(?P<hour>\d{1,2})[:h](?P<minute>\d{2})\b")
_TEMPERATURE = re.compile(rf"(?P<number>-?(?:{_RAW})(?:,\d+)?)\s*(?:°|graus?\s+)C?\b")


def longestFirst(words: object) -> str:
    """Alternativa de regex com as opcoes maiores na frente.

    A ordem nao e cosmetica: a alternancia do `re` para na primeira opcao que
    casa, entao "km" antes de "km/h" faria "80 km/h" virar "oitenta quilometros
    /h".
    """
    return "|".join(sorted(words, key=len, reverse=True))  # type: ignore[call-overload]


_UNIT = re.compile(
    rf"(?P<number>-?(?:{_RAW})(?:,\d+)?)\s*(?P<unit>{longestFirst(UNITS)})\b",
    re.IGNORECASE,
)
_ORDINAL = re.compile(r"\b(?P<number>\d{1,2})\s*(?P<marker>[ºª°ao])(?![a-z])", re.IGNORECASE)
_ABBREV = re.compile(rf"\b({longestFirst(ABBREVIATIONS)})\.", re.IGNORECASE)
# Os dois-pontos ao redor sao um veto: um numero grudado num deles faz parte de
# algo maior — uma hora, um placar, uma duracao. A regra da hora ja teve a sua
# chance e, se recusou, foi porque nao reconheceu o formato. Ler as metades como
# numeros soltos remontaria a expressao errado, que e pior que nao mexer.
_NUMBER = re.compile(rf"(?<![\d:])-?(?:{_RAW})(?:,\d+)?(?![\d:])")

#: A ordem e a propria regra: quem reconhece mais contexto vai primeiro.
_RULES = (
    money,
    time,
    percent,
    temperature,
    units,
    ordinals,
    abbreviations,
    numbers,
)
