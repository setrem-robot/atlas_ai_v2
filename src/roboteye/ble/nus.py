"""Ponte Bluetooth: o celular manda comandos direto para o Pi.

Hoje o caminho de um comando de motor e celular -> BLE -> ESP32 -> serial -> Pi.
O ESP32 nao interpreta nada: confere que a mensagem e JSON e repassa pelo fio.
E o Pi tem radio Bluetooth proprio, parado.

Esta ponte assume o papel que o ESP32 fazia. O detalhe que torna a troca barata
e que o ESP32 anuncia um servico **padrao** — o Nordic UART Service —, entao
anunciando o mesmo servico, com os mesmos UUIDs e o mesmo formato de mensagem,
**o app nao precisa saber que o hardware mudou**. Muda so o nome que aparece na
busca.

O que chega aqui vai para o mesmo lugar de sempre: `robo/comando/entrada`, o
topico que o `serial_ingestor` alimentava. O orquestrador e os motores nao sabem
a diferenca.

**Perder a conexao para o robo.** O app manda "F" quando o dedo desce e "S"
quando sobe; se a conexao morre entre os dois, o "S" nunca chega. O firmware do
ESP32 aprendeu a mandar uma parada de emergencia ao perder o BLE, e esta ponte
faz o mesmo — direto no MQTT, sem atravessar serial nenhuma.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: Nordic UART Service. Os mesmos do `esp32_ble_bridge.ino` e do
#: `RobotBleIds` no app — mudou aqui, muda nos tres.
NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # o celular escreve aqui
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # o robo notifica aqui

#: Teto de uma linha. O ESP32 usa o mesmo limite; uma linha maior que isto e
#: lixo de transmissao, nao comando.
MAX_LINHA = 256


def _dados_de_anuncio(uuid: str) -> str:
    """Monta o pacote de anuncio com o UUID do servico, em hexadecimal.

    O formato e o do proprio Bluetooth: um byte de tamanho, um de tipo, e os
    dados. Tipo 0x07 e "lista completa de UUIDs de 128 bits", e o UUID vai em
    ordem inversa de bytes — o padrao manda little-endian, e trocar a ordem faz
    o celular procurar por um servico que nao existe.
    """
    bytes_uuid = bytes.fromhex(uuid.replace("-", ""))[::-1]
    return f"{len(bytes_uuid) + 1:02x}07{bytes_uuid.hex()}"


def _dados_de_nome(nome: str) -> str:
    """O nome vai na resposta de varredura: no anuncio nao cabe.

    Um anuncio tem 31 bytes e o UUID de 128 bits ja consome 18. Tipo 0x09 e
    "nome completo do dispositivo".
    """
    bruto = nome.encode("utf-8")[:20]
    return f"{len(bruto) + 1:02x}09{bruto.hex()}"


def anunciar_pelo_kernel(nome: str = "Atlas", uuid: str = NUS_SERVICE) -> bool:
    """Poe o anuncio no ar pelo `btmgmt`, falando direto com o kernel.

    O caminho normal seria o `bluetoothd`, mas neste controlador ele recusa
    todo registro de anuncio — inclusive um vazio, e inclusive vindo do
    `bluetoothctl` — com `Invalid Parameters (0x0d)`. Pelo kernel, o mesmo
    anuncio sobe: `Instance added: 1`, e o celular passa a encontrar o robo.
    """
    import subprocess

    def btmgmt(*args: str) -> subprocess.CompletedProcess:
        # `input=""` e nao `stdin=DEVNULL`, e a diferenca custou um servico que
        # nao subia: com a entrada apenas fechada, o `btmgmt` fica esperando
        # comandos do modo interativo e nunca retorna. Medido no robo: com
        # `DEVNULL` trava; com `input=""` volta em 0,0 s. Como servico, travar
        # aqui vira um arranque que expira em silencio depois de um minuto e meio.
        return subprocess.run(
            ["btmgmt", *args], capture_output=True, text=True, input="", timeout=15
        )

    # Nada de `advertising on` aqui, por mais tentador que pareca — e foi
    # tentador: o `advertising` aparece em `supported settings` e nao em
    # `current settings`, o que parece um radio desligado esperando ser ligado.
    #
    # Nao e. Esse comando liga o anuncio **legado**, que o kernel monta com
    # dados proprios, e ele sobrescreve a instancia registrada logo abaixo. O
    # radio passa a transmitir, o `current settings` passa a mostrar
    # `advertising`, tudo parece mais certo do que antes — e o celular deixa de
    # achar o robo, porque o UUID do servico nao esta mais no ar.
    #
    # Os dois modos se excluem. O nosso e o gerenciado, e com ele funcionando o
    # `current settings` **nao** mostra `advertising`. Confirmado no robo: com
    # o anuncio gerenciado sozinho, o app conecta com o Wi-Fi ligado, no mesmo
    # canal de 2,4 GHz e com o intervalo padrao de 1280 ms.
    btmgmt("rm-adv", "1")
    pronto = btmgmt(
        "add-adv",
        "-d",
        _dados_de_anuncio(uuid),
        "-s",
        _dados_de_nome(nome),
        # `-c` marca o anuncio como conectavel; sem isso o celular ve o robo e
        # nao consegue abrir conexao.
        "-c",
        "1",
    )
    if "Instance added" in pronto.stdout:
        logger.info("anunciando %r pelo bluetooth", nome)
        return True
    logger.error("nao consegui anunciar: %s", (pronto.stderr or pronto.stdout).strip()[:120])
    return False


class PonteBLE:
    """Recebe linhas JSON pelo BLE e as entrega a quem souber o que fazer.

    Nao conhece MQTT: recebe uma funcao para entregar o comando. E o mesmo
    desenho da pagina web e da escuta — quem monta as pecas e quem as liga.
    """

    def __init__(
        self,
        entregar: Callable[[dict], None],
        *,
        nome: str = "Atlas",
        adapter_address: str | None = None,
    ) -> None:
        self._entregar = entregar
        self._nome = nome
        self._adapter = adapter_address
        self._buffer = bytearray()
        self._conectado = False
        self._periferico = None

    # -- montagem ----------------------------------------------------------
    def _radio(self):
        """O adaptador Bluetooth a usar."""
        from bluezero import adapter

        disponiveis = list(adapter.Adapter.available())
        if not disponiveis:
            raise RuntimeError("nenhum radio bluetooth encontrado (o servico esta ligado?)")
        if self._adapter is None:
            return disponiveis[0]
        for radio in disponiveis:
            if radio.address == self._adapter:
                return radio
        raise RuntimeError(f"radio {self._adapter} nao encontrado")

    def montar(self):
        """Cria o periferico BLE, sem ainda anunciar."""
        from bluezero import peripheral

        radio = self._radio()
        endereco = radio.address

        # O nome vai no **alias do radio**, e nao no pacote de anuncio.
        #
        # Um anuncio BLE tem 31 bytes. Um UUID de 128 bits ocupa 18 deles, as
        # flags mais 3, e o nome nao cabe no que sobra — o BlueZ recusa o
        # registro inteiro com "Invalid Parameters (0x0d)", sem dizer qual
        # parametro. Pelo alias, o nome viaja na resposta de varredura, que e
        # outro pacote, e o app o le do mesmo jeito.
        try:
            radio.alias = self._nome
        except Exception as exc:
            # Amplo de proposito: o nome e conforto para quem procura no app,
            # nao requisito — o app filtra pelo UUID do servico.
            logger.debug("nao consegui nomear o radio (%s); segue sem nome", exc)

        p = peripheral.Peripheral(endereco)

        p.add_service(srv_id=1, uuid=NUS_SERVICE, primary=True)
        p.add_characteristic(
            srv_id=1,
            chr_id=1,
            uuid=NUS_RX,
            value=[],
            notifying=False,
            # `write-without-response` e o que o app usa: comando de direcao e
            # sempre substituivel, e esperar confirmacao de cada um so poria
            # atraso entre o dedo e a roda.
            flags=["write", "write-without-response"],
            write_callback=self._ao_receber,
        )
        p.add_characteristic(
            srv_id=1,
            chr_id=2,
            uuid=NUS_TX,
            value=[],
            notifying=False,
            flags=["notify"],
            notify_callback=self._ao_assinar,
        )
        p.on_connect = self._ao_conectar
        p.on_disconnect = self._ao_desconectar
        self._periferico = p
        return p

    def anunciar(self) -> None:
        """Poe o servico no ar e bloqueia. Roda numa thread propria.

        Nao usa o `publish()` da biblioteca, e a razao e concreta: ele registra
        o servico GATT e **em seguida** o anuncio, e o anuncio falha neste
        controlador (`Invalid Parameters (0x0d)` vindo do proprio chip). A
        excecao acontece antes do laco de eventos comecar — e sem laco, o
        servico que ja tinha sido registrado nao responde a ninguem. O celular
        entao encontra o robo, conecta, nao acha o servico e desiste.

        Aqui as duas coisas sao separadas: o anuncio vai pelo kernel, por
        `btmgmt` (ver `anunciar_pelo_kernel`), e o que fica neste processo e
        so o GATT, com o laco rodando.
        """
        p = self._periferico or self.montar()

        for objeto in (*p.services, *p.characteristics, *p.descriptors):
            p.app.add_managed_object(objeto)
        if not p.dongle.powered:
            p.dongle.powered = True
        p.srv_mng.register_application(p.app, {})

        logger.info("servico bluetooth no ar; o celular ja pode conectar")
        try:
            p.mainloop.run()
        except KeyboardInterrupt:
            p.mainloop.quit()

    # -- eventos do radio --------------------------------------------------
    def _ao_conectar(self, device=None) -> None:
        self._conectado = True
        self._buffer.clear()
        logger.info("celular conectado pelo bluetooth")

    def _ao_desconectar(self, adapter_address=None, device_address=None) -> None:
        self._conectado = False
        self._buffer.clear()
        # O celular pode ter sumido no meio de um movimento — saiu de alcance,
        # ficou sem bateria, o app foi fechado. Esta e a ultima coisa que a
        # ponte consegue fazer por quem esta na frente do robo.
        logger.warning("celular desconectou; mandando parar")
        self._entregar({"tipo": "parada_emergencia"})

    def _ao_assinar(self, notifying, characteristic) -> None:
        logger.debug("celular %s as respostas", "assinou" if notifying else "cancelou")

    # -- recepcao ----------------------------------------------------------
    def _ao_receber(self, value, options=None) -> None:
        """Um pacote BLE chegou. Pode trazer meia linha, ou duas coladas."""
        self._buffer.extend(bytes(value))
        if len(self._buffer) > MAX_LINHA:
            logger.warning("linha longa demais no bluetooth; descartando")
            self._buffer.clear()
            return

        while b"\n" in self._buffer:
            linha, _, resto = self._buffer.partition(b"\n")
            self._buffer = bytearray(resto)
            self._processar(linha.strip())

    def _processar(self, linha: bytes | bytearray) -> None:
        if not linha:
            return
        try:
            comando = json.loads(linha)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("bluetooth: linha invalida %r", linha[:60])
            return
        if not isinstance(comando, dict):
            logger.warning("bluetooth: esperava um objeto JSON, veio %s", type(comando).__name__)
            return
        self._entregar(comando)
