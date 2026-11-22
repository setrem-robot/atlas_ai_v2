# Treino e otimização da Atlas no Raspberry Pi

O que foi feito em 21–22/11/2026 para a Atlas ouvir melhor, responder mais
rápido e caber folgada no Pi 5 — com os números medidos antes e depois, como
refazer cada peça e como conferir que nada regrediu.

A regra que guiou tudo: **o Pi não treina nada.** O PC (RTX 4060, WSL) treina e
constrói; o Pi só recebe o modelo pronto. E nada é dado como otimizado sem a
medida no próprio Pi, com o robô rodando.

Para validar, use o agente [`atlas-validador`](./.claude/agents/atlas-validador.md)
(ver [Validar](#validar)).

---

## O resultado

Medido no Pi 5 do robô (`atlas.local`), com face, escuta e LLM no ar:

| | antes | depois (`producao` 3f938a0) |
|---|---|---|
| RAM do processo `roboteye` | 3249 MiB | **821 MiB** |
| RAM livre do Pi | 3,3 GB | **5,7 GB** |
| Até começar a falar, conversa de 10 perguntas (mediana / pior) | 8,8 s / 10,2 s | **1,7 s / 3,3 s** |
| Escuta: frase inteira certa (banco do Pi, SNR 10) | 25% | **79%** |
| Escuta: WER da fala geral | 11% | **3,5%** |
| Escuta: carga do modelo | 27,6 s | **0,5 s** |
| CPU parado (% de um núcleo: face + escuta) | 50,8% | **43,2%** |

Os arquivos de cada medida ficam no Pi em `~/avaliacoes/`
(`consumo-antes.txt`, `conversa-antes.txt`, `20261122-producao-consumo.txt`,
`20261122-producao-conversa.txt`, `20261122-batch8-conversa.txt`, ...).

**O que ainda está errado:** o `gemma3:1b` mistura fatos — diz que o
coordenador é o Antonio Ternes (o diretor), com os dois fatos certos na memória.
É o que o `atlas-1b` v2 (seção 3) está sendo treinado para corrigir.

---

## 1. Escuta: `vosk-pt-atlas`

### O problema

O `vosk-pt-grande` (FalaBrasil) ocupava 2,6 GB de RAM, levava 27 s para
carregar e errava justo o que se diz à Atlas: "SETREM", nomes de professores,
"Atlas" no começo da frase (25% de frases inteiras certas no banco de testes).

### O que mudou

Mesmo modelo acústico, grafo refeito no PC por
`scripts/escuta-treino/construir-modelo.sh`:

- **léxico** do grande + `palavras-novas.txt` (SETREM, Ropke, Goetz...);
- **LM** em lookahead (sem `HCLG` estático, sem reescore), mistura linear de três:
  o 3-grama geral do FalaBrasil, **legendas pt-BR** do OpenSubtitles
  (`legendas.py`, o texto aberto mais parecido com fala) e as frases ditas à
  Atlas (`corpus.py`).

Os pesos foram escolhidos por varredura no banco de testes (PC, 1960 decodificações):

| modelo | frase certa (todas, limpo) | WER geral | RAM pico |
|---|---|---|---|
| base (grande) | 24,9% | 10,9% | ~2,6 GB |
| `atlas-0.3` (domínio 0,3, sem legendas) | 75,7% | 10,5% | 0,72 GB |
| **`atlas-0.3-leg0.5`** | **82,4%** | **5,4%** | 1,24 GB |
| `atlas-0.5-leg0.5` | 81,2% | 6,3% | 1,21 GB |

No Pi (`avaliar.py` rodando lá, SNR 10): `atlas-0.3-leg0.5` 79,3% de frases,
537 MiB de pico, 67 s para 140 frases (o grande: 2630 MiB, 75 s). É o
`vosk-pt-atlas`.

`voskEars.limparTexto` tira as marcas de ruído (`[unk]`, e o `<UNK>` que o
grande escreve) antes de a frase chegar ao LLM.

### Onde está

- Release **[`vosk-pt-atlas-v1`](https://github.com/setrem-robot/atlas_ai_v2/releases/tag/vosk-pt-atlas-v1)**:
  `vosk-pt-atlas.zip` (o modelo) e `escuta-treino-insumos.tgz` (banco de testes,
  ruído do microfone do Pi, 3-grama do FalaBrasil e `legendas.arpa` — o que é
  caro ou difícil de refazer).
- No Pi: `models/escuta/vosk-pt-atlas`, com `ROBOTEYE_HEARING_VOSK_MODEL=vosk-pt-atlas`.
  O `vosk-pt-grande` continua no cartão como plano de volta.

Instalar do zero: `./scripts/baixar-modelo-escuta.sh --atlas`.

### Refazer

Ambiente no WSL (`~/escuta-treino`), montado à mão; as versões que funcionaram:

| peça | versão / origem |
|---|---|
| `env/` (micromamba, conda-forge) | `kaldi 5.5.1172`, `openfst 1.8.4`, `python 3.12`, + `vosk` e `numpy` por pip |
| `env-ngram/` (micromamba) | `ngram 1.3.17` (OpenGrm) |
| `downloads/kenlm` | github.com/kpu/kenlm, compilado (`build/bin/lmplz`) |
| `downloads/kaldi` | `egs/wsj/s5/{utils,steps}` do github.com/kaldi-asr/kaldi |
| `downloads/kaldi-br`, `lm-br` | github.com/falabrasil |
| `modelos/vosk-pt-grande` | `vosk-model-pt-fb-v0.1.1-20220516_2113` (alphacephei) |
| `downloads/opus/legendas-30M.txt.gz` | OpenSubtitles pt_br do OPUS, 30 M linhas |

```bash
cd ~/escuta-treino && tar xzf escuta-treino-insumos.tgz   # da release
S=<repo>/scripts/escuta-treino
LEGENDAS=0.5 bash $S/construir-modelo.sh 0.3 ~/escuta-treino/construido/vosk-pt-atlas
env/bin/python $S/avaliar.py --modelo construido/vosk-pt-atlas --rotulo atlas \
    --banco banco --ruido ruido/ruido-pi-1.wav --threads 10
env/bin/python $S/avaliar.py --resumo resultados/*.jsonl
```

---

## 2. LLM: a conversa não relê mais o histórico

### O problema

No Ollama do Pi (0.32.15, que roda o `llama-server`), o Gemma 3 usa atenção em
janela, e o servidor só reaproveita o cache a partir de um *checkpoint* salvo.
O log mostrava, em toda pergunta, `forcing full prompt re-processing due to lack
of cache data` e o cache voltando ao fim do system (token 971): o histórico
inteiro era relido a ~25 tokens/s — de 4 a 8 s, crescendo a cada turno.

Dois motivos se somavam:

1. a resposta guardada no histórico (neutralizada, juntada em frases) não é o
   texto que o modelo gerou, então o prefixo divergia logo depois da pergunta
   anterior;
2. a janela do histórico (`LLM_HISTORY=8`) desliza: quando a pergunta nova
   entra, a mensagem mais antiga sai, e o prompt diverge logo depois do system.

### O que mudou

- `Assistant.run`: depois de cada resposta, fora do `busy`, chama
  `llm.warmConversation(memoria.buildNextPrefix())`. O Ollama lê o histórico
  **enquanto a Atlas fala**, e deixa o checkpoint onde a próxima pergunta começa.
- `ConversationMemory.buildNextPrefix()`: o histórico **como ele vai ficar**
  quando a próxima pergunta entrar (já sem a mensagem que a janela vai descartar).
- `LLMClient.warmConversation` (Ollama, Echo, Fallback): só processa o prefixo,
  sem sondar rede nem carregar modelo — o `warmUp` do fallback faz as duas coisas
  e não serve a cada turno.

Medido no Pi, conversa de 10 perguntas (`scripts/medir-conversa.sh`):

| | mediana | pior | tokens lidos por pergunta |
|---|---|---|---|
| antes | 8,8 s | 10,2 s | 109 → 224 |
| reaquecendo com `buildPrompt` | 6,2 s | 7,8 s | 136 → 156 (janela deslizando) |
| **com `buildNextPrefix`** | **2,0 s** | **3,4 s** | **10 a 13** |
| `producao` 3f938a0 (com a face nova) | 1,7 s | 3,3 s | 10 a 13 |

O que sobra é gerar a primeira frase (~10 tokens/s no Pi).

### Afinação medida

- `LLM_NUM_THREAD=2`: gera 12,3 tok/s; 3 threads 11,5; 4 threads 3,7–10 (disputa
  com a face e a escuta). Fica 2.
- `LLM_NUM_BATCH=8`: põe o checkpoint perto do fim de um prompt curto (achado
  com o `atlas-1b` antes do reaquecimento: 7,4 s → 0,5 s). Com a conversa
  aquecida a cada turno não ganha nada (mediana 2,1 s com 8, 1,7 s sem), então
  o robô fica no padrão do Ollama. Medir de novo ao trocar para o `atlas-1b`.
- `LLM_TEMPERATURE=0.4`: erra menos fato que o 0.8 padrão.
- `OLLAMA_MAX_LOADED_MODELS=1` no Pi: trocar de modelo custa ~40 s (carga +
  persona inteira relida). Não rode provas de outro modelo com o robô em uso.

---

## 3. LLM treinado: `atlas-1b`

LoRA sobre o `gemma-3-1b-it`, treinado no PC e instalado no Ollama do Pi como
GGUF q4_K_M (o mesmo tamanho e velocidade do `gemma3:1b`). Troca a persona
longa (~1000 tokens) por pesos que já sabem quem a Atlas é; no prompt ficam só
os fatos e a data (`LLM_PROMPT_CURTO=true`).

- `scripts/treino/professor.py`: o `qwen3:8b` do Ollama do PC gera exemplos de
  aula, conversa, conversas encadeadas e paráfrases "como o Vosk ouve", e depois
  julga cada par (só nota 4 ou 5 entra). Tudo em `scripts/treino/dados/*.jsonl`,
  retomável linha a linha.
- `scripts/treino/dataset.py`: junta os exemplos escritos à mão e os aprovados.
- `scripts/treino/treinar.py`: Unsloth, LoRA rank 32 em todas as camadas, fica
  com o melhor checkpoint pela `eval_loss`.
- `scripts/treino/instalar-no-pi.sh`: quantiza no Ollama do PC e registra no Pi.
- `scripts/treino/avaliar.py`: a prova — perguntas que o treino nunca viu,
  corrigidas sozinhas, com o tempo até o primeiro texto. Aquece com o system de
  cada caso, como o robô (senão mede um reprocessamento que o robô nunca paga).

| modelo (prova no Pi) | certas |
|---|---|
| `gemma3:1b` (persona longa) | 35/68 (51%) |
| `atlas-1b` v1 (587 exemplos à mão) | 52/68 (76%) |
| `atlas-1b` v2 (com o professor) | em treino — ver abaixo |

### Orquestração

`scripts/orquestrar-treinos.sh` roda tudo no WSL, destacado do terminal, e é
retomável do começo ao fim:

```
IA   (GPU): professor (aula ‖ papo -> seguida -> parafrase) -> julgar -> dataset
            -> descarrega o professor -> LoRA -> instala no Pi como atlas-1b-v2
            -> release atlas-1b-v2 no GitHub (GGUF + dados) -> prova no Pi
Vosk (CPU): constrói e avalia cada combinação de pesos; resumo em ~/escuta-treino/resumo.txt
```

O LoRA espera o Vosk acabar (o WSL tem 7 GB de RAM). Andamento em
`scripts/orquestrar-treinos.log`. Relançar depois de reiniciar o PC:

```
powershell Start-Process -WindowStyle Hidden wsl -ArgumentList '-d','Ubuntu','--','bash','<caminho no WSL>/scripts/orquestrar-treinos.sh'
```

**A troca do modelo no robô não é automática.** Com a prova pronta em
`~/avaliacoes/atlas-1b-v2.txt` (e melhor que o `gemma3:1b`), no `.env` do Pi:
`ROBOTEYE_LLM_MODEL=atlas-1b-v2` e `ROBOTEYE_LLM_PROMPT_CURTO=true`; reiniciar e
validar.

---

## Validar

O agente `atlas-validador` (`.claude/agents/atlas-validador.md`) roda a bateria
inteira e compara com as linhas de base desta página. As ferramentas, uma a uma:

| o quê | comando | aprova se |
|---|---|---|
| testes | `pytest -q` | tudo passa (o segfault ocasional em `test_faceApp.py` no Windows é do SDL e já existia) |
| consumo parado | `ssh atlas@atlas.local bash -s 30 < scripts/medir-pi.sh` | `roboteye` ≤ ~1,1 GB; CPU ≤ ~50% de um núcleo; `throttled 0x0` |
| conversa ponta a ponta | `ssh atlas@atlas.local bash -s rotulo < scripts/medir-conversa.sh` | mediana ≤ 2,5 s, pior ≤ 4 s (a Atlas fala em voz alta) |
| cache | `journalctl -u ollama` → `prompt eval time` | pergunta real lê ≤ ~20 tokens |
| escuta | `scripts/escuta-treino/avaliar.py` no Pi, `~/escuta-treino` | frase certa ≥ 77%, RAM ≤ 600 MiB |
| LLM | `scripts/treino/avaliar.py --modelo <m> [--curto]` no Pi | certas ≥ a do modelo em uso |

## Reiniciar o robô

O botão da página falha (`NoNewPrivileges` no serviço bloqueia o `sudo`). Sem
senha de sudo, o caminho é matar o processo e deixar o systemd subir de novo
(`Restart=on-failure`):

```bash
kill -KILL $(systemctl show -p MainPID --value roboteye)
```

## Voltar atrás

- Escuta: `ROBOTEYE_HEARING_VOSK_MODEL=vosk-pt-grande` no `.env`.
- LLM: `ROBOTEYE_LLM_MODEL=gemma3:1b`, `ROBOTEYE_LLM_PROMPT_CURTO=false`.
- Código: o reaquecimento não tem chave; reverter o commit
  "IA: conversa aquecida a cada turno".
