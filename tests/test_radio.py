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
    def test_le_ssid_frequencia_e_sinal(self) -> None:
        assert radio.ler_link(LINK_5GHZ) == ("Setrem", 5180, -47)

    def test_le_a_saida_curta_de_uma_conexao_em_24ghz(self) -> None:
        # A saída do `iw` varia com o que o driver reporta: sem taxa, sem RX/TX.
        # O que precisa sair certo é a frequência, que é o que decide a banda.
        assert radio.ler_link(LINK_24GHZ) == ("Setrem", 2437, -58)

    def test_sem_conexao_devolve_o_estado_neutro(self) -> None:
        # Não estar conectado é um estado normal do robô, não uma falha de
        # leitura: ele sobe antes de a rede existir.
        assert radio.ler_link(SEM_CONEXAO) == ("", 0, 0)

    def test_power_save(self) -> None:
        assert radio.ler_power_save("Power save: on") is True
        assert radio.ler_power_save("Power save: off") is False
        assert radio.ler_power_save("qualquer outra coisa") is None


class TestBanda:
    def test_5ghz(self) -> None:
        assert radio.EstadoRadio(frequencia_mhz=5180).banda == "5 GHz"

    def test_24ghz(self) -> None:
        assert radio.EstadoRadio(frequencia_mhz=2437).banda == "2,4 GHz"

    def test_sem_conexao_nao_tem_banda(self) -> None:
        assert radio.EstadoRadio().banda == ""


class TestDisputa:
    def test_em_24ghz_com_bluetooth_ligado_ha_disputa(self) -> None:
        estado = radio.EstadoRadio(ssid="Setrem", frequencia_mhz=2437, bluetooth_ligado=True)
        assert estado.disputando

    def test_em_5ghz_nao_ha(self) -> None:
        # É o ponto inteiro do exercício: o Bluetooth só existe em 2,4 GHz, e
        # levar o Wi-Fi para 5 GHz acaba com a disputa em vez de administrá-la.
        estado = radio.EstadoRadio(ssid="Setrem", frequencia_mhz=5180, bluetooth_ligado=True)
        assert not estado.disputando

    def test_sem_bluetooth_nao_ha(self) -> None:
        estado = radio.EstadoRadio(ssid="Setrem", frequencia_mhz=2437, bluetooth_ligado=False)
        assert not estado.disputando


class TestConselhos:
    def test_em_5ghz_e_sem_economia_nao_ha_o_que_dizer(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequencia_mhz=5180,
            power_save=False,
            bluetooth_ligado=True,
        )
        assert radio.aconselhar(estado) == []
        assert "não estão se atrapalhando" in radio.render(estado)

    def test_disputa_vira_comando_com_o_ssid_certo(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequencia_mhz=2437,
            power_save=False,
            bluetooth_ligado=True,
        )
        conselhos = radio.aconselhar(estado)
        assert len(conselhos) == 1
        assert "wifi.band a" in conselhos[0].comando
        assert "Setrem" in conselhos[0].comando

    def test_economia_ligada_tambem_vira_conselho(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequencia_mhz=5180,
            power_save=True,
            bluetooth_ligado=True,
        )
        conselhos = radio.aconselhar(estado)
        assert [c.titulo for c in conselhos] == ["desligar a economia de energia do Wi-Fi"]

    def test_os_dois_problemas_juntos_dao_os_dois_conselhos(self) -> None:
        estado = radio.EstadoRadio(
            interface="wlan0",
            ssid="Setrem",
            frequencia_mhz=2437,
            power_save=True,
            bluetooth_ligado=True,
        )
        assert len(radio.aconselhar(estado)) == 2

    def test_power_save_desconhecido_nao_inventa_conselho(self) -> None:
        # `None` é "não consegui ler", e não "está ligado": aconselhar por cima
        # de uma leitura que falhou mandaria mexer no que talvez já esteja certo.
        estado = radio.EstadoRadio(ssid="Setrem", frequencia_mhz=5180, power_save=None)
        assert radio.aconselhar(estado) == []


class TestRelatorio:
    def test_sem_radio_explica_em_vez_de_quebrar(self) -> None:
        assert "instalado" in radio.render(
            radio.EstadoRadio(erro="o comando `iw` não está instalado")
        )

    def test_mostra_a_banda_e_o_bluetooth(self) -> None:
        texto = radio.render(
            radio.EstadoRadio(
                interface="wlan0",
                ssid="Setrem",
                frequencia_mhz=2437,
                sinal_dbm=-58,
                power_save=False,
                bluetooth_ligado=True,
            )
        )
        assert "2,4 GHz" in texto
        assert "Bluetooth   ligado" in texto
        assert "separar-radios.sh" in texto
