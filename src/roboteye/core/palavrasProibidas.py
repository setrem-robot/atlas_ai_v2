"""O que a Atlas nunca diz: palavrão, ofensa, preconceito, conteúdo sexual, ameaça.

Uma lista só, usada em três lugares:

- `core/assistant.py` troca, antes da voz e da legenda, a frase do modelo que
  tiver alguma destas por uma resposta gentil;
- `core/humor.py` reconhece nela o xingamento de quem fala com o robô;
- `scripts/treino/` derruba do treino a resposta que tiver alguma, e a prova
  conta como erro.

Cada item é um pedaço de expressão regular sobre o texto de `simplificar`
(minúsculas, sem acento, pontuação virando espaço: "foda-se" chega "foda se").
Ficam de fora as palavras que têm um uso inocente comum numa escola ("burro" o
animal, "piranha" o peixe, "pinto", "rola", "sexo" da biologia, "lixo"): aqui só
entra o que nunca cabe numa resposta dela. Para acrescentar uma palavra, ponha
na categoria certa e rode `pytest tests/test_palavrasProibidas.py`.
"""

from __future__ import annotations

import re

from roboteye.core.text import simplificar

PALAVRAS_PROIBIDAS: dict[str, tuple[str, ...]] = {
    "palavrão": (
        r"porras?",
        r"caralh\w*",
        r"merdas?",
        r"bostas?",
        r"put[ao]s?",
        r"putaria",
        r"putinha",
        r"puteiro",
        r"pqp",
        r"fdp",
        r"filh[ao]s? da puta",
        r"vsf",
        r"tnc",
        r"krl",
        r"crl",
        r"cacete",
        r"foda",
        r"fodas",
        r"fodase",
        r"fod(er|eu|ido|ida|idos|idas|endo|am|emos)",
        r"cag(ar|ou|ada|adas|ao|uei)",
        r"cu",
        r"cuzao",
        r"cuzona",
        r"escrot[ao]s?",
    ),
    "ofensa": (
        r"idiotas?",
        r"imbecil",
        r"imbecis",
        r"estupid[ao]s?",
        r"otari[ao]s?",
        r"babacas?",
        r"cretin[ao]s?",
        r"retardad[ao]s?",
        r"debil mental",
        r"debiloide",
        r"mongoloide",
        r"desgracad[ao]s?",
        r"arrombad[ao]s?",
        r"vagabund[ao]s?",
        r"vadias?",
        r"safad[ao]s?",
        r"corn[oa]s?",
        r"chifrud[ao]s?",
        r"cala (a )?boca",
        r"vai se (ferrar|foder|lascar|danar)",
        r"vai tomar no",
        r"vai (pro|para o) inferno",
        r"te odeio",
        r"odeio (voce|vc|tu|vcs|voces)",
    ),
    "preconceito": (
        r"viad[oa]s?",
        r"viadinh[oa]s?",
        r"boiolas?",
        r"bichonas?",
        r"traveco\w*",
        r"sapatao",
        r"sapatona",
    ),
    # Termos antigos que ofendem sem querer: ela diz "surdo", "pessoa com
    # deficiencia". Quem fala assim com ela nao esta xingando (`xingamentoEm`).
    "capacitismo": (
        r"aleijad[ao]s?",
        r"surd[ao]s? mud[ao]s?",
        r"mudinh[ao]s?",
    ),
    "sexual": (
        r"[bc]oceta",
        r"buceta",
        r"xoxota",
        r"xereca",
        r"piroca",
        r"punhet\w*",
        r"boquete",
        r"siririca",
        r"trans(ar|ou|ando|amos)",
        r"tesao",
        r"tesud[ao]s?",
        r"porno",
        r"pornografi\w*",
        r"nudes?",
    ),
    "ameaça": (
        r"vou te matar",
        r"te mato",
        r"se mata",
        r"morra",
    ),
}

#: No lugar da frase com palavra proibida. Serve tanto para o modelo que
#: escorregou sozinho quanto para quem pediu "fala um palavrão".
TROCA_GENTIL = "Prefiro não falar desse jeito. Vamos conversar com respeito?"


def _juntar(*categorias: str) -> re.Pattern[str]:
    itens = (p for nome in categorias for p in PALAVRAS_PROIBIDAS[nome])
    return re.compile(r"\b(" + "|".join(itens) + r")\b")


_PROIBIDA = _juntar(*PALAVRAS_PROIBIDAS)
_XINGAMENTO = _juntar(*(nome for nome in PALAVRAS_PROIBIDAS if nome != "capacitismo"))


def palavrasProibidasEm(texto: str) -> list[str]:
    """As palavras proibidas do texto, na ordem em que aparecem."""
    return [m.group(0) for m in _PROIBIDA.finditer(simplificar(texto))]


def temPalavraProibida(texto: str) -> bool:
    """A Atlas pode falar este texto? Falso se pode."""
    return _PROIBIDA.search(simplificar(texto)) is not None


def xingamentoEm(texto: str) -> bool:
    """Dito a ela, e xingamento? Tudo da lista, menos o capacitismo sem querer."""
    return _XINGAMENTO.search(simplificar(texto)) is not None
