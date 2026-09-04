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

from roboteye import voice_catalog

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
def _raw(name: str) -> str | None:
    value = os.environ.get(ENV_PREFIX + name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _get_str(name: str, default: str) -> str:
    return _raw(name) or default


def _get_optional_str(name: str) -> str | None:
    return _raw(name)


def _get_bool(name: str, default: bool) -> bool:
    raw = _raw(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    raise ConfigError(f"{ENV_PREFIX}{name}: esperava um booleano, recebi {raw!r}")


def _get_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name}: esperava um inteiro, recebi {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{ENV_PREFIX}{name}: deve ser >= {minimum}, recebi {value}")
    return value


def _get_float(name: str, default: float, *, minimum: float | None = None) -> float:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{ENV_PREFIX}{name}: esperava um numero, recebi {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{ENV_PREFIX}{name}: deve ser >= {minimum}, recebi {value}")
    return value


def _get_choice(name: str, default: str, allowed: frozenset[str]) -> str:
    value = _get_str(name, default).lower()
    if value not in allowed:
        options = ", ".join(sorted(allowed))
        raise ConfigError(f"{ENV_PREFIX}{name}: {value!r} invalido (use: {options})")
    return value


def parse_color(raw: str) -> tuple[int, int, int]:
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
        hex_text = text.lstrip("#")
        if len(hex_text) != 6:
            raise ConfigError(f"cor invalida: {raw!r} (esperava #RRGGBB)")
        try:
            rgb = tuple(int(hex_text[i : i + 2], 16) for i in (0, 2, 4))
        except ValueError as exc:
            raise ConfigError(f"cor invalida: {raw!r}") from exc

    if not all(0 <= c <= 255 for c in rgb):
        raise ConfigError(f"cor fora do intervalo 0-255: {raw!r}")
    return rgb  # type: ignore[return-value]


def _get_color(name: str, default: str) -> tuple[int, int, int]:
    return parse_color(_get_str(name, default))


def is_arm() -> bool:
    """Se a maquina e ARM — na pratica, se este e o Raspberry Pi de producao.

    Mora aqui, e nao no renderizador, porque a face nao e a unica coisa cujo
    padrao muda com o orcamento de CPU do Pi.
    """
    return platform.machine().lower().startswith(("arm", "aarch"))


def default_fps() -> int:
    """Quadros por segundo quando ninguem escolheu.

    A face redesenha todo quadro — respiracao, sacadas e piscada nunca param —
    entao esse numero e gasto continuo de CPU, nao pico. Num Pi 5 a 800x480
    cada quadro custa poucos milissegundos, mas 60 vezes por segundo isso ja e
    mais de meio nucleo tirado do Piper e do servidor web. A 30 os movimentos
    desta face — todos lentos, medidos em decimos de segundo — nao se
    distinguem dos de 60; num monitor de mesa, onde CPU sobra, fica em 60.
    """
    return 30 if is_arm() else 60


def _resolve_path(raw: str) -> Path:
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
#: Motores de reconhecimento de fala.
HEARING_BACKENDS: Final = frozenset({"whisper", "vosk", "null"})


@dataclass(frozen=True, slots=True)
class LLMSettings:
    """Como conversar com o modelo de linguagem."""

    backend: str = "ollama"
    host: str = "http://localhost:11434"
    model: str = "llama3.2:1b"
    timeout: float = 60.0
    history_messages: int = 8
    reply_language: str = "en"
    #: Teto de tokens por resposta. O robo fala, nao redige.
    max_tokens: int = 120
    #: Primeira coisa que o robo diz ao ligar. Serve de prova de vida: se sair
    #: som, a caixinha, o volume e o motor de voz estao todos de pe — e quem
    #: montou o robo descobre isso na hora, nao na frente da plateia. Vazio
    #: desliga a saudacao.
    saudacao: str = "Oi oi, acordei!"
    #: Nome da persona (arquivo `<nome>.md` dentro de `persona_dir`).
    persona: str = "atlas"
    persona_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "persona")
    #: Ollama de reserva, no proprio robo, para quando o de `host` nao responder.
    #: Vazio desliga a reserva e deixa a falha de rede virar erro, como antes.
    fallback_host: str = ""
    #: Modelo do reserva. Vazio usa o mesmo `model` — o que so faz sentido se as
    #: duas maquinas tiverem o mesmo modelo instalado; num Pi ele costuma ser menor.
    fallback_model: str = ""
    #: De quanto em quanto tempo perguntar se o `host` voltou.
    probe_interval: float = 10.0
    #: Tamanho da janela de contexto, em tokens. E o que mais pesa na memoria
    #: do robo depois do proprio modelo: o Ollama reserva o cache de atencao
    #: pelo tamanho declarado, nao pelo texto que chega. Este robo conversa com
    #: ~500 tokens de persona, oito mensagens curtas de historico e respostas de
    #: 120 tokens — 2048 sobra, e o padrao de 4096 do Ollama dobra a conta a
    #: troco de espaco que nunca e usado.
    num_ctx: int = 2048
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
    num_thread: int = 0
    #: Quanto tempo o modelo fica na memoria depois de responder, no formato do
    #: Ollama ("5m", "30s", "0"). Vale para o `host` principal, que costuma ser
    #: a maquina de mesa — onde memoria sobra.
    keep_alive: str = "5m"
    #: O mesmo, para o reserva que roda no proprio Pi. "0" faz ele devolver a
    #: memoria assim que termina de falar, que e o que mantem ~1,5 GB livres
    #: enquanto a rede esta de pe. Quem paga por isso e a primeira resposta
    #: depois de uma queda — e mesmo essa e coberta na maior parte das vezes,
    #: porque o `FallbackLLMClient` carrega o modelo no instante em que percebe
    #: a queda, e nao na hora da pergunta.
    fallback_keep_alive: str = "0"

    @classmethod
    def from_env(cls, *, default_language: str = "en") -> LLMSettings:
        """Le a configuracao do LLM.

        `default_language` normalmente vem do idioma da voz escolhida: de nada
        adianta uma voz brasileira se o modelo responde em ingles. Definir
        ROBOTEYE_REPLY_LANGUAGE continua tendo a palavra final.
        """
        return cls(
            backend=_get_choice("LLM_BACKEND", "ollama", LLM_BACKENDS),
            host=_get_str("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
            model=_get_str("LLM_MODEL", "llama3.2:1b"),
            timeout=_get_float("LLM_TIMEOUT", 60.0, minimum=1.0),
            history_messages=_get_int("LLM_HISTORY", 8, minimum=0),
            reply_language=_get_str("REPLY_LANGUAGE", default_language).lower(),
            max_tokens=_get_int("LLM_MAX_TOKENS", 120, minimum=16),
            saudacao=_get_str("SAUDACAO", "Oi oi, acordei!"),
            persona=_get_str("PERSONA", "atlas"),
            persona_dir=_resolve_path(_get_str("PERSONA_DIR", "persona")),
            fallback_host=_get_str("LLM_FALLBACK_HOST", "").rstrip("/"),
            fallback_model=_get_str("LLM_FALLBACK_MODEL", ""),
            probe_interval=_get_float("LLM_PROBE_INTERVAL", 10.0, minimum=0.0),
            num_ctx=_get_int("LLM_NUM_CTX", 2048, minimum=256),
            num_thread=_get_int("LLM_NUM_THREAD", 0, minimum=0),
            keep_alive=_get_str("LLM_KEEP_ALIVE", "5m"),
            fallback_keep_alive=_get_str("LLM_FALLBACK_KEEP_ALIVE", "0"),
        )


MODELS_DIR: Final = PROJECT_ROOT / "models"


def _spec_or_fail(key: str) -> voice_catalog.VoiceSpec:
    spec = voice_catalog.get(key)
    if spec is None:
        options = ", ".join(voice_catalog.names())
        raise ConfigError(f"{ENV_PREFIX}VOICE: voz desconhecida {key!r} (disponiveis: {options})")
    return spec


def model_path_for_voice(key: str) -> Path:
    """Onde o modelo de uma voz do catalogo fica depois de baixado."""
    return _spec_or_fail(key).target_paths(MODELS_DIR)[0]


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    """Motor de sintese de voz e parametros do modelo."""

    #: "auto" deixa a voz escolher o motor.
    backend: str = "auto"
    #: Nome da voz no catalogo. Trocar isto e a forma normal de trocar de voz.
    voice: str = voice_catalog.DEFAULT_VOICE
    model_path: Path = field(
        default_factory=lambda: model_path_for_voice(voice_catalog.DEFAULT_VOICE)
    )
    config_path: Path | None = None
    #: Nome da voz dentro do pacote — so o Kokoro usa.
    speaker: str | None = None
    length_scale: float = 1.0
    #: Tom da voz online, em semitons. Negativo desce a voz e a deixa mais
    #: macia; a velocidade quem controla e o `length_scale`. So a voz de rede
    #: entende isto — o Piper nao expoe controle de tom.
    pitch: float = 0.0
    noise_scale: float = 0.667
    noise_w: float = 0.8
    #: Placa de som. "auto" procura uma USB antes de aceitar o padrao do
    #: sistema — num robo, quem plugou uma caixinha quer ouvir por ela, e o
    #: HDMI depende de a tela ter alto-falante. Ver `speech/devices.py`.
    audio_device: str | None = "auto"
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

    @classmethod
    def from_env(cls) -> VoiceSettings:
        voice = _get_str("VOICE", voice_catalog.DEFAULT_VOICE).lower()
        spec = _spec_or_fail(voice)
        catalog_model, catalog_config = spec.target_paths(MODELS_DIR)

        # Um caminho explicito ganha do catalogo: e a saida para modelos que nao
        # estao na nossa lista. Nesse caso convem definir REPLY_LANGUAGE tambem.
        model_raw = _get_optional_str("VOICE_MODEL")
        config_raw = _get_optional_str("VOICE_CONFIG")

        if model_raw:
            model_path = _resolve_path(model_raw)
            config_path = _resolve_path(config_raw) if config_raw else None
        else:
            model_path = catalog_model
            config_path = _resolve_path(config_raw) if config_raw else catalog_config

        return cls(
            backend=_get_choice("TTS_BACKEND", "auto", TTS_BACKENDS),
            voice=voice,
            model_path=model_path,
            config_path=config_path,
            speaker=_get_optional_str("VOICE_SPEAKER") or spec.speaker,
            length_scale=_get_float("VOICE_LENGTH_SCALE", 1.0, minimum=0.1),
            pitch=_get_float("VOICE_PITCH", 0.0),
            noise_scale=_get_float("VOICE_NOISE_SCALE", 0.667, minimum=0.0),
            noise_w=_get_float("VOICE_NOISE_W", 0.8, minimum=0.0),
            audio_device=_get_str("AUDIO_DEVICE", "auto"),
            fallback=_get_str("VOICE_FALLBACK", "auto").lower(),
            gain=_get_float("VOICE_GAIN", 1.0, minimum=0.0),
        )

    def for_voice(self, key: str) -> VoiceSettings:
        """Copia apontando para outra voz do catalogo.

        Os caminhos de modelo sao recalculados a partir do catalogo: um caminho
        explicito valia para a voz que o usuario pediu, nao para a reserva.
        """
        spec = _spec_or_fail(key)
        model_path, config_path = spec.target_paths(MODELS_DIR)
        return replace(
            self,
            voice=key,
            backend="auto",
            model_path=model_path,
            config_path=config_path,
            speaker=spec.speaker,
        )

    def fallback_voice(self) -> str | None:
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
            return voice_catalog.fallback_for(self.voice)

        _spec_or_fail(choice)  # nome invalido falha aqui, e nao no meio de uma fala
        return choice

    @property
    def language(self) -> str:
        """Idioma que esta voz fala, segundo o catalogo."""
        return voice_catalog.language_of(self.voice)

    @property
    def engine(self) -> str:
        """Motor que vai sintetizar: o pedido, ou o que a voz exige."""
        if self.backend != "auto":
            return self.backend
        return voice_catalog.engine_of(self.voice)

    def resolved_config_path(self) -> Path:
        """Caminho do JSON de configuracao do modelo Piper.

        Por convencao o Piper usa `<modelo>.onnx.json` quando nao ha um explicito.
        """
        if self.config_path is not None:
            return self.config_path
        return self.model_path.with_suffix(self.model_path.suffix + ".json")


@dataclass(frozen=True, slots=True)
class FaceSettings:
    """Janela e aparencia dos olhos."""

    enabled: bool = True
    fullscreen: bool = False
    width: int = 1280
    height: int = 720
    #: Ver `default_fps()`: cai para 30 em ARM, onde o quadro e gasto continuo.
    fps: int = field(default_factory=default_fps)
    eye_color: tuple[int, int, int] = (4, 201, 253)
    background_color: tuple[int, int, int] = (0, 0, 0)
    idle_animations: bool = True

    #: Raio dos cantos como fracao do menor lado do olho.
    #: 0.5 e um circulo; 0.30 e o quadrado de cantos macios; 0.1 e quase reto.
    corner_radius: float = 0.30

    #: Quanto se pode gastar por quadro: "low", "medium", "high" ou "auto".
    #: O antialiasing nao depende disso — e analitico e sai igual nos tres. O
    #: que muda e o teto de resolucao do campo, o halo e o degrade.
    #: "auto" cai para "low" em ARM (Raspberry Pi) e "medium" no resto.
    quality: str = "auto"

    @classmethod
    def from_env(cls) -> FaceSettings:
        return cls(
            enabled=_get_bool("FACE_ENABLED", True),
            fullscreen=_get_bool("FACE_FULLSCREEN", False),
            width=_get_int("FACE_WIDTH", 1280, minimum=320),
            height=_get_int("FACE_HEIGHT", 720, minimum=240),
            fps=_get_int("FACE_FPS", default_fps(), minimum=10),
            eye_color=_get_color("EYE_COLOR", "#04C9FD"),
            background_color=_get_color("BACKGROUND_COLOR", "#000000"),
            idle_animations=_get_bool("IDLE_ANIMATIONS", True),
            corner_radius=_get_float("EYE_CORNER_RADIUS", 0.30, minimum=0.0),
            quality=_get_choice("FACE_QUALITY", "auto", FACE_QUALITIES),
        )


@dataclass(frozen=True, slots=True)
class HearingSettings:
    """Microfone e reconhecimento de fala."""

    #: Desligada por padrao: um microfone aberto e uma decisao de quem monta o
    #: robo, nao algo que se liga sozinho ao instalar.
    enabled: bool = False
    #: "whisper" entende muito melhor que "vosk" — e a diferenca decide quando
    #: quem fala com o robo sao criancas. Ver `hearing/whisper_ears.py`.
    backend: str = "whisper"
    #: Tamanho do modelo Whisper: "tiny" (mais rapido) ou "base" (melhor). Num
    #: Pi 5, medidos a 0,35x e 0,59x do tempo real.
    model: str = "base"
    #: Onde os modelos ficam. O Whisper baixa o seu na primeira vez.
    model_path: Path = field(default_factory=lambda: MODELS_DIR / "escuta")
    #: Acima disto conta como fala. 0 mede a sala no arranque, que e o padrao e
    #: acerta na maioria das salas. Um numero fixo existe para quando ele erra:
    #: a medicao e feita uma vez, logo depois da saudacao, e uma sala que estava
    #: barulhenta naquele instante deixa o robo surdo pelo resto do dia. Visto
    #: neste robo, o limiar medido variando entre arranques: 0.036, 0.041,
    #: 0.045, 0.057 — e nos mais altos ele passou a nao fechar as frases.
    limiar: float = 0.0
    #: Nucleos para transcrever. Um fica de fora para a face nao engasgar.
    cpu_threads: int = 3
    #: Microfone. "auto" procura uma placa USB; ver `speech/devices.py`.
    device: str = "auto"
    #: Nome que acorda o robo. Vazio faz ele responder a tudo que ouvir — util
    #: para testar, ruim numa sala com gente conversando.
    wake_word: str = "atlas"
    #: Segundos que a Atlas continua ouvindo depois de ser chamada, aceitando a
    #: pergunta seguinte sem o nome. 0 exige o nome em toda frase.
    janela_s: float = 8.0
    #: O que ela diz quando chamam o nome e a pergunta nao vem. Sem isso, chamar
    #: a Atlas e nao ser respondido parece robo quebrado — e quem chamou repete
    #: o nome em vez de perguntar. Vazio faz ela so esperar, calada.
    resposta_ao_chamado: str = "Oi?"
    #: Quanto esperar a pergunta antes de dizer aquilo.
    espera_do_chamado_s: float = 3.0

    @classmethod
    def from_env(cls) -> HearingSettings:
        return cls(
            enabled=_get_bool("HEARING_ENABLED", False),
            backend=_get_choice("HEARING_BACKEND", "whisper", HEARING_BACKENDS),
            model=_get_choice("HEARING_MODEL_SIZE", "base", HEARING_MODEL_SIZES),
            model_path=_resolve_path(_get_str("HEARING_MODEL_DIR", "models/escuta")),
            limiar=_get_float("HEARING_LIMIAR", 0.0, minimum=0.0),
            cpu_threads=_get_int("HEARING_THREADS", 3, minimum=1),
            device=_get_str("HEARING_DEVICE", "auto"),
            wake_word=_get_str("WAKE_WORD", "atlas"),
            janela_s=_get_float("WAKE_JANELA", 8.0, minimum=0.0),
            resposta_ao_chamado=_get_str("WAKE_RESPOSTA", "Oi?"),
            espera_do_chamado_s=_get_float("WAKE_ESPERA", 3.0, minimum=0.5),
        )


@dataclass(frozen=True, slots=True)
class WebSettings:
    """Pagina de configuracao servida pelo robo."""

    enabled: bool = True
    #: Mostra na pagina os comandos que chegam ao robo. Precisa de um broker
    #: MQTT local — que so existe quando o corpo do robo (o `orquestrador`)
    #: esta instalado na mesma maquina.
    mostrar_comandos: bool = True
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    #: 0.0.0.0 de proposito: a pagina existe para ser aberta do celular.
    host: str = "0.0.0.0"
    port: int = 8080
    #: PIN de acesso. Vazio faz o robo sortear um e mostra-lo no arranque.
    pin: str = ""

    @classmethod
    def from_env(cls) -> WebSettings:
        return cls(
            enabled=_get_bool("WEB_ENABLED", True),
            mostrar_comandos=_get_bool("WEB_COMANDOS", True),
            mqtt_host=_get_str("WEB_MQTT_HOST", "127.0.0.1"),
            mqtt_port=_get_int("WEB_MQTT_PORT", 1883, minimum=1),
            host=_get_str("WEB_HOST", "0.0.0.0"),
            port=_get_int("WEB_PORT", 8080, minimum=1),
            pin=_get_str("WEB_PIN", ""),
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuracao completa da aplicacao."""

    llm: LLMSettings = field(default_factory=LLMSettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    face: FaceSettings = field(default_factory=FaceSettings)
    hearing: HearingSettings = field(default_factory=HearingSettings)
    web: WebSettings = field(default_factory=WebSettings)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, *, env_file: Path | str | None = None) -> Settings:
        """Carrega a configuracao do ambiente (e de um `.env`, se existir).

        Variaveis ja presentes no ambiente tem prioridade sobre o arquivo.
        """
        candidate = Path(env_file) if env_file else PROJECT_ROOT / ".env"
        if candidate.is_file():
            load_dotenv(candidate, override=False)

        # A voz vem primeiro: e ela que define em que idioma o assistente
        # responde, quando isso nao esta dito explicitamente.
        voice = VoiceSettings.from_env()

        return cls(
            llm=LLMSettings.from_env(default_language=voice.language),
            voice=voice,
            face=FaceSettings.from_env(),
            hearing=HearingSettings.from_env(),
            web=WebSettings.from_env(),
            log_level=_get_str("LOG_LEVEL", "INFO").upper(),
        )
