#!/usr/bin/env python3
"""Junta perguntas reais em português de datasets abertos para o professor.

O professor inventa as perguntas dos temas que recebe, e o modelo aprende a
responder aqueles jeitos de perguntar. Gente de verdade pergunta de mil outros:
estas fontes trazem o pedido dito por pessoas, que `professor.py web` responde
no jeito da Atlas e o julgamento filtra.

- CohereLabs/aya_dataset: perguntas escritas por falantes nativos (Apache-2.0)
- OpenAssistant/oasst2: mensagens de usuários pt-BR (Apache-2.0)
- openai/MMMLU, PT-BR: computação, elétrica, física e matemática de graduação,
  com tradução humana (MIT); só as que fazem sentido sem as alternativas

Fica só o que cabe numa pergunta falada: de 3 a 25 palavras, sem código, link
ou lista. Os arquivos baixados ficam em DOWNLOADS (fora do repositório).

Uso (no WSL, o Python do treino tem pyarrow):
    ~/atlas-treino/bin/python scripts/treino/baixar-perguntas.py [quantas]   # padrão 6000
"""

from __future__ import annotations

import csv
import random
import re
import sys
import urllib.request
from pathlib import Path

import pyarrow.parquet as pq

DOWNLOADS = Path.home() / "fontes-web"
SAIDA = Path(__file__).resolve().parent / "fontes" / "perguntas-web.txt"
HF = "https://huggingface.co/datasets"
URLS = {
    "aya.parquet": f"{HF}/CohereLabs/aya_dataset/resolve/main/data/train-00000-of-00001.parquet",
    "oasst2.parquet": f"{HF}/OpenAssistant/oasst2/resolve/main/data/train-00000-of-00001-88ba0162028a73fc.parquet",
    "mmmlu-pt.csv": f"{HF}/openai/MMMLU/resolve/main/test/mmlu_PT-BR.csv",
}
#: Matérias do MMMLU que um aluno de Engenharia de Computação perguntaria.
MATERIAS = {
    "college_computer_science", "high_school_computer_science", "computer_security",
    "electrical_engineering", "college_physics", "high_school_physics", "conceptual_physics",
    "college_mathematics", "high_school_mathematics", "elementary_mathematics",
    "machine_learning", "astronomy",
}
#: Pergunta que só existe com as alternativas ao lado.
DEPENDE_DAS_OPCOES = re.compile(r"seguintes|abaixo|acima|alternativ|afirma[cç][aã]o|op[cç][aã]o|___", re.I)
CODIGO = re.compile(r"[{}<>=;`#|\\]|https?:|www\.|\.(py|js|com)\b|\d{4,}")


def baixar(nome: str) -> Path:
    destino = DOWNLOADS / nome
    if not destino.exists():
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        print(f"baixando {nome}...", file=sys.stderr)
        urllib.request.urlretrieve(URLS[nome], destino.with_suffix(".parcial"))
        destino.with_suffix(".parcial").rename(destino)
    return destino


def falavel(texto: str) -> str | None:
    """A pergunta numa linha, se ela cabe numa conversa falada."""
    texto = " ".join(str(texto).split())
    palavras = texto.split()
    if not 3 <= len(palavras) <= 25 or CODIGO.search(texto):
        return None
    if sum(c.isupper() for c in texto) > len(texto) / 3:  # GRITANDO ou sigla demais
        return None
    return texto


def perguntas() -> list[str]:
    achadas: list[str] = []
    aya = pq.read_table(baixar("aya.parquet"), columns=["inputs", "language"]).to_pylist()
    achadas += [r["inputs"] for r in aya if r["language"] == "Portuguese"]
    oasst = pq.read_table(baixar("oasst2.parquet"), columns=["text", "role", "lang"]).to_pylist()
    achadas += [r["text"] for r in oasst if r["role"] == "prompter" and r["lang"] == "pt-BR"]
    with open(baixar("mmmlu-pt.csv"), encoding="utf-8") as arquivo:
        for linha in csv.DictReader(arquivo):
            if linha.get("Subject") in MATERIAS and not DEPENDE_DAS_OPCOES.search(linha["Question"]):
                achadas.append(linha["Question"])

    vistas, saida = set(), []
    for texto in achadas:
        boa = falavel(texto)
        if boa and boa.lower() not in vistas:
            vistas.add(boa.lower())
            saida.append(boa)
    return saida


if __name__ == "__main__":
    quantas = int(sys.argv[1]) if len(sys.argv) > 1 else 6000
    todas = perguntas()
    random.Random(7).shuffle(todas)
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text("\n".join(todas[:quantas]) + "\n", encoding="utf-8")
    print(f"{min(quantas, len(todas))} de {len(todas)} perguntas em {SAIDA}", file=sys.stderr)
