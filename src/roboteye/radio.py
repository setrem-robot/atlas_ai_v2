"""Wi-Fi e Bluetooth dividindo o mesmo radio (`roboteye radio`).

No Raspberry Pi 5 as duas coisas saem do mesmo chip e da mesma antena. Em 2,4
GHz elas ocupam literalmente a mesma faixa, e o chip precisa reveza-las: o
Bluetooth so transmite nas frestas que o Wi-Fi deixa, e vice-versa. Medido neste
robo com `scripts/bench-radio.sh`, o efeito no Wi-Fi e visivel — media 18% maior
e picos cinco vezes maiores com o anuncio BLE no ar.

Enquanto o ESP32 existia o problema nao existia: o radio Bluetooth era dele, do
outro lado de um cabo. Com a ponte rodando no proprio Pi, os dois passaram a
disputar.

**A saida e de banda, nao de ajuste fino.** O Bluetooth so existe em 2,4 GHz e
nao ha o que fazer quanto a isso — mas o Wi-Fi tambem fala 5 GHz, onde nao ha
Bluetooth nenhum. Levando o Wi-Fi para la, a disputa acaba em vez de ser
administrada. Este modulo verifica se e isso que esta acontecendo e, quando nao
esta, diz exatamente o comando que resolve.

O segundo ajuste e o `power_save` do Wi-Fi: ele desliga o radio entre pacotes
para poupar bateria, o que num robo ligado na tomada nao compra nada e custa
latencia — e piora justamente a coexistencia, porque encurta as frestas que o
Bluetooth teria.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

SYS_NET = Path("/sys/class/net")

#: Fronteira entre as bandas, em MHz. Nada opera entre 2,5 e 5 GHz.
LIMITE_BANDA_MHZ = 4000


@dataclass(frozen=True, slots=True)
class EstadoRadio:
    """O que o radio esta fazendo agora."""

    interface: str = ""
    ssid: str = ""
    frequencia_mhz: int = 0
    #: Potencia do sinal em dBm. Negativo; quanto mais perto de zero, melhor.
    sinal_dbm: int = 0
    power_save: bool | None = None
    bluetooth_ligado: bool = False
    erro: str = ""

    @property
    def conectado(self) -> bool:
        return bool(self.ssid)

    @property
    def banda(self) -> str:
        """Banda em que o Wi-Fi esta: 5 GHz, 2,4 GHz, ou vazio sem conexao."""
        if not self.frequencia_mhz:
            return ""
        return "5 GHz" if self.frequencia_mhz >= LIMITE_BANDA_MHZ else "2,4 GHz"

    @property
    def disputando(self) -> bool:
        """Se Wi-Fi e Bluetooth estao na mesma faixa, brigando pela antena."""
        return self.bluetooth_ligado and self.banda == "2,4 GHz"


@dataclass(frozen=True, slots=True)
class Conselho:
    """Um ajuste que vale a pena, e o comando que o aplica."""

    titulo: str
    motivo: str
    comando: str


def aconselhar(estado: EstadoRadio) -> list[Conselho]:
    """O que ainda da para melhorar neste estado. Funcao pura."""
    conselhos: list[Conselho] = []

    if estado.disputando:
        conselhos.append(
            Conselho(
                titulo="mover o Wi-Fi para 5 GHz",
                motivo=(
                    "o Wi-Fi está em 2,4 GHz, a mesma faixa do Bluetooth — os dois "
                    "revezam a antena, e é isso que faz o app engasgar e a IA da rede demorar"
                ),
                comando=(
                    f"nmcli connection modify '{estado.ssid}' wifi.band a "
                    f"&& nmcli connection up '{estado.ssid}'"
                ),
            )
        )

    if estado.power_save:
        conselhos.append(
            Conselho(
                titulo="desligar a economia de energia do Wi-Fi",
                motivo=(
                    "o rádio desliga entre pacotes para poupar bateria; num robô "
                    "na tomada isso só adiciona latência e encurta as frestas que o "
                    "Bluetooth usaria"
                ),
                comando=(
                    f"nmcli connection modify '{estado.ssid or '<conexão>'}' "
                    "802-11-wireless-powersave 2"
                ),
            )
        )

    return conselhos


def render(estado: EstadoRadio) -> str:
    """Relatorio legivel de `EstadoRadio` mais os conselhos."""
    if estado.erro:
        return f"\nRádio do RobotEye\n{'=' * 60}\n{estado.erro}\n"

    linhas = ["", "Rádio do RobotEye", "=" * 60]
    if estado.conectado:
        linhas.append(
            f"  Wi-Fi       {estado.ssid} · {estado.banda} "
            f"({estado.frequencia_mhz} MHz) · {estado.sinal_dbm} dBm"
        )
    else:
        linhas.append(f"  Wi-Fi       sem conexão ({estado.interface or 'sem interface'})")

    economia = {True: "ligada", False: "desligada", None: "não sei dizer"}[estado.power_save]
    linhas.append(f"  economia    {economia}")
    linhas.append(f"  Bluetooth   {'ligado' if estado.bluetooth_ligado else 'desligado'}")

    conselhos = aconselhar(estado)
    linhas.append("=" * 60)
    if not conselhos:
        if estado.disputando:  # pragma: no cover - `aconselhar` sempre cobre esse caso
            linhas.append("Wi-Fi e Bluetooth estão na mesma faixa.")
        else:
            linhas.append("Wi-Fi e Bluetooth não estão se atrapalhando.")
        return "\n".join(linhas)

    for conselho in conselhos:
        linhas.append(f"  → {conselho.titulo}")
        linhas.append(f"    porque {conselho.motivo}")
        linhas.append(f"    {conselho.comando}")
    linhas.append("")
    linhas.append("Aplique tudo de uma vez com: sudo ./scripts/separar-radios.sh")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def medir() -> EstadoRadio:
    """Le o estado atual dos dois radios."""
    interface = interface_wifi()
    if not interface:
        return EstadoRadio(erro="nenhuma interface Wi-Fi encontrada (isto roda no robô)")
    if shutil.which("iw") is None:
        return EstadoRadio(
            interface=interface,
            erro="o comando `iw` não está instalado: sudo apt install iw",
        )

    ssid, frequencia, sinal = ler_link(_rodar("iw", "dev", interface, "link"))
    return EstadoRadio(
        interface=interface,
        ssid=ssid,
        frequencia_mhz=frequencia,
        sinal_dbm=sinal,
        power_save=ler_power_save(_rodar("iw", "dev", interface, "get", "power_save")),
        bluetooth_ligado=_bluetooth_ligado(),
    )


def interface_wifi() -> str:
    """A primeira interface sem fio da maquina, normalmente `wlan0`.

    O diretorio `wireless` so existe em interfaces de radio — e mais confiavel
    que casar o nome, que muda com as regras de nomenclatura do systemd.
    """
    try:
        for caminho in sorted(SYS_NET.iterdir()):
            if (caminho / "wireless").is_dir():
                return caminho.name
    except OSError:  # pragma: no cover - maquina sem /sys (Windows, macOS)
        pass
    return ""


def ler_link(saida: str) -> tuple[str, int, int]:
    """Extrai SSID, frequencia e sinal de `iw dev X link`. Funcao pura.

    Sem conexao a saida e a linha "Not connected." — dai o retorno neutro em
    vez de uma excecao: nao estar conectado e um estado normal do robo, nao um
    defeito de leitura.
    """
    ssid = ""
    frequencia = 0
    sinal = 0
    for linha in saida.splitlines():
        limpa = linha.strip()
        if limpa.startswith("SSID:"):
            ssid = limpa.split(":", 1)[1].strip()
        elif limpa.startswith("freq:"):
            achado = re.search(r"(\d+)", limpa)
            if achado:
                frequencia = int(achado.group(1))
        elif limpa.startswith("signal:"):
            achado = re.search(r"(-?\d+)", limpa)
            if achado:
                sinal = int(achado.group(1))
    return ssid, frequencia, sinal


def ler_power_save(saida: str) -> bool | None:
    """Le `iw dev X get power_save`. None quando a resposta nao foi entendida."""
    texto = saida.lower()
    if "power save: on" in texto:
        return True
    if "power save: off" in texto:
        return False
    return None


def _bluetooth_ligado() -> bool:
    """Se ha um controlador Bluetooth ligado.

    `rfkill` diz apenas se o radio foi bloqueado; o que interessa aqui e se ele
    esta de fato em uso, e isso o `/sys/class/bluetooth` responde sem chamar
    programa nenhum.
    """
    try:
        controladores = list(Path("/sys/class/bluetooth").glob("hci*"))
    except OSError:  # pragma: no cover - sistema sem bluetooth
        return False
    for controlador in controladores:
        try:
            # 0 = desligado (`rfkill block`), 1 = ligado.
            if (controlador / "rfkill0" / "state").read_text().strip() != "0":
                return True
        except OSError:
            # Sem o no de rfkill exposto: a existencia do controlador ja e o
            # melhor sinal disponivel.
            return True
    return False


def _rodar(*comando: str) -> str:
    try:
        pronto = subprocess.run(comando, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("comando %s falhou: %s", comando[0], exc)
        return ""
    return pronto.stdout or pronto.stderr
