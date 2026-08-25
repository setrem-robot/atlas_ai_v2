"""Decide se o que foi ouvido era para o robo.

Um microfone aberto numa sala escuta a sala inteira. Sem filtro, a Atlas
responderia a conversa alheia, ao professor explicando outra coisa e a propria
apresentacao sobre ela — falando por cima de todos.

O filtro e o nome dela. "Atlas, quantos alunos tem o curso?" e uma pergunta; a
mesma frase sem o nome e alguem conversando perto do robo.

E texto puro, sem audio e sem modelo, para poder ser testado como qualquer outra
funcao — o que importa aqui e a regra, nao o reconhecimento.
"""

from __future__ import annotations

import re
import unicodedata

#: Palavras que costumam vir grudadas no nome e nao fazem parte da pergunta.
_RESTOS = ("me diga", "diga", "responda", "por favor", "pergunta")


def dirigido_ao_robo(texto: str, palavra: str) -> str | None:
    """Devolve a pergunta, ja sem o nome do robo, ou None se nao era com ele.

    Com `palavra` vazia tudo passa: e o modo de quem esta testando, ou de um
    robo numa sala silenciosa.
    """
    limpo = texto.strip()
    if not limpo:
        return None
    if not palavra.strip():
        return limpo

    alvo = _simplificar(palavra)
    palavras = _simplificar(limpo).split()
    if alvo not in palavras:
        return None

    # Tudo que veio depois do nome e a pergunta. Antes dele costuma ser o final
    # de outra frase ("...entao a gente pergunta, Atlas, quantos alunos tem?").
    corte = palavras.index(alvo) + 1
    pergunta = " ".join(limpo.split()[corte:]).strip(" ,.?!")
    for resto in _RESTOS:
        if pergunta.lower().startswith(resto):
            pergunta = pergunta[len(resto) :].strip(" ,.?!")

    # So o nome, sem mais nada, e alguem chamando: vale como pergunta para o
    # robo responder qualquer coisa, em vez de ignorar quem o chamou.
    return pergunta or limpo


def _simplificar(texto: str) -> str:
    """Sem acento, sem pontuacao e em minusculas — o Vosk erra os tres."""
    sem_acento = "".join(
        letra
        for letra in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(letra) != "Mn"
    )
    return re.sub(r"[^\w\s]", " ", sem_acento)
