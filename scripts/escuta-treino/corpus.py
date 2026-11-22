#!/usr/bin/env python3
"""Gera o texto de domínio do modelo de linguagem da escuta: o que se diz à Atlas.

Saída: uma frase por linha, minúsculas, sem pontuação, números por extenso —
o formato do Vosk. O modelo de linguagem geral (FalaBrasil, texto da web) quase
não tem perguntas faladas a um robô; este texto é o que puxa o reconhecimento
para "atlas que dia é hoje" em vez de "a dose que dia é hoje".

Fontes:
- as perguntas de `scripts/treino/dataset.py` (lidas pela árvore sintática,
  sem importar nada de lá: aquele script é de outro trabalho);
- modelos de frase com os nomes e fatos da SETREM, contas, datas, disciplinas;
- os jeitos de chamar a Atlas ("atlas", "oi atlas", "ô atlas"...).

As frases de `frases-teste.tsv` são retiradas, com e sem o "atlas" na frente:
o banco de testes mede generalização, não decoreba.

Uso:  python corpus.py > dominio.txt
"""

from __future__ import annotations

import ast
import itertools
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from avaliar import normalizar  # noqa: E402
from gerar_audio import lerFrases  # noqa: E402

DATASET = AQUI.parent / "treino" / "dataset.py"

UNIDADES = "zero um dois três quatro cinco seis sete oito nove dez onze doze treze catorze quinze dezesseis dezessete dezoito dezenove".split()
DEZENAS = "_ _ vinte trinta quarenta cinquenta sessenta setenta oitenta noventa".split()
CENTENAS = "_ cento duzentos trezentos quatrocentos quinhentos seiscentos setecentos oitocentos novecentos".split()


def porExtenso(n: int) -> str:
    """0 a 999, como se fala."""
    if n < 20:
        return UNIDADES[n]
    if n < 100:
        d, u = divmod(n, 10)
        return DEZENAS[d] + (f" e {UNIDADES[u]}" if u else "")
    if n == 100:
        return "cem"
    c, resto = divmod(n, 100)
    return CENTENAS[c] + (f" e {porExtenso(resto)}" if resto else "")


assert porExtenso(56) == "cinquenta e seis" and porExtenso(105) == "cento e cinco"


