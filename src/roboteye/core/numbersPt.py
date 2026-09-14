"""Numeros por extenso, em portugues do Brasil.

Um modelo de TTS aprende a pronunciar o que viu escrito, e nenhum dos que este
projeto usa viu digitos suficientes para ler "137" direito. Na pratica eles
soletram, inventam, ou pulam. Escrever o numero por extenso antes de mandar para
a sintese resolve o problema na origem — e nao ha jeito de contornar isso do
lado do audio.

O portugues traz duas armadilhas que o ingles nao tem:

* **Concordancia.** "um"/"uma" e "dois"/"duas" mudam com o genero do que contam,
  e as centenas tambem ("duzentos reais", "duzentas pessoas"). Quem chama passa
  o genero; o padrao e masculino.
* **O "e".** Ao contrario do ingles, ele e obrigatorio entre as ordens de
  grandeza — "cento e vinte e tres" —, mas some antes das centenas redondas
  ("mil duzentos", nao "mil e duzentos"), exceto quando o que vem depois e
  redondo ("mil e duzentos" esta certo se for exatamente 1200).
"""

from __future__ import annotations

UNITS = (
    "zero",
    "um",
    "dois",
    "tres",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "quatorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
)

TENS = (
    "",
    "",
    "vinte",
    "trinta",
    "quarenta",
    "cinquenta",
    "sessenta",
    "setenta",
    "oitenta",
    "noventa",
)

HUNDREDS = (
    "",
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
)

#: Nome de cada ordem de grandeza, no singular e no plural.
SCALES = (
    ("", ""),
    ("mil", "mil"),
    ("milhao", "milhoes"),
    ("bilhao", "bilhoes"),
    ("trilhao", "trilhoes"),
)

#: Palavras que mudam no feminino. As centenas seguem o mesmo padrao (-entos
#: vira -entas) e sao tratadas por regra, nao por tabela.
_FEMININE = {"um": "uma", "dois": "duas"}


def spell(value: int, *, feminine: bool = False) -> str:
    """Escreve um numero inteiro por extenso."""
    if value < 0:
        return f"menos {spell(-value, feminine=feminine)}"
    if value < 20:
        return agree(UNITS[value], feminine)
    if value < 100:
        return spellTens(value, feminine)
    if value < 1000:
        return spellHundreds(value, feminine)
    return spellLarge(value, feminine)


def spellDecimal(whole: int, fraction: str, *, feminine: bool = False) -> str:
    """Escreve um numero com virgula: `3,5` vira "tres virgula cinco".

    Os digitos depois da virgula sao lidos um a um, que e como se le em voz alta
    quando eles nao formam uma unidade conhecida.
    """
    digits = " ".join(UNITS[int(d)] for d in fraction if d.isdigit())
    if not digits:
        return spell(whole, feminine=feminine)
    return f"{spell(whole, feminine=feminine)} virgula {digits}"


def spellYear(value: int) -> str:
    """Escreve um ano. Anos sao lidos como numeros inteiros em portugues."""
    return spell(value)


def spellOrdinal(value: int, *, feminine: bool = False) -> str:
    """Escreve um ordinal ate 10, que cobre o que aparece em conversa."""
    names = (
        "primeiro",
        "segundo",
        "terceiro",
        "quarto",
        "quinto",
        "sexto",
        "setimo",
        "oitavo",
        "nono",
        "decimo",
    )
    if not 1 <= value <= len(names):
        return spell(value, feminine=feminine)
    word = names[value - 1]
    return word[:-1] + "a" if feminine else word


# ---------------------------------------------------------------------------
# Interno
# ---------------------------------------------------------------------------
def agree(word: str, feminine: bool) -> str:
    """Concorda uma palavra com o genero pedido."""
    if not feminine:
        return word
    if word in _FEMININE:
        return _FEMININE[word]
    if word.endswith("entos"):
        return word[:-5] + "entas"
    return word


def spellTens(value: int, feminine: bool) -> str:
    tens, unit = divmod(value, 10)
    if unit == 0:
        return TENS[tens]
    return f"{TENS[tens]} e {agree(UNITS[unit], feminine)}"


def spellHundreds(value: int, feminine: bool) -> str:
    hundreds, rest = divmod(value, 100)
    if value == 100:
        return "cem"
    if rest == 0:
        return agree(HUNDREDS[hundreds], feminine)
    return f"{agree(HUNDREDS[hundreds], feminine)} e {spell(rest, feminine=feminine)}"


def spellLarge(value: int, feminine: bool) -> str:
    """Monta o numero por grupos de mil, do maior para o menor."""
    groups: list[int] = []
    remaining = value
    while remaining > 0:
        remaining, group = divmod(remaining, 1000)
        groups.append(group)

    parts: list[str] = []
    for index in range(len(groups) - 1, -1, -1):
        group = groups[index]
        if group == 0:
            continue
        parts.append(nameGroup(group, index, feminine))

    return join(parts, groups)


def nameGroup(group: int, index: int, feminine: bool) -> str:
    """Nomeia um grupo de tres digitos com a sua ordem de grandeza."""
    if index == 0:
        return spell(group, feminine=feminine)

    singular, plural = SCALES[min(index, len(SCALES) - 1)]
    if index == 1:
        # "mil" nao leva "um" na frente: 1000 e "mil", nao "um mil".
        prefix = "" if group == 1 else spell(group, feminine=feminine)
        return f"{prefix} {singular}".strip()

    # Milhao e acima contam coisas masculinas: "duas milhoes" nao existe.
    scale = singular if group == 1 else plural
    return f"{spell(group)} {scale}"


def join(parts: list[str], groups: list[int]) -> str:
    """Junta os grupos com o "e" nos lugares em que o portugues o exige.

    A regra que quase todo mundo erra: o ultimo grupo entra com "e" quando ele e
    pequeno (menor que cem) ou redondo (multiplo de cem) — "mil e vinte", "mil e
    duzentos" — e sem "e" quando nao e nem um nem outro: "mil duzentos e trinta".
    """
    if len(parts) == 1:
        return parts[0]

    last = groups[0]
    if last == 0:
        return " ".join(parts)

    joiner = " e " if (last < 100 or last % 100 == 0) else " "
    return joiner.join([" ".join(parts[:-1]), parts[-1]])
