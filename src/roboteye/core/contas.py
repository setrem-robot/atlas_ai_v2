"""Contas: ela calcula de verdade em vez de chutar.

O modelo do robo e pequeno demais para aritmetica. Medido no Pi: "qual a raiz
quadrada de dezesseis" deu "oito"; com mais penalidade de repeticao, "doze
vezes tres" virou "quinhentos". Conta, porem, tem forma — "quanto e doze vezes
tres", "raiz quadrada de dezesseis" — e a forma da para reconhecer sem modelo.

A transcricao do Vosk chega por extenso ("doze vezes tres"), entao os numeros
sao lidos de palavras. A resposta sai com digitos: o locutor ja os escreve por
extenso antes da voz (`core/normalizePt.py`), e a legenda mostra o numero.
So responde quando a frase inteira e uma conta; qualquer coisa a mais ("quanto
e dois mais dois em binario") fica com o modelo.
"""

from __future__ import annotations

import math
import random
import re

from roboteye.core.humor import simplificar

_UNIDADES = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "quatrocentos": 400,
    "quinhentos": 500,
    "seiscentos": 600,
    "setecentos": 700,
    "oitocentos": 800,
    "novecentos": 900,
}

_PEDIDO = (
    r"^(?:atlas )?(?:me )?(?:(?:diz|fala|calcula|sabe)(?: pra mim)? )?"
    r"(?:quanto (?:que )?(?:e|da|seria|fica)|qual(?: e)?(?: o resultado de)?|calcula)?\s*"
)
_OPERACAO = {
    "mais": "+",
    "menos": "-",
    "vezes": "*",
    "x": "*",
    "multiplicado por": "*",
    "dividido por": "/",
    "divido por": "/",
    "sobre": "/",
}
_BINARIA = re.compile(
    _PEDIDO + r"(?P<a>[\w ]+?) (?P<op>mais|menos|vezes|x|multiplicado por|dividido por|divido por"
    r"|sobre) (?P<b>[\w ]+)$"
)
_RAIZ = re.compile(_PEDIDO + r"(?:a )?raiz quadrada de (?P<a>[\w ]+)$")
_POTENCIA = re.compile(_PEDIDO + r"(?P<a>[\w ]+?) ao (?P<exp>quadrado|cubo)$")


def numero(texto: str) -> int | None:
    """Le um numero escrito por extenso ou com digitos; None se nao for so numero."""
    palavras = texto.split()
    if len(palavras) == 1 and palavras[0].isdigit():
        return int(palavras[0])
    total = atual = 0
    achou = False
    for palavra in palavras:
        if palavra in _UNIDADES:
            atual += _UNIDADES[palavra]
            achou = True
        elif palavra == "mil":
            total += (atual or 1) * 1000
            atual = 0
            achou = True
        elif palavra != "e":
            return None
    return total + atual if achou else None


def _falado(valor: float) -> str:
    """Numero com digitos e virgula decimal, como o locutor sabe ler."""
    if valor == int(valor):
        return str(int(valor))
    return f"{valor:.2f}".rstrip("0").replace(".", ",")


def responder(pergunta: str) -> str | None:
    """Resposta pronta se a pergunta for uma conta; None deixa para o modelo."""
    s = simplificar(pergunta)
    if m := _BINARIA.match(s):
        a, b = numero(m["a"]), numero(m["b"])
        if a is None or b is None:
            return None
        op = _OPERACAO[m["op"]]
        if op == "/" and b == 0:
            return "Dividir por zero não dá: nenhum número vezes zero chega lá."
        valor = {"+": a + b, "-": a - b, "*": a * b, "/": a / b if b else 0}[op]
        conta = f"{a} {m['op']} {b}"
    elif m := _RAIZ.match(s):
        a = numero(m["a"])
        if a is None:
            return None
        valor = math.sqrt(a)
        conta = f"A raiz quadrada de {a}"
        if valor != int(valor):
            return f"{conta} é mais ou menos {_falado(valor)}."
    elif m := _POTENCIA.match(s):
        a = numero(m["a"])
        if a is None:
            return None
        valor = a ** (2 if m["exp"] == "quadrado" else 3)
        conta = f"{a} ao {m['exp']}"
    else:
        return None
    resultado = _falado(valor)
    if valor < 0:
        resultado = f"menos {_falado(-valor)}"
    if valor != int(valor):
        resultado = f"mais ou menos {resultado}"
    conta = conta[0].upper() + conta[1:]
    return random.choice(
        (f"{conta} dá {resultado}.", f"{conta} é {resultado}.", f"Dá {resultado}.")
    )
