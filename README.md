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

- [O robô hoje](#o-robô-hoje)
- [Como funciona](#como-funciona)
- [Instalação](#instalação)
- [Uso](#uso)
- [Configuração](#configuração)
- [Arquitetura](#arquitetura)
- [Raspberry Pi](#raspberry-pi)
- [Publicando no robô](#publicando-no-robô)
- [Falando com ela](#falando-com-ela)
- [O que falta](#o-que-falta)
- [Desenvolvimento](#desenvolvimento)
- [Solução de problemas](#solução-de-problemas)
- [Créditos](#créditos)

---

## O robô hoje

A Atlas está montada e rodando num **Raspberry Pi 5 de 8 GB**, com Raspberry Pi
OS Lite (Debian 13, sem ambiente gráfico), numa tela de 800x480. Ela liga
sozinha na tomada e não precisa de teclado, mouse nem monitor de serviço.

**O que acontece quando você liga:** em cerca de sete segundos o sistema sobe, o
serviço `roboteye` arranca e os olhos aparecem na tela. Não há desktop no
caminho: a face desenha direto no vídeo do kernel (KMS/DRM). Ao mesmo tempo, a
página de configuração começa a servir na porta 8080 e os modelos de linguagem
são aquecidos em segundo plano, para que a primeira pergunta não seja a mais
lenta.

**Para falar com ela**, abra `http://<ip-do-robo>:8080` no celular, digite o PIN
e use o campo *Conversar*. Ela responde falando, e os olhos acompanham a voz. Não
é preciso parar o robô nem entrar por SSH.

**A inteligência é dupla.** Enquanto houver rede, quem responde é um modelo
grande numa máquina de mesa (`qwen3:8b` numa placa de vídeo, ~1 s até começar a
falar). Se essa máquina sumir — Wi-Fi caiu, PC desligou —, um modelo pequeno no
próprio Pi (`gemma3:1b`) assume a conversa sem que ela pare. Quando a rede volta,
o robô volta ao modelo grande sozinho. Veja [Quando o Wi-Fi cai](#quando-o-wi-fi-cai).

**A voz também tem reserva.** A voz padrão é online (Microsoft Edge, a mais
natural em português do Brasil); sem internet, uma voz local em Piper assume, e
ficar offline vira uma troca de timbre em vez de silêncio.

O que isso custa, medido no próprio Pi 5:

| | |
|---|---|
| Arranque até a face na tela | **6,9 s** |
| CPU da face (contínuo, 30 FPS, 800x480) | **17–21% de um núcleo** |
| Memória da face | 130–145 MB |
| Custo de um quadro | 3,4 ms mediana / 3,9 ms p95 |
| Resposta pela IA de rede (modelo quente) | **1–3 s** |
| Resposta pela IA local, depois do aquecimento | ~1 s |
| Temperatura em repouso / sob carga de IA | 50 °C / **78,5 °C** |

O número que merece atenção é o último: **não há ventoinha**, e trinta segundos
de modelo local levam o Pi de 56 °C a quase 80 °C. Conversas longas pela IA local
vão reduzir a frequência do processador. Um cooler oficial resolve.

### O que ainda não está ligado

Este repositório é só a **cabeça** do robô — face, voz e conversa. O corpo
(motores, GPS, Wi-Fi) vive em [`orquestrador`](https://github.com/setrem-robot/orquestrador),
e o controle no celular em [`aplicativo`](https://github.com/setrem-robot/aplicativo).
As três partes compartilham a marca "Atlas" e **nada mais**: este repositório não
fala MQTT, serial nem GPIO. Veja [O que falta](#o-que-falta).

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

> **Se a tela ficar preta com o robô rodando**, o mais provável é faltar
> `libGL.so.1` — instale `libgl1 libopengl0 libglx-mesa0` (o
> `setup-raspberry-pi.sh` já faz). Sem ela o SDL não avisa nada: cria os
> framebuffers, aceita todo `flip` e não desenha. O sintoma que denuncia é a taxa
> de quadros — se um teste marcar 2000 quadros/s numa tela de 60 Hz, o SDL está
> desenhando para lugar nenhum. O erro real só aparece com
> `SDL_LOGGING="video=verbose"`.

### Do cartão em branco ao robô ligando sozinho

O caminho completo, na ordem, para um Pi 5 com Raspberry Pi OS **Lite** (sem
ambiente gráfico). Foi assim que o robô de produção foi montado.

**1. Grave o cartão e ligue o Pi.** Use o Raspberry Pi Imager, ative SSH e
defina o usuário nas configurações avançadas dele.

**2. Confira se o cartão inteiro está sendo usado.**

```bash
df -h /
```

Se a raiz tiver poucos gigabytes num cartão grande, o sistema não expandiu a
partição — e você vai bater no limite antes de instalar qualquer coisa. Veja
[o cartão de 32 GB que tinha 2](#o-sistema-diz-que-está-sem-espaço-num-cartão-grande)
para o conserto.

**3. Instale o robô.**

```bash
git clone https://github.com/setrem-robot/atlas_ai_v2.git
cd atlas_ai_v2
./scripts/setup-raspberry-pi.sh --service --ollama 192.168.1.50:11434
```

O script instala as dependências de sistema, cria o ambiente virtual, chama o
[assistente de configuração](#o-assistente-de-configuração), baixa o que a voz
escolhida precisa e instala o serviço systemd. **Reinicie depois**: a instalação
adiciona o usuário aos grupos `video`, `render` e `input`, e isso só passa a
valer numa sessão nova.

**4. Diga por onde sai o som.** O `setup` já faz isso, mas se você plugou a
caixinha depois:

```bash
sudo ./scripts/configurar-audio.sh
```

Ele encontra a placa (preferindo uma **USB** sobre o HDMI), aponta o sistema para
ela, sobe o volume e o ganho do microfone, e guarda os níveis para o próximo
arranque. `--mostrar` lista o que existe sem mudar nada; `--card N` força uma
placa; `--hdmi` insiste no HDMI.

Três coisas que ele resolve e que custam horas quando feitas à mão:

- **no Pi 5 não há saída de fone**, e o padrão é o HDMI — que só toca se a tela
  tiver alto-falante (a telinha de 5" costuma não ter);
- **placas USB baratas chegam com o volume em ~30% e o microfone em zero**, o que
  faz o robô parecer mudo e surdo mesmo com tudo instalado corretamente;
- **elas quase sempre recusam 22050 Hz**, que é a taxa do Piper. O `plug` do ALSA
  converte; sem ele, a primeira frase morre com `Invalid sample rate`.

Teste com `speaker-test -D default -c 2 -t sine -f 660 -l 1`, e confira para onde
o som está indo com `roboteye doctor`:

```
[ ok ] saida de audio         default -> Device (hw:2)
```

**5. Se quiser a IA de reserva rodando no próprio Pi:**

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma3:1b
```

E aponte a reserva no `.env` — veja [Quando o Wi-Fi cai](#quando-o-wi-fi-cai).
Vale manter o modelo residente e fazer o Ollama ceder CPU para a face:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Nice=5
EOF
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

`OLLAMA_KEEP_ALIVE=-1` mantém o modelo na memória para sempre. São ~815 MB de uma
máquina com 8 GB, e o que se compra com eles é a queda do Wi-Fi não custar também
o tempo de ler o modelo do cartão SD — que é onde o Pi é mais lento. Sem isso, o
Ollama o descarrega depois de cinco minutos parado, que é exatamente o estado em
que ele vai estar quando for preciso.

**6. Confira e ligue.**

```bash
roboteye doctor
sudo systemctl start roboteye
```

### Deixando o arranque mais leve

Opcionais, todos reversíveis. No robô de produção derrubaram o arranque de
**23 s para 6,9 s**:

```bash
# O cloud-init já fez o trabalho dele (a primeira configuração do cartão);
# daqui para frente são ~10 s de arranque por nada.
sudo touch /etc/cloud/cloud-init.disabled

# Sem caixa Bluetooth (o som sai pelo HDMI): rádio ligado e memória por nada.
sudo systemctl disable --now bluetooth udisks2

# Um robô em apresentação não pode parar para atualizar pacotes sozinho.
sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer
```

Não desabilite o `avahi-daemon`: é ele que faz `nome-do-robo.local` funcionar.

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

E dá para **conversar por ela**. Essa é a única entrada de texto que o robô
instalado tem: o serviço sobe sem terminal, e até aqui falar com a Atlas exigia
parar o robô e rodar `roboteye run` por SSH — ou seja, apagar a face na frente de
quem veio ver o robô funcionar.

```
Conversar
  você  quanto é três mais três?
  atlas Três mais três é seis.
```

A resposta desta chamada é só o aceite: o que ela responde sai pela voz e pela
face — é um robô, não um chat — e aparece na página na leitura seguinte. Como a
página fica olhando, ela mostra também as conversas que não passaram por ela.

Isso é também o que faz o aquecimento valer sempre. `roboteye face` não aquecia o
modelo, porque sem entrada de texto não havia conversa a preparar; agora há,
então a primeira pergunta feita do celular não paga mais os segundos de carregar
o modelo e ler a persona.

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

## Publicando no robô

O robô se atualiza sozinho, e **não** segue o `main`. Ele segue um branch de
publicação, `producao`, e a diferença entre os dois é o que separa "estou
mexendo" de "está no robô":

```bash
git push origin main                # trabalha à vontade, quebra, conserta
git push origin main:producao       # ← só isto chega no robô
```

Publicado, o robô traz a versão nova **no próximo arranque** ou quando alguém
apertar **Atualizar** na página do celular. Não há verificação periódica de
propósito: um robô que se reinicia sozinho no meio de uma apresentação é pior que
um robô desatualizado.

Quem procura o GitHub é o Pi, nunca o contrário — então isso funciona atrás de
qualquer firewall de faculdade, sem porta aberta, sem túnel e sem runner.

**Se a versão nova não subir, ele volta sozinho para a anterior.** Não basta o
systemd dizer `active`: um serviço reiniciando em laço também passa por isso
entre as tentativas, então a prova é a página respondendo, duas vezes com folga.
Falhando, o robô volta ao commit anterior, reinstala o que precisar e reinicia.

Antes de reiniciar, ele pergunta a si mesmo se está no meio de uma resposta e
espera até 45 s — ninguém quer a face sumindo no meio de uma frase.

Para acompanhar:

```bash
journalctl -u roboteye-update -f
```

O `.env`, os modelos de voz e de escuta e o ambiente Python ficam de fora do
processo. Mas atenção: o repositório no robô é um **espelho** do publicado, não um
lugar de trabalho — a atualização descarta qualquer alteração local que você
tenha feito lá.

---

## Falando com ela

Um microfone plugado no robô, e a Atlas passa a ouvir. É opcional e vem
desligado: microfone aberto é decisão de quem monta o robô.

```bash
./scripts/setup-raspberry-pi.sh --escuta      # na instalação
# ou, depois:
pip install -e ".[stt]" && ./scripts/baixar-modelo-escuta.sh
```

O modelo (142 MB) é baixado na instalação, e não na primeira pergunta de alguém —
num robô que pode estar sem rede na hora da apresentação, isso é a diferença
entre ouvir e não ouvir.

Ligue com `ROBOTEYE_HEARING_ENABLED=true` e fale:

```
você:  "Atlas, quantos alunos tem o curso?"
Atlas: (responde falando, e os olhos acompanham a voz)
```

**O nome dela é o gatilho.** Um microfone aberto numa sala escuta a sala inteira:
sem filtro, ela responderia à conversa alheia, ao professor explicando outra
coisa e à própria apresentação sobre ela. Com `ROBOTEYE_WAKE_WORD=atlas` (o
padrão), só as frases que contêm o nome viram pergunta — e o que vem antes do
nome é descartado, porque costuma ser o fim de outra frase. Deixe vazio para ela
responder a tudo que ouvir, o que serve para testar e atrapalha numa sala cheia.

**Ela não se ouve.** O microfone fica a centímetros da caixinha; sem cuidado, ela
transcreveria a própria voz e responderia a si mesma, em laço. A escuta é pausada
enquanto a Atlas fala, usando os eventos de voz que já existiam.

### Qual motor de reconhecimento

Medido no Pi 5, com a mesma frase gravada no mesmo microfone:

| Motor | Velocidade | O que entendeu |
|---|---|---|
| Vosk (modelo pequeno, 52 MB) | rápido | *"quanto os alunos pena"* |
| **Whisper `tiny`** | 0,35× tempo real | *"Atlas, quantos alunos tem o curso de engenharia de computação?"* |
| **Whisper `base`** (padrão) | 0,59× tempo real | igual, com a pontuação certa |

O Whisper ganha por uma margem grande, e o custo cabe no robô: `base` transcreve
4 s de fala em 2,5 s. Por isso ele é o padrão, pelo `faster-whisper` — que tem
pacote pronto para ARM e roda quantizado em `int8`, sem PyTorch.

**Essa diferença importa mais do que parece quando quem fala são crianças**: voz
aguda, dicção variável, frases quebradas. É exatamente onde um modelo pequeno
erra mais — e errar aqui significa a Atlas responder outra coisa.

O Vosk continua disponível (`ROBOTEYE_HEARING_BACKEND=vosk`) para quem precisar
de latência mínima ou de um hardware mais fraco. Um núcleo fica fora da
transcrição de propósito: a face desenha o tempo todo, e uma transcrição que toma
a máquina inteira faz a animação engasgar bem quando alguém espera resposta.

---

## O que falta

Lista honesta do que **não** está pronto, para quem for continuar o projeto. Nada
aqui é bug esquecido — é trabalho que ainda não foi feito.

### A Atlas não fala o que o app manda

O `orquestrador` já publica em `robo/voz/falar` quando alguém pede para o robô
falar pelo celular. **Ninguém consome esse tópico.** Este repositório não fala
MQTT: os dois lados do contrato existem, e os fios nunca foram ligados.

O lugar natural para isso é um assinante MQTT que publique no `EventBus` daqui —
sem que `core/assistant.py` ou a face saibam que MQTT existe, do mesmo jeito que
a página web conversa hoje sem conhecer o `Assistant`. Enquanto isso não existir,
a Atlas só responde a quem digita nela.

### A Atlas não sabe nada sobre o próprio corpo

Ela não recebe telemetria: não sabe o nível da bateria, onde está, se os motores
estão andando. Reagir a isso — mudar de expressão com a bateria baixa, comentar
que está se movendo — é o tipo de coisa que faria o robô parecer vivo, e depende
do mesmo assinante MQTT acima.

### A escuta não tem reserva de rede

A IA e a voz já sabem usar uma máquina da rede quando ela existe e cair para o
local quando não. A escuta não: transcreve sempre no próprio Pi. Um Whisper
`medium` rodando no PC daria transcrição melhor ainda, com o modelo local como
reserva — é a mesma ideia já aplicada duas vezes no projeto, e ainda não feita
aqui.

### O Pi esquenta

Sem ventoinha, a IA local leva o Pi a quase 80 °C em trinta segundos e o
processador começa a reduzir a frequência. Enquanto não houver cooler, prefira a
IA de rede para conversas longas.

### O áudio é exclusivo

Com o serviço rodando, nenhum outro processo consegue abrir a placa de som — nem
`roboteye say`, nem `roboteye doctor`. É preciso parar o serviço para testar a
voz. Resolver de verdade exigiria um servidor de áudio (PipeWire) rodando o dia
todo, o que foi considerado caro demais para o que resolve. Veja
[Solução de problemas](#solução-de-problemas).

### Falta uma segunda voz de licença limpa

A reserva offline em português é a `dii`, cuja licença **não é declarada** pelo
autor. Para uso além da sala de aula, confirme antes — ou troque para a `faber`
(CC0, masculina), única voz Piper em pt-BR do catálogo com licença sem dúvida.

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

A primeira coisa a rodar é sempre o diagnóstico:

```bash
roboteye doctor
```

Ele confere Python, pygame, voz, saída de áudio e **as duas IAs** em linhas
separadas. Uma máquina de rede fora do ar aparece como *aviso*, não falha — o
robô continua conversando pela reserva local.

A maior parte desta seção veio de uma instalação real num Pi 5 com a imagem Lite.
Vários destes problemas **não dão mensagem de erro**: o robô parece funcionar, e
o que falha é exatamente o que você foi ver.

### A tela

#### A tela fica preta, mas tudo indica que está funcionando

O sintoma mais traiçoeiro do projeto. O serviço fica `active`, o log diz
`face iniciada em 800x480`, o kernel mostra o vídeo apontando para a face — e o
monitor não acende. O console aparece normalmente, então o cabo e a tela estão
bons.

Falta a biblioteca **`libGL.so.1`**. O SDL não trata isso como erro: registra a
falha apenas em log de depuração, cria os buffers de vídeo, aceita todo pedido de
desenho — e não desenha nada.

```bash
sudo apt install -y libgl1 libopengl0 libglx-mesa0
```

O que denuncia é a **taxa de quadros**. Se um teste marcar milhares de quadros
por segundo numa tela de 60 Hz, o SDL está desenhando para lugar nenhum:

```bash
# 2143 quadros/s = quebrado.  827 quadros/s = desenhando de verdade.
SDL_LOGGING="video=verbose" python -c "
import os, time, pygame
os.environ['SDL_VIDEODRIVER'] = 'kmsdrm'
pygame.display.init()
tela = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
n, fim = 0, time.monotonic() + 5
while time.monotonic() < fim:
    tela.fill((255, 0, 0)); pygame.display.flip(); n += 1
print(n / 5, 'quadros por segundo')
"
```

Com `SDL_LOGGING` ligado, a linha que importa é
`Could not initialize OpenGL / GLES library`.

#### `pygame.error: kmsdrm not available`

Duas causas, e vale checar nesta ordem.

**Outro processo está com a tela.** Só um cliente pode ser dono do vídeo por vez.
Um teste esquecido rodando, ou o próprio serviço, faz o próximo processo falhar —
e como o serviço tenta reiniciar, ele entra em laço.

```bash
sudo cat /sys/kernel/debug/dri/1/clients   # quem está com a tela
sudo systemctl stop roboteye               # libere antes de testar
```

**O pygame do PyPI não fala KMSDRM.** A roda distribuída no PyPI embute um SDL
compilado sem esse suporte: funciona em qualquer desktop e falha exatamente no Pi
sem desktop. Use o pacote do Debian, que usa o SDL do sistema:

```bash
sudo apt install -y python3-pygame
sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' .venv/pyvenv.cfg
.venv/bin/pip uninstall -y pygame
```

Para conferir de que lado está o problema:

```bash
strings /usr/lib/aarch64-linux-gnu/libSDL2-2.0.so.0 | grep -c KMSDRM   # do sistema: > 0
strings .venv/lib/python*/site-packages/pygame.libs/libSDL2*.so* | grep -c -i kmsdrm  # da roda: 0
```

#### `pygame.error: EGL not initialized`

O KMSDRM desenha por EGL, e a imagem Lite não traz essas bibliotecas:

```bash
sudo apt install -y libegl1 libegl-mesa0 libgles2 libgl1-mesa-dri
```

#### O erro fala do mouse, não do vídeo

`pygame.error: video system not initialized` apontando para
`pygame.mouse.set_visible` significa que a **tela não abriu** — a chamada do
mouse foi só a primeira a reclamar depois. Procure a causa real acima; foi
corrigido para que o traceback aponte para o lugar certo.

#### O serviço reinicia de 5 em 5 segundos, para sempre

Versões antigas do `roboteye.service` esperavam por `graphical.target` e
`DISPLAY=:0`. Num Pi Lite esse alvo nunca chega. Reinstale o serviço com
`./scripts/setup-raspberry-pi.sh --service`.

#### A janela não abre pelo SSH

Se **há** monitor ligado no Pi, a face vai para ele — é o esperado, e o SSH é só
quem deu a partida. Se não há monitor nenhum, use `roboteye chat`.

### O áudio

#### `doctor` diz que não há dispositivo de saída, mas há

Quase sempre é **o próprio robô**. A saída HDMI é exclusiva: com o serviço
tocando, nenhum outro processo abre a placa.

```bash
sudo systemctl stop roboteye
roboteye doctor
```

Um servidor de áudio (PipeWire) permitiria os dois ao mesmo tempo, mas é um
processo rodando o dia todo para resolver um caso que só aparece em teste.
O `dmix` do ALSA seria a alternativa barata — **e não funciona aqui**: o
PortAudio não consegue abri-lo neste hardware, falhando com
`Sample format not supported`.

#### Não sai som, e nada dá erro

Confira a linha `saida de audio` do `doctor`. No Linux, instale o PortAudio:
`sudo apt install libportaudio2`. Se ainda assim falhar, o projeto cai
automaticamente para o `aplay`.

No Pi 5 **não existe saída de fone**: o som sai pelo HDMI, e depende de o monitor
ter alto-falante. Confira o que ele aceita:

```bash
aplay -l                            # quais placas existem
cat /proc/asound/card0/eld#0        # o que o monitor declara aceitar
```

Se ali não aparecer `22050` — e normalmente não aparece —, o ALSA precisa
converter, porque é nessa taxa que o Piper sintetiza. Sem isso a primeira frase
falha. Veja o `/etc/asound.conf` no [guia de instalação](#do-cartão-em-branco-ao-robô-ligando-sozinho).

#### A voz sai picotada

A máquina não está sintetizando rápido o bastante. Aumente
`ROBOTEYE_VOICE_LENGTH_SCALE` para `1.1`–`1.2`, ou use um modelo de voz menor.

#### A voz reserva ficou arrastada, e baixou centenas de megabytes

Você escolheu uma voz **Kokoro** como reserva (`dora`, `alex`, `heart`). Elas
soam melhor, mas sintetizam a ~0,25× do tempo real: num Pi, isso troca "sem
internet" por "fala arrastada", além de 338 MB de modelo.

Deixe `ROBOTEYE_VOICE_FALLBACK` **vazio**: o catálogo escolhe sozinho uma voz
leve em ARM (`dii`, do Piper, 61 MB e oito vezes mais rápida).

### A inteligência

#### `doctor` acusa a IA de rede como inacessível

O Ollama só aceita conexões locais por padrão. Na máquina que roda a IA, exponha
na rede com `OLLAMA_HOST=0.0.0.0`. No Windows, isso é uma variável de ambiente do
usuário **e o Ollama precisa ser reiniciado** para lê-la — confira com
`Get-NetTCPConnection -LocalPort 11434 -State Listen`: se aparecer `127.0.0.1`,
ele ainda está fechado.

Lembre também da regra de firewall. E prefira restringi-la ao IP do robô, em vez
de abrir a porta para a rede inteira.

Enquanto isso não estiver resolvido, o robô continua conversando pela IA local —
o `doctor` marca a de rede como *aviso*, não como falha.

#### A primeira resposta demora 10 a 30 segundos

Normal, e há duas causas diferentes:

- **na IA de rede**, é o modelo subindo na placa de vídeo (~30 s para um modelo
  de 8B). Acontece depois de reiniciar o Ollama ou de horas sem uso;
- **na IA local**, é a persona sendo lida: num Pi, os ~500 tokens dela custam
  10 s, contra menos de 1 s para escrever a resposta.

As duas são pagas no arranque do robô, de propósito. Se você perguntou nos
primeiros segundos, esperou junto. Da segunda pergunta em diante são 1–3 s.

#### As respostas são longas demais

Modelos pequenos como o `llama3.2:1b` ignoram instruções de tamanho com alguma
frequência. Um modelo de 3B para cima obedece bem melhor ao prompt.

#### O robô ficou "menos esperto" de repente

Provavelmente a IA de rede caiu e a reserva local assumiu — ela é bem menor. O
robô avisa no log, e o `doctor` mostra qual das duas está de pé.

### O sistema

#### O sistema diz que está sem espaço num cartão grande

O cartão está inteiro lá; o que não foi expandido é a partição. Num cartão de
32 GB, é comum a raiz ficar com 2 GB e o resto virar uma partição vazia, marcada
com um tipo qualquer, que ninguém usa.

```bash
df -h /                  # raiz pequena?
lsblk                    # e uma partição grande sem ponto de montagem?
```

Antes de mexer, **confirme que a partição sobrando está vazia** — sem sistema de
arquivos, fora do `/etc/fstab` e não montada:

```bash
sudo blkid /dev/mmcblk0p3
sudo dd if=/dev/mmcblk0p3 bs=512 count=1 2>/dev/null | hexdump -C | head -3
cat /etc/fstab
```

Se confirmado, guarde a tabela de partições e expanda a raiz:

```bash
sudo sfdisk -d /dev/mmcblk0 | sudo tee /boot/firmware/particoes-backup.sfdisk
sudo sfdisk --delete /dev/mmcblk0 3
echo ", +" | sudo sfdisk -N 2 --force /dev/mmcblk0
sudo partx -u /dev/mmcblk0
sudo resize2fs /dev/mmcblk0p2
```

Isso mexe na tabela de partições do disco de boot — leia duas vezes antes de
rodar. `raspi-config` não resolve neste caso, porque ele assume que a raiz é a
última partição, e aqui não é.

#### `resize2fs: command not found` (e outros comandos que existem)

Um comando por SSH não interativo não recebe `/usr/sbin` no caminho. Não é que o
programa falte:

```bash
export PATH=/usr/sbin:/sbin:$PATH
```

#### A instalação falha compilando algo

O extra `online` traz o `miniaudio`, que não publica pacote pronto para ARM e
precisa ser compilado. A imagem Lite não tem compilador:

```bash
sudo apt install -y build-essential python3-dev
```

#### `sudo` pede senha no meio de um script

O `sudo` guarda a autorização por alguns minutos e depois esquece. Em scripts
longos ou automação, passe a senha pela entrada padrão (`sudo -S`) ou configure
`NOPASSWD` conscientemente.

#### O robô esquenta e fica lento

Sem ventoinha, o Pi 5 chega a ~80 °C com a IA local e reduz a frequência:

```bash
vcgencmd measure_temp
vcgencmd get_throttled     # 0x0 = nunca limitou
```

Qualquer bit ligado no segundo comando indica que já houve limitação. A solução é
física: instale o cooler oficial.

#### `atlas.local` não resolve

Do WSL, o mDNS do Windows não é enxergado — use o IP. No Pi, confira que o
`avahi-daemon` está rodando; ele é quem responde por esse nome.

### Cuidados ao mexer no robô remotamente

Dois erros de operação que valem aviso, porque não geram mensagem nenhuma:

**`rsync` sem exclusões apaga o que você não queria.** Sincronizar a pasta do
projeto sem excluir `.venv`, `.git` e `.env` sobrescreve o ambiente virtual do Pi
(que é ARM) com o da sua máquina, e apaga a configuração do robô. Sempre:

```bash
rsync -az --exclude '.venv' --exclude '.git' --exclude '.env' \
      --exclude '__pycache__' --exclude 'models' ./ robo:~/atlas_ai_v2/
```

**Processos de teste ficam vivos e seguram a tela.** Antes de investigar vídeo,
confira `sudo cat /sys/kernel/debug/dri/1/clients` — um teste esquecido faz o
próximo processo falhar e manda você atrás da pista errada.

---

## Créditos

- Estética dos olhos inspirada na biblioteca [RoboEyes](https://github.com/FluxGarage/RoboEyes) (FluxGarage).
- Síntese de voz com [Piper](https://github.com/rhasspy/piper) (Rhasspy).
- Vozes em português do catálogo Piper, Kokoro e Edge — cada uma com a própria
  licença, listada em `roboteye voice list`.

A Atlas é um projeto do curso de Engenharia de Computação da Setrem (Sociedade
Educacional Três de Maio).

Código sob licença [MIT](LICENSE).
