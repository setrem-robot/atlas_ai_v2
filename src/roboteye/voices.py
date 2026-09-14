"""Download dos modelos de voz.

O catalogo em si vive em `voiceCatalog.py`; aqui fica so o que envolve rede e
disco. Os modelos sao grandes (dezenas de MB) e por isso nao ficam no
repositorio: sao baixados sob demanda para `models/`.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import httpx

from roboteye.config import PROJECT_ROOT
from roboteye.loggingSetup import getLogger
from roboteye.voiceCatalog import CATALOG, VoiceSpec, get, names

logger = getLogger(__name__)

DEFAULT_MODELS_DIR = PROJECT_ROOT / "models"
_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)

ProgressCallback = Callable[[str, int, int | None], None]

__all__ = [
    "CATALOG",
    "DEFAULT_MODELS_DIR",
    "VoiceDownloadError",
    "VoiceSpec",
    "consoleProgress",
    "downloadVoice",
]


class VoiceDownloadError(RuntimeError):
    """Falha ao baixar um modelo de voz."""


def downloadVoice(
    key: str,
    *,
    modelsDir: Path = DEFAULT_MODELS_DIR,
    force: bool = False,
    onProgress: ProgressCallback | None = None,
) -> Path:
    """Baixa o modelo `key` e devolve o caminho do arquivo `.onnx`."""
    spec = get(key)
    if spec is None:
        raise VoiceDownloadError(f"voz desconhecida: {key!r} (disponiveis: {', '.join(names())})")

    if not spec.modelUrl:
        raise VoiceDownloadError(
            f"a voz {key!r} roda na nuvem e nao tem modelo para baixar. "
            'Instale o suporte com: pip install -e ".[online]"'
        )

    modelPath, configPath = spec.targetPaths(modelsDir)
    modelPath.parent.mkdir(parents=True, exist_ok=True)

    if modelPath.is_file() and configPath.is_file() and not force:
        logger.info("voz %s ja esta em %s", key, modelPath)
        return modelPath

    download(spec.configUrl, configPath, onProgress)
    download(spec.modelUrl, modelPath, onProgress)

    if spec.licenseNote:
        logger.info("licenca de %s: %s", key, spec.licenseNote)
    return modelPath


def download(url: str, destination: Path, onProgress: ProgressCallback | None) -> None:
    """Baixa para um arquivo temporario e so entao substitui o destino."""
    temporary = destination.with_suffix(destination.suffix + ".part")
    logger.info("baixando %s", destination.name)

    try:
        with httpx.stream("GET", url, timeout=_TIMEOUT, follow_redirects=True) as response:
            response.raise_for_status()
            length = response.headers.get("content-length")
            total = int(length) if length else None

            with temporary.open("wb") as handle:
                for chunk in response.iter_bytes(chunk_size=256 * 1024):
                    handle.write(chunk)
                    if onProgress is not None:
                        onProgress(destination.name, response.num_bytes_downloaded, total)
    except httpx.HTTPError as exc:
        temporary.unlink(missing_ok=True)
        raise VoiceDownloadError(f"falha ao baixar {url}: {exc}") from exc

    shutil.move(str(temporary), str(destination))


def consoleProgress(name: str, downloaded: int, total: int | None) -> None:
    """Barra de progresso simples para uso no terminal."""
    megabytes = downloaded / 1_048_576
    if total:
        percent = downloaded * 100 // total
        barLength = percent // 4
        bar = "#" * barLength + "." * (25 - barLength)
        print(f"\r  {name:<24} [{bar}] {percent:3d}% ({megabytes:.1f} MB)", end="", flush=True)
        if downloaded >= total:
            print()
    else:
        print(f"\r  {name:<24} {megabytes:.1f} MB", end="", flush=True)
