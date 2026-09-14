"""Testes da escolha da placa de som."""

from __future__ import annotations

import pytest

from roboteye.speech import devices
from roboteye.speech.devices import resolverSaida


@pytest.fixture
def placas(monkeypatch):
    """Finge a lista de dispositivos e quais deles aceitam a taxa pedida."""

    def instalar(lista: list[dict], aceita: set[int] | None = None) -> None:
        monkeypatch.setattr(devices, "listar", lambda: lista)
        monkeypatch.setattr(devices, "aceita", lambda indice, taxa: indice in (aceita or set()))

    return instalar


def placa(nome: str, saidas: int = 2) -> dict:
    return {"name": nome, "max_output_channels": saidas, "max_input_channels": 0}


class TestValoresExplicitos:
    def testVazioDeixaOSistemaDecidir(self) -> None:
        assert resolverSaida("") is None
        assert resolverSaida(None) is None
        assert resolverSaida("   ") is None

    def testNumeroViraIndice(self) -> None:
        assert resolverSaida("2") == 2

    def testTextoVaiComoNome(self) -> None:
        # O sounddevice aceita pedaco do nome; nao cabe a nos interpretar.
        assert resolverSaida("USB PnP") == "USB PnP"

    def testAutoNaoDiferenciaMaiuscula(self, placas) -> None:
        placas([], aceita=set())
        assert resolverSaida("AUTO") is None


class TestAuto:
    def testEscolheAPlacaUsb(self, placas) -> None:
        placas([placa("vc4-hdmi-0"), placa("USB PnP Sound Device")], aceita={1})
        assert resolverSaida("auto") == 1

    def testSemUsbFicaComOPadrao(self, placas) -> None:
        placas([placa("vc4-hdmi-0"), placa("bcm2835 Headphones")], aceita={0, 1})
        assert resolverSaida("auto") is None

    def testUsbQueNaoAceitaATaxaVaiParaOPadrao(self, placas) -> None:
        # O caso real da C-Media: so aceita 44100 e 48000, e o Piper toca a
        # 22050. Falar com ela direto daria "Invalid sample rate"; pelo padrao
        # do sistema, o `plug` do ALSA converte e sai som.
        placas([placa("USB PnP Sound Device")], aceita=set())
        assert resolverSaida("auto") is None

    def testIgnoraOQueNaoToca(self, placas) -> None:
        placas([placa("USB Microphone", saidas=0), placa("USB Speaker")], aceita={0, 1})
        assert resolverSaida("auto") == 1

    def testIgnoraApelidosDoAlsa(self, placas) -> None:
        # "default" e "sysdefault" nao sao placas: escolher um deles devolveria
        # a decisao para o /etc/asound.conf, que e o que `auto` quer evitar.
        placas([placa("default"), placa("sysdefault"), placa("USB Audio")], aceita={0, 1, 2})
        assert resolverSaida("auto") == 2

    def testSemAudioNoSistemaNaoDerruba(self, monkeypatch) -> None:
        monkeypatch.setattr(
            devices, "listar", lambda: (_ for _ in ()).throw(OSError("sem PortAudio"))
        )
        assert resolverSaida("auto") is None
