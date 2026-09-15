"""Onde o comando vai depois de chegar pelo Bluetooth.

O Pi recebe o Bluetooth direto e este modulo publica cada linha, sem
interpretar, em `robo/comando/entrada`.

O topico e o contrato do outro repositorio (`roboCommon/topics.py`). Mudar o
nome aqui sem mudar la faz o robo aceitar comandos e nao mover nada.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from roboteye.loggingSetup import getLogger

if TYPE_CHECKING:
    from paho.mqtt.client import Client

logger = getLogger(__name__)

#: O topico onde os comandos do app entram no barramento do robo.
TOPICO_ENTRADA = "robo/comando/entrada"


class EntregaMqtt:
    """Publica no broker local o que chegou pelo Bluetooth."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 1883,
        topico: str = TOPICO_ENTRADA,
        clientId: str = "roboteye-ble",
    ) -> None:
        self.host = host
        self.port = port
        self.topico = topico
        self.clientId = clientId
        self.cliente: Client | None = None

    def conectar(self) -> None:
        """Liga ao broker e passa a reconectar sozinho se ele cair."""
        import paho.mqtt.client as mqtt

        cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, clientId=self.clientId)
        # `loop_start` poe a reconexao numa thread propria: sem isso, um broker
        # que reinicia deixaria o Bluetooth funcionando e os motores mudos, sem
        # nada no log dizendo por que.
        cliente.connect_async(self.host, self.port, keepalive=30)
        cliente.loop_start()
        self.cliente = cliente
        logger.info("publicando comandos em %s (%s:%d)", self.topico, self.host, self.port)

    def fechar(self) -> None:
        if self.cliente is not None:
            self.cliente.loop_stop()
            self.cliente.disconnect()
            self.cliente = None

    def __call__(self, comando: dict) -> None:
        """Entrega um comando. Assinatura combinada com `PonteBLE`."""
        if self.cliente is None:
            logger.warning("sem conexao com o broker; comando descartado: %s", comando)
            return
        # QoS 1: um comando de direcao perdido e o robo seguindo em frente
        # quando alguem mandou parar.
        self.cliente.publish(self.topico, json.dumps(comando), qos=1)
