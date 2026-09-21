"""Comandos de controle que chegam ao robo pelo barramento MQTT.

A face e a ponte Bluetooth sao dois processos separados: o app fala com a ponte,
a ponte publica em `robo/comando/entrada`, e quem quiser reagir assina esse
topico. Os motores ja fazem isso (pelo `orquestrador`); este modulo faz o mesmo
do lado da face, para o unico comando que e dela: o **switch de IA** do app
("IA local" / "IA nuvem").

Escuta o mesmo topico que os motores, e nao a ponte direto: assim um comando
publicado a mao no barramento — para testar — tambem vale.

Tolerante de proposito. Um broker fora do ar deixa o switch sem efeito e nao
pode derrubar a face; o robo segue conversando no modo em que estava.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from roboteye.loggingSetup import getLogger

if TYPE_CHECKING:
    from paho.mqtt.client import Client

logger = getLogger(__name__)

#: O mesmo topico que a ponte Bluetooth alimenta e que os motores assinam.
TOPICO_ENTRADA = "robo/comando/entrada"

#: Modos de IA que o switch do app pode pedir.
MODOS_IA = ("local", "nuvem")


class ControleRemoto:
    """Aplica no robo os comandos de controle vindos do barramento.

    Nao conhece o LLM: recebe uma funcao que troca a IA de modo. E o mesmo
    desenho da ponte e da pagina — quem monta as pecas e quem as liga.
    """

    def __init__(self, aoTrocarIa: Callable[[str], None]) -> None:
        self.aoTrocarIa = aoTrocarIa
        self.cliente: Client | None = None

    # -- despacho ----------------------------------------------------------
    def tratar(self, comando: dict) -> None:
        """Decide o que fazer com um comando ja decodificado."""
        if not isinstance(comando, dict) or comando.get("tipo") != "ia":
            return
        modo = comando.get("modo")
        if modo not in MODOS_IA:
            logger.warning("comando de IA com modo invalido: %r", modo)
            return
        logger.info("switch de IA recebido do app: %s", modo)
        self.aoTrocarIa(modo)

    # -- ciclo de vida -----------------------------------------------------
    def escutar(self, *, host: str = "127.0.0.1", port: int = 1883) -> None:
        """Assina o topico de comandos. Nunca levanta."""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.debug("sem paho-mqtt; o switch de IA do app nao tem efeito")
            return

        def aoConectar(cliente, dados, flags, motivo, propriedades=None) -> None:
            cliente.subscribe(TOPICO_ENTRADA, qos=1)
            logger.info("ouvindo o switch de IA em %s", TOPICO_ENTRADA)

        def aoReceber(cliente, dados, mensagem) -> None:
            try:
                self.tratar(json.loads(mensagem.payload))
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                logger.debug("comando ilegivel no topico; ignorado")

        try:
            cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="roboteye-controle")
            cliente.on_connect = aoConectar
            cliente.on_message = aoReceber
            cliente.connect_async(host, port, keepalive=30)
            cliente.loop_start()
            self.cliente = cliente
        except Exception as exc:
            # Amplo de proposito: um broker fora do ar deixa o switch sem efeito
            # e nao pode impedir a face de subir.
            logger.debug("nao consegui ouvir os comandos de controle: %s", exc)

    def fechar(self) -> None:
        if self.cliente is not None:
            self.cliente.loop_stop()
            self.cliente.disconnect()
            self.cliente = None
