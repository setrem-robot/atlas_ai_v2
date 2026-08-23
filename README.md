# RobotEye

> A face animada da **Atlas** — o robô do curso de Engenharia de Computação da
> Setrem. Dois olhos, uma voz, e uma IA que roda na sua rede.

Você digita, ela responde falando. Os olhos reagem ao que está acontecendo —
olham para cima enquanto ela pensa, pulsam junto com a voz enquanto ela fala. A
síntese pode ser local com [Piper](https://github.com/rhasspy/piper), o que
derruba a latência da fala para cerca de **100 ms**, ou pela rede, com as vozes
em português que soam mais naturais.

```
você> quem é você?

  …pensando
Atlas> Sou a Atlas, um robô construído aqui na Setrem. Ainda estou aprendendo.
```

---

## Índice

- [Como funciona](#como-funciona)
- [Instalação](#instalação)
- [Uso](#uso)
- [Configuração](#configuração)
- [Arquitetura](#arquitetura)
- [Raspberry Pi](#raspberry-pi)
- [Desenvolvimento](#desenvolvimento)
- [Solução de problemas](#solução-de-problemas)
- [Créditos](#créditos)

---

## Como funciona

```
   texto digitado
         │
         ▼
   ┌───────────┐   frases prontas   ┌──────────┐   PCM    ┌─────────────┐
   │ Assistant │ ─────────────────► │ Speaker  │ ───────► │ alto-falante│
   └───────────┘                    └──────────┘          └─────────────┘
         │                            │      │
         │ streaming de tokens        │      │ amplitude do áudio
         ▼                     eventos│      ▼
   ┌───────────┐                      │  ┌──────────┐
   │  Ollama   │                      └─►│   Face   │  (olhos animados)
   └───────────┘                         └──────────┘
```

O truque para a resposta parecer rápida está no **streaming em duas pontas**:
o texto do modelo é cortado em frases assim que cada uma fecha, e a primeira já
vai para a síntese enquanto o modelo ainda escreve o resto. O Piper, por sua vez,
devolve o áudio em blocos, então o alto-falante começa a tocar antes de a frase
inteira ter sido sintetizada.

Cortar em frases tem um custo, e ele aparece na segunda: cada síntese paga o
custo fixo do motor — que num motor de rede é uma ida e volta inteira — e esse
custo vira silêncio no meio da fala. Medido com a voz online, o buraco entre a
primeira e a segunda frase passava de um segundo.

Por isso o locutor **junta o que já chegou**: ao pegar uma frase da fila, leva
junto as que já estiverem esperando ali. Se o modelo ainda não escreveu a
próxima, a primeira sai sozinha e a fala começa na hora, como antes; se já
escreveu, as duas viram uma síntese só. Nas mesmas duas frases, o tempo até ter
todo o áudio caiu de 2,26 s para 1,53 s, e o silêncio no meio sumiu.

Juntar também soa melhor, e não só mais rápido: um motor que recebe as duas
frases de uma vez entoa a passagem de uma para a outra como quem fala, com a
pausa no lugar. Recebendo uma de cada vez, ele produz duas leituras separadas —
e dá para ouvir a emenda.

Medido neste projeto, do enter até o primeiro som sair do alto-falante:

| Configuração | Começa a falar em |
|---|---|
| `llama3.2:1b` em CPU (outra máquina) + Piper | 2,21 s |
| `qwen3:8b` em RTX 4060 + Piper | **0,83 s** |
| `qwen3:8b` em RTX 4060 + Kokoro (24 kHz) | 3,44 s |

O motor de voz pesa mais que o modelo de linguagem nessa conta: o Piper sintetiza
a ~0,05× do tempo real, o Kokoro a ~0,25×. Trocar de voz troca esse número — veja
[Trocando de voz](#trocando-de-voz).

Entre a síntese e a placa de som o áudio ainda passa por um acabamento, que é o
que separa uma fala de uma sequência de arquivos tocados em seguida:

- **rampas de poucos milissegundos nas pontas.** Uma forma de onda que começa
  longe de zero entrega um degrau ao alto-falante, e um degrau é um clique;
- **um respiro no fim de cada frase.** Como cada uma vai para a placa assim que
  fica pronta, a seguinte começaria no exato sample em que a anterior acabou;
- **um limitador**, para que ajustar o ganho não faça o sinal dar a volta.

A mesma amplitude que sai daí alimenta a face: o olho pulsa junto com a voz, não
num ritmo próprio. Veja [A face](#a-face).

---

## Instalação

Requisitos: **Python 3.10+**. A IA em si é o [Ollama](https://ollama.com), que
roda nesta máquina ou em qualquer outra da rede — e dá para começar sem ela.

### Um script, e está pronto

```bash
git clone https://github.com/setrem-robot/IAv2.git
cd IAv2
```

**Linux / Raspberry Pi**

```bash
./scripts/setup-raspberry-pi.sh
```

**Windows** (PowerShell)

```powershell
.\scripts\setup.ps1
```

O script instala as dependências, cria o ambiente virtual e chama o assistente
de configuração — que é onde você escolhe **onde roda a IA, qual modelo e qual
voz**. No fim ele roda o diagnóstico e diz o que ficou faltando.

### Passo a passo, se preferir fazer à mão

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[tts,online]"   # o projeto + as vozes local e de nuvem
roboteye setup                   # onde roda a IA, qual modelo, qual voz
```

### O assistente de configuração

`roboteye setup` faz três perguntas e grava as respostas no `.env` — sem apagar
os comentários que explicam cada chave.

```
[1/3] Onde roda a IA?

  * 1) local        nesta maquina (http://localhost:11434)
    2) rede         noutra maquina da rede (informar o endereco)
    3) nenhuma      sem IA por enquanto — modo `echo`, so para testar a voz

onde [local]: 2
endereco (IP:PORTA) [http://localhost:11434]: 192.168.1.50
      testando http://192.168.1.50:11434 ...
      ok: respondeu em 42 ms, 3 modelos instalados

[2/3] Qual modelo?
      Estes ja estao na maquina da IA:

    1) gemma3:4b     instalado
  * 2) llama3.2:1b   instalado
    3) qwen3:8b      instalado
```

Três detalhes valem a explicação:

- **O endereço é testado antes de ser gravado.** Ele vem por VPN e muda de
  lugar; um IP errado só daria sinal na primeira conversa, longe de quem o
  digitou. Falhando, dá para corrigir ali mesmo, sem sair do assistente.
- **A lista de modelos vem do próprio Ollama que respondeu** — não há como
  escolher um modelo que a máquina não tem. Se ela não tiver nenhum, o
  assistente sugere alguns e oferece baixar com `ollama pull`.
- **A voz escolhida já sai com os arquivos no disco**, inclusive a reserva
  offline de uma voz de nuvem: é ela que precisa estar lá *antes* de a internet
  cair, e não depois.

Nada de interativo é obrigatório — tudo cabe em flags, que é como o script do
Raspberry Pi o chama:

```bash
roboteye setup --ollama 192.168.1.50 --model qwen3:8b --voice dora --non-interactive
roboteye setup --no-llm            # só a face e a voz, sem modelo de linguagem
```

### Conferindo

```bash
roboteye doctor
```

```
Diagnostico do RobotEye
============================================================
[ ok ] Python                 3.12.10 (Windows AMD64)
[ ok ] pygame                 versao 2.6.1
[ ok ] piper-tts              instalado
[ ok ] modelo de voz          dii.onnx (61 MB)
[ ok ] saida de audio         Fones de ouvido
[ ok ] LLM                    llama3.2:1b em http://192.168.1.150:11434
============================================================
Tudo pronto.
```

Para ver o que a máquina da IA tem instalado, sem entrar nela por SSH:

```bash
roboteye models
ollama pull llama3.2:1b          # na máquina da IA, se faltar algum
```

---

## Uso

```bash
roboteye                       # face animada + chat de texto (padrão)
roboteye run --fullscreen      # tela cheia, para o robô de verdade
roboteye chat                  # só o terminal, sem janela
roboteye face                  # só os olhos, sem conversa
roboteye say "Oi, tudo bem?"   # testa a voz e sai
roboteye setup                 # escolhe IA, modelo e voz (grava no .env)
roboteye models                # o que a máquina da IA tem instalado
roboteye doctor                # diagnóstico do ambiente
roboteye preview               # salva um PNG com todas as expressões
roboteye web                   # página de configuração, para abrir do celular
roboteye voice ensure          # baixa o que a configuração atual precisa
```

**No chat:**

| Comando | O que faz |
|---|---|
| `/ajuda` | lista os comandos |
| `/limpar` | esquece o histórico da conversa |
| `/parar` | interrompe a fala atual |
| `/lembrar <fato>` | **ensina algo** que ela guarda para sempre |
| `/esquecer <trecho>` | apaga os fatos que contenham o trecho |
| `/memoria` | lista tudo que ela aprendeu |
| `/recarregar` | relê o arquivo de persona do disco |
| `/sair` | encerra |

**Na janela da face:**

| Tecla | O que faz |
|---|---|
| `ESC` / `Q` | sair |
| `S` | dormir / acordar |
| `ESPAÇO` | piscar |
| `H` | mostra ou esconde a ajuda (e o contador de FPS junto dela) |

Mandar uma mensagem nova enquanto ela fala **interrompe a fala anterior** — quem
fala por último é você.

---

## Configuração

Tudo é configurado por variáveis de ambiente, lidas de um arquivo `.env` na raiz
do projeto (veja [`.env.example`](.env.example) para a lista completa). Há três
formas de mexer nele, e todas preservam os comentários do arquivo:
`roboteye setup` (o assistente), a página do celular (`roboteye web`) ou o
editor de texto.

| Variável | Padrão | Para quê |
|---|---|---|
| `ROBOTEYE_OLLAMA_HOST` | `http://localhost:11434` | Endereço do Ollama |
| `ROBOTEYE_LLM_MODEL` | `llama3.2:1b` | Modelo de linguagem |
| `ROBOTEYE_LLM_BACKEND` | `ollama` | `ollama` ou `echo` (respostas prontas, sem LLM) |
| `ROBOTEYE_REPLY_LANGUAGE` | *(o da voz)* | Força um idioma de resposta |
| `ROBOTEYE_TTS_BACKEND` | `auto` | Motor: `auto` (a voz decide), `piper`, `kokoro`, `edge`, `null` |
| `ROBOTEYE_LLM_MAX_TOKENS` | `120` | Teto de tokens por resposta |
| `ROBOTEYE_VOICE` | `francisca` | **Voz do catálogo** — é assim que se troca de voz |
| `ROBOTEYE_VOICE_FALLBACK` | `auto` | Reserva offline: `auto`, `off` ou o nome de uma voz |
| `ROBOTEYE_VOICE_MODEL` | — | Caminho para um modelo fora do catálogo |
| `ROBOTEYE_VOICE_LENGTH_SCALE` | `1.0` | Velocidade da fala (menor = mais rápido) |
| `ROBOTEYE_VOICE_GAIN` | `1.0` | Volume — as vozes não saem no mesmo nível |
| `ROBOTEYE_FACE_FULLSCREEN` | `false` | Tela cheia |
| `ROBOTEYE_EYE_COLOR` | `#04C9FD` | Cor dos olhos |
| `ROBOTEYE_EYE_CORNER_RADIUS` | `0.30` | Cantos: `0.5` = círculo, `0.1` = quase reto |
| `ROBOTEYE_FACE_QUALITY` | `auto` | Esforço do desenho: `auto`, `low`, `medium`, `high` |
| `ROBOTEYE_WEB_ENABLED` | `true` | Página de configuração pelo navegador |
| `ROBOTEYE_WEB_PORT` | `8080` | Porta da página |
| `ROBOTEYE_WEB_PIN` | *(sorteado)* | PIN de acesso; fixe um numa instalação real |

### Trocando de voz

```bash
roboteye voice list                 # o que existe, e o que já está baixado
roboteye voice download dii         # baixa a voz (~60 MB)
roboteye say --voice dii "olá!"     # experimenta sem mexer em nada
```

Gostou? Fixe no `.env`:

```bash
ROBOTEYE_VOICE=dii
```

São três motores, com trocas diferentes. **Piper**: um arquivo por voz, leve e
rapidíssimo — é o que roda confortável num Raspberry Pi. **Kokoro**: um único
modelo de 325 MB com dezenas de vozes, 24 kHz e qualidade audivelmente superior,
ao custo de ~5× mais CPU e ~6 s de carregamento no arranque. **Edge**: vozes
neurais da Microsoft pela rede — não baixa modelo nem gasta CPU, mas precisa de
internet.

| Nome | Motor | Voz | Idioma | Licença |
|---|---|---|---|---|
| `dii` | piper | Dii — feminina | **pt-BR** | Não declarada pelo autor |
| `faber` | piper | Faber — masculina | pt-BR | CC0 |
| `lessac` | piper | Lessac — feminina | inglês | MIT |
| `dora` | kokoro | Dora — feminina | **pt-BR** | Apache 2.0 |
| `alex` | kokoro | Alex — masculina | pt-BR | Apache 2.0 |
| `heart` | kokoro | Heart — feminina | inglês | Apache 2.0 |
| `thalita` | edge | Thalita — feminina | **pt-BR** | Serviço da Microsoft |
| `francisca` | edge | Francisca — feminina | **pt-BR** | Serviço da Microsoft |

Você não escolhe o motor: cada voz já sabe no qual roda. As vozes Kokoro
compartilham os mesmos arquivos, então baixar a segunda não baixa nada de novo.
O motor Kokoro exige `pip install -e ".[kokoro]"`; o Edge, `pip install -e ".[online]"`.

#### Qual voz feminina em português escolher

As opções em pt-BR são poucas, e vale saber o que cada uma custa:

| | Soa como | Precisa de | Ressalva |
|---|---|---|---|
| **`thalita`** | O mais natural que existe hoje — entonação de frase de verdade | Internet | Chega em MP3 de 48 kbps, então o sinal vem comprimido |
| **`dora`** | Boa prosódia, 24 kHz | ~325 MB e CPU | Pesa num Raspberry Pi |
| **`dii`** | Clara, mas plana | ~60 MB | Licença não declarada pelo autor |

No catálogo oficial do Piper **não há voz feminina em pt-BR** — `cadu`, `edresson`,
`faber` e `jeff` são todas masculinas. Por isso `dii` é comunitária.

Escolher uma voz online **não** deixa o robô refém da internet: ela ganha
automaticamente uma reserva offline no mesmo idioma — `dora` num PC, `dii` num
Raspberry Pi, onde a Kokoro pesaria demais — e a
troca acontece antes de qualquer som sair, então uma queda de rede muda o timbre
em vez de calar o robô. Depois de uma falha a voz online fica um minuto de
molho, para que uma conversa inteira offline não pague o tempo limite da rede a
cada frase. Para desligar, `ROBOTEYE_VOICE_FALLBACK=off`; para fixar outra voz, ponha o nome dela ali.

E a troca **avisa**:

```
  ~ [speech] falando pela voz reserva (kokoro): edge indisponivel
```

Isso não é cosmético. A reserva é do mesmo idioma e do mesmo gênero, então soa
como "a voz configurada, só que errada" — e quem ouve vai procurar o problema no
`.env`, que é o único lugar onde ele não está. O aviso sai uma vez por queda,
não a cada frase, e outro avisa quando a voz preferida volta.

Pela mesma razão, `roboteye doctor` **sintetiza uma palavra de verdade** com a
voz online em vez de só conferir se os pacotes importam:

```
[ ok ] voz online             francisca (pt-BR-FranciscaNeural), falou 83 KB
[ ok ] reserva offline        dora (pronta)
```

Conferir que a biblioteca importa não prova quase nada: o que costuma faltar é a
rede, e é exatamente esse caso que o teste antigo deixava passar por "ok".

> **Números e horas viram texto antes de falar.** Nenhum destes motores lê
> "R$ 25,90" ou "15:30" corretamente — soletram, erram ou pulam. Com uma voz em
> português, o texto passa antes por uma normalização que os reescreve como uma
> pessoa diria: "vinte e cinco reais e noventa centavos", "quinze e trinta".

> **O idioma da resposta acompanha a voz.** Escolher `lessac` faz a Atlas
> responder em inglês sem mais nenhuma configuração — de nada adiantaria uma voz
> inglesa lendo texto em português. Para forçar outra combinação, defina
> `ROBOTEYE_REPLY_LANGUAGE` explicitamente.

> **A voz padrão fala pela rede.** A `francisca` é sintetizada pelo serviço da
> Microsoft, então precisa de internet. Quando ela falta, a reserva offline
> assume sozinha e o robô continua falando — só muda o timbre. Num Raspberry Pi
> a reserva escolhida é sempre uma voz leve.

---

## Arquitetura

O projeto é um pacote Python em `src/`, dividido por responsabilidade. Cada
camada conversa com as outras por **interfaces** (`Protocol`) e por um
**barramento de eventos** — nada importa nada de concreto de outra camada.

```
src/roboteye/
├── app.py            Raiz de composição: o único lugar que monta o sistema
├── cli.py            Interface de linha de comando
├── config.py         Configuração tipada, lida do ambiente
├── diagnostics.py    O comando `doctor`
├── setup_wizard.py   O assistente de primeira configuração
├── voices.py         Catálogo e download dos modelos de voz
│
├── core/             Regras que não dependem de biblioteca externa
│   ├── events.py     Barramento pub/sub e os tipos de evento
│   ├── assistant.py  Orquestra: mensagem → LLM → frases → voz
│   ├── text.py       Limpeza e segmentação de texto em frases
│   ├── normalize_pt.py  "R$ 25,90" → "vinte e cinco reais e noventa centavos"
│   └── numbers_pt.py    Números por extenso, com gênero e o "e" no lugar certo
│
├── llm/              Modelo de linguagem
│   ├── base.py       Protocolo LLMClient
│   ├── ollama.py     Cliente Ollama com streaming
│   ├── probe.py      Sonda a máquina da IA: está de pé? quais modelos tem?
│   ├── echo.py       Cliente falso, para rodar sem LLM
│   ├── memory.py     Histórico com janela deslizante
│   └── persona.py    Personalidade em markdown + regras de saída falada
│
├── speech/           Voz
│   ├── base.py       Protocolo TTSEngine
│   ├── piper_engine.py  TTS local, leve (bom num Raspberry Pi)
│   ├── kokoro_engine.py TTS local 24 kHz, melhor prosódia
│   ├── edge_engine.py   TTS na nuvem, o mais natural em pt-BR
│   ├── fallback.py   Voz online com queda automática para a offline
│   ├── polish.py     Rampas nas pontas, respiro entre frases, limitador
│   ├── envelope.py   Amplitude do áudio tocando, para a face animar junto
│   ├── player.py     Saída de áudio (sounddevice, aplay, mudo)
│   └── speaker.py    Locutor assíncrono com fila, lote e interrupção
│
├── face/             Olhos animados
│   ├── shapes.py     O olho como parâmetros contínuos, e os presets
│   ├── mask.py       O olho como campo de distância — a forma e as bordas
│   ├── easing.py     Curvas de aceleração e tweening
│   ├── animator.py   As camadas de movimento — lógica pura, sem pygame
│   ├── renderer.py   Amostra o campo e põe na tela
│   ├── layout.py     Escala e posições
│   ├── expressions.py Expressões e humores
│   ├── theme.py      Cores
│   ├── preview.py    Folha de contato das expressões
│   └── app.py        Janela e loop principal
│
├── web/              Página de configuração servida pelo robô
│   ├── server.py     Rotas, PIN e o teste de conexão com a IA
│   ├── envfile.py    Edita o `.env` sem apagar seus comentários
│   └── page.py       A página, num arquivo só
│
└── ui/
    └── console.py    Chat de texto no terminal
```

**Três decisões que valem explicação:**

1. **Barramento de eventos.** A face não sabe que existe um LLM; ela só reage a
   `ThinkingStarted`, `SpeechStarted`, `SpeechFinished`. Trocar o chat de texto
   por reconhecimento de voz é acrescentar um publicador, sem tocar em nada mais.

2. **Animação por tempo decorrido (`dt`), não por quadro.** A versão anterior
   media a animação em quadros a 60 FPS; se a máquina engasgava, a animação
   desacelerava junto. Agora o `EyeAnimator` não importa pygame e é testável.

3. **Três threads com papéis claros.** A thread principal desenha (exigência do
   pygame), uma thread lê o teclado, uma thread fala. Nenhuma espera pela outra —
   por isso a face continua a 60 FPS enquanto o modelo pensa.

---

## Quem ela é, e o que ela sabe

A personalidade não está no código. Está em markdown, em `persona/`:

```
persona/atlas.md            quem ela é, como fala, o que lembra de si
persona/atlas.memoria.md    fatos que você ensinou (um por linha)
```

Edite `atlas.md` como quiser — o texto vai direto para o prompt de sistema.
Vêm duas prontas:

| Persona | Quem é |
|---|---|
| `atlas` | Atlas: o robô da Setrem — calorosa, honesta, ainda em construção |
| `iris` | Íris: IA de bordo calorosa, curiosa e direta — sem bajulação |

```bash
roboteye chat --persona iris     # experimenta sem mexer em nada
```

A mesma pergunta, com cada uma:

> **você:** tô meio cansado hoje, foi um dia longo
> **atlas:** Puxa, dia cheio então. Quer só desabafar ou te ajudo com alguma coisa?
> **iris:** Entendo. Precisa de um descanso? Eu posso ficar aqui, se quiser.

Para criar outro personagem, escreva `persona/jarvis.md` e aponte
`ROBOTEYE_PERSONA=jarvis` no `.env` (ou `--persona jarvis`).

> **Dica de português:** diga na persona que ela fala de si no feminino
> ("obrigada", "estou cansada"). Sem isso o modelo escorrega para o masculino —
> as duas personas que vêm prontas já trazem essa linha.

O que **não** fica nesse arquivo são as restrições de saída (responder em prosa
simples, sem markdown, em duas frases). Elas existem porque o texto vira áudio,
não porque combinam com o personagem — deixá-las editáveis só daria chance de
quebrar o TTS sem entender por quê. O prompt final é montado nesta ordem:
identidade, fatos aprendidos, regras de saída.

### Ensinando coisas a ela

Pelo chat, e vale para sempre:

```
você> /lembrar o robô se chama Bifrost e mora em Belo Horizonte
  guardado: o robô se chama Bifrost e mora em Belo Horizonte

você> como você se chama e onde mora?
Atlas> Me chamo Bifrost e moro em Belo Horizonte.
```

Os fatos vão para `persona/<nome>.memoria.md`, que é um arquivo de texto comum —
dá para editar à mão, com um fato por linha. Linhas começadas por `#` são
comentários. Depois de editar à mão, `/recarregar` aplica sem reiniciar o robô.

`/esquecer <trecho>` remove tudo que contenha aquele trecho, e `/memoria` lista
o que ela já sabe.

> A memória é sua e não vai para o Git (está no `.gitignore`, como o `.env`).
> A persona, sim: ela é parte do projeto.

**Sobre o tamanho:** tudo isso entra no prompt de sistema a cada mensagem. Uma
persona de meia página mais algumas dezenas de fatos cabem folgado; centenas de
fatos começariam a comer o contexto e a atrapalhar. Para uma base de
conhecimento grande de verdade, o caminho seria busca por embeddings — que é
bem mais complexidade do que "dar um background" pede.

---

## A face

Um olho aqui não é um desenho escolhido de um catálogo: é um punhado de números.

```python
EyeShape(width, height, radius, offset_x, offset_y,
         top_lid, top_lid_slant, bottom_lid)
```

Uma expressão é um ponto nesse espaço, e **trocar de expressão é caminhar até
outro ponto**. Bravo vira feliz atravessando todos os estados do meio; a piscada
é a pálpebra de cima descendo e voltando. É a mesma abordagem que a Anki usou no
Cozmo e no Vector, e é o que elimina o defeito mais visível da versão anterior,
em que cada expressão era uma função de desenho diferente e a troca era seca.

Uma pálpebra superior inclinada para dentro faz o olho bravo; inclinada para
fora, o cansado; um arco por baixo faz o sorriso.

### Como o olho é desenhado

O olho não é desenhado com primitivas do pygame: é descrito como um **campo de
distância** — para cada ponto, a distância até a borda, negativa dentro e
positiva fora — e a expressão é a combinação de três desses campos (a caixa
arredondada, a pálpebra de cima, a de baixo).

A combinação usa uma interseção *suave*, que arredonda sozinha toda quina que
apareça. É o que resolveu, sem nenhum caso especial, os três defeitos mais
visíveis do desenho anterior, que recortava um retângulo com polígonos:

- o corte reto amputava os cantos arredondados e deixava **pontas agudas** — era
  o que fazia o olho bravo parecer uma fatia de queijo;
- o arco do sorriso não alcançava as quinas e sobrava uma **tira solta** embaixo;
- as diagonais das pálpebras saíam **serrilhadas**, porque a suavização vinha de
  desenhar grande e reduzir, que é justamente onde esse método suaviza menos.

Da distância sai o antialiasing de graça: um pixel a meio caminho da borda fica
com meia opacidade, em qualquer tamanho. E como a forma é uma função, e não uma
grade de pixels, a posição pode ser **fracionária**: a respiração e as
microssacadas deslizam, em vez de andar de pixel em pixel como antes.

Custa em torno de 0,6 ms por quadro numa tela de Raspberry Pi e 2,6 ms em
1280×720. Telas maiores caem num teto de resolução e o resultado é ampliado —
o campo é suave, então ampliar quase não cobra qualidade.

**As camadas de movimento**, da mais lenta para a mais rápida:

| Camada | O que faz |
|---|---|
| Forma de repouso | A expressão atual, alcançada por interpolação (~0,38 s) |
| Respiração | Oscilação de ~1,4% na altura, a 0,19 Hz. Quase invisível — e é o que separa "parado" de "vivo" |
| Olhar | Sacadas: saltos de ~80 ms entre pontos de fixação, com pausas de 1 a 4 s. Olho de verdade não desliza, salta e espera |
| Microssacadas | Tremores de poucos pixels durante a fixação |
| Piscada | A pálpebra de cima desce sobre um olho de altura constante: 110 ms para fechar, 45 ms fechada, 190 ms para abrir. Às vezes vem dobrada |
| Atividade | Pensar e falar sobrepõem seus próprios movimentos |

Três exageros pequenos fazem quase todo o trabalho de dar vida:

- **O olho direito atrasa** alguns quadros em relação ao esquerdo. Sem isso, a
  face parece duas formas idênticas coladas.
- **Curiosidade**: o olho mais próximo da borda para onde ela olha cresce até 16%
  (truque emprestado do RoboEyes).
- **Assimetria ao pensar**: um olho fecha mais que o outro. É a diferença entre
  uma forma geométrica e uma cara de quem está matutando.

**Pensando** — o olhar dá uma caída rápida antes de subir (antecipação), depois
vagueia pela parte alta do campo de visão, com pousos curtos, enquanto os olhos
ficam levemente estreitados e desiguais.

**Falando** — os olhos pulsam ~5,5% em altura, alargando quando achatam
(*squash and stretch*). O ritmo **vem do áudio que está tocando**: o mesmo PCM
que vai para o alto-falante passa antes por um medidor que o reduz a um envelope
de amplitude, e é ele que move o olho. É a diferença entre uma face que se move
*enquanto* fala e uma que se move *junto com* a fala — numa pausa entre frases o
olho descansa, num pico ele abre.

O medidor não vê o alto-falante, só o áudio entrando; como o som toca em tempo
real e sem buracos, basta ancorar o primeiro bloco num instante e deixar o
relógio andar. O único erro sistemático é o atraso do buffer da placa, que é
constante e por isso é descontado de uma vez.

Quando o caminho de áudio não informa amplitude nenhuma — um motor silencioso,
por exemplo — a face cai numa soma de três senoides em frequências
incomensuráveis na faixa silábica (2,7 / 4,3 / 6,1 Hz), que nunca se repete.
É o plano B, não o padrão.

Para ver tudo de uma vez, sem esperar cada expressão aparecer:

```bash
roboteye preview            # gera preview.png com a folha de expressões
```

Quer ajustar a estética? `ROBOTEYE_EYE_CORNER_RADIUS` vai de `0.5` (círculo) a
`0.1` (quase retangular); `ROBOTEYE_FACE_QUALITY` controla halo e degradê (o
antialiasing não depende dele — é analítico e sai igual nos três níveis); e os
tempos e amplitudes de cada camada são constantes nomeadas no topo de
`face/animator.py`.

---

## Raspberry Pi

```bash
git clone https://github.com/setrem-robot/IAv2.git
cd IAv2
./scripts/setup-raspberry-pi.sh --service --ollama 192.168.1.50:11434
```

O script instala as dependências de sistema, cria o ambiente virtual, chama o
[assistente de configuração](#o-assistente-de-configuração), baixa o que a voz
escolhida precisa e instala um serviço systemd para o robô subir sozinho no boot.

Tudo o que o assistente perguntaria também cabe em flags, para instalar sem
ninguém na frente do teclado:

| Flag | Para quê |
|---|---|
| `--ollama IP:PORTA` | endereço da máquina com a IA |
| `--model NOME` | modelo de linguagem (`qwen3:8b`, `llama3.2:3b`, …) |
| `--voice NOME` | voz do catálogo |
| `--no-llm` | instala sem IA, só face e voz |
| `--service` | instala o serviço systemd (sobe no boot) |
| `--bluetooth` | configura áudio Bluetooth |
| `--yes` | não pergunta nada |

**Sem desktop, e melhor assim.** A imagem Lite não tem X nem Wayland, e a face
não precisa de nenhum dos dois: ela procura um monitor no DRM e desenha direto na
tela do kernel (KMSDRM). Não instale um ambiente gráfico só por causa dela — o
desktop custaria CPU e memória contínuos para não desenhar nada que a face já não
desenhe. Medido num Pi 5 com uma tela de 800x480, a face sozinha custa **17% de um
núcleo e 130 MB**, e o robô sobe em segundos.

Notas de desempenho num Pi:

- O Piper roda confortavelmente num Pi 4/5. Num Pi Zero 2 W espere síntese perto
  do tempo real — aumente `ROBOTEYE_VOICE_LENGTH_SCALE` se picotar.
- **A IA principal não é para rodar no Pi** — aponte `ROBOTEYE_OLLAMA_HOST` para
  um PC da rede. Mas vale ter uma pequena aqui como reserva; veja
  [Quando o Wi-Fi cai](#quando-o-wi-fi-cai).
- A face cai sozinha para **30 FPS em ARM**. Os movimentos desta face são todos
  lentos, medidos em décimos de segundo, e a 30 não se distinguem dos de 60 —
  mas o quadro é gasto contínuo, então o que se economiza é metade de um núcleo,
  o dia inteiro.
- Em telas pequenas, use `ROBOTEYE_FACE_FULLSCREEN=true`; a face se redimensiona
  sozinha para qualquer resolução.
- A reserva offline da voz escolhe sozinha uma voz **leve** em ARM. Cair numa
  voz Kokoro num Pi trocaria "sem internet" por "fala arrastada".
- O Pi 5 não tem saída de fone: o som sai pelo HDMI. Se o monitor só aceitar
  44,1/48 kHz — a maioria — o ALSA precisa converter, porque o Piper sintetiza a
  22050 Hz. Um `/etc/asound.conf` com `type plug` na frente de `hw:0,0` resolve.

### Quando o Wi-Fi cai

Numa apresentação, o robô fica na ponta de um Wi-Fi de faculdade e a IA que
responde bem está noutra máquina. Quando esse caminho some, o robô não precisa
emudecer: `ROBOTEYE_LLM_FALLBACK_HOST` aponta para um Ollama no próprio Pi, com um
modelo pequeno, e ele assume a conversa.

```bash
ROBOTEYE_OLLAMA_HOST=http://192.168.1.50:11434     # a IA boa, noutra máquina
ROBOTEYE_LLM_MODEL=qwen3:8b
ROBOTEYE_LLM_FALLBACK_HOST=http://127.0.0.1:11434  # a reserva, aqui dentro
ROBOTEYE_LLM_FALLBACK_MODEL=gemma3:1b
```

Descobrir que a rede caiu custa um tempo limite inteiro, e pagar isso a cada
pergunta transformaria a queda em segundos de silêncio antes de cada frase. Por
isso quem vigia a máquina de rede é uma thread de fundo (`ROBOTEYE_LLM_PROBE_INTERVAL`,
10 s por padrão): a troca em si é imediata, e a única pergunta que paga o preço da
queda é a que estava no ar quando ela aconteceu. Quando a rede volta, o robô
volta para a IA boa sozinho.

Num modelo rodando em CPU, quase todo o tempo da primeira resposta é **ler a
persona**, não escrever a resposta: num Pi 5, os ~500 tokens dela custam 10 s, e a
geração em si menos de 1 s. Por isso o aquecimento manda a persona junto — o
servidor guarda o prefixo já processado, e o custo é pago no arranque em vez de na
primeira pergunta de quem chegou perto do robô. Medido, com o Wi-Fi cortado no
meio da conversa:

| Primeira pergunta pela reserva local | Tempo até falar |
|---|---|
| aquecendo só a conexão (como era) | 12 s |
| aquecendo com a persona | **1 s** |

Qual modelo cabe no Pi 5, medido com a face rodando junto:

| Modelo | Velocidade | Português |
|---|---|---|
| `gemma3:1b` | **12,7 tokens/s** | acentua certo |
| `llama3.2:1b` | 7,5 tokens/s | troca palavras, come acentos |
| `llama3.2:3b` | 4,9 tokens/s | o melhor dos três, e o mais lento |

O `doctor` mostra as duas IAs em linhas separadas, e uma máquina de rede fora do
ar é **aviso**, não falha — o robô ainda conversa:

```
[aviso] IA de rede             inacessivel em http://192.168.1.50:11434
[ ok ] IA local (reserva)     gemma3:1b em http://127.0.0.1:11434
```

### Configurando pelo celular

Um robô instalado roda de tela cheia, sem teclado e muitas vezes preso atrás de
um monitor. Trocar a voz ou apontar para outra máquina de IA por SSH é
inviável na prática, então o robô serve a própria página de configuração:

```
Configuracao pelo navegador:
  http://192.168.1.108:8080
  PIN: 678613
```

Ela sobe junto com o robô (`roboteye run`, `chat` ou `face`) e também pode rodar
sozinha com `roboteye web`. De lá dá para trocar a voz, a personalidade, a cor
dos olhos — e, o que mais importa numa instalação real, **apontar para a máquina
da IA e testar a conexão antes de salvar**:

```
Endereço da máquina com a IA:  [192.168.1.50:11434]  [Testar]
  respondeu em 42 ms — 3 modelo(s)
```

Esse botão existe porque o endereço vem por VPN e muda de lugar. Sem ele,
descobrir que o IP está errado exigiria salvar, reiniciar e esperar o robô
falhar falando. Quando falha, a mensagem diz o que houve em vez de despejar a
exceção: *"conexão recusada — a máquina responde, mas nada escuta nessa porta"*.

Salvar valida antes de gravar: uma configuração inválida é recusada e desfeita,
em vez de só aparecer no próximo arranque, longe de quem a escreveu. E os
comentários do seu `.env` sobrevivem à edição — a página troca o valor da linha,
não reescreve o arquivo.

> **Sobre segurança.** A página mostra e altera endereços da rede interna, faz o
> robô falar e reinicia o serviço; por isso há um PIN, com bloqueio depois de
> cinco erros. Ele impede que alguém que descubra a porta mexa no robô — não
> substitui pôr o robô numa rede separada. Para fechar totalmente, use
> `ROBOTEYE_WEB_HOST=127.0.0.1` ou `ROBOTEYE_WEB_ENABLED=false`.

---

## Desenvolvimento

```bash
pip install -e ".[tts,dev]"

pytest                    # 550 testes, ~10 s
ruff check src tests      # lint
ruff format src tests     # formatação
mypy                      # tipos
```

Os testes não tocam em hardware de áudio, rede nem modelos ONNX: cada fronteira
externa tem um dublê em `tests/conftest.py`. O desenho da face é testado de
verdade, com o driver `dummy` do SDL.

---

## Solução de problemas

**`roboteye doctor` acusa o LLM como inacessível**
O Ollama só aceita conexões locais por padrão. Para expô-lo na rede, no servidor:
`OLLAMA_HOST=0.0.0.0 ollama serve`.

**Não sai som, mas nada dá erro**
Rode `roboteye doctor` e veja a linha `saida de audio`. No Linux, instale o
PortAudio: `sudo apt install libportaudio2`. Se ainda assim falhar, o projeto cai
automaticamente para o `aplay`.

**A voz sai picotada**
A máquina não está sintetizando rápido o bastante. Aumente
`ROBOTEYE_VOICE_LENGTH_SCALE` para `1.1`–`1.2`, ou use um modelo de voz menor.

**As respostas são longas demais**
Modelos pequenos como o `llama3.2:1b` ignoram instruções de tamanho com alguma
frequência. Um modelo de 3B para cima obedece bem melhor ao prompt.

**A janela não abre no Raspberry Pi via SSH**
Não há display. Use `roboteye chat`, ou exporte `DISPLAY=:0` se houver uma sessão
gráfica ativa na tela do Pi.

---

## Créditos

- Estética dos olhos inspirada na biblioteca [RoboEyes](https://github.com/FluxGarage/RoboEyes) (FluxGarage).
- Síntese de voz com [Piper](https://github.com/rhasspy/piper) (Rhasspy).
- Vozes em português do catálogo Piper, Kokoro e Edge — cada uma com a própria
  licença, listada em `roboteye voice list`.

A Atlas é um projeto do curso de Engenharia de Computação da Setrem (Sociedade
Educacional Três de Maio).

Código sob licença [MIT](LICENSE).
