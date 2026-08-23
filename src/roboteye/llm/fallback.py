"""IA de rede com reserva no proprio robo.

O modelo que responde melhor nao cabe no Pi: ele roda numa maquina de mesa, e o
caminho ate la passa pelo WiFi. WiFi cai — normalmente no meio de uma
apresentacao. Este cliente mantem os dois modelos e escolhe a cada pergunta:
fala com o da rede enquanto ele responder, e com o do proprio Pi quando nao.

**Descobrir a queda nao pode custar a resposta.** Um servidor que sumiu da rede
so se revela quando o tempo limite de conexao estoura, e pagar isso a cada
pergunta transformaria a queda do WiFi em segundos de silencio antes de cada
frase. Por isso quem vigia a rede e uma thread de fundo, e `stream_reply` apenas
le um sinalizador ja pronto: a unica pergunta que paga o preco da queda e a que
estava no ar quando ela aconteceu.

**A troca acontece antes do primeiro token.** O `Assistant` corta a resposta em
frases e manda falar assim que a primeira fecha; trocar de modelo depois disso
faria a Atlas recomecar a frase com outras palavras. Por isso o primeiro pedaco
e sempre pedido antes de comprometer a resposta.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Sequence

from roboteye.llm.base import ChatMessage, LLMClient, LLMError
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: De quanto em quanto tempo a thread de fundo pergunta se a rede voltou.
DEFAULT_PROBE_INTERVAL = 10.0


class FallbackLLMClient:
    """Responde pela IA de rede; cai para a local quando ela some."""

    def __init__(
        self,
        primary: LLMClient,
        backup: LLMClient,
        *,
        probe_interval: float = DEFAULT_PROBE_INTERVAL,
        on_switch: Callable[[str], None] | None = None,
    ) -> None:
        self._primary = primary
        self._backup = backup
        self._probe_interval = max(0.0, probe_interval)
        self._on_switch = on_switch
        #: Atributo, e nao propriedade: o protocolo `LLMClient` declara `name`
        #: como variavel, e uma propriedade so de leitura nao o satisfaz.
        self.name = "rede+local"

        # Comeca otimista. O `warm_up` corrige em seguida, e uma pergunta feita
        # antes dele apenas cai para o modelo local sozinha.
        self._primary_up = True
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._watcher: threading.Thread | None = None

    # -- estado ------------------------------------------------------------
    @property
    def using_primary(self) -> bool:
        """Quem responderia agora. Lido pelo `doctor` e pela pagina web."""
        with self._lock:
            return self._primary_up

    def _set_primary(self, up: bool) -> None:
        with self._lock:
            mudou = up != self._primary_up
            self._primary_up = up
        if not mudou:
            return
        # Uma resposta que vem do modelo pequeno e mais curta e mais simples que
        # a de costume. Sem aviso, isso passa por "a IA ficou burra" — e quem
        # esta vendo vai procurar o erro no modelo, que e o lugar onde ele nao esta.
        if up:
            logger.info("IA de rede de volta")
            self._notify("IA de rede de volta")
        else:
            logger.warning("IA de rede indisponivel; respondendo pelo modelo local")
            self._notify("respondendo pelo modelo local: a IA de rede nao respondeu")

    def _notify(self, message: str) -> None:
        if self._on_switch is not None:
            self._on_switch(message)

    # -- ciclo de vida -----------------------------------------------------
    def warm_up(self, messages: Sequence[ChatMessage] = ()) -> None:
        """Descobre quem esta de pe, aquece os dois e comeca a vigiar a rede.

        Perguntar primeiro e depois aquecer nao e detalhe de ordem. Aquecer a
        IA de rede quando ela nao existe significa esperar o tempo limite
        inteiro, e ate ele voltar o robo ainda se acha conectado — a primeira
        pergunta de quem chegou perto do robo seria justamente a que paga a
        espera. A pergunta barata (`is_available`) resolve isso em segundos.

        O reserva aquece de qualquer jeito, e pelo mesmo motivo que a voz
        reserva: de nada adianta trocar de modelo num milissegundo se o que
        assume ainda precisa ser lido do cartao SD, que e onde o Pi e mais lento.
        """
        self._set_primary(self._primary.is_available())

        alvos = [self._backup, self._primary] if self.using_primary else [self._backup]
        for client in alvos:
            try:
                client.warm_up(messages)
            except Exception as exc:
                # Amplo de proposito: um modelo que nao carrega nao pode
                # impedir o robo de subir com o outro.
                logger.debug("aquecimento de %s falhou: %s", client.name, exc)

        if self._watcher is None and self._probe_interval > 0:
            self._stop.clear()
            self._watcher = threading.Thread(
                target=self._watch, name="llm-fallback-probe", daemon=True
            )
            self._watcher.start()

    def close(self) -> None:
        self._stop.set()
        if self._watcher is not None:
            self._watcher.join(timeout=2.0)
            self._watcher = None
        self._primary.close()
        self._backup.close()

    def is_available(self) -> bool:
        return self._primary.is_available() or self._backup.is_available()

    def _watch(self) -> None:
        while not self._stop.wait(self._probe_interval):
            self._set_primary(self._primary.is_available())

    # -- inferencia --------------------------------------------------------
    def stream_reply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        if self.using_primary:
            stream = self._try_primary(messages)
            if stream is not None:
                yield from stream
                return

        yield from self._backup.stream_reply(messages)

    def _try_primary(self, messages: Sequence[ChatMessage]) -> Iterator[str] | None:
        """Devolve a resposta da rede, ou None se ela nao veio.

        O primeiro pedaco e forcado aqui dentro — a conexao so acontece nele — e
        e o que garante que a escolha entre um modelo e outro seja feita antes
        de qualquer palavra ir para a voz.
        """
        stream = self._primary.stream_reply(messages)
        try:
            first = next(stream)
        except StopIteration:
            return iter(())
        except LLMError as exc:
            logger.warning("IA de rede falhou (%s); usando o modelo local", exc)
            self._set_primary(False)
            return None

        return self._resume(first, stream)

    def _resume(self, first: str, stream: Iterator[str]) -> Iterator[str]:
        """Entrega o primeiro pedaco e segue com o resto da resposta.

        Cair no meio e outra historia: a Atlas ja falou a primeira frase, e
        refazer a resposta no outro modelo a faria recomecar do zero, em voz
        alta. A queda e anotada — a proxima pergunta ja nasce no modelo local —
        e o erro sobe para quem chamou, que e quem sabe avisar na tela.
        """
        yield first
        try:
            yield from stream
        except LLMError:
            logger.warning("a IA de rede caiu no meio da resposta")
            self._set_primary(False)
            raise
