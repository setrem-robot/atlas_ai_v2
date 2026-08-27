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


def _processo(raiz: Path, pid: int, *, comando: str, comm: str, rss_kb: int) -> None:
    """Monta em disco um processo como o kernel o exporia."""
    pasta = raiz / str(pid)
    pasta.mkdir()
    # O kernel separa os argumentos por NUL, e é assim que o módulo os lê.
    (pasta / "cmdline").write_bytes(comando.replace(" ", "\x00").encode() + b"\x00")
    (pasta / "comm").write_text(f"{comm}\n")
    (pasta / "status").write_text(f"Name:\t{comm}\nVmRSS:\t{rss_kb} kB\n")


@pytest.fixture
def proc_falso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    raiz = tmp_path / "proc"
    raiz.mkdir()
    (raiz / "meminfo").write_text(MEMINFO)
    monkeypatch.setattr(memoria, "PROC", raiz)
    return raiz


class TestLeituraDoSistema:
    def test_converte_para_mib(self, proc_falso: Path) -> None:
        relatorio = memoria.medir()
        assert relatorio.total_mib == 7873
        assert relatorio.disponivel_mib == 5859
        assert relatorio.usado_mib == 2014
        # Metade do swap em uso: num Pi isso é o cartão SD no caminho crítico.
        assert relatorio.swap_usado_mib == 512
        assert relatorio.cma_mib == 320

    def test_sem_proc_explica_em_vez_de_quebrar(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(memoria, "PROC", tmp_path / "nao-existe")
        relatorio = memoria.medir()
        assert relatorio.erro
        assert "Linux" in relatorio.render()


class TestQuemOcupa:
    def test_acha_os_processos_do_robo_do_maior_para_o_menor(self, proc_falso: Path) -> None:
        _processo(proc_falso, 10, comando="ollama serve", comm="ollama", rss_kb=1_500_000)
        _processo(
            proc_falso,
            11,
            comando="/opt/atlas/.venv/bin/roboteye face --fullscreen",
            comm="roboteye",
            rss_kb=250_000,
        )
        _processo(proc_falso, 12, comando="/usr/bin/sshd -D", comm="sshd", rss_kb=9_000)

        rotulos = [(p.rotulo, p.rss_mib) for p in memoria.medir().processos]
        assert rotulos == [("Ollama (servidor)", 1464), ("face (pygame)", 244)]

    def test_mencionar_o_ollama_nao_faz_de_ninguem_o_ollama(self, proc_falso: Path) -> None:
        # O próprio comando que faz esta medida recebe o endereço do Ollama como
        # argumento — casar por trecho da linha o contaria como inquilino.
        _processo(
            proc_falso,
            20,
            comando="python3 -c medir(ollama_host=http://127.0.0.1:11434)",
            comm="python3",
            rss_kb=30_000,
        )
        assert memoria.medir().processos == []

    def test_processo_que_some_no_meio_da_leitura_e_ignorado(self, proc_falso: Path) -> None:
        # Entre listar `/proc` e ler os arquivos o processo pode ter morrido.
        # Isso é rotina, não erro — e não pode derrubar o relatório.
        (proc_falso / "99").mkdir()
        assert memoria.medir().processos == []


class TestVeredito:
    def test_com_folga_para_a_reserva_subir(self, proc_falso: Path) -> None:
        relatorio = memoria.medir()
        assert relatorio.folgado
        assert "folga" in relatorio.render()

    def test_sem_folga_aponta_o_que_ajustar(self) -> None:
        apertado = memoria.RelatorioMemoria(total_mib=8000, disponivel_mib=800)
        assert not apertado.folgado
        assert "KEEP_ALIVE" in apertado.render()

    def test_o_json_leva_os_mesmos_numeros(self, proc_falso: Path) -> None:
        import json

        dados = json.loads(memoria.render_json(memoria.medir()))
        assert dados["total_mib"] == 7873
        assert dados["uso_pct"] == pytest.approx(25.6, abs=0.1)
