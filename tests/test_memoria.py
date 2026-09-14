"""Testes do relatório de memória (`roboteye memoria`).

Tudo aqui roda contra um `/proc` de mentira montado num diretório temporário:
a medida real depende da máquina, e um teste que dependesse dela passaria ou
falharia conforme o que mais estivesse aberto.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from roboteye import memoria

MEMINFO = """\
MemTotal:        8062044 kB
MemFree:         4000000 kB
MemAvailable:    6000000 kB
SwapTotal:       1048576 kB
SwapFree:         524288 kB
CmaTotal:         327680 kB
"""


def processo(raiz: Path, pid: int, *, comando: str, comm: str, rssKb: int) -> None:
    """Monta em disco um processo como o kernel o exporia."""
    pasta = raiz / str(pid)
    pasta.mkdir()
    # O kernel separa os argumentos por NUL, e é assim que o módulo os lê.
    (pasta / "cmdline").write_bytes(comando.replace(" ", "\x00").encode() + b"\x00")
    (pasta / "comm").write_text(f"{comm}\n")
    (pasta / "status").write_text(f"Name:\t{comm}\nVmRSS:\t{rssKb} kB\n")


@pytest.fixture
def procFalso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raiz = tmp_path / "proc"
    raiz.mkdir()
    (raiz / "meminfo").write_text(MEMINFO)
    monkeypatch.setattr(memoria, "PROC", raiz)
    return raiz


class TestLeituraDoSistema:
    def testConverteParaMib(self, procFalso: Path) -> None:
        relatorio = memoria.medir()
        assert relatorio.totalMib == 7873
        assert relatorio.disponivelMib == 5859
        assert relatorio.usadoMib == 2014
        # Metade do swap em uso: num Pi isso é o cartão SD no caminho crítico.
        assert relatorio.swapUsadoMib == 512
        assert relatorio.cmaMib == 320

    def testSemProcExplicaEmVezDeQuebrar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(memoria, "PROC", tmp_path / "nao-existe")
        relatorio = memoria.medir()
        assert relatorio.erro
        assert "Linux" in relatorio.render()


class TestQuemOcupa:
    def testAchaOsProcessosDoRoboDoMaiorParaOMenor(self, procFalso: Path) -> None:
        processo(procFalso, 10, comando="ollama serve", comm="ollama", rssKb=1_500_000)
        processo(
            procFalso,
            11,
            comando="/opt/atlas/.venv/bin/roboteye face --fullscreen",
            comm="roboteye",
            rssKb=250_000,
        )
        processo(procFalso, 12, comando="/usr/bin/sshd -D", comm="sshd", rssKb=9_000)

        rotulos = [(p.rotulo, p.rssMib) for p in memoria.medir().processos]
        assert rotulos == [("Ollama (servidor)", 1464), ("face (pygame)", 244)]

    def testMencionarOOllamaNaoFazDeNinguemOOllama(self, procFalso: Path) -> None:
        # O próprio comando que faz esta medida recebe o endereço do Ollama como
        # argumento — casar por trecho da linha o contaria como inquilino.
        processo(
            procFalso,
            20,
            comando="python3 -c medir(ollama_host=http://127.0.0.1:11434)",
            comm="python3",
            rssKb=30_000,
        )
        assert memoria.medir().processos == []

    def testProcessoQueSomeNoMeioDaLeituraEIgnorado(self, procFalso: Path) -> None:
        # Entre listar `/proc` e ler os arquivos o processo pode ter morrido.
        # Isso é rotina, não erro — e não pode derrubar o relatório.
        (procFalso / "99").mkdir()
        assert memoria.medir().processos == []


class TestVeredito:
    def testComFolgaParaAReservaSubir(self, procFalso: Path) -> None:
        relatorio = memoria.medir()
        assert relatorio.folgado
        assert "folga" in relatorio.render()

    def testSemFolgaApontaOQueAjustar(self) -> None:
        apertado = memoria.RelatorioMemoria(totalMib=8000, disponivelMib=800)
        assert not apertado.folgado
        assert "KEEP_ALIVE" in apertado.render()

    def testOJsonLevaOsMesmosNumeros(self, procFalso: Path) -> None:
        import json

        dados = json.loads(memoria.renderJson(memoria.medir()))
        assert dados["total_mib"] == 7873
        assert dados["uso_pct"] == pytest.approx(25.6, abs=0.1)
