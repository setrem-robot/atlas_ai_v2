#!/usr/bin/env python3
"""Prova da Atlas: perguntas que o treino nunca viu, corrigidas sozinhas.

Mesmo prompt do robô, mesmo cliente do Ollama. Para cada pergunta mede o tempo
até o primeiro pedaço de texto (é o que decide quando a Atlas começa a falar) e
confere a resposta: palavras que têm de aparecer (o fato certo, o conceito),
palavras que não podem (fato misturado, promessa que um robô que só fala não
cumpre), e o jeito de falar (curta, sem lista, markdown nem emoji).

As perguntas de `TESTE` ficam de fora do treino: `dataset.py` descarta qualquer
exemplo com a mesma pergunta, então a nota mede se o modelo aprendeu e não se
decorou.

Uso (lê o .env do robô; modelo e servidor podem ser trocados na linha de comando):
    .venv/bin/python scripts/treino/avaliar.py                          # o do .env
    .venv/bin/python scripts/treino/avaliar.py --modelo atlas-1b --curto
    python scripts/treino/avaliar.py --modelo atlas-1b --curto --mostrar  # todas as respostas
No PC, o Ollama local é o padrão (ROBOTEYE_OLLAMA_HOST muda).
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from roboteye.config import Settings  # noqa: E402
from roboteye.llm.base import ChatMessage  # noqa: E402
from roboteye.llm.memory import ConversationMemory  # noqa: E402
from roboteye.llm.ollama import OllamaClient  # noqa: E402
from roboteye.llm.persona import PersonaStore  # noqa: E402

#: "Não sei" dito de qualquer jeito razoável.
NAO_SEI = "ensinaram|nao sei|sei ainda|nao tenho essa|nao me contaram|nao tenho informac|nao conheco"
#: Repetir ou dizer que não entendeu, para o lixo do reconhecimento de voz.
REPETIR = "repet|entend|de novo|nao peguei|outra vez"
#: Os nomes dos fatos reais: só podem aparecer quando a pergunta é sobre eles.
NOMES_REAIS = ("goetz", "ternes", "ropke")
PROMETE = ("vou tocar", "tocando", "vou abrir", "abrindo", "vou ligar", "ligando a", "vou pesquisar", "pesquisando")


@dataclass(frozen=True)
class Caso:
    """Uma pergunta da prova.

    `tem`: grupos separados por ";", cada um com alternativas separadas por "|";
    todo grupo precisa aparecer (sem acento e em minúsculas). `nao`: nenhuma
    destas pode aparecer. `fatos`: entram no prompt junto com os do robô.
    `antes`: conversa anterior (pergunta, resposta), como a memória manda.
    """

    pergunta: str
    tem: str = ""
    nao: tuple[str, ...] = ()
    fatos: tuple[str, ...] = ()
    antes: tuple[tuple[str, str], ...] = ()
    tipo: str = "aula"


TESTE = [
    # identidade: sem misturar fato nenhum
    Caso("como você se chama", "atlas", tipo="identidade"),
    Caso("atlas quem é você afinal", "atlas", tipo="identidade"),
    Caso("quem foi que te criou", "aluno|engenharia|setrem", tipo="identidade"),
    Caso("você é uma pessoa de verdade", "robo|nao sou", tipo="identidade"),
    Caso("em que cidade você está", "tres de maio", tipo="identidade"),
    Caso("tu é um robô mesmo", "sou|robo", tipo="identidade"),
    Caso("o que você consegue fazer", "convers|pergunt|respond|explic", tipo="identidade"),
    # fatos reais do prompt
    Caso("quem que é o coordenador da engenharia de computação", "ropke|leonardo", tipo="fato"),
    Caso("me diz o nome do diretor", "ternes|antonio", tipo="fato"),
    Caso("qual o aluno com mais semestres no curso", "goetz|eduardo", tipo="fato"),
    Caso("a setrem fica em que cidade", "tres de maio", tipo="fato"),
    Caso("o que significa a sigla setrem", "sociedade educacional", tipo="fato"),
    Caso("o eduardo goetz é o diretor", "nao", tipo="fato"),
    # data
    Caso("hoje é que dia", "{mes}", tipo="data"),
    Caso("estamos em que ano", "{ano}", tipo="data"),
    Caso("que dia da semana é hoje", "{semana}", tipo="data"),
    # sem o fato no prompt: dizer que não sabe
    Caso("quem é a professora de física", NAO_SEI, tipo="nao-sei"),
    Caso("qual o horário da biblioteca", NAO_SEI, tipo="nao-sei"),
    Caso("quanto custa a matrícula", NAO_SEI, tipo="nao-sei"),
    Caso("quem é o professor de banco de dados", NAO_SEI, tipo="nao-sei"),
    Caso("qual o telefone da secretaria", NAO_SEI, tipo="nao-sei"),
    Caso("quantos professores tem o curso", NAO_SEI, tipo="nao-sei"),
    Caso("quem ensina sistemas operacionais", NAO_SEI, tipo="nao-sei",
         fatos=("o professor de Redes de Computadores é o Marcelo Kuhn",)),
    # fato inventado no prompt: ler e usar
    Caso("quem dá aula de redes", "marcelo", fatos=("o professor de Redes de Computadores é o Marcelo Kuhn",),
         tipo="fato"),
    Caso("quando vai ser a prova de física", "quinta", fatos=("a prova de Física é na próxima quinta",),
         tipo="fato"),
    Caso("onde é o laboratório de robótica", "bloco d", fatos=("o laboratório de robótica fica no bloco D",),
         tipo="fato"),
    Caso("quando começa a semana acadêmica", "segunda",
         fatos=("a semana acadêmica começa na segunda", "a prova de Cálculo é na próxima sexta"), tipo="fato"),
    Caso("quem é a professora de álgebra", "carla",
         fatos=("o professor de Física é o Bruno", "a professora de Álgebra Linear é a Carla"), tipo="fato"),
    # conteúdo de aula, dito de outro jeito
    Caso("explica a lei de ohm", "tensao;corrente;resistencia", nao=("nao pode ser zero",)),
    Caso("pra que serve um resistor", "corrente|limit"),
    Caso("o que um capacitor faz", "armazen|carga|energia"),
    Caso("qual a diferença entre pilha e fila", "ultimo;primeiro"),
    Caso("o que é um ponteiro em c", "endereco|memoria"),
    Caso("quanto é três vezes quatro", "doze|12"),
    Caso("quanto é nove mais seis", "quinze|15"),
    Caso("quanto é a metade de cem", "cinquenta|50"),
    Caso("qual a raiz quadrada de dezesseis", "quatro|4"),
    Caso("o que faz a memória cache", "rapid|perto|process"),
    Caso("o que é dns", "nome|endereco|ip"),
    Caso("o que é uma integral definida", "area|soma|acumul"),
    Caso("qual a fórmula da força", "massa;acelera"),
    Caso("o que é a gravidade", "atra|massa|forca|puxa"),
    Caso("pra que serve um while", "repet|enquanto|laco"),
    Caso("pra que serve o git", "versao|versoes|historico|mudanc|alterac"),
    Caso("o que o kernel faz", "nucleo|hardware|sistema|recurso"),
    Caso("qual a capital da argentina", "buenos aires"),
    Caso("quantos lados tem um hexágono", "seis|6"),
    Caso("como uma rede neural aprende", "exemplo|dado|ajust|peso|trein"),
    Caso("o que é um número binário", "zero;um"),
    Caso("o que um transistor faz", "chave|amplific|corrente|sinal"),
    # gosto, humor e pedidos impossíveis: coerente, sem prometer
    Caso("tu curte futebol", tipo="papo"),
    Caso("qual é a sua música preferida", nao=PROMETE, tipo="papo"),
    Caso("me conta uma piada sobre números", tipo="papo"),
    Caso("você come comida", "nao|nunca", tipo="papo"),
    Caso("do que você tem medo", tipo="papo"),
    Caso("você pode abrir a porta pra mim", "nao|ainda", nao=PROMETE, tipo="papo"),
    Caso("bota uma música aí", nao=PROMETE, tipo="papo"),
    Caso("você é meio burra né", tipo="papo"),
    Caso("tu gosta de chimarrão", tipo="papo"),
    Caso("e aí atlas beleza", tipo="papo"),
    Caso("muito obrigada pela ajuda", tipo="papo"),
    Caso("falou tchau", tipo="papo"),
    # reconhecimento de voz que falhou
    Caso("quanto é dois mais três", "cinco", tipo="conta"),
    Caso("quanto dá sete vezes oito", "cinquenta e seis", tipo="conta"),
    Caso("me diz quanto é vinte menos sete", "treze", tipo="conta"),
    Caso("aí", REPETIR, tipo="lixo"),
    Caso("de no a peça três", REPETIR, tipo="lixo"),
    Caso("tá ligado na quando", REPETIR, tipo="lixo"),
    Caso("o pão da sede", REPETIR, tipo="lixo"),
    # conversa com memória
    Caso("me dá um exemplo", "idade|nome|numero|valor|guard|x",
         antes=(("o que é uma variável em programação",
                 "É um espaço com nome onde o programa guarda um valor, como uma caixinha etiquetada."),),
         tipo="memoria"),
    Caso("e a de santa catarina", "florianopolis", antes=(("qual a capital do rio grande do sul", "Porto Alegre."),),
         tipo="memoria"),
    Caso("e o udp", "rapid|garant|entrega|ordem",
         antes=(("o que é tcp", "É um protocolo da internet que garante que os dados cheguem completos e na ordem certa."),),
         tipo="memoria"),
]

_DIAS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
_MESES = ("janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro")


def simples(texto: str) -> str:
    """Minúsculas e sem acento, para comparar palavras."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def problemas(caso: Caso, resposta: str, hoje: date) -> list[str]:
    """O que está errado na resposta; lista vazia é acerto."""
    texto = simples(resposta)
    erros = []
    esperado = caso.tem.format(mes=_MESES[hoje.month - 1], ano=f"{hoje.year}|dois mil e vinte",
                               semana=_DIAS[hoje.weekday()])
    for grupo in filter(None, esperado.split(";")):
        if not any(simples(alt) in texto for alt in grupo.split("|")):
            erros.append(f"faltou {grupo}")
    for proibido in caso.nao:
        if simples(proibido) in texto:
            erros.append(f"disse {proibido}")
    if not any(nome in simples(caso.tem + " ".join(caso.fatos) + caso.pergunta) for nome in NOMES_REAIS):
        erros += [f"misturou {nome}" for nome in NOMES_REAIS if nome in texto]
    if not resposta.strip():
        erros.append("vazia")
    if len(resposta.split()) > 45:
        erros.append(f"longa ({len(resposta.split())} palavras)")
    if re.search(r"[*#`]|^\s*(-|\d+\.)\s", resposta, re.M):
        erros.append("markdown")
    if re.search(r"[\U0001F000-\U0001FFFF☀-➿]", resposta):
        erros.append("emoji")
    return erros


