"""Decide se o que foi ouvido era para o robo.

Um microfone aberto numa sala escuta a sala inteira. Sem filtro, a Atlas
responderia a conversa alheia, ao professor explicando outra coisa e a propria
apresentacao sobre ela — falando por cima de todos.

O filtro e o nome dela. "Atlas, quantos alunos tem o curso?" e uma pergunta; a
mesma frase sem o nome e alguem conversando perto do robo.

**Mas ninguem fala assim.** O natural — e o que uma crianca faz — e chamar,
esperar o robo olhar, e so entao perguntar: "Atlas!" ... "quanto e dois mais
dois?". Exigir o nome em toda frase transformava a segunda metade dessa conversa
em silencio, e quem estava falando concluia que o robo tinha quebrado.

Por isso o nome abre uma **janela**: depois de ser chamada, a Atlas aceita a
proxima frase sem exigir o nome de novo. A janela fecha sozinha em alguns
segundos, para o robo nao passar a responder a sala inteira depois de ter sido
chamado uma vez.

E texto puro, sem audio e sem modelo, para poder ser testado como qualquer outra
funcao — o que importa aqui e a regra, nao o reconhecimento.
"""

from __future__ import annotations

import re
import time
import unicodedata

#: Palavras que costumam vir grudadas no nome e nao fazem parte da pergunta.
_RESTOS = ("me diga", "diga", "responda", "por favor", "pergunta")

#: Quanto tempo o robo continua ouvindo depois de ser chamado. Oito segundos
#: cobrem "Atlas!" seguido de alguem pensando na pergunta; muito mais que isso e
#: o robo respondendo a conversa que veio depois.
JANELA_S = 8.0


class Conversa:
    """Lembra que a Atlas foi chamada ha pouco.

    Guardar isto num objeto, e nao numa variavel global, e o que permite testar a
    janela sem esperar em tempo real: quem chama informa o instante.
    """

    def __init__(self, janela_s: float = JANELA_S) -> None:
        self._janela = janela_s
        self._ate = 0.0

    def aberta(self, agora: float | None = None) -> bool:
        return (agora if agora is not None else time.monotonic()) < self._ate

    def abrir(self, agora: float | None = None) -> None:
        self._ate = (agora if agora is not None else time.monotonic()) + self._janela

    def fechar(self) -> None:
        self._ate = 0.0


def dirigido_ao_robo(
    texto: str,
    palavra: str,
    *,
    conversa: Conversa | None = None,
    agora: float | None = None,
) -> str | None:
    """Devolve a pergunta, ja sem o nome do robo, ou None se nao era com ele.

    Com `palavra` vazia tudo passa: e o modo de quem esta testando, ou de um
    robo numa sala silenciosa.

    Com `conversa`, o nome abre uma janela: a frase seguinte e aceita sem ele.
    """
    limpo = texto.strip()
    if not limpo:
        return None
    if not palavra.strip():
        return limpo

    alvo = _simplificar(palavra)
    palavras = _simplificar(limpo).split()

    if alvo not in palavras:
        # Sem o nome, so passa quem chegou dentro da janela — e responder fecha
        # a janela, para a conversa ao lado nao emendar na proxima frase.
        if conversa is not None and conversa.aberta(agora):
            conversa.fechar()
            return limpo
        return None

    if conversa is not None:
        conversa.abrir(agora)

    # Tudo que veio depois do nome e a pergunta. Antes dele costuma ser o final
    # de outra frase ("...entao a gente pergunta, Atlas, quantos alunos tem?").
    corte = palavras.index(alvo) + 1
    pergunta = " ".join(limpo.split()[corte:]).strip(" ,.?!")
    for resto in _RESTOS:
        if pergunta.lower().startswith(resto):
            pergunta = pergunta[len(resto) :].strip(" ,.?!")

    # So o nome, sem mais nada, e alguem chamando. Com a janela aberta, o certo e
    # ficar esperando a pergunta — responder "atlas" faria ela falar por cima de
    # quem ainda ia perguntar.
    if not pergunta:
        return None if conversa is not None else limpo
    return pergunta


def _simplificar(texto: str) -> str:
    """Sem acento, sem pontuacao e em minusculas — o Vosk erra os tres."""
    sem_acento = "".join(
        letra
        for letra in unicodedata.normalize("NFD", texto.lower())
        if unicodedata.category(letra) != "Mn"
    )
    return re.sub(r"[^\w\s]", " ", sem_acento)
