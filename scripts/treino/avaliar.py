#!/usr/bin/env python3
"""Mesmas perguntas, mesmo prompt do robô: compara modelos antes de trocar.

Mede, por pergunta, o tempo até o primeiro pedaço de texto (é o que decide
quando a Atlas começa a falar) e o tempo total, e mostra a resposta para julgar
no olho se ela entendeu, inventou ou foi clara.

Uso, no Pi (lê o .env do robô; o modelo pode ser trocado na linha de comando):
    .venv/bin/python scripts/treino/avaliar.py
    .venv/bin/python scripts/treino/avaliar.py --modelo gemma3:4b
    .venv/bin/python scripts/treino/avaliar.py --modelo atlas-1b --curto
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from roboteye.config import Settings  # noqa: E402
from roboteye.llm.base import ChatMessage  # noqa: E402
from roboteye.llm.memory import ConversationMemory  # noqa: E402
from roboteye.llm.ollama import OllamaClient  # noqa: E402
from roboteye.llm.persona import PersonaStore  # noqa: E402

PERGUNTAS = [
    "qual é o seu nome",
    "que dia é hoje",
    "quem é o coordenador do curso",
    "quem é o diretor da setrem",
    "quanto é dois mais dois",
    "o que é um algoritmo",
    "qual a diferença entre ram e memória de armazenamento",
    "me explica o que é uma variável em programação",
    "o que é a lei de ohm",
    "qual é a capital do brasil",
    "me conta uma piada de programador",
    "quem é o professor de cálculo",
    "você gosta de música",
    "obrigado atlas",
]


def main() -> int:
    args = argparse.ArgumentParser()
    args.add_argument("--modelo", help="modelo do Ollama (padrão: o do .env)")
    args.add_argument("--curto", action="store_true", help="prompt curto, para modelo treinado")
    opcoes = args.parse_args()

    settings = Settings.fromEnv()
    llm = settings.llm
    if opcoes.modelo:
        llm = dataclasses.replace(llm, model=opcoes.modelo)
    persona = PersonaStore(llm.personaDir, llm.persona, curto=opcoes.curto).load(llm.replyLanguage)
    cliente = OllamaClient(llm)
    sistema = persona.systemPrompt()
    print(f"modelo {llm.model} | persona {llm.persona} | temperatura {llm.temperature} | "
          f"prompt {len(sistema)} caracteres\n")

    cliente.warmUp(ConversationMemory(sistema).buildPrompt())
    primeiros = []
    for pergunta in PERGUNTAS:
        # Cada pergunta sozinha, como a primeira de uma conversa.
        mensagens = [*ConversationMemory(sistema).buildPrompt(), ChatMessage(role="user", content=pergunta)]
        inicio = time.perf_counter()
        primeiro = None
        pedacos = []
        for pedaco in cliente.streamReply(mensagens):
            primeiro = primeiro or time.perf_counter() - inicio
            pedacos.append(pedaco)
        total = time.perf_counter() - inicio
        primeiros.append(primeiro or total)
        print(f"[{primeiro or 0:4.1f}s / {total:4.1f}s] {pergunta}\n    -> {''.join(pedacos).strip()}")
    primeiros.sort()
    print(f"\nprimeiro texto: mediana {primeiros[len(primeiros) // 2]:.1f} s, pior {primeiros[-1]:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
