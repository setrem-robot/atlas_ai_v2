"""Testes da ponte Bluetooth.

Nao precisam de radio: o que se testa aqui e o tratamento das linhas que chegam
pelo BLE, que e logica pura — a mesma que o firmware do ESP32 fazia em C++.
"""

from __future__ import annotations

import pytest

from roboteye.ble import NUS_RX, NUS_SERVICE, NUS_TX, PonteBLE


@pytest.fixture
def recebidos() -> list[dict]:
    return []


@pytest.fixture
def ponte(recebidos: list[dict]) -> PonteBLE:
    return PonteBLE(recebidos.append)


def escrever(ponte: PonteBLE, dados: bytes) -> None:
    """Simula um pacote BLE chegando na caracteristica de escrita."""
    ponte._ao_receber(list(dados))


class TestProtocolo:
    def test_os_uuids_sao_os_do_nordic_uart_service(self) -> None:
        # Os mesmos do firmware do ESP32 e do RobotBleIds no app. Mudar aqui
        # sem mudar la faz o app parar de achar o robo.
        assert NUS_SERVICE == "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
        assert NUS_RX == "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
        assert NUS_TX == "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


class TestLinhasQueChegam:
    def test_comando_simples(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        escrever(ponte, b'{"cmd":"F"}\n')
        assert recebidos == [{"cmd": "F"}]

    def test_duas_mensagens_no_mesmo_pacote(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # Um pacote BLE pode trazer mais de uma linha colada.
        escrever(ponte, b'{"cmd":"F"}\n{"cmd":"S"}\n')
        assert recebidos == [{"cmd": "F"}, {"cmd": "S"}]

    def test_mensagem_partida_em_dois_pacotes(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # E uma linha pode chegar pela metade.
        escrever(ponte, b'{"cmd":')
        assert recebidos == []
        escrever(ponte, b'"F"}\n')
        assert recebidos == [{"cmd": "F"}]

    def test_linha_sem_quebra_ainda_nao_e_comando(
        self, ponte: PonteBLE, recebidos: list[dict]
    ) -> None:
        escrever(ponte, b'{"cmd":"F"}')
        assert recebidos == []

    def test_linha_em_branco_e_ignorada(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        escrever(ponte, b"\n\n")
        assert recebidos == []


class TestLixoNaLinha:
    def test_json_invalido_nao_derruba_a_ponte(
        self, ponte: PonteBLE, recebidos: list[dict]
    ) -> None:
        escrever(ponte, b"nao sou json\n")
        assert recebidos == []
        # E a proxima mensagem boa continua funcionando.
        escrever(ponte, b'{"cmd":"F"}\n')
        assert recebidos == [{"cmd": "F"}]

    def test_json_que_nao_e_objeto_e_recusado(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # `[1,2,3]` e JSON valido e nao e um comando.
        escrever(ponte, b"[1,2,3]\n")
        assert recebidos == []

    def test_linha_longa_demais_e_descartada(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # Sem teto, um fluxo sem quebra de linha encheria a memoria.
        escrever(ponte, b"x" * 300)
        assert recebidos == []
        escrever(ponte, b'{"cmd":"F"}\n')
        assert recebidos == [{"cmd": "F"}]


class TestQuandoOCelularSome:
    def test_desconectar_manda_parar(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # O app manda "F" quando o dedo desce e "S" quando sobe. Se a conexao
        # morre entre os dois, o "S" nunca chega — e o robo fica andando.
        escrever(ponte, b'{"cmd":"F"}\n')
        ponte._ao_desconectar()
        assert recebidos[-1] == {"tipo": "parada_emergencia"}

    def test_sobra_de_linha_nao_atravessa_conexoes(
        self, ponte: PonteBLE, recebidos: list[dict]
    ) -> None:
        # Meia mensagem de uma conexao nao pode se juntar com a metade de
        # outra e virar um comando que ninguem mandou.
        escrever(ponte, b'{"cmd":')
        ponte._ao_desconectar()
        ponte._ao_conectar()
        escrever(ponte, b'"F"}\n')
        assert {"cmd": "F"} not in recebidos
