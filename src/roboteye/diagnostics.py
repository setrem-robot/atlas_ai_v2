"""Diagnostico do ambiente (`roboteye doctor`).

Verifica, numa passada so, tudo que costuma faltar: dependencias opcionais,
o modelo de voz, a saida de audio e o servidor do LLM.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from enum import Enum

from roboteye.config import Settings


class Status(Enum):
    OK = "ok"
    WARN = "aviso"
    FAIL = "falha"

    @property
    def marker(self) -> str:
        return {Status.OK: "[ ok ]", Status.WARN: "[aviso]", Status.FAIL: "[falha]"}[self]


@dataclass(frozen=True, slots=True)
class Check:
    """Resultado de uma verificacao."""

    name: str
    status: Status
    detail: str
    hint: str = ""


@dataclass(slots=True)
class Report:
    """Conjunto de verificacoes."""

    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.status is not Status.FAIL for check in self.checks)

    def render(self) -> str:
        lines = ["", "Diagnostico do RobotEye", "=" * 60]
        for check in self.checks:
            lines.append(f"{check.status.marker} {check.name:<22} {check.detail}")
            if check.hint and check.status is not Status.OK:
                lines.append(f"        -> {check.hint}")
        lines.append("=" * 60)
        lines.append("Tudo pronto." if self.ok else "Ha problemas a resolver acima.")
        return "\n".join(lines)


def run_diagnostics(settings: Settings) -> Report:
    """Executa todas as verificacoes."""
    report = Report()
    report.checks.append(_check_python())
    report.checks.append(_check_pygame())
    report.checks.extend(_check_voice(settings))
    report.checks.append(_check_audio_output(settings))
    report.checks.extend(_check_llm(settings))
    return report


# ---------------------------------------------------------------------------
def _check_python() -> Check:
    version = platform.python_version()
    status = Status.OK if sys.version_info >= (3, 10) else Status.FAIL
    return Check(
        name="Python",
        status=status,
        detail=f"{version} ({platform.system()} {platform.machine()})",
        hint="o projeto requer Python 3.10 ou superior",
    )


def _check_pygame() -> Check:
    try:
        import pygame
    except ImportError as exc:
        return Check("pygame", Status.FAIL, str(exc), "pip install -e .")
    return Check("pygame", Status.OK, f"versao {pygame.version.ver}")


def _check_voice(settings: Settings) -> list[Check]:
    voice = settings.voice
    engine = voice.engine

    if engine == "null":
        return [Check("motor de voz", Status.WARN, "desativado (backend=null)")]

    if engine == "edge":
        return _check_online_voice(settings)

    checks: list[Check] = []
    pacote, extra = ("kokoro_onnx", "kokoro") if engine == "kokoro" else ("piper", "tts")

    try:
        __import__(pacote)
    except ImportError as exc:
        checks.append(Check(pacote, Status.FAIL, str(exc), f'pip install -e ".[{extra}]"'))
        return checks

    checks.append(Check(pacote, Status.OK, f"instalado (motor {engine})"))

    model = voice.model_path
    config = voice.resolved_config_path()
    if not model.is_file():
        checks.append(
            Check(
                "modelo de voz",
                Status.FAIL,
                f"nao encontrado: {model}",
                f"roboteye voice download {voice.voice}",
            )
        )
    elif not config.is_file():
        checks.append(
            Check(
                "modelo de voz",
                Status.FAIL,
                f"falta o arquivo {config.name}",
                f"roboteye voice download {voice.voice} --force",
            )
        )
    else:
        size_mb = model.stat().st_size / 1_048_576
        checks.append(
            Check(
                "modelo de voz",
                Status.OK,
                f"{voice.voice} [{voice.language}] — {model.name} ({size_mb:.0f} MB)",
            )
        )

    return checks


def _check_online_voice(settings: Settings) -> list[Check]:
    """Confere as dependencias da voz na nuvem e qual voz a substitui sem rede."""
    voice = settings.voice
    checks: list[Check] = []

    faltando = [nome for nome in ("edge_tts", "miniaudio") if not _importable(nome)]
    if faltando:
        checks.append(
            Check(
                "voz online",
                Status.FAIL,
                f"falta {', '.join(faltando)}",
                'pip install -e ".[online]"',
            )
        )
        return checks

    checks.append(_speak_a_word(settings))

    reserva = voice.fallback_voice()
    if reserva is None:
        checks.append(
            Check(
                "reserva offline",
                Status.WARN,
                "desativada",
                "sem internet o robo fica mudo; ligue com ROBOTEYE_VOICE_FALLBACK=true",
            )
        )
        return checks

    modelo = settings.voice.for_voice(reserva).model_path
    if modelo.is_file():
        checks.append(Check("reserva offline", Status.OK, f"{reserva} (pronta)"))
    else:
        checks.append(
            Check(
                "reserva offline",
                Status.WARN,
                f"{reserva} ainda nao foi baixada",
                f"roboteye voice download {reserva}",
            )
        )

    return checks


def _speak_a_word(settings: Settings) -> Check:
    """Sintetiza uma palavra de verdade pela voz online.

    Conferir que os pacotes importam nao prova quase nada: o que costuma faltar
    e a rede, e sem a rede o robo fala pela voz reserva — que, sendo tambem
    feminina e em portugues, passa facilmente por "a voz configurada, so que
    errada". Este teste separa os dois casos antes de virar confusao.
    """
    from roboteye.speech.edge_engine import EdgeEngine

    engine = EdgeEngine(settings.voice)
    try:
        audio = sum(len(chunk.audio) for chunk in engine.synthesize("teste"))
    except Exception as exc:
        # Amplo de proposito: um diagnostico que estoura no meio nao diagnostica
        # nada, e o que se quer saber aqui e apenas "falou ou nao falou".
        return Check(
            "voz online",
            Status.FAIL,
            f"{settings.voice.voice} nao respondeu: {exc}",
            "sem internet o robo falara pela voz reserva; veja a linha abaixo",
        )

    if audio == 0:
        return Check(
            "voz online",
            Status.FAIL,
            f"{settings.voice.voice} respondeu sem audio",
            "sem internet o robo falara pela voz reserva; veja a linha abaixo",
        )

    # Sem travessao: o console do Windows usa cp1252 e o transforma em lixo.
    return Check(
        "voz online",
        Status.OK,
        f"{settings.voice.voice} ({settings.voice.speaker}), falou {audio / 1024:.0f} KB",
    )


def _importable(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def _check_audio_output(settings: Settings) -> Check:
    try:
        import sounddevice as sd
    except (ImportError, OSError) as exc:
        return Check(
            "saida de audio",
            Status.WARN,
            f"sounddevice indisponivel ({exc})",
            'pip install -e ".[tts]" (no Linux tambem: sudo apt install libportaudio2)',
        )

    try:
        device = sd.query_devices(kind="output")
    except Exception as exc:
        return Check(
            "saida de audio",
            Status.FAIL,
            f"nenhum dispositivo de saida ({exc})",
            "verifique se ha placa de som ativa e se o usuario esta no grupo audio",
        )

    name = device["name"] if isinstance(device, dict) else str(device)
    return Check("saida de audio", Status.OK, name.strip())


def _check_llm(settings: Settings) -> list[Check]:
    """Verifica a IA — e, se houver reserva local, verifica as duas.

    Uma linha so nao serve quando ha duas maquinas: a que fica de pe esconde a
    que caiu, e o robo responderia pelo modelo pequeno sem ninguem entender por
    que ficou menos esperto.
    """
    from roboteye.llm.factory import create_llm_client

    if settings.llm.backend != "ollama":
        client = create_llm_client(settings.llm)
        try:
            return [Check("LLM", Status.OK, f"backend {client.name}")]
        finally:
            client.close()

    fallback = settings.llm.fallback_host and settings.llm.fallback_host != settings.llm.host
    if not fallback:
        return [_check_ollama("LLM", settings.llm.host, settings.llm.model, critico=True)]

    principal = _check_ollama("IA de rede", settings.llm.host, settings.llm.model, critico=False)
    reserva = _check_ollama(
        "IA local (reserva)",
        settings.llm.fallback_host,
        settings.llm.fallback_model or settings.llm.model,
        # A reserva e a ultima linha: se ela tambem nao esta de pe, uma queda de
        # rede deixa o robo sem resposta nenhuma, e isso e falha de verdade.
        critico=principal.status is not Status.OK,
    )
    return [principal, reserva]


def _check_ollama(nome: str, host: str, modelo: str, *, critico: bool) -> Check:
    """Um servidor Ollama: esta de pe, e tem o modelo pedido?"""
    from dataclasses import replace

    from roboteye.config import LLMSettings
    from roboteye.llm.ollama import OllamaClient

    ruim = Status.FAIL if critico else Status.WARN
    client = OllamaClient(replace(LLMSettings(), host=host, model=modelo))
    try:
        if not client.is_available():
            return Check(
                nome,
                ruim,
                f"inacessivel em {host}",
                "inicie o Ollama (ollama serve) ou use ROBOTEYE_LLM_BACKEND=echo",
            )

        models = client.list_models()
        if modelo not in models:
            available = ", ".join(models[:5]) or "nenhum"
            return Check(
                nome,
                ruim,
                f"modelo {modelo!r} ausente em {host} (ha: {available})",
                f"ollama pull {modelo}",
            )
        return Check(nome, Status.OK, f"{modelo} em {host}")
    finally:
        client.close()
