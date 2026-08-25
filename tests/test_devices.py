"""Testes da escolha da placa de som."""

from __future__ import annotations

import pytest

from roboteye.speech import devices
from roboteye.speech.devices import resolver_saida


@pytest.fixture
def placas(monkeypatch):
    """Finge a lista de dispositivos e quais deles aceitam a taxa pedida."""

    def instalar(lista: list[dict], aceita: set[int] | None = None) -> None:
        monkeypatch.setattr(devices, "_listar", lambda: lista)
        monkeypatch.setattr(devices, "_aceita", lambda indice, _taxa: indice in (aceita or set()))

    return instalar


def placa(nome: str, saidas: int = 2) -> dict:
    return {"name": nome, "max_output_channels": saidas, "max_input_channels": 0}


class TestValoresExplicitos:
    def test_vazio_deixa_o_sistema_decidir(self) -> None:
        assert resolver_saida("") is None
        assert resolver_saida(None) is None
        assert resolver_saida("   ") is None

    def test_numero_vira_indice(self) -> None:
        assert resolver_saida("2") == 2

    def test_texto_vai_como_nome(self) -> None:
        # O sounddevice aceita pedaco do nome; nao cabe a nos interpretar.
        assert resolver_saida("USB PnP") == "USB PnP"

    def test_auto_nao_diferencia_maiuscula(self, placas) -> None:
        placas([], aceita=set())
        assert resolver_saida("AUTO") is None


class TestAuto:
    def test_escolhe_a_placa_usb(self, placas) -> None:
        placas([placa("vc4-hdmi-0"), placa("USB PnP Sound Device")], aceita={1})
        assert resolver_saida("auto") == 1

    def test_sem_usb_fica_com_o_padrao(self, placas) -> None:
        placas([placa("vc4-hdmi-0"), placa("bcm2835 Headphones")], aceita={0, 1})
        assert resolver_saida("auto") is None

    def test_usb_que_nao_aceita_a_taxa_vai_para_o_padrao(self, placas) -> None:
        # O caso real da C-Media: so aceita 44100 e 48000, e o Piper toca a
        # 22050. Falar com ela direto daria "Invalid sample rate"; pelo padrao
        # do sistema, o `plug` do ALSA converte e sai som.
        placas([placa("USB PnP Sound Device")], aceita=set())
        assert resolver_saida("auto") is None

    def test_ignora_o_que_nao_toca(self, placas) -> None:
        placas([placa("USB Microphone", saidas=0), placa("USB Speaker")], aceita={0, 1})
        assert resolver_saida("auto") == 1

    def test_ignora_apelidos_do_alsa(self, placas) -> None:
        # "default" e "sysdefault" nao sao placas: escolher um deles devolveria
        # a decisao para o /etc/asound.conf, que e o que `auto` quer evitar.
        placas([placa("default"), placa("sysdefault"), placa("USB Audio")], aceita={0, 1, 2})
        assert resolver_saida("auto") == 2

    def test_sem_audio_no_sistema_nao_derruba(self, monkeypatch) -> None:
        monkeypatch.setattr(
            devices, "_listar", lambda: (_ for _ in ()).throw(OSError("sem PortAudio"))
        )
        assert resolver_saida("auto") is None
