"""O que o robo esta sentindo agora.

A pagina ja servia configuracao e conversa. Faltava a pergunta que se faz antes
das duas — "ele esta bem?" —, e que hoje so tem resposta por SSH: se esta quente
demais, se o cartao encheu, se a IA de rede caiu, se o celular esta conectado
pelo Bluetooth.

Tudo aqui e leitura barata de arquivo do sistema. E consultado a cada poucos
segundos por uma pagina aberta, entao nada aqui pode abrir conexao, esperar por
rede ou tocar no hardware — quem faz isso e o `doctor`, que roda uma vez e
demora o quanto precisar.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: Acima disto o Pi comeca a reduzir a frequencia para nao cozinhar.
TEMPERATURA_ALERTA = 75.0
#: Abaixo disto o cartao esta perto de encher, e o robo para de gravar log,
#: modelo de voz e qualquer coisa que precise de espaco.
DISCO_MINIMO_GB = 1.0


def instantaneo(repo_dir: Path) -> dict:
    """Um retrato do robo agora, para a pagina mostrar."""
    return {
        "temperatura": _temperatura(),
        "temperatura_alerta": TEMPERATURA_ALERTA,
        "carga": _carga(),
        "memoria": _memoria(),
        "disco": _disco(repo_dir),
        "ligado_ha": _ligado_ha(),
        "servicos": _servicos(),
        "bluetooth": _bluetooth(),
        "versao": _versao(repo_dir),
    }


def _temperatura() -> float | None:
    """Graus do processador. O Pi 5 nao tem ventoinha; isto importa."""
    try:
        bruto = Path("/sys/class/thermal/thermal_zone0/temp").read_text()
    except OSError:
        return None
    return round(int(bruto.strip()) / 1000, 1)


def _carga() -> float | None:
    """Media de processos esperando CPU no ultimo minuto."""
    try:
        return round(float(Path("/proc/loadavg").read_text().split()[0]), 2)
    except (OSError, ValueError, IndexError):
        return None


def _memoria() -> dict | None:
    """Memoria em uso e disponivel, em MB."""
    try:
        linhas = dict(
            (parte[0].rstrip(":"), int(parte[1]))
            for parte in (linha.split() for linha in Path("/proc/meminfo").read_text().splitlines())
            if len(parte) >= 2 and parte[1].isdigit()
        )
    except OSError:
        return None
    total = linhas.get("MemTotal", 0) // 1024
    livre = linhas.get("MemAvailable", 0) // 1024
    return {"total_mb": total, "usada_mb": total - livre, "livre_mb": livre}


def _disco(caminho: Path) -> dict | None:
    """Espaco no cartao. Encher e a forma mais comum de o robo parar."""
    try:
        uso = shutil.disk_usage(caminho)
    except OSError:
        return None
    return {
        "total_gb": round(uso.total / 1e9, 1),
        "livre_gb": round(uso.free / 1e9, 1),
        "minimo_gb": DISCO_MINIMO_GB,
    }


def _ligado_ha() -> int | None:
    """Segundos desde que a maquina ligou."""
    try:
        return int(float(Path("/proc/uptime").read_text().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def _servicos() -> dict:
    """Quais partes do robo estao de pe.

    `systemctl is-active` com varias unidades de uma vez: uma chamada so, e
    nenhuma delas espera por rede.
    """
    unidades = ("roboteye", "roboteye-ble", "ollama", "bluetooth")
    try:
        pronto = subprocess.run(
            ["systemctl", "is-active", *unidades],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    estados = pronto.stdout.strip().splitlines()
    return {nome: estados[i] if i < len(estados) else "?" for i, nome in enumerate(unidades)}


def _bluetooth() -> dict:
    """Se ha celular conectado pelo Bluetooth, e com que nome."""
    try:
        pronto = subprocess.run(
            ["bluetoothctl", "devices", "Connected"],
            capture_output=True,
            text=True,
            input="",
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return {"conectado": False, "aparelhos": []}

    aparelhos = [
        " ".join(linha.split()[2:]) or linha.split()[1]
        for linha in pronto.stdout.splitlines()
        if linha.startswith("Device")
    ]
    return {"conectado": bool(aparelhos), "aparelhos": aparelhos}


def _versao(repo_dir: Path) -> dict | None:
    """Que versao do robo esta rodando agora."""
    try:
        pronto = subprocess.run(
            ["git", "-C", str(repo_dir), "log", "-1", "--format=%h|%s|%cr"],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if pronto.returncode != 0 or not pronto.stdout.strip():
        return None
    partes = pronto.stdout.strip().split("|", 2)
    if len(partes) != 3:
        return None
    return {"commit": partes[0], "titulo": partes[1], "quando": partes[2]}


def formatar_duracao(segundos: int | None) -> str:
    """Segundos em algo que se le: "3 h 12 min"."""
    if segundos is None:
        return "?"
    if segundos < 60:
        return f"{segundos} s"
    minutos, _ = divmod(segundos, 60)
    horas, minutos = divmod(minutos, 60)
    dias, horas = divmod(horas, 24)
    if dias:
        return f"{dias} d {horas} h"
    if horas:
        return f"{horas} h {minutos} min"
    return f"{minutos} min"


def agora() -> float:
    return time.time()
