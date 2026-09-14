"""Testes da ponte Bluetooth.

Nao precisam de radio: o que se testa aqui e o tratamento das linhas que chegam
pelo BLE, que e logica pura — a mesma que o firmware do ESP32 fazia em C++.
"""

from __future__ import annotations

import pytest

from roboteye.ble import NUS_RX, NUS_SERVICE, NUS_TX, PonteBLE
from roboteye.ble.nus import MAX_LINHA


@pytest.fixture
def recebidos() -> list[dict]:
    return []


@pytest.fixture
def ponte(recebidos: list[dict]) -> PonteBLE:
    return PonteBLE(recebidos.append)


def escrever(ponte: PonteBLE, dados: bytes) -> None:
    """Simula um pacote BLE chegando na caracteristica de escrita."""
    ponte.aoReceber(list(dados))


class TestProtocolo:
    def testOsUuidsSaoOsDoNordicUartService(self) -> None:
        # Os mesmos do firmware do ESP32 e do RobotBleIds no app. Mudar aqui
        # sem mudar la faz o app parar de achar o robo.
        assert NUS_SERVICE == "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
        assert NUS_RX == "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
        assert NUS_TX == "6e400003-b5a3-f393-e0a9-e50e24dcca9e"


class TestLinhasQueChegam:
    def testComandoSimples(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        escrever(ponte, b'{"cmd":"F"}\n')
        assert recebidos == [{"cmd": "F"}]

    def testDuasMensagensNoMesmoPacote(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # Um pacote BLE pode trazer mais de uma linha colada.
        escrever(ponte, b'{"cmd":"F"}\n{"cmd":"S"}\n')
        assert recebidos == [{"cmd": "F"}, {"cmd": "S"}]

    def testMensagemPartidaEmDoisPacotes(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # E uma linha pode chegar pela metade.
        escrever(ponte, b'{"cmd":')
        assert recebidos == []
        escrever(ponte, b'"F"}\n')
        assert recebidos == [{"cmd": "F"}]

    def testLinhaSemQuebraAindaNaoEComando(
        self, ponte: PonteBLE, recebidos: list[dict]
    ) -> None:
        escrever(ponte, b'{"cmd":"F"}')
        assert recebidos == []

    def testLinhaEmBrancoEIgnorada(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        escrever(ponte, b"\n\n")
        assert recebidos == []


class TestLixoNaLinha:
    def testJsonInvalidoNaoDerrubaAPonte(
        self, ponte: PonteBLE, recebidos: list[dict]
    ) -> None:
        escrever(ponte, b"nao sou json\n")
        assert recebidos == []
        # E a proxima mensagem boa continua funcionando.
        escrever(ponte, b'{"cmd":"F"}\n')
        assert recebidos == [{"cmd": "F"}]

    def testJsonQueNaoEObjetoERecusado(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # `[1,2,3]` e JSON valido e nao e um comando.
        escrever(ponte, b"[1,2,3]\n")
        assert recebidos == []

    def testLinhaLongaDemaisEDescartada(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # Sem teto, um fluxo sem quebra de linha encheria a memoria. O teto vem
        # da constante, e nao de um numero escrito aqui: repetir o valor faria
        # este teste continuar verde depois de o limite mudar de um lado so.
        escrever(ponte, b"x" * (MAX_LINHA + 1))
        assert recebidos == []
        escrever(ponte, b'{"cmd":"F"}\n')
        assert recebidos == [{"cmd": "F"}]

    def testOTetoDaLinhaEOMesmoDoEsp32(self) -> None:
        """`MAX_LINE` no `esp32_ble_bridge.ino` e o fatiamento da rota no app.

        As duas pontes (ESP32 e Pi) precisam aceitar exatamente as mesmas
        mensagens: com limites diferentes, uma mensagem entre um teto e o outro
        funciona por um caminho e some pelo outro, sem erro em lugar nenhum.
        """
        assert MAX_LINHA == 512


class TestQuandoOCelularSome:
    def testDesconectarMandaParar(self, ponte: PonteBLE, recebidos: list[dict]) -> None:
        # O app manda "F" quando o dedo desce e "S" quando sobe. Se a conexao
        # morre entre os dois, o "S" nunca chega — e o robo fica andando.
        escrever(ponte, b'{"cmd":"F"}\n')
        ponte.aoDesconectar()
        assert recebidos[-1] == {"tipo": "parada_emergencia"}

    def testSobraDeLinhaNaoAtravessaConexoes(
        self, ponte: PonteBLE, recebidos: list[dict]
    ) -> None:
        # Meia mensagem de uma conexao nao pode se juntar com a metade de
        # outra e virar um comando que ninguem mandou.
        escrever(ponte, b'{"cmd":')
        ponte.aoDesconectar()
        ponte.aoConectar()
        escrever(ponte, b'"F"}\n')
        assert {"cmd": "F"} not in recebidos


class TestPacoteDeAnuncio:
    """O pacote que vai no ar, byte a byte.

    Errar aqui nao da erro em lugar nenhum: o robo anuncia, o celular ve outro
    servico (ou nenhum) e simplesmente nao acha o Atlas.
    """

    def testOUuidVaiEmOrdemInversa(self) -> None:
        from roboteye.ble.nus import dadosDeAnuncio

        # O Bluetooth manda os UUIDs em little-endian. Na ordem natural, o
        # celular procuraria um servico que nao existe.
        pacote = dadosDeAnuncio("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
        assert pacote == "11079ecadc240ee5a9e093f3a3b50100406e"

    def testOCabecalhoDizTamanhoETipo(self) -> None:
        from roboteye.ble.nus import dadosDeAnuncio

        pacote = dadosDeAnuncio(NUS_SERVICE)
        assert pacote[:2] == "11", "17 bytes seguem"
        assert pacote[2:4] == "07", "lista completa de UUIDs de 128 bits"
        assert len(bytes.fromhex(pacote)) == 18

    def testONomeCabeNaRespostaDeVarredura(self) -> None:
        from roboteye.ble.nus import dadosDeNome

        pacote = dadosDeNome("Atlas")
        assert pacote == "060941746c6173"
        assert bytes.fromhex(pacote)[2:].decode() == "Atlas"

    def testNomeLongoECortado(self) -> None:
        from roboteye.ble.nus import dadosDeNome

        # A resposta de varredura tambem tem 31 bytes; um nome enorme faria o
        # kernel recusar o anuncio inteiro.
        pacote = dadosDeNome("A" * 60)
        assert len(bytes.fromhex(pacote)) <= 31
