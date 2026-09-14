"""Onde a memoria do robo esta indo (`roboteye memoria`).

O Pi 5 tem 8 GB e tres inquilinos grandes disputando: o modelo de linguagem
local, o modelo de escuta e a face. Nenhum deles aparece no `free -h`, que so
diz quanto sobrou — nao *de quem* era o que acabou. Este modulo responde a
segunda pergunta, que e a unica acionavel.

Le tudo de `/proc` e da API do Ollama; nao ha dependencia nova. Onde nao houver
`/proc` (Windows, macOS) o relatorio sai vazio com o motivo, em vez de quebrar.

Convencao de unidade: **MiB inteiros** em todo o modulo. Memoria de processo em
bytes exatos e precisao falsa — o valor muda entre duas leituras seguidas.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from roboteye.loggingSetup import getLogger

logger = getLogger(__name__)

PROC = Path("/proc")

#: Processos reconhecidos pelo **nome do executavel** (`/proc/pid/comm`).
#: Casar por trecho da linha de comando aqui daria falso positivo em qualquer
#: coisa que mencione "ollama" de passagem — inclusive neste proprio comando,
#: que recebe o endereco do Ollama como argumento.
_EXECUTAVEIS: dict[str, str] = {
    "ollama": "Ollama (servidor)",
    "mosquitto": "broker MQTT",
}

#: Processos reconhecidos pelo **subcomando** na linha. Sao todos `python`, e o
#: executavel nao os distingue: quem separa a face da ponte bluetooth e o
#: argumento.
_SUBCOMANDOS: tuple[tuple[str, str], ...] = (
    ("roboteye face", "face (pygame)"),
    ("roboteye run", "face + chat"),
    ("roboteye chat", "chat"),
    ("roboteye web", "pagina de configuracao"),
    ("roboteye ble", "ponte bluetooth"),
    ("-m orquestrador", "orquestrador (corpo)"),
    ("-m motores", "motores"),
    ("-m gps", "GPS"),
    ("-m wifi", "Wi-Fi"),
)

#: Acima disto o robo esta sem folga para o modelo local subir quando a rede
#: cair. Nao e um limite do sistema — e o ponto em que a reserva deixa de caber.
LIMITE_USO_PCT = 70.0

#: Quanto cada inquilino ocupa quando esta bem, em MiB. Medido, e nao estimado:
#:
#:   face (pygame + numpy, 800x480)   70 MiB, estavel apos 16 mil quadros
#:   escuta (whisper base, int8)     276 MiB, estavel apos cinco transcricoes
#:
#: Estao aqui porque a suspeita natural — "a tela e a escuta e que estao comendo
#: a memoria" — e falsa por uma ordem de grandeza, e sem um numero ao lado do
#: outro ela volta toda vez. Num Pi de 8 GB os dois juntos sao ~4%; quem ocupa
#: giga e o modelo de linguagem. Servem tambem de alarme: uma face em 300 MiB
#: nao e uma face grande, e uma face com defeito.
_ESPERADO_MIB: dict[str, int] = {
    "face (pygame)": 70,
    "face + chat": 70,
    "ponte bluetooth": 40,
    "pagina de configuracao": 40,
    "broker MQTT": 15,
}

#: Quantas vezes acima do esperado um processo precisa estar para merecer
#: destaque. Dois e folgado de proposito: a escuta entra e sai do mesmo
#: processo da face, e um teto apertado acusaria isso como problema.
FATOR_DE_ALERTA = 3.0


@dataclass(frozen=True, slots=True)
class Processo:
    """Um processo do robo e o quanto ele ocupa de fato."""

    pid: int
    rotulo: str
    #: RSS: paginas realmente residentes. E o numero que importa quando a
    #: pergunta e "cabe mais um?" — o virtual conta memoria que nunca foi tocada.
    rssMib: int
    comando: str


@dataclass(frozen=True, slots=True)
class ModeloCarregado:
    """Um modelo que o Ollama esta segurando na memoria agora."""

    nome: str
    tamanhoMib: int
    #: Quando o Ollama pretende solta-lo. Vazio quando ele nao diz.
    expira: str = ""


@dataclass(slots=True)
class RelatorioMemoria:
    """Retrato da memoria do robo num instante."""

    totalMib: int = 0
    disponivelMib: int = 0
    swapUsadoMib: int = 0
    processos: list[Processo] = field(default_factory=list)
    modelos: list[ModeloCarregado] = field(default_factory=list)
    #: Memoria reservada para a tela (CMA). Sai do mesmo bolo de 8 GB.
    cmaMib: int = 0
    erro: str = ""

    @property
    def usadoMib(self) -> int:
        return max(0, self.totalMib - self.disponivelMib)

    @property
    def usoPct(self) -> float:
        if self.totalMib <= 0:
            return 0.0
        return 100.0 * self.usadoMib / self.totalMib

    @property
    def folgado(self) -> bool:
        return self.usoPct < LIMITE_USO_PCT

    def render(self) -> str:
        if self.erro:
            return f"\nMemoria do RobotEye\n{'=' * 60}\n{self.erro}\n"

        linhas = ["", "Memoria do RobotEye", "=" * 60]
        linhas.append(
            f"  total {self.totalMib} MiB · em uso {self.usadoMib} MiB "
            f"({self.usoPct:.0f}%) · livre {self.disponivelMib} MiB"
        )
        if self.swapUsadoMib:
            # Swap em uso num Pi significa cartao SD no caminho critico: a face
            # engasga e a transcricao demora, sem nada no log dizendo por que.
            linhas.append(f"  swap em uso: {self.swapUsadoMib} MiB — o cartão está no caminho")
        if self.cmaMib:
            linhas.append(f"  reservado para a tela (CMA): {self.cmaMib} MiB")

        linhas.append("")
        linhas.append("  Processos do robô")
        if self.processos:
            for p in self.processos:
                linhas.append(f"    {p.rssMib:>6} MiB  {p.rotulo} (pid {p.pid}){comparado(p)}")
        else:
            linhas.append("    (nenhum encontrado — o robô está parado?)")

        linhas.append("")
        linhas.append("  Modelos carregados no Ollama local")
        if self.modelos:
            for modelo in self.modelos:
                sufixo = f"  (expira em {modelo.expira})" if modelo.expira else ""
                linhas.append(f"    {modelo.tamanhoMib:>6} MiB  {modelo.nome}{sufixo}")
        else:
            linhas.append("    (nenhum — a reserva local não está ocupando memória)")

        linhas.append("=" * 60)
        if self.folgado:
            linhas.append("Há folga para a reserva local subir quando a rede cair.")
        else:
            linhas.append(
                f"Uso acima de {LIMITE_USO_PCT:.0f}%: quando o Wi-Fi cair, o modelo local "
                "pode não caber. Veja ROBOTEYE_LLM_KEEP_ALIVE e ROBOTEYE_LLM_NUM_CTX."
            )
        return "\n".join(linhas)

    def asDict(self) -> dict:
        """Mesmo conteudo em JSON, para a pagina web e para graficos."""
        return {
            "total_mib": self.totalMib,
            "disponivel_mib": self.disponivelMib,
            "usado_mib": self.usadoMib,
            "uso_pct": round(self.usoPct, 1),
            "swap_usado_mib": self.swapUsadoMib,
            "cma_mib": self.cmaMib,
            "processos": [
                {"pid": p.pid, "rotulo": p.rotulo, "rss_mib": p.rssMib} for p in self.processos
            ],
            "modelos": [
                {"nome": m.nome, "tamanho_mib": m.tamanhoMib, "expira": m.expira}
                for m in self.modelos
            ],
            "erro": self.erro,
        }


def comparado(processo: Processo) -> str:
    """Sufixo que situa o processo contra o que ja foi medido dele.

    So aparece quando ha do que reclamar: uma linha que repete "está normal" em
    todo processo vira ruido e some da leitura junto com o resto.
    """
    esperado = _ESPERADO_MIB.get(processo.rotulo)
    if esperado is None or processo.rssMib < esperado * FATOR_DE_ALERTA:
        return ""
    return f"  ← esperado ~{esperado} MiB"


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def medir(*, ollamaHost: str = "") -> RelatorioMemoria:
    """Monta o relatorio. `ollama_host` vazio pula a consulta ao Ollama."""
    if not PROC.is_dir():
        return RelatorioMemoria(erro="sem /proc: esta medida só faz sentido no Linux do robô")

    info = meminfo()
    relatorio = RelatorioMemoria(
        totalMib=info.get("MemTotal", 0),
        disponivelMib=info.get("MemAvailable", 0),
        swapUsadoMib=max(0, info.get("SwapTotal", 0) - info.get("SwapFree", 0)),
        cmaMib=info.get("CmaTotal", 0),
        processos=processos(),
        modelos=modelosCarregados(ollamaHost) if ollamaHost else [],
    )
    return relatorio


def meminfo() -> dict[str, int]:
    """Le `/proc/meminfo` em MiB. As linhas de la vem em kB."""
    valores: dict[str, int] = {}
    try:
        texto = (PROC / "meminfo").read_text()
    except OSError as exc:  # pragma: no cover - /proc existe mas nao le
        logger.debug("nao consegui ler meminfo: %s", exc)
        return valores

    for linha in texto.splitlines():
        chave, _, resto = linha.partition(":")
        partes = resto.split()
        if partes and partes[0].isdigit():
            valores[chave] = int(partes[0]) // 1024
    return valores


def processos() -> list[Processo]:
    """Acha os processos do robo e mede o RSS de cada um.

    Percorrer `/proc` inteiro e barato (dezenas de diretorios) e evita depender
    do `ps`, que nem toda imagem Lite traz com as mesmas flags.
    """
    encontrados: list[Processo] = []
    eu = os.getpid()
    for entrada in PROC.iterdir():
        if not entrada.name.isdigit() or int(entrada.name) == eu:
            continue
        comando = cmdline(entrada)
        if not comando:
            continue
        rotulo = rotular(comando, comm(entrada))
        if rotulo is None:
            continue
        rss = rssMib(entrada)
        if rss is None:
            continue
        encontrados.append(
            Processo(pid=int(entrada.name), rotulo=rotulo, rssMib=rss, comando=comando)
        )

    encontrados.sort(key=lambda p: p.rssMib, reverse=True)
    return encontrados


def cmdline(diretorio: Path) -> str:
    try:
        bruto = (diretorio / "cmdline").read_bytes()
    except OSError:
        # O processo morreu entre listar e ler. Normal; nao e erro.
        return ""
    return bruto.replace(b"\x00", b" ").decode("utf-8", "replace").strip()


def comm(diretorio: Path) -> str:
    """Nome do executavel, sem caminho e sem argumentos."""
    try:
        return (diretorio / "comm").read_text().strip().lower()
    except OSError:
        return ""


def rotular(comando: str, executavel: str) -> str | None:
    """Nome humano do processo, ou None se ele nao e do robo."""
    if executavel in _EXECUTAVEIS:
        return _EXECUTAVEIS[executavel]
    minusculo = comando.lower()
    for marca, rotulo in _SUBCOMANDOS:
        if marca in minusculo:
            return rotulo
    return None


def rssMib(diretorio: Path) -> int | None:
    try:
        texto = (diretorio / "status").read_text()
    except OSError:
        return None
    for linha in texto.splitlines():
        if linha.startswith("VmRSS:"):
            partes = linha.split()
            if len(partes) >= 2 and partes[1].isdigit():
                return int(partes[1]) // 1024
    # Processo de kernel: nao tem RSS e nao interessa aqui.
    return None


def modelosCarregados(host: str) -> list[ModeloCarregado]:
    """Pergunta ao Ollama o que ele esta segurando na memoria agora.

    `/api/ps` e o equivalente do `ollama ps`, e e a unica forma honesta de saber
    isso: o RSS do processo do Ollama nao acompanha o modelo, que ele mapeia por
    fora do heap.
    """
    try:
        import httpx

        resposta = httpx.get(f"{host.rstrip('/')}/api/ps", timeout=3.0)
        resposta.raise_for_status()
        carregados = resposta.json().get("models", [])
    except Exception as exc:
        logger.debug("Ollama local nao respondeu ao /api/ps: %s", exc)
        return []

    modelos = []
    for item in carregados:
        modelos.append(
            ModeloCarregado(
                nome=str(item.get("name") or item.get("model") or "?"),
                tamanhoMib=int(item.get("size", 0)) // (1024 * 1024),
                expira=str(item.get("expires_at", ""))[:19].replace("T", " "),
            )
        )
    return modelos


def renderJson(relatorio: RelatorioMemoria) -> str:
    return json.dumps(relatorio.asDict(), ensure_ascii=False, indent=2)