def doDataset() -> tuple[list[str], dict[str, list[str]]]:
    """Perguntas (1º item de cada par de strings) e as listas de nomes do dataset."""
    arvore = ast.parse(DATASET.read_text(encoding="utf-8"))
    perguntas, listas = [], {}
    for no in ast.walk(arvore):
        if (
            isinstance(no, ast.Tuple)
            and len(no.elts) == 2
            and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in no.elts)
        ):
            perguntas.append(no.elts[0].value)
        if isinstance(no, ast.Assign) and isinstance(no.targets[0], ast.Name) and isinstance(no.value, ast.List):
            with_strs = [e.value for e in no.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if with_strs and len(with_strs) == len(no.value.elts):
                listas[no.targets[0].id] = with_strs
    return perguntas, listas


CHAMADAS = ["", "atlas", "oi atlas", "olá atlas", "ô atlas", "ei atlas", "e aí atlas", "atlas me diz",
            "atlas me fala", "atlas você sabe", "atlas me explica", "bom dia atlas", "boa tarde atlas",
            "boa noite atlas", "atlas por favor", "escuta atlas"]

FATOS = [
    "quem é o coordenador do curso", "quem é o coordenador de engenharia de computação",
    "quem coordena o curso de engenharia de computação", "o leonardo ropke é o coordenador do curso",
    "quem é o leonardo ropke", "o que o leonardo ropke faz", "o professor ropke", "o ropke é professor",
    "quem é o diretor da setrem", "o antonio ternes é o diretor da setrem", "quem é o antonio ternes",
    "o que é a setrem", "onde fica a setrem", "a setrem fica em três de maio", "eu estudo na setrem",
    "a setrem é uma escola", "o que significa setrem", "sociedade educacional três de maio",
    "quantos alunos tem a setrem", "qual o site da setrem", "a setrem faz parte da rede sinodal",
    "quem é o eduardo goetz", "o eduardo goetz é aluno", "em que semestre está o eduardo goetz",
    "o goetz é o aluno mais velho do curso", "quem é o aluno mais velho do curso", "o goetz",
    "quantos alunos tem o curso", "quantos semestres tem o curso", "quantos anos dura o curso",
    "o curso de engenharia de computação da setrem", "quem trabalha em você",
    "o que é o interdisciplinar quatro", "quem te construiu", "quem fez você", "você é da setrem",
    "onde fica o laboratório", "onde é a sala dos professores", "onde fica a biblioteca",
    "onde fica a cantina", "a que horas começa a aula", "quando começa o semestre",
    "quando são as férias", "quando é a próxima prova", "tem aula amanhã", "tem aula hoje",
]

TEMPO = ["que dia é hoje", "qual a data de hoje", "hoje é que dia", "que dia da semana é hoje",
         "em que mês estamos", "que ano é hoje", "que horas são", "que horas são agora",
         "qual é a hora", "me diz as horas", "amanhã é que dia", "que dia foi ontem",
         "quantos dias faltam para o fim do ano", "hoje é feriado"]

CONVERSA = ["tudo bem", "tudo bem com você", "como você está", "como vai", "oi", "olá", "bom dia",
            "boa tarde", "boa noite", "obrigado", "obrigada", "muito obrigado", "valeu", "tchau",
            "até logo", "até mais", "pode repetir", "não entendi", "fala mais devagar", "repete por favor",
            "o que você disse", "você me ouviu", "você está me ouvindo", "está me escutando",
            "fala mais alto", "para de falar", "silêncio", "espera um pouco", "deixa eu pensar",
            "legal", "que legal", "muito bom", "entendi", "certo", "sim", "não", "talvez",
            "qual o seu nome", "como você se chama", "quem é você", "o que você é", "você é um robô",
            "você é uma inteligência artificial", "você pensa", "você tem sentimentos",
            "você sabe fazer o que", "o que você sabe fazer", "você pode me ajudar",
            "me ajuda", "eu tenho uma pergunta", "posso te fazer uma pergunta", "me conta uma piada",
            "conta uma curiosidade", "me conta uma história", "você gosta de música", "do que você gosta",
            "qual a sua cor favorita", "você está feliz", "você está bem", "você dorme", "você come",
            "você sonha", "quantos anos você tem", "você é homem ou mulher", "você tem nome",
            "meu nome é {nome}", "eu sou o {nome}", "eu sou a {nome}", "prazer em te conhecer",
            "muito prazer atlas", "eu sou aluno da setrem", "eu sou professor", "eu sou calouro",
            "eu estou nervoso com a prova", "estou cansado", "estou com fome", "hoje está frio",
            "hoje está calor", "vai chover hoje", "como está o tempo"]

#: Com o artigo junto: "o que é um recursão" ensinaria ao modelo um português que ninguém fala.
TERMOS = ["um algoritmo", "uma variável", "uma função", "um vetor", "uma matriz", "um ponteiro",
          "um compilador", "um processador", "um transistor", "um resistor", "um capacitor", "um diodo",
          "um indutor", "um microcontrolador", "um sensor", "um circuito", "um protocolo", "um servidor",
          "um banco de dados", "um sistema operacional", "uma rede neural", "inteligência artificial",
          "aprendizado de máquina", "um robô", "um arduino", "um raspberry pi",
          "uma linguagem de programação", "um programa", "software", "hardware", "a memória ram",
          "um computador", "a internet", "um bit", "um byte", "uma porta lógica", "a lei de ohm",
          "corrente elétrica", "tensão elétrica", "resistência elétrica", "potência", "energia",
          "uma derivada", "uma integral", "um limite", "um logaritmo", "um número primo", "uma equação",
          "uma fração", "porcentagem", "física", "cálculo", "programação", "eletrônica", "engenharia",
          "computação", "recursão", "uma classe", "um objeto", "herança", "polimorfismo",
          "um laço de repetição", "uma estrutura de dados", "uma pilha", "uma fila", "uma lista",
          "a cpu", "a gpu", "um sistema embarcado", "um led", "uma placa de vídeo", "um teclado"]
PERGUNTA_TERMO = ["o que é {t}", "o que significa {t}", "me explica o que é {t}", "explica {t}",
                  "para que serve {t}", "como funciona {t}", "você sabe o que é {t}",
                  "me fala sobre {t}", "qual a definição de {t}"]

CONTAS = [("mais", None), ("menos", None), ("vezes", None), ("dividido por", None)]


def frasesDominio() -> list[str]:
    perguntas, listas = doDataset()
    nomes = listas.get("NOMES", []) + ["eduardo", "leonardo", "antonio", "maria", "joão", "pedro", "ana"]
    disciplinas = listas.get("DISCIPLINAS", [])
    base = list(perguntas) + FATOS + TEMPO + CONVERSA
    base += [m.format(t=t) for m, t in itertools.product(PERGUNTA_TERMO, TERMOS)]
    for d in disciplinas:
        base += [f"o que se estuda em {d}", f"quando é a prova de {d}", f"me explica {d}",
                 f"quem é o professor de {d}", f"eu tenho prova de {d} amanhã", f"eu gosto de {d}"]
    for a, b in itertools.product(range(0, 11), range(1, 11)):
        for op, _ in CONTAS:
            base.append(f"quanto é {porExtenso(a)} {op} {porExtenso(b)}")
    for n in range(2, 101):
        base += [f"qual a raiz quadrada de {porExtenso(n)}", f"quanto é {porExtenso(n)} ao quadrado",
                 f"{porExtenso(n)} é primo"]
    frases = []
    for f in base:
        if "{nome}" in f:
            frases += [f.format(nome=n) for n in nomes]
        else:
            frases.append(f)
    # Cada frase também chamada pelo nome: é assim que o robô costuma ouvir.
    saida = []
    for f in frases:
        f = normalizar(f)
        if not f:
            continue
        saida.append(f)
        saida += [f"{c} {f}".strip() for c in CHAMADAS if c]
    return saida


def main() -> None:
    proibidas = set()
    for _, texto in lerFrases():
        t = normalizar(texto)
        proibidas |= {t, t.removeprefix("atlas ").strip()}
    vistas = set()
    for f in frasesDominio():
        if f in proibidas or f.removeprefix("atlas ") in proibidas or f in vistas:
            continue
        vistas.add(f)
        print(f)


if __name__ == "__main__":
    main()
