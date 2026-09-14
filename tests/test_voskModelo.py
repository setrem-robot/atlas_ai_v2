"""Qual modelo do Vosk a fábrica abre.

O caminho estava fixo em `vosk-pt`. Medidos neste Pi, os dois modelos de
português, a mesma fala:

    vosk-pt          52 MB no disco     76 MB de RAM   0,38-0,45x do tempo real
    vosk-pt-grande  2,6 GB no disco   2536 MB de RAM   0,05x do tempo real

O grande é **mais rápido**, não mais lento — fecha a frase em 34-55 ms contra
83-681 ms. O que ele custa é memória, e num Pi de 8 GB que também roda o Ollama
(~1,3 GB) isso é uma escolha, não um detalhe. Por isso é configurável.
"""

from __future__ import annotations

from pathlib import Path

from roboteye.config import HearingSettings


class TestQualModeloAFabricaAbre:
    def testOPadraoContinuaSendoOPequeno(self) -> None:
        """Trocar o padrão exigiria 2,6 GB no disco de quem instalar do zero."""
        assert HearingSettings().voskModel == "vosk-pt"

    def testAVariavelEscolheOutro(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_HEARING_VOSK_MODEL", "vosk-pt-grande")
        assert HearingSettings.fromEnv().voskModel == "vosk-pt-grande"

    def testSemAVariavelCaiNoPadrao(self, monkeypatch) -> None:
        monkeypatch.delenv("ROBOTEYE_HEARING_VOSK_MODEL", raising=False)
        assert HearingSettings.fromEnv().voskModel == "vosk-pt"

    def testAFabricaUsaOEscolhido(self, monkeypatch) -> None:
        """O que este teste cerca é o caminho fixo que existia antes.

        Sem ele, trocar a variável não mudaria nada e a única pista seria o
        robô continuar ouvindo mal — sem nada no log dizendo por quê.
        """
        from roboteye.hearing import factory

        vistos: list[Path] = []

        class OuvidoFalso:
            name = "vosk"

            def __init__(self, modelPath, **kwargs) -> None:
                vistos.append(Path(modelPath))

        import roboteye.hearing.voskEars as ve

        monkeypatch.setattr(ve, "VoskEars", OuvidoFalso)
        monkeypatch.setattr("roboteye.speech.devices.resolverEntrada", lambda d: None)

        ajustes = HearingSettings(
            enabled=True,
            backend="vosk",
            modelPath=Path("/modelos"),
            voskModel="vosk-pt-grande",
        )
        factory.createEars(ajustes)

        assert vistos == [Path("/modelos/vosk-pt-grande")]
