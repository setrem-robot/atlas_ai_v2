"""O que o robo esta recebendo do controle, agora.

A pagina ja mostrava como o robo esta (temperatura, memoria, servicos) e deixava
conversar com ele. Faltava a terceira coisa que se quer saber olhando para um
robo: **o que ele esta obedecendo**. Sem isso, quando o celular aperta "frente" e
nada acontece, nao ha como saber de que lado esta o problema — se o comando nao
saiu do app, se nao chegou ao Pi, ou se chegou e os motores nao responderam.

Escuta o mesmo topico que os motores escutam, e nao a ponte Bluetooth: assim
aparece tambem o que vier de outro lugar — do ESP32, se ainda estiver montado, ou
de um teste publicado a mao. O que a pagina mostra e o que o robo recebeu, nao o
que alguem acha que mandou.

Tolerante de proposito. Um broker fora do ar deixa este painel vazio e nao pode
derrubar a pagina, que serve para outras coisas — inclusive para descobrir que o
broker caiu.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from roboteye.logging_setup import get_logger

if TYPE_CHECKING:
    from paho.mqtt.client import Client

logger = get_logger(__name__)

#: O mesmo topico que a ponte Bluetooth alimenta e que o orquestrador assina.
TOPICO_ENTRADA = "robo/comando/entrada"

#: Quantos comandos guardar. O direcional de um celular gera dois por toque
#: (o movimento e o "parar" ao soltar), entao isto e cerca de meio minuto de
#: uso — o suficiente para ver o que acabou de acontecer, e pouco o bastante
#: para nao virar historico num processo que fica ligado o dia inteiro.
LIMITE = 40

#: Depois disto sem receber nada, o comando deixa de ser "o atual" e a pagina
#: mostra o robo como parado. Sem isso, um "frente" de dez minutos atras
#: continuaria aceso na tela como se o robo estivesse andando.
VALIDADE_S = 3.0

#: As letras que o app manda, e o que cada uma quer dizer.
DIRECOES = {
    "F": "frente",
    "B": "tras",
    "L": "esquerda",
    "R": "direita",
    "S": "parar",
}


class ComandosRecebidos:
    """Guarda os ultimos comandos que chegaram ao robo."""

    def __init__(self, limite: int = LIMITE) -> None:
        self._itens: deque[dict] = deque(maxlen=limite)
        self._lock = threading.Lock()
        self._cliente: Client | None = None

    # -- leitura -----------------------------------------------------------
    def instantaneo(self, agora: float | None = None) -> dict:
        """O comando valendo agora e os ultimos que chegaram."""
        momento = agora if agora is not None else time.time()
        with self._lock:
            itens = list(self._itens)

        atual = None
        if itens:
            ultimo = itens[-1]
            recente = momento - ultimo["quando"] <= VALIDADE_S
            # "Parar" nao expira: enquanto ninguem mandar outra coisa, o robo
            # continua parado, e e isso que a pagina deve mostrar.
            if recente or ultimo["direcao"] == "parar":
                atual = ultimo["direcao"]

        return {
            "atual": atual,
            "recebendo": bool(itens) and momento - itens[-1]["quando"] <= VALIDADE_S,
            "ultimos": [
                {"direcao": i["direcao"], "ha": round(momento - i["quando"], 1)}
                for i in reversed(itens[-12:])
            ],
            "total": len(itens),
        }

    def anotar(self, comando: dict, agora: float | None = None) -> None:
        """Registra um comando ja decodificado."""
        direcao = _direcao_de(comando)
        if direcao is None:
            return
        with self._lock:
            self._itens.append(
                {"direcao": direcao, "quando": agora if agora is not None else time.time()}
            )

    # -- ciclo de vida -----------------------------------------------------
    def escutar(self, *, host: str = "127.0.0.1", port: int = 1883) -> None:
        """Assina o topico de comandos. Nunca levanta."""
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            logger.debug("sem paho-mqtt; a pagina nao mostra os comandos recebidos")
            return

        def ao_conectar(cliente, _dados, _flags, _motivo, _propriedades=None) -> None:
            cliente.subscribe(TOPICO_ENTRADA, qos=1)
            logger.info("mostrando na pagina o que chega em %s", TOPICO_ENTRADA)

        def ao_receber(_cliente, _dados, mensagem) -> None:
            try:
                self.anotar(json.loads(mensagem.payload))
            except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
                logger.debug("comando ilegivel no topico; ignorado")

        try:
            cliente = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="roboteye-web")
            cliente.on_connect = ao_conectar
            cliente.on_message = ao_receber
            cliente.connect_async(host, port, keepalive=30)
            cliente.loop_start()
            self._cliente = cliente
        except Exception as exc:
            # Amplo de proposito: um broker fora do ar deixa este painel vazio
            # e nao pode derrubar a pagina — que serve, entre outras coisas,
            # para descobrir que o broker caiu.
            logger.debug("nao consegui escutar os comandos: %s", exc)

    def fechar(self) -> None:
        if self._cliente is not None:
            self._cliente.loop_stop()
            self._cliente.disconnect()
            self._cliente = None


def _direcao_de(comando: dict) -> str | None:
    """Traduz os dois formatos que o robo aceita numa direcao.

    O app manda a forma curta (`{"cmd":"F"}`); o formato expandido
    (`{"tipo":"motor","acao":"frente"}`) existe para quem publica direto no
    barramento. Ver `docs/contrato-mqtt.md` no repositorio do orquestrador.
    """
    if not isinstance(comando, dict):
        return None

    letra = comando.get("cmd")
    if isinstance(letra, str) and letra.upper() in DIRECOES:
        return DIRECOES[letra.upper()]

    if comando.get("tipo") == "motor":
        acao = comando.get("acao")
        if isinstance(acao, str) and acao in DIRECOES.values():
            return acao
    if comando.get("tipo") == "parada_emergencia":
        return "parar"
    return None
