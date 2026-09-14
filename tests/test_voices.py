"""Testes do catálogo de vozes (sem baixar nada da rede)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from roboteye import voices
from roboteye.voiceCatalog import DEFAULT_VOICE
from roboteye.voices import CATALOG, VoiceDownloadError, downloadVoice


class TestCatalogo:
    def testAVozPadraoExiste(self) -> None:
        assert DEFAULT_VOICE in CATALOG

    def testTodaVozLocalTemModeloEConfiguracao(self) -> None:
        for spec in CATALOG.values():
            assert spec.description
            if not spec.modelUrl:
                continue  # voz da nuvem: não há arquivo para baixar
            assert spec.modelUrl.endswith(".onnx")
            assert spec.configUrl  # .onnx.json no Piper, pacote de vozes no Kokoro

    def testBaixarVozOnlineExplicaQueNaoHaArquivo(self, tmp_path: Path) -> None:
        with pytest.raises(VoiceDownloadError, match="nuvem"):
            downloadVoice("thalita", modelsDir=tmp_path)

    def testCaminhosDeDestino(self, tmp_path: Path) -> None:
        modelo, config = CATALOG["dii"].targetPaths(tmp_path)
        assert modelo == tmp_path / "dii" / "dii.onnx"
        assert config == tmp_path / "dii" / "dii.onnx.json"


class TestDownload:
    def testVozDesconhecidaListaAsOpcoes(self, tmp_path: Path) -> None:
        with pytest.raises(VoiceDownloadError, match="dii"):
            downloadVoice("inexistente", modelsDir=tmp_path)

    def testNaoRebaixaOQueJaExiste(self, tmp_path: Path, monkeypatch) -> None:
        modelo, config = CATALOG["dii"].targetPaths(tmp_path)
        modelo.parent.mkdir(parents=True)
        modelo.write_bytes(b"modelo")
        config.write_text("{}")

        def falhar(*_: object, **__: object) -> None:
            raise AssertionError("não deveria baixar nada")

        monkeypatch.setattr(voices, "download", falhar)

        assert downloadVoice("dii", modelsDir=tmp_path) == modelo

    def testBaixaModeloEConfiguracao(self, tmp_path: Path, monkeypatch) -> None:
        baixados: list[str] = []

        def fakeDownload(url: str, destino: Path, progress) -> None:
            baixados.append(destino.name)
            destino.write_bytes(b"conteudo")

        monkeypatch.setattr(voices, "download", fakeDownload)

        caminho = downloadVoice("dii", modelsDir=tmp_path)

        assert sorted(baixados) == ["dii.onnx", "dii.onnx.json"]
        assert caminho.is_file()

    def testErroDeRedeViraExcecaoDoDominio(self, tmp_path: Path, monkeypatch) -> None:
        def explode(*_: object, **__: object):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "stream", explode)

        with pytest.raises(VoiceDownloadError, match="falha ao baixar"):
            downloadVoice("dii", modelsDir=tmp_path)

    def testArquivoParcialERemovidoAposFalha(self, tmp_path: Path, monkeypatch) -> None:
        def explode(*_: object, **__: object):
            raise httpx.ConnectError("sem rede")

        monkeypatch.setattr(httpx, "stream", explode)

        with pytest.raises(VoiceDownloadError):
            downloadVoice("dii", modelsDir=tmp_path)

        assert list((tmp_path / "dii").glob("*.part")) == []


class TestProgresso:
    def testBarraNaoQuebraSemTamanhoTotal(self, capsys) -> None:
        voices.consoleProgress("modelo.onnx", 1_048_576, None)
        assert "1.0 MB" in capsys.readouterr().out

    def testBarraMostraPorcentagem(self, capsys) -> None:
        voices.consoleProgress("modelo.onnx", 50, 100)
        assert "50%" in capsys.readouterr().out
