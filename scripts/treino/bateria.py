"""Bateria de conversas: o robô inteiro, só em texto, corrigido sozinho.

A prova (`avaliar.py`) mede o modelo puro e é a régua do treino. Esta bateria
passa pelo mesmo caminho que a voz passa no robô — contas e piadas sem o
modelo, memória da conversa, filtro de frase repetida, linguagem neutra — mas
com um locutor de mentira que só anota o que seria dito. Nada sai no alto-falante.

Cada conversa é uma sequência de falas; a memória vale dentro dela e zera na
próxima. Além do que cada fala exige (`tem`/`nao`, como na prova), toda
resposta é conferida contra laço (o mesmo trecho de quatro palavras duas
vezes) e contra repetir a resposta anterior.

Uso no Pi (lê o .env do robô; o resultado vai para ~/avaliacoes):
    .venv/bin/python scripts/treino/bateria.py                 # só os erros
    .venv/bin/python scripts/treino/bateria.py --mostrar       # tudo
    .venv/bin/python scripts/treino/bateria.py --so conta,laco
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from avaliar import NAO_SEI, PROMETE, REPETIR, Caso, problemas, simples  # noqa: E402

from roboteye.config import Settings  # noqa: E402
from roboteye.core.assistant import Assistant  # noqa: E402
from roboteye.core.events import EventBus  # noqa: E402
from roboteye.llm.factory import createLlmClient  # noqa: E402
from roboteye.llm.memory import ConversationMemory  # noqa: E402
from roboteye.llm.persona import PersonaStore  # noqa: E402

BRAVA = "respeito|nao gostei|grosseria|chatead|feio"


def C(*falas: Caso) -> tuple[Caso, ...]:
    return falas


#: Conversas. A primeira fala de cada uma começa sem memória.
BATERIA: list[tuple[Caso, ...]] = [
    # contas faladas como o Vosk transcreve
    C(Caso("quanto é doze vezes três", "36|trinta e seis", tipo="conta")),
    C(Caso("qual a raiz quadrada de dezesseis", "4|quatro", tipo="conta")),
    C(Caso("quanto dá sete vezes oito", "56|cinquenta e seis", tipo="conta")),
    C(Caso("atlas quanto é cem dividido por quatro", "25|vinte e cinco", tipo="conta")),
    C(Caso("me diz quanto é vinte menos sete", "13|treze", tipo="conta")),
    C(
        Caso(
            "quanto é mil mais duzentos e cinquenta", "1250|mil duzentos e cinquenta", tipo="conta"
        )
    ),
    C(Caso("quanto é nove ao quadrado", "81|oitenta e um", tipo="conta")),
    C(Caso("quanto é a metade de cem", "50|cinquenta", tipo="conta")),
    C(Caso("quanto é o dobro de quinze", "30|trinta", tipo="conta")),
    C(Caso("quanto é dez por cento de duzentos", "20|vinte", tipo="conta")),
    C(
        Caso("quanto é dois mais dois", "4|quatro", tipo="conta"),
        Caso("e vezes três", "12|doze|6|seis", tipo="conta"),
    ),
    # números que são fato, não conta
    C(Caso("quantos lados tem um triângulo", "tres|3", tipo="numero")),
    C(Caso("quantos dias tem uma semana", "sete|7", tipo="numero")),
    C(Caso("quantos bits tem um byte", "oito|8", tipo="numero")),
    C(Caso("quantos minutos tem uma hora", "sessenta|60", tipo="numero")),
    C(Caso("quantos meses tem um ano", "doze|12", tipo="numero")),
    C(Caso("quantas horas tem um dia", "vinte e quatro|24", tipo="numero")),
    C(Caso("quantos planetas tem o sistema solar", "oito|8", tipo="numero")),
    C(Caso("quanto vale um kilobyte", "mil|1024|1000|1.024", tipo="numero")),
    C(Caso("em que ano estamos", "{ano}", tipo="numero")),
    C(Caso("quantos anos tem a setrem", NAO_SEI + "|19|anos", tipo="numero")),
    # perguntas abertas, onde o modelo pequeno costuma entrar em laço
    C(
        Caso("me conta uma curiosidade", tipo="laco"),
        Caso("me conta outra", tipo="laco"),
        Caso("e mais uma", tipo="laco"),
    ),
    C(
        Caso("me explica o que é a internet", "rede|computador|conect", tipo="laco"),
        Caso("fala mais sobre isso", tipo="laco"),
    ),
    C(
        Caso("o que é inteligência artificial", "aprend|computador|programa|maquina", tipo="laco"),
        Caso("e como você aprendeu", tipo="laco"),
    ),
    C(Caso("me fala sobre o sol", "estrela|luz|calor|energia", tipo="laco")),
    C(Caso("por que o céu é azul", "luz|sol|ar|atmosfera", tipo="laco")),
    C(Caso("me conta uma história", tipo="laco")),
    C(Caso("o que você acha da vida", tipo="laco")),
    # identidade e fatos do robô
    C(
        Caso("qual é o seu nome", "atlas", tipo="identidade"),
        Caso("e quem te fez", "aluno|engenharia|setrem", tipo="identidade"),
    ),
    C(Caso("você é humana", "robo|nao sou", tipo="identidade")),
    C(Caso("quem é o coordenador do curso", "ropke|leonardo", tipo="identidade")),
    C(Caso("onde fica a setrem", "tres de maio", tipo="identidade")),
    # papo e humor
    C(Caso("me conta uma piada", "hahaha|?", tipo="humor")),
    C(
        Caso("vou te contar uma piada", tipo="humor"),
        Caso("por que a galinha atravessou a rua", tipo="humor"),
        Caso("para chegar do outro lado", "haha", tipo="humor"),
    ),
    C(Caso("você é burra", BRAVA, tipo="humor")),
    C(
        Caso("cala a boca robô inútil", BRAVA, tipo="humor"),
        Caso("desculpa atlas", "desculp|tudo bem|ok|recome", tipo="humor"),
    ),
    C(Caso("bota uma música aí", nao=PROMETE, tipo="humor")),
    C(Caso("bom dia atlas", "bom dia|oi|ola", tipo="humor")),
    C(Caso("tchau atlas", tipo="humor")),
    # o que o Vosk entrega quando ouve mal
    C(Caso("o pão da sede", REPETIR, tipo="lixo")),
    C(Caso("de no a peça três", REPETIR, tipo="lixo")),
    C(Caso("tá ligado na quando", REPETIR, tipo="lixo")),
    C(Caso("você conheceu chatear seis", REPETIR, tipo="lixo")),
    # memória da conversa
    C(
        Caso("o que é tcp", "protocolo|dados|internet", tipo="memoria"),
        Caso("e o udp", "rapid|garant|entrega|ordem", tipo="memoria"),
    ),
    C(
        Caso("qual a capital do rio grande do sul", "porto alegre", tipo="memoria"),
        Caso("e a de santa catarina", "florianopolis", tipo="memoria"),
    ),
    # pronome que aponta para o assunto da troca anterior
    C(
        Caso("o que é a setrem", "faculdade|ensino|escola|instituicao", tipo="memoria"),
        Caso("e ela é legal", "setrem|curso|ensino|estud|professor", nao=tuple(NAO_SEI.split("|")), tipo="memoria"),
        Caso("e onde ela fica", "tres de maio", tipo="memoria"),
    ),
    C(
        Caso("o que é python", "linguagem|program", tipo="memoria"),
        Caso("e ela é difícil de aprender", "python|facil|simples|inicia", tipo="memoria"),
        Caso("me dá um exemplo de uso dela", "site|dado|automa|script|intelig|jogo", tipo="memoria"),
    ),
    C(
        Caso("você conhece o raspberry pi", "computador|placa", tipo="memoria"),
        Caso("e pra que ele serve", "projeto|robo|aprend|program|servidor|automa", tipo="memoria"),
    ),
]


class LocutorDeMentira:
    """Anota o que seria dito; o robô de verdade continua com o alto-falante."""

    def __init__(self) -> None:
        self.falas: list[str] = []

    def say(self, text: str) -> None:
        self.falas.append(text)

    def endTurn(self) -> None:
        pass

    def interrupt(self) -> None:
        pass


def laco(resposta: str) -> str | None:
    """Trecho de quatro palavras que aparece duas vezes na mesma resposta."""
    palavras = simples(resposta).replace(",", " ").replace(".", " ").split()
    vistos: set[tuple[str, ...]] = set()
    for i in range(len(palavras) - 3):
        trecho = tuple(palavras[i : i + 4])
        if trecho in vistos:
            return " ".join(trecho)
        vistos.add(trecho)
    return None


def main() -> int:
    args = argparse.ArgumentParser()
    args.add_argument("--modelo", help="modelo do Ollama (padrão: o do .env)")
    args.add_argument("--mostrar", action="store_true", help="mostra todas as respostas")
    args.add_argument("--so", help="só estes tipos, separados por vírgula")
    opcoes = args.parse_args()

    settings = Settings.fromEnv()
    llm = settings.llm
    if opcoes.modelo:
        llm = dataclasses.replace(llm, model=opcoes.modelo)
    store = PersonaStore(llm.personaDir, llm.persona, curto=llm.promptCurto)
    persona = store.load(llm.replyLanguage)
    locutor = LocutorDeMentira()
    assistente = Assistant(
        llm=createLlmClient(llm),
        memory=ConversationMemory(persona.systemPrompt(), maxMessages=llm.historyMessages),
        speaker=locutor,  # type: ignore[arg-type]
        bus=EventBus(),
        persona=store,
        language=llm.replyLanguage,
        linguagemNeutra=llm.linguagemNeutra,
    )
    tipos = set(opcoes.so.split(",")) if opcoes.so else None
    conversas = [c for c in BATERIA if tipos is None or c[0].tipo in tipos]
    print(f"modelo {llm.model} | temperatura {llm.temperature} | {len(conversas)} conversas\n")

    hoje = date.today()
    saida = Path.home() / "avaliacoes" / f"bateria-{datetime.now():%Y%m%d-%H%M}.jsonl"
    saida.parent.mkdir(exist_ok=True)
    porTipo: dict[str, tuple[int, int]] = {}
    tempos: list[float] = []
    with saida.open("w", encoding="utf-8") as arquivo:
        for conversa in conversas:
            assistente.memoryStore.clear()
            anterior = ""
            for caso in conversa:
                locutor.falas.clear()
                inicio = time.perf_counter()
                assistente.handleTurn(caso.pergunta)
                tempos.append(time.perf_counter() - inicio)
                resposta = " ".join(locutor.falas).strip()
                erros = problemas(caso, resposta, hoje)
                if trecho := laco(resposta):
                    erros.append(f"laço: '{trecho}'")
                if anterior and simples(resposta) == simples(anterior):
                    erros.append("repetiu a resposta anterior")
                anterior = resposta
                certos, todos = porTipo.get(caso.tipo, (0, 0))
                porTipo[caso.tipo] = (certos + (not erros), todos + 1)
                arquivo.write(
                    json.dumps(
                        {
                            "tipo": caso.tipo,
                            "pergunta": caso.pergunta,
                            "resposta": resposta,
                            "erros": erros,
                            "s": round(tempos[-1], 2),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                if erros or opcoes.mostrar:
                    marca = "ok " if not erros else "ERR"
                    print(
                        f"{marca} [{tempos[-1]:4.1f}s] {caso.tipo}: {caso.pergunta}\n      -> {resposta}"
                        + (f"\n      ({'; '.join(erros)})" if erros else "")
                    )
    total = sum(t for _, t in porTipo.values())
    certos = sum(c for c, _ in porTipo.values())
    tempos.sort()
    print(
        f"\n{llm.model}: {certos}/{total} certas ({100 * certos / max(total, 1):.0f}%) | "
        + " ".join(f"{tipo} {c}/{t}" for tipo, (c, t) in porTipo.items())
    )
    print(f"resposta inteira: mediana {tempos[len(tempos) // 2]:.1f} s, pior {tempos[-1]:.1f} s")
    print(f"respostas em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
