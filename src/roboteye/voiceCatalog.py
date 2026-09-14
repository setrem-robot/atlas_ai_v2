"""Catalogo de vozes conhecidas.

Dados puros, sem dependencia de nenhum outro modulo do projeto: tanto a
configuracao (para resolver o nome de uma voz) quanto o download precisam desta
tabela, e mante-la isolada evita import circular entre os dois.

Cada voz declara o motor que a executa. Sao tres, com trocas diferentes:

* **piper**  — um arquivo `.onnx` por voz, leve e rapidissimo (RTF ~0,05).
  E o que roda confortavelmente num Raspberry Pi.
* **kokoro** — um unico modelo de 325 MB que carrega dezenas de vozes, com
  qualidade audivelmente superior e 24 kHz. Custa mais CPU (RTF ~0,4), entao
  compensa em maquina de mesa e pesa num Pi.
* **edge**   — vozes neurais da Microsoft, pela rede. Nao baixa modelo nenhum e
  nao gasta CPU, mas depende de internet. Em portugues do Brasil e o unico que
  entrega entonacao de frase de verdade.

As vozes do Kokoro compartilham os mesmos dois arquivos: baixar a segunda voz
Kokoro nao baixa nada de novo. As vozes `edge` nao baixam nada.

**Sobre portugues do Brasil.** As vozes femininas em pt-BR sao poucas, e vale
saber o que cada opcao custa. No Piper, o catalogo oficial so tem vozes
masculinas (cadu, edresson, faber, jeff); `dii` e comunitaria e a unica feminina
leve. No Kokoro ha exatamente uma, `pf_dora`, e ela e a melhor voz feminina
pt-BR que roda offline. As vozes `edge` soam melhor que as duas, com duas
ressalvas: precisam de rede e chegam em MP3 de 48 kbps, entao o sinal vem
comprimido.

Os modelos nao ficam no repositorio — sao baixados sob demanda para `models/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_HF = "https://huggingface.co"
_KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

#: Voz usada quando nada e configurado. A Atlas fala portugues do Brasil, entao
#: o padrao e a melhor voz feminina pt-BR que temos — que e uma voz de rede. A
#: reserva offline entra sozinha quando a internet falta, e num Pi ela e leve.
DEFAULT_VOICE = "francisca"

#: Diretorio (dentro de `models/`) onde ficam os arquivos compartilhados do Kokoro.
KOKORO_DIR = "kokoro"


@dataclass(frozen=True, slots=True)
class VoiceSpec:
    """Onde encontrar um modelo de voz e o que esperar dele."""

    key: str
    #: Motor que executa esta voz: "piper" ou "kokoro".
    engine: str
    description: str
    #: Codigo do idioma que a voz fala ("en", "pt"). Define tambem em que idioma
    #: o assistente responde, a menos que ROBOTEYE_REPLY_LANGUAGE diga outra coisa.
    language: str
    modelUrl: str
    #: `.onnx.json` no Piper; o pacote de vozes no Kokoro.
    configUrl: str
    #: Nome da voz dentro do pacote — so o Kokoro usa.
    speaker: str | None = None
    licenseNote: str = ""

    def targetPaths(self, modelsDir: Path) -> tuple[Path, Path]:
        """Caminhos do modelo e do arquivo que o acompanha.

        No Kokoro o par e compartilhado por todas as vozes do motor, entao ele
        nao depende de `key`.
        """
        if self.engine == "kokoro":
            directory = modelsDir / KOKORO_DIR
            return directory / "kokoro.onnx", directory / "voices.bin"

        model = modelsDir / self.key / f"{self.key}.onnx"
        return model, model.with_suffix(".onnx.json")


def piper(
    key: str, description: str, language: str, model: str, licenseNote: str = ""
) -> VoiceSpec:
    return VoiceSpec(
        key=key,
        engine="piper",
        description=description,
        language=language,
        modelUrl=model,
        configUrl=model + ".json",
        licenseNote=licenseNote,
    )


def kokoro(key: str, description: str, language: str, speaker: str) -> VoiceSpec:
    return VoiceSpec(
        key=key,
        engine="kokoro",
        description=description,
        language=language,
        modelUrl=f"{_KOKORO_RELEASE}/kokoro-v1.0.onnx",
        configUrl=f"{_KOKORO_RELEASE}/voices-v1.0.bin",
        speaker=speaker,
        licenseNote="Apache 2.0",
    )


def edge(key: str, description: str, language: str, speaker: str) -> VoiceSpec:
    """Voz da nuvem: nao ha arquivo para baixar, so um nome para pedir."""
    return VoiceSpec(
        key=key,
        engine="edge",
        description=description,
        language=language,
        modelUrl="",
        configUrl="",
        speaker=speaker,
        licenseNote="Servico da Microsoft; uso sujeito aos termos deles.",
    )


CATALOG: dict[str, VoiceSpec] = {
    # -- Piper: leves e rapidas ------------------------------------------
    "dii": piper(
        "dii",
        "Dii — feminina, portugues do Brasil",
        "pt",
        f"{_HF}/csukuangfj/vits-piper-pt_BR-dii-high/resolve/main/pt_BR-dii-high.onnx",
        "Licenca nao declarada pelo autor; confirme antes de uso comercial.",
    ),
    "faber": piper(
        "faber",
        "Faber — masculina, portugues do Brasil",
        "pt",
        f"{_HF}/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium/pt_BR-faber-medium.onnx",
        "CC0 (dominio publico)",
    ),
    "lessac": piper(
        "lessac",
        "Lessac — feminina, ingles, voz neutra do Piper",
        "en",
        f"{_HF}/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "MIT",
    ),
    # -- Kokoro: qualidade alta, 24 kHz ----------------------------------
    "dora": kokoro(
        "dora",
        "Dora — feminina, portugues do Brasil (melhor voz feminina offline)",
        "pt",
        "pf_dora",
    ),
    "alex": kokoro("alex", "Alex — masculina, portugues do Brasil", "pt", "pm_alex"),
    "heart": kokoro("heart", "Heart — feminina, ingles", "en", "af_heart"),
    # -- Edge: as mais naturais em pt-BR, mas precisam de internet --------
    "thalita": edge(
        "thalita",
        "Thalita — feminina, portugues do Brasil (online, a mais natural)",
        "pt",
        "pt-BR-ThalitaMultilingualNeural",
    ),
    "francisca": edge(
        "francisca",
        "Francisca — feminina, portugues do Brasil (online)",
        "pt",
        "pt-BR-FranciscaNeural",
    ),
}

#: Voz local que assume quando uma voz online nao consegue falar.
#:
#: A escolha e por idioma — cair numa voz que fala outra lingua nao ajuda
#: ninguem — e tambem por maquina. As vozes Kokoro soam melhor, mas custam 325 MB
#: de modelo e sintetizam a ~0,4x do tempo real; num Raspberry Pi, cair nelas
#: trocaria "sem internet" por "fala arrastada", que e pior. Por isso o hardware
#: modesto cai nas vozes Piper, que sao oito vezes mais rapidas.
OFFLINE_FALLBACK = {"pt": "dora", "en": "heart"}
OFFLINE_FALLBACK_LIGHT = {"pt": "dii", "en": "lessac"}


def needsDownload(key: str) -> bool:
    """Se esta voz tem arquivos para baixar antes do primeiro uso."""
    spec = get(key)
    return bool(spec and spec.modelUrl)


def fallbackFor(key: str, *, light: bool | None = None) -> str | None:
    """Voz offline que substitui `key` quando a rede falha.

    Devolve None para vozes que ja rodam offline: elas nao precisam de reserva.
    `light` força a escolha barata; sem ele, decide pela maquina.
    """
    spec = get(key)
    if spec is None or spec.engine != "edge":
        return None

    if light is None:
        light = isModestHardware()
    table = OFFLINE_FALLBACK_LIGHT if light else OFFLINE_FALLBACK
    return table.get(spec.language)


def isModestHardware() -> bool:
    """Heuristica de maquina modesta: ARM cobre o Raspberry Pi, que e o alvo."""
    import platform

    return platform.machine().lower().startswith(("arm", "aarch"))


def get(key: str) -> VoiceSpec | None:
    """Busca uma voz pelo nome. Devolve None se nao existir."""
    return CATALOG.get(key.strip().lower())


def languageOf(key: str, default: str = "en") -> str:
    """Idioma falado por uma voz do catalogo."""
    spec = get(key)
    return spec.language if spec else default


def engineOf(key: str, default: str = "piper") -> str:
    """Motor que executa uma voz do catalogo."""
    spec = get(key)
    return spec.engine if spec else default


def names() -> list[str]:
    return sorted(CATALOG)
