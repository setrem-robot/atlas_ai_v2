"""Testes da coexistência entre Wi-Fi e Bluetooth.

O que se testa aqui é a leitura da saída do `iw` e o conselho que sai dela —
tudo função pura. A coleta em si depende de um rádio real e fica de fora: um
teste que precisasse de Wi-Fi não rodaria nem nesta máquina nem no CI.
"""

from __future__ import annotations

from roboteye import radio

LINK_5GHZ = """\
Connected to dc:a6:32:00:00:01 (on wlan0)
	SSID: Setrem
	freq: 5180
	RX: 1234 bytes (10 packets)
	TX: 4321 bytes (12 packets)
	signal: -47 dBm
	tx bitrate: 195.0 MBit/s
"""

LINK_24GHZ = """\
Connected to dc:a6:32:00:00:02 (on wlan0)
	SSID: Setrem
	freq: 2437
	signal: -58 dBm
"""

SEM_CONEXAO = "Not connected.\n"


class TestLeituraDoLink:
    def testLeSsidFrequenciaESinal(self) -> None:
        assert radio.lerLink(LINK_5GHZ) == ("Setrem", 5180, -47)

    def testLeASaidaCurtaDeUmaConexaoEm24ghz(self) -> None:
        # A saída do `iw` varia com o que o driver reporta: sem taxa, sem RX/TX.
        # O que precisa sair certo é a frequência, que é o que decide a banda.
        assert radio.lerLink(LINK_24GHZ) == ("Setrem", 2437, -58)

    def testSemConexaoDevolveOEstadoNeutro(self) -> None:
        # Não estar conectado é um estado normal do robô, não uma falha de
        # leitura: ele sobe antes de a rede existir.
        assert radio.lerLink(SEM_CONEXAO) == ("", 0, 0)

    def testPowerSave(self) -> None:
        assert radio.lerPowerSave("Power save: on") is True
        assert radio.lerPowerSave("Power save: off") is False
        assert radio.lerPowerSave("qualquer outra coisa") is None


class TestBanda:
    def test5ghz(self) -> None:
        assert radio.EstadoRadio(frequenciaMhz=5180).banda == "5 GHz"

    def test24ghz(self) -> None:
        assert radio.EstadoRadio(frequenciaMhz=2437).banda == "2,4 GHz"

    def testSemConexaoNaoTemBanda(self) -> None:
        assert radio.EstadoRadio().banda == ""


class TestDisputa:
    def testEm24ghzComBluetoothLigadoHaDisputa(self) -> None:
        estado = radio.EstadoRadio(ssid="Setrem", frequenciaMhz=2437, bluetoothLigado=True)
        assert estado.disputando

    def testEm5ghzNaoHa(self) -> None:
        # É o ponto inteiro do exercício: o Bluetooth só existe em 2,4 GHz, e
        # levar o Wi-Fi para 5 GHz acaba com a disputa em vez de administrá-la.
        estado = radio.EstadoRadio(ssid="Setrem", frequenciaMhz=5180, bluetoothLigado=True)
        assert not estado.disputando

    def testSemBluetoothNaoHa(self) -> None:
        estado = radio.EstadoRadio(ssid="Setrem", frequenciaMhz=2437, bluetoothLigado=False)
        assert not estado.disputando


class TestConselhos:
    def testEm5ghzESemEconomiaNaoHaOQueDizer(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequenciaMhz=5180,
            powerSave=False,
            bluetoothLigado=True,
        )
        assert radio.aconselhar(estado) == []
        assert "não estão se atrapalhando" in radio.render(estado)

    def testDisputaViraComandoComOSsidCerto(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequenciaMhz=2437,
            powerSave=False,
            bluetoothLigado=True,
        )
        conselhos = radio.aconselhar(estado)
        assert len(conselhos) == 1
        assert "wifi.band a" in conselhos[0].comando
        assert "Setrem" in conselhos[0].comando

    def testEconomiaLigadaTambemViraConselho(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequenciaMhz=5180,
            powerSave=True,
            bluetoothLigado=True,
        )
        conselhos = radio.aconselhar(estado)
        assert [c.titulo for c in conselhos] == ["desligar a economia de energia do Wi-Fi"]

    def testOsDoisProblemasJuntosDaoOsDoisConselhos(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequenciaMhz=2437,
            powerSave=True,
            bluetoothLigado=True,
        )
        assert len(radio.aconselhar(estado)) == 2

    def testPowerSaveDesconhecidoNaoInventaConselho(self) -> None:
        # `None` é "não consegui ler", e não "está ligado": aconselhar por cima
        # de uma leitura que falhou mandaria mexer no que talvez já esteja certo.
        estado = radio.EstadoRadio(ssid="Setrem", frequenciaMhz=5180, powerSave=None)
        assert radio.aconselhar(estado) == []


class TestRelatorio:
    def testSemRadioExplicaEmVezDeQuebrar(self) -> None:
        assert "instalado" in radio.render(
            radio.EstadoRadio(erro="o comando `iw` não está instalado")
        )

    def testMostraABandaEOBluetooth(self) -> None:
        texto = radio.render(
            radio.EstadoRadio(
                interface="wlan0",
                ssid="Setrem",
                frequenciaMhz=2437,
                sinalDbm=-58,
                powerSave=False,
                bluetoothLigado=True,
            )
        )
        assert "2,4 GHz" in texto
        assert "Bluetooth   ligado" in texto
        assert "separar-radios.sh" in texto
