"""Onde o comando vai depois de chegar pelo Bluetooth.

O `serial_ingestor` do orquestrador lia linhas da serial e publicava cada uma em
`robo/comando/entrada`, sem interpretar. Com o Pi recebendo o Bluetooth direto,
essa ponte de serial deixa de existir — e este modulo faz a mesma coisa que ela
fazia, do outro lado do radio.

O topico e o contrato do outro repositorio (`robo_common/topics.py`). Mudar o
nome aqui sem mudar la faz o robo aceitar comandos e nao mover nada.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from roboteye.logging_setup import get_logger

if TYPE_CHECKING:
    from paho.mqtt.client import Client

logger = get_logger(__name__)

#: O mesmo topico que o `serial_ingestor` alimentava.
TOPICO_ENTRADA = "robo/comando/entrada"


class EntregaMqtt:
    """Publica no broker local o que chegou pelo Bluetooth."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 1883,
        topico: str = TOPICO_ENTRADA,
        client_id: str = "roboteye-ble",
    ) -> None:
        self._host = host
        self._port = port
        self._topico = topico
        self._client_id = client_id
        self._cliente: Client | None = None

    def conectar(self) -> None:
        """Liga ao broker e passa a reconectar sozinho se ele cair."""
        import paho.mqtt.client as mqtt

        cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self._client_id)
        # `loop_start` poe a reconexao numa thread propria: sem isso, um broker
        # que reinicia deixaria o Bluetooth funcionando e os motores mudos, sem
        # nada no log dizendo por que.
        cliente.connect_async(self._host, self._port, keepalive=30)
        cliente.loop_start()
        self._cliente = cliente
        logger.info("publicando comandos em %s (%s:%d)", self._topico, self._host, self._port)

    def fechar(self) -> None:
        if self._cliente is not None:
            self._cliente.loop_stop()
            self._cliente.disconnect()
            self._cliente = None

    def __call__(self, comando: dict) -> None:
        """Entrega um comando. Assinatura combinada com `PonteBLE`."""
        if self._cliente is None:
            logger.warning("sem conexao com o broker; comando descartado: %s", comando)
            return
        # QoS 1: um comando de direcao perdido e o robo seguindo em frente
        # quando alguem mandou parar.
        self._cliente.publish(self._topico, json.dumps(comando), qos=1)
