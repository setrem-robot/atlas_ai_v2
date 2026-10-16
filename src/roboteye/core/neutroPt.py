"""Reescreve em linguagem neutra o que o robo diz de si mesmo.

A Atlas fala de si sem marcar genero, pela propria norma do portugues: sem
artigo antes do nome, com adjetivos que nao flexionam ("contente", "sem
energia") e locucoes no lugar de participios ("estou a disposicao" em vez de
"estou pronta"). A persona pede isso, mas pedir nao basta num modelo pequeno.
Medido com o `gemma3:1b` do robo, um terco das respostas a perguntas com
genero ("voce esta pronta?", "esta cansada?") vinha no feminino ou no
masculino: o modelo espelha a pergunta, por mais exemplos que a persona traga.

Por isso a ultima palavra fica aqui, depois do modelo e antes da tela e da
voz, numa troca deterministica e testada.

**So a primeira pessoa.** Cada regra exige um verbo do proprio robo na frente
("estou", "fiquei", "fui"). "A SETREM foi criada em 1950" ou "ela esta pronta"
falam de outra coisa e passam intactas — trocar ali seria estragar uma frase
certa, que e pior do que deixar escapar uma marca de genero de vez em quando.
"""

from __future__ import annotations

import re

#: Raiz do adjetivo (sem a vogal de genero) -> forma neutra.
#:
#: O segundo valor, quando existe, e o que entra se vier um intensificador
#: ("muito curiosa"): "muito com curiosidade" nao e portugues, "com muita
#: curiosidade" e. Nas outras o adverbio continua onde estava ("um pouco sem
#: energia").
ADJETIVOS: dict[str, tuple[str, str | None]] = {
    "pront": ("à disposição", None),
    "preparad": ("à disposição", None),
    "cansad": ("sem energia", None),
    "exaust": ("sem energia", None),
    "pesad": ("sem energia", None),
    "ótim": ("muito bem", None),
    "maravilhos": ("muito bem", None),
    "animad": ("contente", None),
    "empolgad": ("contente", None),
    "satisfeit": ("contente", None),
    "encantad": ("contente", None),
    "tranquil": ("com calma", "com muita calma"),
    "curios": ("com curiosidade", "com muita curiosidade"),
    "grat": ("com gratidão", "com muita gratidão"),
    "emocionad": ("com emoção", "com muita emoção"),
    "orgulhos": ("com orgulho", "com muito orgulho"),
    "nervos": ("com nervosismo", "com muito nervosismo"),
    "atent": ("com atenção", "com muita atenção"),
    "preocupad": ("com preocupação", "com muita preocupação"),
    "confus": ("em dúvida", None),
    "perdid": ("em dúvida", None),
    "sozinh": ("sem companhia", None),
    "ligad": ("em funcionamento", None),
    "acordad": ("em funcionamento", None),
    "terminad": ("em versão final", None),
    "acabad": ("em versão final", None),
    "finalizad": ("em versão final", None),
}

#: Verbos de estado na primeira pessoa. "Sou" fica de fora de proposito: "sou
#: com curiosidade" nao existe, e "sou pronta" ninguem diz.
_ESTADO = r"estou|tô|fico|fiquei|ficarei|estava|estaria|continuo|sigo|me sinto|me senti"
_INTENSOS = {"muito", "muita", "super", "tão", "bem", "bastante"}
#: O que pode ficar entre o verbo e o adjetivo. "aqui," cobre o "estou aqui,
#: pronto para ajudar", que o modelo do robo diz com frequencia.
_MODIFICADOR = (
    r"muito|muita|super|tão|bem|bastante|um pouco|um pouquinho|meio|ainda|já|quase|"
    r"sempre|por aqui,?|aqui,?"
)

_PARTICIPIOS = r"constru[íi]d|criad|feit|desenvolvid|programad|montad|projetad|treinad"
_PREPOSICOES = {"por": "de", "pelo": "do", "pela": "da", "pelos": "dos", "pelas": "das"}


def neutralize(text: str) -> str:
    """Aplica todas as trocas, da mais especifica para a mais geral."""
    for regra in _REGRAS:
        text = regra(text)
    return text


# ---------------------------------------------------------------------------
# Regras, na ordem em que rodam
# ---------------------------------------------------------------------------
def autoria(text: str) -> str:
    """`fui construida por alunos` -> "sou obra de alunos"."""

    def trocar(match: re.Match[str]) -> str:
        neutro = f"sou obra {_PREPOSICOES[match.group('prep').lower()]}"
        return comMaiuscula(neutro, match.group(0))

    return _AUTORIA.sub(trocar, text)


def finalidade(text: str) -> str:
    """`fui criada para conversar` -> "existo para conversar"."""
    return _FINALIDADE.sub(lambda m: comMaiuscula("existo para", m.group(0)), text)


def origem(text: str) -> str:
    """`fui criada na SETREM` -> "nasci na SETREM"."""
    return _ORIGEM.sub(lambda m: comMaiuscula("nasci", m.group(0)), text)


def emAndamento(text: str) -> str:
    """`estou sendo construida` -> "estou em desenvolvimento"."""
    return _ANDAMENTO.sub(r"\g<verbo> em desenvolvimento", text)