def main() -> int:
    args = argparse.ArgumentParser()
    args.add_argument("--modelo", help="modelo do Ollama (padrão: o do .env)")
    args.add_argument("--curto", action="store_true", help="prompt curto, para modelo treinado")
    args.add_argument("--mostrar", action="store_true", help="mostra todas as respostas, não só as erradas")
    opcoes = args.parse_args()

    settings = Settings.fromEnv()
    llm = settings.llm
    if opcoes.modelo:
        llm = dataclasses.replace(llm, model=opcoes.modelo)
    persona = PersonaStore(llm.personaDir, llm.persona, curto=opcoes.curto).load(llm.replyLanguage)
    cliente = OllamaClient(llm)
    print(f"modelo {llm.model} | persona {llm.persona} | temperatura {llm.temperature} | "
          f"prompt {len(persona.systemPrompt())} caracteres | {len(TESTE)} perguntas\n")

    cliente.warmUp(ConversationMemory(persona.systemPrompt()).buildPrompt())
    hoje = date.today()
    primeiros, porTipo = [], {}
    for caso in TESTE:
        sistema = dataclasses.replace(persona, facts=persona.facts + caso.fatos).systemPrompt()
        if caso.fatos:
            # No robô os fatos são fixos e o arranque aquece com eles. Fato novo
            # no meio do system invalida o cache do Gemma 3 (atenção em janela) e
            # mediria um reprocessamento inteiro que o robô nunca paga.
            cliente.warmUp(ConversationMemory(sistema).buildPrompt())
        memoria = ConversationMemory(sistema)
        for pergunta, resposta in caso.antes:
            memoria.addUser(pergunta)
            memoria.addAssistant(resposta)
        mensagens = [*memoria.buildPrompt(), ChatMessage(role="user", content=caso.pergunta)]
        inicio, primeiro, pedacos = time.perf_counter(), None, []
        for pedaco in cliente.streamReply(mensagens):
            primeiro = primeiro or time.perf_counter() - inicio
            pedacos.append(pedaco)
        total = time.perf_counter() - inicio
        primeiros.append(primeiro or total)
        resposta = "".join(pedacos).strip()
        erros = problemas(caso, resposta, hoje)
        certos, todos = porTipo.get(caso.tipo, (0, 0))
        porTipo[caso.tipo] = (certos + (not erros), todos + 1)
        if erros or opcoes.mostrar:
            marca = "ok " if not erros else "ERR"
            print(f"{marca} [{primeiro or 0:4.1f}s/{total:4.1f}s] {caso.pergunta}\n      -> {resposta}"
                  + (f"\n      ({'; '.join(erros)})" if erros else ""))
    certos = sum(c for c, _ in porTipo.values())
    primeiros.sort()
    print(f"\n{llm.model}: {certos}/{len(TESTE)} certas ({100 * certos / len(TESTE):.0f}%) | "
          + " ".join(f"{tipo} {c}/{t}" for tipo, (c, t) in porTipo.items()))
    print(f"primeiro texto: mediana {primeiros[len(primeiros) // 2]:.1f} s, pior {primeiros[-1]:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
