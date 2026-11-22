#!/usr/bin/env python3
"""Limpa legendas (OpenSubtitles pt-BR, do OPUS) para o modelo de linguagem.

Legenda é o texto aberto mais parecido com conversa falada que existe: frases
curtas, perguntas, "a gente", "você viu". O LM do FalaBrasil veio da web
(OSCAR), que escreve; isto puxa para o jeito como se fala.

Mantém só a linha que o Vosk poderia ter dito: minúsculas, sem dígitos (o Vosk
escreve números por extenso), de 2 a 20 palavras, todas no léxico.

Uso:  zcat legendas.txt.gz | python legendas.py words.txt > legendas-limpas.txt
"""

from __future__ import annotations

import re
import sys

PONTUACAO = re.compile(r"[^\w\s-]|(?<!\w)-|-(?!\w)")


def limpar(linha: str, vocab: set[str]) -> str | None:
    if any(c.isdigit() for c in linha):
        return None
    palavras = PONTUACAO.sub(" ", linha.lower()).split()
    if not 2 <= len(palavras) <= 20 or not all(p in vocab for p in palavras):
        return None
    return " ".join(palavras)


def main() -> None:
    with open(sys.argv[1], encoding="utf-8") as f:
        vocab = {l.split()[0] for l in f} - {"<eps>", "!SIL", "<UNK>", "#0", "<s>", "</s>"}
    anterior = None
    for linha in sys.stdin:
        limpa = limpar(linha, vocab)
        # Legenda repete a mesma linha em quadros seguidos; contar duas vezes
        # ensinaria uma frequência que ninguém falou.
        if limpa and limpa != anterior:
            print(limpa)
        anterior = limpa


assert limpar("- Oi, tudo bem?", {"oi", "tudo", "bem"}) == "oi tudo bem"
assert limpar("Tenho 3 gatos.", {"tenho", "gatos"}) is None

if __name__ == "__main__":
    main()
