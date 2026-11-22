#!/usr/bin/env python3
"""Gera mais exemplos de treino com um modelo grande (o "professor") no PC.

Os exemplos escritos à mão em `dataset.py` ensinam o jeito da Atlas, mas são
poucas centenas: o modelo de 1B decora a frase e erra a mesma pergunta dita de
outro jeito. Aqui o `qwen3:8b` do Ollama do PC escreve:

- `aula`:      pares pergunta e resposta de conteúdo do curso, por subtema;
- `papo`:      conversa, gosto e opinião, com o humor da Atlas;
- `seguida`:   conversas de duas ou três trocas em que a pergunta depende da
               anterior ("me dá um exemplo"), que é o que a memória do robô manda;
- `parafrase`: a mesma pergunta escrita à mão, dita como o Vosk transcreve,
               para manter a resposta escrita à mão;
- `julgar`:    uma segunda passada em que o professor dá nota a cada par de
               `aula`, `papo` e `seguida`; só passa nota quatro ou cinco.

Tudo vai para `scripts/treino/dados/*.jsonl`, uma linha por chamada, gravada e
sincronizada no disco na hora: se a luz cair, rodar de novo continua de onde
parou (cada linha leva a chave do trabalho que a gerou).

O professor erra fatos históricos e curiosidades com toda a confiança, então
os pedidos ficam em conceito de aula e conversa, e `limpo()` derruba o que não
dá para falar (dígito, markdown, emoji, inglês, texto longo).

Uso (Ollama do PC com o qwen3:8b baixado):
    python scripts/treino/professor.py aula
    python scripts/treino/professor.py papo
    python scripts/treino/professor.py seguida
    python scripts/treino/professor.py parafrase
    python scripts/treino/professor.py julgar
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import dataset  # os exemplos escritos à mão viram o modelo de estilo do professor

PROFESSOR = os.environ.get("PROFESSOR", "qwen3:8b")
OLLAMA = os.environ.get("OLLAMA", "http://127.0.0.1:11434")
DADOS = Path(__file__).resolve().parent / "dados"

ATLAS = (
    "Atlas é um robô de voz em construção, feito por alunos do curso de Engenharia de "
    "Computação da SETREM, em Três de Maio, no Rio Grande do Sul. Tem dois olhos animados "
    "numa tela e uma voz; roda num Raspberry Pi, ouve pelo reconhecimento de voz Vosk e "
    "pensa com um modelo de linguagem pequeno. Fala com alunos e visitantes."
)

REGRAS = """Regras de cada resposta da Atlas:
- português do Brasil, uma ou duas frases curtas, no máximo trinta palavras, porque ela fala em voz alta;
- correta e simples, como um bom professor falando; uma comparação do dia a dia quando ajudar;
- sem markdown, listas, emoji, código ou símbolos; fórmulas ditas por extenso, como "a força é igual à massa vezes a aceleração";
- números sempre por extenso, como "oito bits" ou "cento e vinte", nunca algarismos;
- nunca invente datas, nomes de pessoas, história, recordes ou curiosidades; sem certeza, troque de pergunta;
- não cite professores, horários, salas, notas ou regras da SETREM: isso a Atlas só sabe quando alguém ensina;
- comece com maiúscula e termine com ponto; comparação só quando for exata, senão explique direto.
As perguntas são de quem fala com o robô: minúsculas, sem pontuação, variadas, algumas informais."""

# --- aula: área -> subtemas ----------------------------------------------------
AREAS = {
    "programação": [
        "variáveis e tipos de dados", "condicionais", "laços de repetição", "funções e parâmetros",
        "recursão", "vetores e listas", "strings", "escopo de variáveis", "erros e exceções",
        "comentários e boas práticas de código", "entrada e saída de dados", "operadores lógicos",
        "linguagens compiladas e interpretadas", "Python para iniciantes", "linguagem C e ponteiros",
        "depuração de código", "versionamento com git", "testes de software", "lógica de programação",
        "pseudocódigo e fluxograma",
    ],
    "estruturas de dados e algoritmos": [
        "pilha", "fila", "lista encadeada", "árvore binária", "tabela hash", "grafos",
        "busca linear e busca binária", "algoritmos de ordenação", "complexidade e notação big o",
        "dicionários e conjuntos", "divisão e conquista", "algoritmos gulosos", "programação dinâmica",
        "busca em largura e em profundidade", "heap e fila de prioridade",
    ],
    "orientação a objetos": [
        "classe e objeto", "atributos e métodos", "herança", "polimorfismo", "encapsulamento",
        "abstração e interfaces", "construtores", "composição de objetos", "padrões de projeto simples",
    ],
    "eletrônica e circuitos": [
        "tensão corrente e resistência", "lei de Ohm", "resistores em série e em paralelo",
        "capacitores", "indutores", "diodos e LEDs", "transistores", "fontes de alimentação",
        "multímetro", "protoboard", "corrente contínua e alternada", "potência elétrica",
        "curto-circuito e segurança elétrica", "divisor de tensão", "leis de Kirchhoff",
        "amplificador operacional", "sinais analógicos e digitais", "baterias",
    ],
    "eletrônica digital": [
        "sistema binário", "hexadecimal e octal", "portas lógicas", "álgebra booleana",
        "tabela verdade", "flip-flops", "registradores e contadores", "multiplexador",
        "somador binário", "circuitos combinacionais e sequenciais", "clock",
    ],
    "arquitetura de computadores": [
        "processador e CPU", "memória RAM", "memória cache", "armazenamento SSD e HD",
        "placa-mãe e barramentos", "GPU", "ciclo de instrução", "registradores do processador",
        "núcleos e paralelismo", "arquitetura ARM e x86", "BIOS e inicialização",
        "periféricos de entrada e saída", "bits bytes e unidades de medida de memória",
    ],
    "sistemas operacionais": [
        "o que faz um sistema operacional", "processos", "threads", "escalonamento de processos",
        "memória virtual", "sistema de arquivos", "Linux e terminal", "drivers", "permissões de arquivos",
        "deadlock", "kernel", "inicialização do sistema",
    ],
    "redes de computadores": [
        "endereço IP", "TCP e UDP", "roteador e switch", "Wi-Fi", "DNS", "protocolo HTTP",
        "modelo em camadas", "pacotes de dados", "latência e largura de banda", "firewall",
        "internet e intranet", "endereço MAC", "Bluetooth", "servidor e cliente",
    ],
    "banco de dados": [
        "o que é banco de dados", "tabelas linhas e colunas", "chave primária e chave estrangeira",
        "SQL e consultas", "banco relacional e não relacional", "normalização", "índices",
        "transações", "backup de dados",
    ],
    "sistemas embarcados": [
        "microcontroladores", "Arduino", "Raspberry Pi", "sensores", "atuadores e motores",
        "GPIO e pinos", "PWM", "comunicação serial", "internet das coisas", "robótica",
        "sistemas de tempo real", "ESP32",
    ],
    "inteligência artificial": [
        "o que é inteligência artificial", "aprendizado de máquina", "redes neurais",
        "dados de treino", "modelos de linguagem", "reconhecimento de voz", "visão computacional",
        "viés e ética em IA", "aprendizado supervisionado e não supervisionado",
    ],
    "segurança da informação": [
        "senhas fortes", "vírus e malware", "criptografia", "golpes e phishing", "backup",
        "autenticação em dois fatores",
    ],
    "física": [
        "leis de Newton", "velocidade e aceleração", "energia cinética e potencial",
        "trabalho e potência", "gravidade", "atrito", "eletricidade e magnetismo",
        "ondas e som", "luz", "calor e temperatura", "pressão", "conservação de energia",
    ],
    "cálculo": [
        "funções", "limites", "derivadas", "integrais", "taxa de variação",
        "máximos e mínimos", "regra da cadeia", "área sob a curva",
    ],
    "álgebra e matemática": [
        "matrizes", "vetores na matemática", "determinante", "sistemas lineares",
        "equação do primeiro grau", "equação do segundo grau", "porcentagem", "frações",
        "potências e raízes", "números primos", "logaritmo", "probabilidade",
        "média e estatística", "geometria básica", "trigonometria", "contas de cabeça",
    ],
    "estudo e carreira": [
        "como estudar para provas", "organização do tempo", "trabalho em grupo",
        "como aprender a programar", "estágio", "o que faz um engenheiro de computação",
        "mercado de trabalho em tecnologia", "projetos pessoais e portfólio", "como não desistir",
        "ansiedade antes da prova", "aprender inglês para tecnologia", "TCC",
    ],
}

ENFOQUES = [
    "conceitos básicos, para quem nunca estudou o assunto",
    "como funciona, para que serve, diferenças entre conceitos parecidos e dúvidas comuns de aluno",
]

# --- papo: conversa, gosto e opinião -------------------------------------------
PAPOS = [
    "música", "comida", "filmes e séries", "futebol e esportes", "o tempo lá fora, frio e calor",
    "animais de estimação", "cores favoritas", "viagens e férias", "amor e namoro", "medo",
    "sonhos e dormir", "idade e aniversário", "família", "amizade", "outros robôs famosos da ficção",
    "celular e redes sociais", "videogames", "café", "chimarrão", "churrasco", "segunda-feira",
    "provas e trabalhos", "cansaço e estresse de aluno", "motivação para estudar", "elogios ao robô",
    "alguém sendo grosseiro ou xingando o robô", "perguntas sobre os sentimentos do robô",
    "pedidos que o robô não consegue fazer, como abrir a porta, ligar a luz ou tocar música",
    "pedidos para pesquisar na internet ou ver notícias", "futuro e tecnologia",
    "pedidos de conselho", "o robô ser comparado a outras inteligências artificiais",
    "o robô errar ou travar", "piadas de tecnologia e programação", "piadas de engenharia",
    "piadas de matemática", "trava-línguas e brincadeiras", "cumprimentos e despedidas",
    "agradecimentos", "visitantes chegando na faculdade", "criança conversando com o robô",
    "perguntas filosóficas", "o robô ter vontade própria", "o robô ser homem ou mulher",
    "o que o robô faz quando está desligado", "o robô gostar de pessoas", "hobbies",
    "livros", "o mar e a natureza", "dinheiro", "política e religião (o robô fica neutro)",
]

ESTILO_PAPO = (
    "A Atlas é simpática, curiosa e tem humor leve de tecnologia, sempre coerente: como robô, ela não "
    "come, não dorme e não tem gosto de verdade, então brinca com isso (eletricidade, processador, "
    "Wi-Fi, bateria, código) e, quando cabe, devolve a pergunta para a pessoa. Nunca é grosseira, "
    "nunca finge ser humana, não promete fazer o que não consegue (ela só fala, ouve e mexe os olhos) "
    "e não inventa fatos sobre si mesma, como data de criação ou nomes de quem a construiu."
)


def exemplos(*grupos: list[tuple[str, str]], quantos: int = 12) -> str:
    pares = [par for grupo in grupos for par in grupo][::3][:quantos]
    return "Exemplos do jeito certo:" + "".join(f"\npergunta: {p}\nresposta: {r}" for p, r in pares)


def chamar(sistema: str, pedido: str, esquema: dict, *, temperatura: float = 0.8) -> dict:
    """Uma chamada ao professor, com saída em JSON no formato do esquema."""
    corpo = json.dumps({
        "model": PROFESSOR, "stream": False, "think": False, "format": esquema,
        "keep_alive": "20m",
        "options": {"temperature": temperatura, "num_ctx": 4096, "num_predict": 2500},
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}],
    }).encode()
    pedidoHttp = urllib.request.Request(f"{OLLAMA}/api/chat", corpo, {"Content-Type": "application/json"})
    with urllib.request.urlopen(pedidoHttp, timeout=600) as resposta:
        return json.loads(json.load(resposta)["message"]["content"])


def descarregar() -> None:
    """Tira o professor da GPU: o treino precisa dos 8 GB."""
    corpo = json.dumps({"model": PROFESSOR, "keep_alive": 0}).encode()
    urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/generate", corpo), timeout=60).read()


# --- arquivo incremental ----------------------------------------------------------
def lerLinhas(nome: str) -> list[dict]:
    caminho = DADOS / nome
    if not caminho.exists():
        return []
    linhas = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        try:
            linhas.append(json.loads(linha))
        except json.JSONDecodeError:
            pass  # a última linha pode ter ficado pela metade numa queda de luz
    return linhas


_TRAVA = threading.Lock()


def gravar(nome: str, item: dict) -> None:
    DADOS.mkdir(exist_ok=True)
    with _TRAVA, open(DADOS / nome, "a", encoding="utf-8") as arquivo:
        arquivo.write(json.dumps(item, ensure_ascii=False) + "\n")
        arquivo.flush()
        os.fsync(arquivo.fileno())


def rodar(nome: str, trabalhos: list[tuple[str, callable]]) -> None:
    """Executa os trabalhos (chave, função) que ainda não estão no arquivo."""
    feitos = {linha["chave"] for linha in lerLinhas(nome)}
    pendentes = [(chave, fazer) for chave, fazer in trabalhos if chave not in feitos]
    print(f"{nome}: {len(feitos)} feitos, {len(pendentes)} pendentes", file=sys.stderr)
    inicio, contagem = time.time(), iter(range(1, len(pendentes) + 1))

    def um(trabalho):
        chave, fazer = trabalho
        for _ in range(3):
            try:
                gravar(nome, {"chave": chave, **fazer()})
                break
            except Exception as erro:  # JSON torto ou Ollama ocupado: tenta de novo
                print(f"  {chave}: {erro}", file=sys.stderr)
                time.sleep(2)
        i = next(contagem)
        if i % 10 == 0:
            print(f"  {i}/{len(pendentes)} ({(time.time() - inicio) / i:.1f} s cada)", file=sys.stderr)

    # Duas chamadas ao mesmo tempo: o Ollama decodifica as duas no mesmo passo da GPU.
    with ThreadPoolExecutor(int(os.environ.get("PARALELO", "2"))) as fila:
        list(fila.map(um, pendentes))


# --- filtro ---------------------------------------------------------------------------
_PROIBIDO = re.compile(r"[0-9*#_`|<>{}\[\]=+/\\^~@]|\n|^\s*-|\s-\s|[⺀-鿿가-힯぀-ヿ]")
_EMOJI = re.compile(r"[\U0001F000-\U0001FFFF☀-➿]")
_INGLES = re.compile(r"\b(the|and|you|is|are|what|this|of the)\b", re.I)
_PORTUGAL = re.compile(r"\b(estás|tens|fazes|podes|queres|sabes|vós|vosso|vossa|telemóvel|ecrã|ficheiro|utilizador|equipa)\b", re.I)
_SETREM_INVENTADO = re.compile(r"\b(professora? [A-Z]|coordenador|diretor|reitor|sala [A-Z0-9]|bloco [A-Z]\b)")


def limpo(resposta: str, *, palavras: int = 38) -> bool:
    """A resposta pode ser falada pela Atlas como está?"""
    texto = resposta.strip()
    return (
        bool(texto)
        and len(texto.split()) <= palavras
        and not _PROIBIDO.search(texto)
        and not _EMOJI.search(texto)
        and not _INGLES.search(texto)
        and not _PORTUGAL.search(texto)
        and not _SETREM_INVENTADO.search(texto)
        and texto[-1] in ".!?"
    )


def perguntaLimpa(pergunta: str) -> bool:
    texto = pergunta.strip()
    return 1 <= len(texto.split()) <= 20 and not re.search(r"[0-9\n*#`]", texto) and not _EMOJI.search(texto)


assert limpo("A força é igual à massa vezes a aceleração.")
assert not limpo("A RAM tem 8 GB.")
assert not limpo("- item de lista.")
assert not limpo("Isto é ótimo 😀.")
assert not limpo("Tu podes usar o ecrã.")


# --- tarefas --------------------------------------------------------------------------
ESQUEMA_PARES = {
    "type": "object",
    "properties": {"pares": {"type": "array", "items": {
        "type": "object",
        "properties": {"pergunta": {"type": "string"}, "resposta": {"type": "string"}},
        "required": ["pergunta", "resposta"],
    }}},
    "required": ["pares"],
}


def tarefaAula() -> None:
    sistema = (f"Você escreve dados de treino para a Atlas. {ATLAS}\n\n{REGRAS}\n\n"
               + exemplos(dataset.AULA, quantos=14))
    trabalhos = []
    for area, subtemas in AREAS.items():
        for subtema in subtemas:
            for e, enfoque in enumerate(ENFOQUES):
                pedido = (f"Área: {area}. Subtema: {subtema}. Enfoque: {enfoque}.\n"
                          "Escreva dez pares de pergunta e resposta novos, diferentes entre si e dos exemplos.")
                trabalhos.append((f"{area}|{subtema}|{e}", lambda p=pedido, a=area, s=subtema: {
                    "area": a, "subtema": s, **chamar(sistema, p, ESQUEMA_PARES)}))
    rodar("aula.jsonl", trabalhos)


def tarefaPapo() -> None:
    sistema = (f"Você escreve dados de treino para a Atlas. {ATLAS}\n\n{ESTILO_PAPO}\n\n{REGRAS}\n\n"
               + exemplos(dataset.HUMOR, dataset.CONVERSA, dataset.IDENTIDADE, quantos=16))
    trabalhos = []
    for tema in PAPOS:
        for rodada in range(3):
            pedido = (f"Tema da conversa: {tema}.\nEscreva oito pares de pergunta ou comentário de uma "
                      "pessoa e a resposta da Atlas, diferentes entre si e dos que você escreveria primeiro.")
            trabalhos.append((f"{tema}|{rodada}", lambda p=pedido, t=tema: {
                "tema": t, **chamar(sistema, p, ESQUEMA_PARES, temperatura=0.9)}))
    rodar("papo.jsonl", trabalhos)


FONTES = Path(__file__).resolve().parent / "fontes"


def tarefaWeb() -> None:
    """Perguntas reais de datasets abertos (fontes/perguntas-web.txt, de
    baixar-perguntas.py), respondidas no jeito da Atlas. É o que ensina a
    entender o pedido dito de mil jeitos, e não só os temas que o professor
    inventa. Pergunta que não dá para responder falando em duas frases vira
    uma resposta curta e honesta, ou é descartada pelo julgamento."""
    sistema = (f"Você escreve dados de treino para a Atlas. {ATLAS}\n\n{REGRAS}\n\n"
               + exemplos(dataset.AULA, dataset.CONVERSA, quantos=14))
    arquivo = FONTES / "perguntas-web.txt"
    if not arquivo.exists():
        print("web: sem fontes/perguntas-web.txt (rode baixar-perguntas.py)", file=sys.stderr)
        return
    perguntas = [linha.strip() for linha in arquivo.read_text(encoding="utf-8").splitlines() if linha.strip()]
    trabalhos = []
    for inicio in range(0, len(perguntas), 10):
        lote = perguntas[inicio:inicio + 10]
        pedido = ("Para cada pergunta abaixo, escreva a pergunta como uma pessoa diria em voz alta para o "
                  "robô (português do Brasil, curta, sem pontuação de texto) e a resposta da Atlas. Mantenha "
                  "o sentido do que foi pedido. Se a pergunta pedir algo que não cabe em duas frases faladas, "
                  "responda o essencial ou diga com honestidade que é longo demais para explicar falando.\n\n"
                  + "\n".join(f"- {q}" for q in lote))
        chave = hashlib.sha1("\n".join(lote).encode()).hexdigest()[:16]
        trabalhos.append((chave, lambda p=pedido: chamar(sistema, p, ESQUEMA_PARES, temperatura=0.6)))
    rodar("web.jsonl", trabalhos)


ESQUEMA_CONVERSA = {
    "type": "object",
    "properties": {"conversas": {"type": "array", "items": {
        "type": "object",
        "properties": {"turnos": ESQUEMA_PARES["properties"]["pares"]},
        "required": ["turnos"],
    }}},
    "required": ["conversas"],
}


def tarefaSeguida() -> None:
    sistema = (f"Você escreve dados de treino para a Atlas. {ATLAS}\n\n{ESTILO_PAPO}\n\n{REGRAS}\n\n"
               + exemplos(dataset.AULA, dataset.HUMOR) + "\n\n"
               "Cada conversa tem duas ou três trocas, e a partir da segunda a pergunta só faz sentido "
               "com a anterior: 'me dá um exemplo', 'e pra que serve isso', 'explica mais simples', "
               "'e qual a diferença pro outro', 'por quê', 'quero sim', 'e você'. A resposta usa o "
               "contexto sem repetir a anterior.")
    temas = [f"{area}: {s}" for area, subtemas in AREAS.items() for s in subtemas[::2]] + PAPOS[::2]
    trabalhos = [(tema, lambda t=tema: {"tema": t, **chamar(
        sistema, f"Tema: {t}.\nEscreva três conversas diferentes.", ESQUEMA_CONVERSA)}) for tema in temas]
    rodar("seguida.jsonl", trabalhos)


ESQUEMA_VARIANTES = {
    "type": "object",
    "properties": {"variantes": {"type": "array", "items": {"type": "string"}}},
    "required": ["variantes"],
}


def tarefaParafrase() -> None:
    sistema = (
        "Você ajuda a treinar um robô de voz que ouve pelo reconhecimento de voz Vosk, em português do "
        "Brasil. Reescreva a pergunta do jeito que pessoas diferentes falariam e o Vosk transcreveria: "
        "tudo em minúsculas, sem pontuação, às vezes sem acento, coloquial (pra, tá, cê, né, tipo, aí), "
        "algumas mais curtas, algumas mais longas, algumas começando com 'atlas', 'ô atlas' ou 'ei', e "
        "uma ou outra com uma palavra trocada por outra de som parecido, como o reconhecimento erra. "
        "O sentido tem de continuar o mesmo, para a mesma resposta servir. Nada de algarismos."
    )
    trabalhos = []
    for pergunta, resposta in dataset.perguntasEscritas():
        pedido = f"Pergunta: {pergunta}\nResposta que ela vai receber: {resposta}\nEscreva dez variantes."
        trabalhos.append((pergunta, lambda p=pedido, q=pergunta: {
            "pergunta": q, **chamar(sistema, p, ESQUEMA_VARIANTES, temperatura=0.9)}))
    rodar("parafrase.jsonl", trabalhos)


ESQUEMA_NOTAS = {
    "type": "object",
    "properties": {"notas": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "nota": {"type": "integer"}, "problema": {"type": "string"}},
        "required": ["id", "nota", "problema"],
    }}},
    "required": ["notas"],
}


def idDoPar(pergunta: str, resposta: str) -> str:
    return hashlib.sha1(f"{pergunta}\n{resposta}".encode()).hexdigest()[:16]


def paresGerados() -> list[tuple[str, str]]:
    """Todos os pares de aula, papo e seguida que passam no filtro, sem repetição."""
    pares = []
    for nome in ("aula.jsonl", "papo.jsonl", "web.jsonl"):
        for linha in lerLinhas(nome):
            pares += [(p["pergunta"], p["resposta"]) for p in linha.get("pares", [])]
    for linha in lerLinhas("seguida.jsonl"):
        for conversa in linha.get("conversas", []):
            pares += [(t["pergunta"], t["resposta"]) for t in conversa.get("turnos", [])]
    vistos, saida = set(), []
    for pergunta, resposta in pares:
        if perguntaLimpa(pergunta) and limpo(resposta) and (pergunta, resposta) not in vistos:
            vistos.add((pergunta, resposta))
            saida.append((pergunta, resposta))
    return saida


def tarefaJulgar() -> None:
    sistema = (
        f"Você é um professor exigente revisando respostas de um robô de voz. {ATLAS}\n"
        "Dê uma nota de um a cinco para cada par:\n"
        "cinco: correta, clara, natural em português do Brasil e responde exatamente à pergunta;\n"
        "quatro: correta e boa, com um detalhe a melhorar;\n"
        "três ou menos: qualquer erro de conteúdo, fato inventado (datas, nomes, números, história), "
        "frase estranha, comparação forçada ou que não ajuda a entender, português de Portugal, não responde à pergunta, ou a Atlas promete fazer algo "
        "que um robô que só fala não consegue (tocar, cantar, dançar, simular, ensinar a tocar).\n"
        "dois ou menos: piada ou comparação que não faz sentido quando lida em voz alta, ou que se "
        "contradiz (diz que não ouve música e depois que ouve).\n"
        "Seja rígido: só dê quatro ou cinco se um professor de verdade aprovaria a resposta como está. "
        "Na dúvida sobre a correção, dê três."
    )
    pares = paresGerados()
    julgados = {linha["chave"] for linha in lerLinhas("julgar.jsonl")}
    pendentes = [(p, r) for p, r in pares if idDoPar(p, r) not in julgados]
    print(f"julgar: {len(julgados)} feitos, {len(pendentes)} pendentes", file=sys.stderr)

    def julgarLote(inicio: int) -> None:
        lote = pendentes[inicio:inicio + 12]
        texto = "\n".join(f"{i}. Pergunta: {p}\n   Resposta: {r}" for i, (p, r) in enumerate(lote))
        try:
            notas = chamar(sistema, texto, ESQUEMA_NOTAS, temperatura=0.1)["notas"]
        except Exception as erro:  # o lote volta na próxima rodada
            print(f"  lote {inicio}: {erro}", file=sys.stderr)
            return
        # Par sem nota fica para a próxima rodada: grava só os que voltaram.
        for n in notas:
            if 0 <= n["id"] < len(lote):
                gravar("julgar.jsonl", {"chave": idDoPar(*lote[n["id"]]), "nota": n["nota"],
                                        "problema": n["problema"]})
        if inicio % 240 == 0:
            print(f"  {inicio}/{len(pendentes)}", file=sys.stderr)

    # Em paralelo, como `rodar`: o Ollama decodifica os lotes no mesmo passo da GPU.
    with ThreadPoolExecutor(int(os.environ.get("PARALELO", "2"))) as fila:
        list(fila.map(julgarLote, range(0, len(pendentes), 12)))


def aprovados() -> dict[str, int]:
    """id do par -> nota, só os de nota quatro ou cinco."""
    return {linha["chave"]: linha["nota"] for linha in lerLinhas("julgar.jsonl") if linha.get("nota", 0) >= 4}


TAREFAS = {"aula": tarefaAula, "papo": tarefaPapo, "seguida": tarefaSeguida, "web": tarefaWeb,
           "parafrase": tarefaParafrase, "julgar": tarefaJulgar, "descarregar": descarregar}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TAREFAS:
        sys.exit(__doc__)
    TAREFAS[sys.argv[1]]()
