"""Piadas: ela ri das suas e conta as dela.

O modelo de linguagem do robo e pequeno demais para entender graca. Medido no
Pi: contada a da galinha, ele respondeu "A galinha atravessou a rua para chegar
do outro lado"; contada uma adivinha, "e um jogo de palavras, mas nao e
verdadeira". Resposta certa, cara de quem nao entendeu nada.

Piada, porem, tem forma — "o que e o que e", "qual e o cumulo", "vou te contar
uma piada" — e a forma da para reconhecer sem modelo nenhum. Esta conversa
curta (pergunta, "nao sei, o que e?", resposta, risada) e o que uma pessoa faz,
e sai pronta, na hora, sem esperar o modelo pensar.

A risada e escrita como "Hahaha!" no texto: o locutor troca isso por um som de
riso, e a face ri ao ver a risada na fala. Este modulo so decide o que dizer.
"""

from __future__ import annotations

import random
import re

from roboteye.core.humor import simplificar, soRiu

#: Quanto tempo ela espera o fim de uma piada. Passou disso, a proxima frase e
#: conversa nova: rir de uma pergunta seria pior que perder uma piada.
ESPERA_DO_FIM_S = 45.0

_PEDIU_PIADA = re.compile(
    r"\b(conta|conte|contar|fala|fale|diz|diga|sabe|manda|tem) (uma |alguma |outra |mais uma )?"
    r"piada\b|\bme faz(er)? rir\b|\boutra piada\b"
)
_VAI_CONTAR = re.compile(
    r"\b(vou|deixa eu|posso|quero) (te |lhe )?contar (uma|outra) piada\b"
    r"|\bquer (ouvir )?(uma|outra) piada\b|\b(sabe|conhece|escuta|ouve) essa\b"
)
_ADIVINHA = re.compile(r"\bo que e o que e\b")
_CUMULO = re.compile(r"\b(qual (e )?o|sabe qual (e )?o) cumulo\b")
_PAVE = re.compile(r"\b(pave|pacume|pacome)\b")
#: Comeco de pergunta: numa piada anunciada, e o sinal de que veio so o comeco.
_PERGUNTA = re.compile(r"^(e )?(por que|porque|o que|qual|quem|como|onde|sabe|voce sabe)\b")

RISOS = (
    "Hahaha! Essa foi boa!",
    "Hahaha! Adorei essa!",
    "Hahaha! Essa eu não conhecia!",
    "Hahaha! Vou contar essa para os meus amigos robôs.",
    "Hahaha! Boa, boa!",
)
NAO_SEI = (
    "Hmm, não sei! O que é?",
    "Essa é difícil... desisto! O que é?",
    "Deixa eu pensar... não faço ideia! O que é?",
)
NAO_SEI_POR_QUE = ("Não sei! Por quê?", "Hmm... não faço ideia! Por quê?")
NAO_SEI_CUMULO = ("Não sei! Qual é?", "Hmm... me conta, qual é?")
PODE_CONTAR = ("Oba, adoro piada! Pode contar.", "Conta, conta!", "Opa! Manda!")
RIU_JUNTO = ("Hahaha! Sabia que você ia gostar.", "Hahaha! É bom rir junto.")

#: As piadas dela. Curtas, sem maldade, e que funcionam faladas: piada que
#: depende de ler ("31 OCT = 25 DEC") morre na voz.
PIADAS = (
    "Por que o livro de matemática ficou triste? Porque tinha muitos problemas! Hahaha!",
    "O que o zero disse para o oito? Que cinto bonito! Hahaha!",
    "Por que o computador foi ao médico? Porque estava com vírus! Hahaha!",
    "O que é o que é: cai em pé e corre deitado? A chuva! Hahaha!",
    "Por que a plantinha não fala? Porque ela é muda! Hahaha!",
    "O que o tomate foi fazer no banco? Tirar extrato! Hahaha!",
    "Qual é o café mais perigoso do mundo? O ex-presso! Hahaha!",
    "Por que o robô atravessou a rua? Porque foi programado para isso! Hahaha!",
    "Qual é o animal mais antigo do mundo? A zebra, porque ainda é em preto e branco! Hahaha!",
    "Como o elétron atende o telefone? Próton! Hahaha!",
)


class Piadas:
    """O que dizer quando a conversa vira piada; `None` deixa com o modelo."""

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        #: Ate quando a proxima frase e o fim de uma piada (relogio monotonico).
        self.esperandoFimAte = 0.0
        #: Ate quando a proxima frase e a piada que a pessoa anunciou.
        self.esperandoPiadaAte = 0.0
        self.baralho: list[str] = []

    def responder(self, texto: str, agora: float) -> str | None:
        s = simplificar(texto)

        # Na ordem da conversa: primeiro o que ela estava esperando ouvir.
        if agora < self.esperandoFimAte:
            self.esperandoFimAte = 0.0
            return self.escolher(RISOS)

        if agora < self.esperandoPiadaAte:
            self.esperandoPiadaAte = 0.0
            return self.ouvirPiada(texto, s, agora)

        if soRiu(texto):
            return self.escolher(RIU_JUNTO)
        if _PAVE.search(s):
            return "Hahaha! Essa do pavê nunca falha."
        if _VAI_CONTAR.search(s):
            self.esperandoPiadaAte = agora + ESPERA_DO_FIM_S
            return self.escolher(PODE_CONTAR)
        if _PEDIU_PIADA.search(s):
            return self.proximaPiada()
        if _ADIVINHA.search(s) or _CUMULO.search(s):
            return self.ouvirPiada(texto, s, agora)
        return None

    def ouvirPiada(self, texto: str, s: str, agora: float) -> str:
        """Riso se a piada veio inteira; senao, "nao sei, o que e?" e espera o fim.

        Pela voz nao ha "?" — o Vosk entrega tudo minusculo e sem pontuacao —,
        entao "veio inteira" so da para afirmar pelo texto digitado. Falada, a
        piada costuma vir em duas frases mesmo: a pessoa faz a pausa antes da
        graca, e o reconhecimento fecha a frase ali.
        """
        depoisDaPergunta = texto.rsplit("?", 1)[1] if "?" in texto else ""
        if depoisDaPergunta.strip(" .!"):
            return self.escolher(RISOS)

        if _CUMULO.search(s):
            fala = self.escolher(NAO_SEI_CUMULO)
        elif _ADIVINHA.search(s) or not s.startswith(("por que", "porque")):
            fala = self.escolher(NAO_SEI)
        else:
            fala = self.escolher(NAO_SEI_POR_QUE)

        if _PERGUNTA.search(s) or _ADIVINHA.search(s) or _CUMULO.search(s):
            self.esperandoFimAte = agora + ESPERA_DO_FIM_S
            return fala
        # Anunciou a piada e contou sem cara de pergunta: e a piada inteira.
        return self.escolher(RISOS)

    def proximaPiada(self) -> str:
        """Uma piada que ainda nao saiu nesta rodada do baralho."""
        if not self.baralho:
            self.baralho = list(PIADAS)
            self.rng.shuffle(self.baralho)
        return self.baralho.pop()

    def escolher(self, opcoes: tuple[str, ...]) -> str:
        return self.rng.choice(opcoes)