def estados(text: str) -> str:
    """`estou pronta` -> "estou a disposicao"; `muito curiosa` -> "com muita curiosidade"."""

    def trocar(match: re.Match[str]) -> str:
        neutro, intenso = ADJETIVOS[match.group("raiz").lower()]
        modificadores = match.group("mods").split()
        if intenso is not None and _INTENSOS.intersection(m.lower() for m in modificadores):
            restantes = " ".join(m for m in modificadores if m.lower() not in _INTENSOS)
            return " ".join(p for p in (match.group("verbo"), restantes, intenso) if p)
        return f"{match.group('verbo')} {match.group('mods')}{neutro}"

    return _ESTADOS.sub(trocar, text)


def prontoSolto(text: str) -> str:
    """`Pronto pra ajudar!` -> "A disposicao pra ajudar!".

    O modelo do robo diz isso sem verbo nenhum, no comeco da frase ou depois
    de "aqui". So nesses lugares: "o almoco esta pronto para servir" tem
    sujeito, e o sujeito nao e o robo.
    """
    return _PRONTO_SOLTO.sub(lambda m: comMaiuscula("à disposição", m.group(0)), text)


def nome(text: str) -> str:
    """`Eu sou a Atlas` -> "Eu sou Atlas"."""
    return _NOME.sub(r"\g<verbo> Atlas", text)


def robo(text: str) -> str:
    """`sou uma robo` -> "sou robo" — sem artigo, como em "sou estudante"."""
    return _ROBO.sub(r"\g<verbo> robô", text)


def agradecimento(text: str) -> str:
    """`Muito obrigada!` -> "Agradeco muito!"; `obrigado por` -> "agradeco por".

    Nao mexe quando "obrigado" e participio ("nao sou obrigada a"): ali a
    palavra significa outra coisa, e trocar daria uma frase sem sentido.
    """

    def trocar(match: re.Match[str]) -> str:
        if _PARTICIPIO_ANTES.search(text, 0, match.start()):
            return match.group(0)
        partes = ["agradeço"]
        if match.group("muito"):
            partes.append("muito")
        if match.group("prep"):
            partes.append(match.group("prep"))
        return comMaiuscula(" ".join(partes), match.group(0))

    return _AGRADECIMENTO.sub(trocar, text)


def boasVindas(text: str) -> str:
    """`Seja bem-vindo!` -> "Boas-vindas!" — o robo nao chuta o genero de ninguem."""

    def trocar(match: re.Match[str]) -> str:
        return comMaiuscula("boas-vindas", match.group(0))

    return _BOAS_VINDAS.sub(trocar, text)


# ---------------------------------------------------------------------------
# Apoio
# ---------------------------------------------------------------------------
def comMaiuscula(neutro: str, original: str) -> str:
    """Repete a maiuscula inicial do trecho trocado (inicio de frase)."""
    return neutro[:1].upper() + neutro[1:] if original[:1].isupper() else neutro


def alternativas(palavras: object) -> str:
    """Alternativa de regex com as opcoes maiores na frente (ver `normalizePt`)."""
    return "|".join(sorted(palavras, key=len, reverse=True))  # type: ignore[call-overload]


_I = re.IGNORECASE
_AUTORIA = re.compile(
    rf"\b(?:fui|sou)\s+(?:{_PARTICIPIOS})[ao]\s+(?P<prep>pelos|pelas|pelo|pela|por)\b", _I
)
_FINALIDADE = re.compile(rf"\b(?:fui|sou)\s+(?:{_PARTICIPIOS})[ao]\s+para\b", _I)
_ORIGEM = re.compile(rf"\bfui\s+(?:{_PARTICIPIOS})[ao]\b", _I)
_ANDAMENTO = re.compile(rf"\b(?P<verbo>estou|tô|continuo)\s+sendo\s+(?:{_PARTICIPIOS})[ao]\b", _I)
_ESTADOS = re.compile(
    rf"\b(?P<verbo>{_ESTADO})\s+(?P<mods>(?:(?:{_MODIFICADOR})\s+)*)"
    rf"(?P<raiz>{alternativas(ADJETIVOS)})[ao]s?\b",
    _I,
)
_PRONTO_SOLTO = re.compile(
    r"(?:^|(?<=[,.!?;] )|(?<=aqui )|(?<=aqui, ))pront[ao]s?(?=\s+(?:pra|para)\b)", _I
)
_NOME = re.compile(r"\b(?P<verbo>sou|me chamo|chamo-me)\s+[ao]\s+Atlas\b", _I)
_ROBO = re.compile(r"\b(?P<verbo>sou)\s+(?:um|uma)\s+robô\b", _I)
_AGRADECIMENTO = re.compile(
    r"\b(?P<muito>muit[ao]\s+)?obrigad[ao]s?\b(?:\s+(?P<prep>pelos|pelas|pelo|pela|por)\b)?", _I
)
# A palavra imediatamente antes de "obrigado" decide se ele e participio.
_PARTICIPIO_ANTES = re.compile(r"\b(?:sou|é|são|foi|fui|ser|estou|está|ficou|fiquei)\s+$", _I)
_BOAS_VINDAS = re.compile(r"\b(?:sejam?\s+)?bem-vind[ao]s?\b", _I)

#: A ordem e a propria regra: autoria antes de origem, senao "fui criada por
#: alunos" viraria "nasci por alunos".
_REGRAS = (
    autoria,
    finalidade,
    origem,
    emAndamento,
    estados,
    prontoSolto,
    nome,
    robo,
    agradecimento,
    boasVindas,
)
