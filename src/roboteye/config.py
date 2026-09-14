"""Configuracao da aplicacao.

Toda a configuracao vem de variaveis de ambiente (opcionalmente carregadas de um
arquivo `.env`) e e materializada em dataclasses imutaveis. Nenhum outro modulo le
`os.environ` diretamente: quem precisa de configuracao recebe o objeto pronto.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

from roboteye import voiceCatalog

ENV_PREFIX: Final = "ROBOTEYE_"

#: Raiz do repositorio (…/src/roboteye/config.py -> …/)
PROJECT_ROOT: Final = Path(__file__).resolve().parents[2]

_TRUE_VALUES: Final = frozenset({"1", "true", "yes", "on", "y"})
_FALSE_VALUES: Final = frozenset({"0", "false", "no", "off", "n"})


class ConfigError(ValueError):
    """Valor de configuracao invalido."""


# ---------------------------------------------------------------------------
# Leitura primitiva do ambiente
# ---------------------------------------------------------------------------
def rawEnv(name: str) -> str | None:
    value = os.environ.get(ENV_PREFIX + name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def getStr(name: str, default: str) -> str:
    return rawEnv(name) or default


def getOptionalStr(name: str) -> str | None:
    return rawEnv(name)


def getTexto(name: str, default: str) -> str:
    """Como `_get_str`, mas **vazio quer dizer vazio**.

    Alguns textos tem um significado proprio quando estao em branco: sem palavra
    de despertar o robo responde a tudo, sem saudacao ele sobe calado. `_raw`
    trata vazio como ausente — o que e certo para um host ou um caminho, e
    errado aqui: `ROBOTEYE_WAKE_WORD=` voltava a valer "atlas".

    O efeito era mudo e caro. O robo continuava exigindo o nome, o log dizia
    `ouvi '...', mas nao era comigo`, e quem tinha acabado de desligar a palavra
    no `.env` procurava o defeito no reconhecimento — que estava funcionando.

    A diferenca esta em consultar o ambiente direto: `None` (a variavel nao
    existe) cai no padrao; `""` (existe e esta vazia) e uma escolha, e vale.
    """
    bruto = os.environ.get(ENV_PREFIX + name)
    return default if bruto is None else bruto.strip()


def getBool(name: str, default: bool) -> bool:
    raw = rawEnv(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigError(f"{ENV_PREFIX}{name}: esperava um booleano, recebi {raw!r}")


def getInt(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = rawEnv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name}: esperava um inteiro, recebi {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{ENV_PREFIX}{name}: deve ser >= {minimum}, recebi {value}")
    return value


def getFloat(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = rawEnv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name}: esperava um numero, recebi {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{ENV_PREFIX}{name}: deve ser >= {minimum}, recebi {value}")
    return value


def getChoice(name: str, default: str, allowed: frozenset[str]) -> str:
    value = getStr(name, default).lower()
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        raise ConfigError(f"{ENV_PREFIX}{name}: {value!r} invalido (use: {options})")
    return value


def parseColor(raw: str) -> tuple[int, int, int]:
    """Converte `#RRGGBB`, `RRGGBB` ou `r,g,b` numa tupla RGB."""
    text = raw.strip()
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 3:
            raise ConfigError(f"cor invalida: {raw!r} (esperava 3 componentes)")
        try:
            rgb = tuple(int(p) for p in parts)
        except ValueError as exc:
            raise ConfigError(f"cor invalida: {raw!r}") from exc
    else:
        hexText = text.lstrip("#")
        if len(hexText) != 6:
            raise ConfigError(f"cor invalida: {raw!r} (esperava #RRGGBB)")
        try:
            rgb = tuple(int(hexText[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError as exc:
            raise ConfigError(f"cor invalida: {raw!r}") from exc

    if not all(0 <= c <= 255 for c in rgb):
        raise ConfigError(f"cor fora do intervalo 0-255: {raw!r}")
    return rgb  # type: ignore[return-value]


def getColor(name: str, default: str) -> tuple[int, int, int]:
    return parseColor(getStr(name, default))


def isArm() -> bool:
    """Se a maquina e ARM — na pratica, se este e o Raspberry Pi de producao.

    Mora aqui, e nao no renderizador, porque a face nao e a unica coisa cujo
    padrao muda com o orcamento de CPU do Pi.
    """
    return platform.machine().lower().startswith(("arm", "aarch"))


def defaultFps() -> int:
    """Quadros por segundo quando ninguem escolheu.

    A face redesenha todo quadro — respiracao, sacadas e piscada nunca param —
    entao esse numero e gasto continuo de CPU, nao pico. Num Pi 5 a 800x480
    cada quadro custa poucos milissegundos, mas 60 vezes por segundo isso ja e
    mais de meio nucleo tirado do Piper e do servidor web. A 30 os movimentos
    desta face — todos lentos, medidos em decimos de segundo — nao se
    distinguem dos de 60; num monitor de mesa, onde CPU sobra, fica em 60.
    """
    return 30 if isArm() else 60


def resolvePath(raw: str) -> Path:
    """Resolve caminhos relativos a partir da raiz do projeto, nao do cwd."""
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


# ---------------------------------------------------------------------------
# Secoes de configuracao
# ---------------------------------------------------------------------------
LLM_BACKENDS: Final = frozenset({"ollama", "echo"})
#: "auto" deixa a voz escolher o motor — e o normal, ja que cada voz do
#: catalogo declara em qual motor roda.
TTS_BACKENDS: Final = frozenset({"auto", "piper", "kokoro", "edge", "null"})
#: Niveis de esforco do desenho da face.
FACE_QUALITIES: Final = frozenset({"auto", "low", "medium", "high"})

#: Tamanhos de modelo de reconhecimento que fazem sentido neste robô. Lista
#: fechada porque o `faster-whisper` **baixa** o que pedirem: um erro de
#: digitação viraria uma tentativa de download de um modelo inexistente, no
#: arranque, com o robô já ligado e a escuta desligando em silêncio.
#:
#: Medidos no Pi 5, 2,5 s de áudio: `tiny` 920 ms, `base` 1930 ms. O `small`
#: entra porque cabe na mesma escolha, para quem trocar o Pi por algo maior.
HEARING_MODEL_SIZES: Final = frozenset({"tiny", "base", "small"})

#: Tamanho padrao da janela de contexto. Constante, e nao um numero repetido:
#: ele estava escrito em dois lugares — no campo da dataclass e no `from_env` —
#: e mudar so um deles nao mudou nada, porque quem monta a configuracao de
#: verdade e o `from_env`. O robo continuou com 2048 e o aviso do arranque foi
#: quem denunciou.
DEFAULT_NUM_CTX: Final = 4096
#: Motores de reconhecimento de fala.
HEARING_BACKENDS: Final = frozenset({"whisper", "vosk", "null"})


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Como conversar com o modelo de linguagem."""

    backend: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "llama3.2:1b"
    timeout: float = 60.0
    historyMessages: int = 8
    replyLanguage: str = "en"
    #: Teto de tokens por resposta. O robo fala, nao redige.
    maxTokens: int = 120
    #: Primeira coisa que o robo diz ao ligar. Serve de prova de vida: se sair
    #: som, a caixinha, o volume e o motor de voz estao todos de pe — e quem
    #: montou o robo descobre isso na hora, nao na frente da plateia. Vazio
    #: desliga a saudacao.
    saudacao: str = "Oi oi, acordei!"
    #: Nome da persona (arquivo `<nome>.md` dentro de `persona_dir`).
    persona: str = "atlas"
    personaDir: Path = field(default_factory=lambda: PROJECT_ROOT / "persona")
    #: Ollama de reserva, no proprio robo, para quando o de `host` nao responder.
    #: Vazio desliga a reserva e deixa a falha de rede virar erro, como antes.
    fallbackHost: str = ""
    #: Modelo do reserva. Vazio usa o mesmo `model` — o que so faz sentido se as
    #: duas maquinas tiverem o mesmo modelo instalado; num Pi ele costuma ser menor.
    fallbackModel: str = ""
    #: De quanto em quanto tempo perguntar se o `host` voltou.
    probeInterval: float = 10.0
    #: Tamanho da janela de contexto, em tokens. E o que mais pesa na memoria
    #: do robo depois do proprio modelo: o Ollama reserva o cache de atencao
    #: pelo tamanho declarado, nao pelo texto que chega.
    #:
    #: Eram 2048, escolhidos supondo "~500 tokens de persona". A persona real
    #: deste robo tem **1800**, e com a pergunta o prompt chega a 1968 — 96% da
    #: janela. Somando a resposta (220 tokens), o contexto transbordava e o
    #: Ollama passava a deslocar a janela no meio da geracao, que e caro e
    #: piora a resposta.
    #:
    #: 4096 e o que faz persona, historico e resposta caberem juntos. Custa
    #: memoria, e a alternativa honesta e mais barata continua sendo encurtar a
    #: persona — ver o aviso em `PersonaStore`.
    numCtx: int = DEFAULT_NUM_CTX
    #: Quantos nucleos o modelo pode usar. 0 deixa o Ollama decidir, e ele
    #: decide pegar **todos**.
    #:
    #: Isso e o certo numa maquina de mesa dedicada e errado num Raspberry Pi,
    #: onde os mesmos quatro nucleos desenham a face e reconhecem a fala.
    #: Medido neste robo, a mesma pergunta ao mesmo modelo:
    #:
    #:     sozinho       primeiro token   200 ms   resposta inteira   1,4 s
    #:     disputando    primeiro token  3300 ms   resposta inteira  24,6 s
    #:
    #: A escuta agora para enquanto ele pensa, o que resolve a maior parte da
    #: disputa. Este teto e a segunda camada: a face desenha o tempo todo, e um
    #: modelo que toma a maquina inteira faz a animacao engasgar bem no momento
    #: em que a pessoa esta esperando resposta.
    numThread: int = 0
    #: Quanto tempo o modelo fica na memoria depois de responder, no formato do
    #: Ollama ("5m", "30s", "0"). Vale para o `host` principal, que costuma ser
    #: a maquina de mesa — onde memoria sobra.
    keepAlive: str = "5m"
    #: O mesmo, para o reserva que roda no proprio Pi. "0" faz ele devolver a
    #: memoria assim que termina de falar, que e o que mantem ~1,5 GB livres
    #: enquanto a rede esta de pe. Quem paga por isso e a primeira resposta
    #: depois de uma queda — e mesmo essa e coberta na maior parte das vezes,
    #: porque o `FallbackLLMClient` carrega o modelo no instante em que percebe
    #: a queda, e nao na hora da pergunta.
    fallbackKeepAlive: str = "0"

    @classmethod
    def fromEnv(cls, *, defaultLanguage: str = "en") -> LLMSettings:
        """Le a configuracao do LLM.

        `default_language` normalmente vem do idioma da voz escolhida: de nada
        adianta uma voz brasileira se o modelo responde em ingles. Definir
        ROBOTEYE_REPLY_LANGUAGE continua tendo a palavra final.
        """
        return cls(
            backend=getChoice("LLM_BACKEND", "ollama", LLM_BACKENDS),
            host=getStr("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
            model=getStr("LLM_MODEL", "llama3.2:1b"),
            timeout=getFloat("LLM_TIMEOUT", 60.0, minimum=1.0),
            historyMessages=getInt("LLM_HISTORY", 8, minimum=0),
            replyLanguage=getStr("REPLY_LANGUAGE", defaultLanguage).lower(),
            maxTokens=getInt("LLM_MAX_TOKENS", 120, minimum=16),
            saudacao=getTexto("SAUDACAO", "Oi oi, acordei!"),
            persona=getStr("PERSONA", "atlas"),
            personaDir=resolvePath(getStr("PERSONA_DIR", "persona")),
            fallbackHost=getStr("LLM_FALLBACK_HOST", "").rstrip("/"),
            fallbackModel=getStr("LLM_FALLBACK_MODEL", ""),
            probeInterval=getFloat("LLM_PROBE_INTERVAL", 10.0, minimum=0.0),
            numCtx=getInt("LLM_NUM_CTX", DEFAULT_NUM_CTX, minimum=256),
            numThread=getInt("LLM_NUM_THREAD", 0, minimum=0),
            keepAlive=getStr("LLM_KEEP_ALIVE", "5m"),
            fallbackKeepAlive=getStr("LLM_FALLBACK_KEEP_ALIVE", "0"),
        )


MODELS_DIR: Final = PROJECT_ROOT / "models"


def specOrFail(key: str) -> voiceCatalog.VoiceSpec:
    spec = voiceCatalog.get(key)
    if spec is None:
        options = ", ".join(voiceCatalog.names())
        raise ConfigError(f"{ENV_PREFIX}VOICE: voz desconhecida {key!r} (disponiveis: {options})")
    return spec


def modelPathForVoice(key: str) -> Path:
    """Onde o modelo de uma voz do catalogo fica depois de baixado."""
    return specOrFail(key).targetPaths(MODELS_DIR)[0]


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    """Motor de sintese de voz e parametros do modelo."""

    #: "auto" deixa a voz escolher o motor.
    backend: str = "auto"
    #: Nome da voz no catalogo. Trocar isto e a forma normal de trocar de voz.
    voice: str = voiceCatalog.DEFAULT_VOICE
    modelPath: Path = field(
        default_factory=lambda: modelPathForVoice(voiceCatalog.DEFAULT_VOICE)
    )
    configPath: Path | None = None
    #: Nome da voz dentro do pacote — so o Kokoro usa.
    speaker: str | None = None
    lengthScale: float = 1.0
    #: Tom da voz online, em semitons. Negativo desce a voz e a deixa mais
    #: macia; a velocidade quem controla e o `length_scale`. So a voz de rede
    #: entende isto — o Piper nao expoe controle de tom.
    pitch: float = 0.0
    noiseScale: float = 0.667
    noiseW: float = 0.8
    #: Placa de som. "auto" procura uma USB antes de aceitar o padrao do
    #: sistema — num robo, quem plugou uma caixinha quer ouvir por ela, e o
    #: HDMI depende de a tela ter alto-falante. Ver `speech/devices.py`.
    audioDevice: str | None = "auto"
    #: Reserva offline de uma voz online: "auto", "off" ou o nome de uma voz.
    #: "auto" escolhe pelo idioma e pela maquina — num Raspberry Pi cai numa voz
    #: leve, porque cair numa pesada trocaria "sem internet" por "fala arrastada".
    fallback: str = "auto"
    #: Multiplicador de volume aplicado ao audio sintetizado.
    #:
    #: Existe porque as vozes nao saem no mesmo nivel: medindo a mesma frase, a
    #: `dii` sai com mais que o dobro da energia da `thalita`. Trocar de voz
    #: muda o volume, e este e o ajuste para compensar. Nao ha risco de estourar:
    #: o acabamento limita o sinal antes de mandar para a placa.
    gain: float = 1.0
    #: Acima desta frequencia (Hz) o audio e atenuado. 0 desliga, e e o padrao.
    #:
    #: Existe porque as vozes nao ocupam a mesma faixa. Medida a mesma frase
    #: neste robo, a energia acima de 8 kHz: `francisca` 15,4%, `dii` 0,04%.
    #: Numa caixinha pequena esse brilho todo sai como chiado, e quem ouve
    #: descreve a voz como "bugada" — nao e defeito de sintese nem de
    #: reamostragem, as duas foram descartadas por medida. 6500 foi o valor
    #: escolhido de ouvido neste robo, entre quatro variantes.
    trebleHz: float = 0.0

    @classmethod
    def fromEnv(cls) -> VoiceSettings:
        voice = getStr("VOICE", voiceCatalog.DEFAULT_VOICE).lower()
        spec = specOrFail(voice)
        catalogModel, catalogConfig = spec.targetPaths(MODELS_DIR)

        # Um caminho explicito ganha do catalogo: e a saida para modelos que nao
        # estao na nossa lista. Nesse caso convem definir REPLY_LANGUAGE tambem.
        modelRaw = getOptionalStr("VOICE_MODEL")
        configRaw = getOptionalStr("VOICE_CONFIG")

        if modelRaw:
            modelPath = resolvePath(modelRaw)
            configPath = resolvePath(configRaw) if configRaw else None
        else:
            modelPath = catalogModel
            configPath = resolvePath(configRaw) if configRaw else catalogConfig

        return cls(
            backend=getChoice("TTS_BACKEND", "auto", TTS_BACKENDS),
            voice=voice,
            modelPath=modelPath,
            configPath=configPath,
            speaker=getOptionalStr("VOICE_SPEAKER") or spec.speaker,
            lengthScale=getFloat("VOICE_LENGTH_SCALE", 1.0, minimum=0.1),
            pitch=getFloat("VOICE_PITCH", 0.0),
            noiseScale=getFloat("VOICE_NOISE_SCALE", 0.667, minimum=0.0),
            noiseW=getFloat("VOICE_NOISE_W", 0.8, minimum=0.0),
            audioDevice=getStr("AUDIO_DEVICE", "auto"),
            fallback=getStr("VOICE_FALLBACK", "auto").lower(),
            gain=getFloat("VOICE_GAIN", 1.0, minimum=0.0),
            trebleHz=getFloat("VOICE_TREBLE_HZ", 0.0, minimum=0.0),
        )

    def forVoice(self, key: str) -> VoiceSettings:
        """Copia apontando para outra voz do catalogo.

        Os caminhos de modelo sao recalculados a partir do catalogo: um caminho
        explicito valia para a voz que o usuario pediu, nao para a reserva.
        """
        spec = specOrFail(key)
        modelPath, configPath = spec.targetPaths(MODELS_DIR)
        return replace(
            self,
            voice=key,
            backend="auto",
            modelPath=modelPath,
            configPath=configPath,
            speaker=spec.speaker,
        )

    def fallbackVoice(self) -> str | None:
        """Voz offline que assume se esta aqui nao conseguir falar.

        Aceita "auto" (o catalogo escolhe pelo idioma e pela maquina), "off"
        para desligar, ou o nome de uma voz — util para fixar a reserva quando a
        heuristica de hardware nao serve, como num Pi potente ou num mini-PC.
        """
        if self.backend != "auto":
            return None

        choice = self.fallback
        if choice in _FALSE_VALUES or choice == "off":
            return None
        if choice in _TRUE_VALUES or choice == "auto":
            return voiceCatalog.fallbackFor(self.voice)

        specOrFail(choice)  # nome invalido falha aqui, e nao no meio de uma fala
        return choice

    @property
    def language(self) -> str:
        """Idioma que esta voz fala, segundo o catalogo."""
        return voiceCatalog.languageOf(self.voice)

    @property
    def engine(self) -> str:
        """Motor que vai sintetizar: o pedido, ou o que a voz exige."""
        if self.backend != "auto":
            return self.backend
        return voiceCatalog.engineOf(self.voice)

    def resolvedConfigPath(self) -> Path:
        """Caminho do JSON de configuracao do modelo Piper.

        Por convencao o Piper usa `<modelo>.onnx.json` quando nao ha um explicito.
        """
        if self.configPath is not None:
            return self.configPath
        return self.modelPath.with_suffix(self.modelPath.suffix + ".json")


@dataclass(frozen=True, slots=True)
class FaceSettings:
    """Janela e aparencia dos olhos."""

    enabled: bool = True
    fullscreen: bool = False
    width: int = 1280
    height: int = 720
    #: Ver `default_fps()`: cai para 30 em ARM, onde o quadro e gasto continuo.
    fps: int = field(default_factory=defaultFps)
    eyeColor: tuple[int, int, int] = (4, 201, 253)
    backgroundColor: tuple[int, int, int] = (0, 0, 0)
    idleAnimations: bool = True

    #: Raio dos cantos como fracao do menor lado do olho.
    #: 0.5 e um circulo; 0.30 e o quadrado de cantos macios; 0.1 e quase reto.
    cornerRadius: float = 0.30

    #: Quanto se pode gastar por quadro: "low", "medium", "high" ou "auto".
    #: O antialiasing nao depende disso — e analitico e sai igual nos tres. O
    #: que muda e o teto de resolucao do campo, o halo e o degrade.
    #: "auto" cai para "low" em ARM (Raspberry Pi) e "medium" no resto.
    quality: str = "auto"

    @classmethod
    def fromEnv(cls) -> FaceSettings:
        return cls(
            enabled=getBool("FACE_ENABLED", True),
            fullscreen=getBool("FACE_FULLSCREEN", False),
            width=getInt("FACE_WIDTH", 1280, minimum=320),
            height=getInt("FACE_HEIGHT", 720, minimum=240),
            fps=getInt("FACE_FPS", defaultFps(), minimum=10),
            eyeColor=getColor("EYE_COLOR", "#04C9FD"),
            backgroundColor=getColor("BACKGROUND_COLOR", "#000000"),
            idleAnimations=getBool("IDLE_ANIMATIONS", True),
            cornerRadius=getFloat("EYE_CORNER_RADIUS", 0.30, minimum=0.0),
            quality=getChoice("FACE_QUALITY", "auto", FACE_QUALITIES),
        )


@dataclass(frozen=True, slots=True)
class HearingSettings:
    """Microfone e reconhecimento de fala."""

    #: Desligada por padrao: um microfone aberto e uma decisao de quem monta o
    #: robo, nao algo que se liga sozinho ao instalar.
    enabled: bool = False
    #: A escolha e entre **entender melhor** e **responder antes**, e nao ha
    #: opcao que ganhe nas duas:
    #:
    #:     vosk      decodifica enquanto a pessoa fala; ao parar, o texto ja
    #:               existe. Erra mais: "quanto os alunos pena".
    #:     whisper   so comeca depois da frase inteira, a 0,59x do tempo real
    #:               num Pi — quase 2 s de silencio antes de o LLM receber
    #:               qualquer coisa. Entende muito melhor.
    #:
    #: O padrao e `vosk` porque esses 2 s eram a maior parcela isolada do tempo
    #: de resposta, e porque quem espera calado na frente do robo conclui que
    #: ele quebrou. Trocar e uma variavel: `ROBOTEYE_HEARING_BACKEND=whisper`.
    backend: str = "vosk"
    #: Tamanho do modelo Whisper: "tiny" (mais rapido) ou "base" (melhor). Num
    #: Pi 5, medidos a 0,35x e 0,59x do tempo real. Nao afeta o vosk.
    model: str = "base"
    #: Pasta do modelo do Vosk, dentro de `model_path`. Baixe com
    #: `./scripts/baixar-modelo-escuta.sh` (pequeno) ou `--grande`.
    #:
    #: Medidos neste Pi, a mesma fala pelos dois:
    #:
    #:     vosk-pt          52 MB no disco    76 MB de RAM   0,38-0,45x t.real
    #:     vosk-pt-grande  2,6 GB no disco  2536 MB de RAM   0,05x t.real
    #:
    #: O grande e **mais rapido**, nao mais lento: fecha a frase em 34-55 ms
    #: contra 83-681 ms, e gasta oito vezes menos CPU. O que ele custa e
    #: memoria. Num Pi de 8 GB cabe junto com o Ollama (que usa ~1,3 GB), mas e
    #: a primeira coisa a rever se algo comecar a ser morto por falta dela.
    voskModel: str = "vosk-pt"
    #: Onde os modelos ficam. O Whisper baixa o seu na primeira vez.
    modelPath: Path = field(default_factory=lambda: MODELS_DIR / "escuta")
    #: Acima disto conta como fala. 0 mede a sala no arranque, que e o padrao e
    #: acerta na maioria das salas. Um numero fixo existe para quando ele erra:
    #: a medicao e feita uma vez, logo depois da saudacao, e uma sala que estava
    #: barulhenta naquele instante deixa o robo surdo pelo resto do dia. Visto
    #: neste robo, o limiar medido variando entre arranques: 0.036, 0.041,
    #: 0.045, 0.057 — e nos mais altos ele passou a nao fechar as frases.
    limiar: float = 0.0
    #: Nucleos para transcrever. Um fica de fora para a face nao engasgar.
    cpuThreads: int = 3
    #: Microfone. "auto" procura uma placa USB; ver `speech/devices.py`.
    device: str = "auto"
    #: Nome que acorda o robo. Vazio faz ele responder a tudo que ouvir — util
    #: para testar, ruim numa sala com gente conversando.
    wakeWord: str = "atlas"
    #: Segundos que a Atlas continua ouvindo depois de ser chamada, aceitando a
    #: pergunta seguinte sem o nome. 0 exige o nome em toda frase.
    janelaS: float = 8.0
    #: O que ela diz quando chamam o nome e a pergunta nao vem. Sem isso, chamar
    #: a Atlas e nao ser respondido parece robo quebrado — e quem chamou repete
    #: o nome em vez de perguntar. Vazio faz ela so esperar, calada.
    respostaAoChamado: str = "Oi?"
    #: Quanto esperar a pergunta antes de dizer aquilo.
    esperaDoChamadoS: float = 3.0

    @classmethod
    def fromEnv(cls) -> HearingSettings:
        return cls(
            enabled=getBool("HEARING_ENABLED", False),
            backend=getChoice("HEARING_BACKEND", "vosk", HEARING_BACKENDS),
            model=getChoice("HEARING_MODEL_SIZE", "base", HEARING_MODEL_SIZES),
            voskModel=getStr("HEARING_VOSK_MODEL", "vosk-pt"),
            modelPath=resolvePath(getStr("HEARING_MODEL_DIR", "models/escuta")),
            limiar=getFloat("HEARING_LIMIAR", 0.0, minimum=0.0),
            cpuThreads=getInt("HEARING_THREADS", 3, minimum=1),
            device=getStr("HEARING_DEVICE", "auto"),
            wakeWord=getTexto("WAKE_WORD", "atlas"),
            janelaS=getFloat("WAKE_JANELA", 8.0, minimum=0.0),
            respostaAoChamado=getTexto("WAKE_RESPOSTA", "Oi?"),
            esperaDoChamadoS=getFloat("WAKE_ESPERA", 3.0, minimum=0.5),
        )


@dataclass(frozen=True, slots=True)
class WebSettings:
    """Pagina de configuracao servida pelo robo."""

    enabled: bool = True
    #: Mostra na pagina os comandos que chegam ao robo. Precisa de um broker
    #: MQTT local — que so existe quando o corpo do robo (o `orquestrador`)
    #: esta instalado na mesma maquina.
    mostrarComandos: bool = True
    mqttHost: str = "127.0.0.1"
    mqttPort: int = 1883
    #: 0.0.0.0 de proposito: a pagina existe para ser aberta do celular.
    host: str = "0.0.0.0"
    port: int = 8080
    #: PIN de acesso. Vazio faz o robo sortear um e mostra-lo no arranque.
    pin: str = ""

    @classmethod
    def fromEnv(cls) -> WebSettings:
        return cls(
            enabled=getBool("WEB_ENABLED", True),
            mostrarComandos=getBool("WEB_COMANDOS", True),
            mqttHost=getStr("WEB_MQTT_HOST", "127.0.0.1"),
            mqttPort=getInt("WEB_MQTT_PORT", 1883, minimum=1),
            host=getStr("WEB_HOST", "0.0.0.0"),
            port=getInt("WEB_PORT", 8080, minimum=1),
            pin=getStr("WEB_PIN", ""),
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuracao completa da aplicacao."""

    llm: LLMSettings = field(default_factory=LLMSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    face: FaceSettings = field(default_factory=FaceSettings)
    hearing: HearingSettings = field(default_factory=HearingSettings)
    web: WebSettings = field(default_factory=WebSettings)
    logLevel: str = "INFO"

    @classmethod
    def fromEnv(cls, *, envFile: Path | str | None = None) -> Settings:
        """Carrega a configuracao do ambiente (e de um `.env`, se existir).

        Variaveis ja presentes no ambiente tem prioridade sobre o arquivo.
        """
        candidate = Path(envFile) if envFile else PROJECT_ROOT / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)

        # A voz vem primeiro: e ela que define em que idioma o assistente
        # responde, quando isso nao esta dito explicitamente.
        voice = VoiceSettings.fromEnv()

        return cls(
            llm=LLMSettings.fromEnv(defaultLanguage=voice.language),
            voice=voice,
            face=FaceSettings.fromEnv(),
            hearing=HearingSettings.fromEnv(),
            web=WebSettings.fromEnv(),
            logLevel=getStr("LOG_LEVEL", "INFO").upper(),
        )
