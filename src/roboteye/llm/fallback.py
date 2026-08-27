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

from roboteye.llm.base import ChatMessage, LLMClient, LLMError, ModeloResidente
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: De quanto em quanto tempo a thread de fundo pergunta se a rede voltou.
DEFAULT_PROBE_INTERVAL = 10.0

#: Quanto tempo o modelo de reserva fica residente **enquanto ele e quem
#: responde**. Nao e o mesmo que o `fallback_keep_alive` da configuracao, que
#: vale para o estado normal (rede de pe, reserva fora da memoria).
KEEP_ALIVE_EM_USO = "5m"


class FallbackLLMClient:
    """Responde pela IA de rede; cai para a local quando ela some."""

    def __init__(
        self,
        primary: LLMClient,
        backup: LLMClient,
        *,
        probe_interval: float = DEFAULT_PROBE_INTERVAL,
        on_switch: Callable[[str], None] | None = None,
        keep_alive_ocioso: str = "0",
    ) -> None:
        self._primary = primary
        self._backup = backup
        self._probe_interval = max(0.0, probe_interval)
        self._on_switch = on_switch
        #: O mesmo objeto de `_backup`, quando ele sabe soltar a propria
        #: memoria. None para um reserva que nao ocupa RAM desta maquina —
        #: o `EchoClient` dos testes, por exemplo.
        self._residente = backup if isinstance(backup, ModeloResidente) else None
        #: Ultima troca de memoria pedida, para nao repetir o mesmo pedido a
        #: cada sondagem quando o estado nao mudou.
        self._memoria: threading.Thread | None = None
        #: Ultimo arranjo de memoria efetivamente aplicado. None enquanto
        #: nenhum foi — e o que faz o arranque valer como uma aplicacao.
        self._memoria_estado: bool | None = None
        #: Quanto tempo o reserva fica residente quando *nao* e ele quem
        #: responde. "0" devolve a memoria assim que ele termina de falar.
        self._keep_alive_ocioso = keep_alive_ocioso
        #: A persona, guardada no aquecimento. E o que o reserva precisa
        #: reprocessar se um dia tiver de assumir — sao ~500 tokens, e num Pi
        #: le-los custa segundos que ninguem quer pagar no meio de uma pergunta.
        self._prompt: Sequence[ChatMessage] = ()
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
        self._ajustar_memoria(up)
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

    # -- memoria do reserva -------------------------------------------------
    def _ajustar_memoria(self, primaria_no_ar: bool) -> None:
        """Poe o modelo de reserva na memoria, ou o tira dela.

        Num Raspberry Pi de 8 GB o modelo local ocupa mais de um giga o tempo
        todo — e, na maior parte desse tempo, sem responder nada: quem responde
        e a maquina de mesa. Deixa-lo residente "por garantia" e reservar a
        memoria do robo inteiro para o caso raro.

        O momento de carregar nao e a primeira pergunta depois da queda, e sim a
        **queda**. A sondagem descobre isso em ate `probe_interval` segundos, e
        e ali que este metodo manda ler o modelo do cartao — em segundo plano,
        enquanto ninguem esta esperando. Quando a rede volta, a memoria e
        devolvida na hora, sem esperar o tempo de expiracao do Ollama.
        """
        if self._residente is None:
            return
        # Idempotente de proposito: e chamado tanto pela troca de estado quanto
        # pelo arranque, e repetir o pedido significaria descarregar um modelo
        # que a chamada anterior acabou de mandar carregar.
        if self._memoria_estado is primaria_no_ar:
            return
        self._memoria_estado = primaria_no_ar

        # Uma troca anterior ainda em andamento: a de agora e mais recente e a
        # de la ja vai encontrar o estado mudado. Deixar as duas correrem juntas
        # renderia carregar e descarregar o mesmo modelo ao mesmo tempo.
        if self._memoria is not None and self._memoria.is_alive():
            self._memoria.join(timeout=0.1)

        alvo = self._soltar_reserva if primaria_no_ar else self._segurar_reserva
        thread = threading.Thread(target=alvo, name="llm-memoria-reserva", daemon=True)
        self._memoria = thread
        thread.start()

    def _segurar_reserva(self) -> None:
        """A rede caiu: o modelo local passa a valer a RAM que ocupa."""
        assert self._residente is not None
        self._residente.set_keep_alive(KEEP_ALIVE_EM_USO)
        try:
            self._backup.warm_up(self._prompt)
        except Exception as exc:
            # Amplo de proposito: se o reserva nao carregar agora, ele ainda
            # sera tentado na pergunta seguinte — so mais devagar.
            logger.debug("nao consegui preparar o modelo local: %s", exc)

    def _soltar_reserva(self) -> None:
        """A rede voltou: o modelo local devolve a memoria."""
        assert self._residente is not None
        self._residente.set_keep_alive(self._keep_alive_ocioso)
        self._residente.unload()

    # -- ciclo de vida -----------------------------------------------------
    def warm_up(self, messages: Sequence[ChatMessage] = ()) -> None:
        """Descobre quem esta de pe, aquece os dois e comeca a vigiar a rede.

        Perguntar primeiro e depois aquecer nao e detalhe de ordem. Aquecer a
        IA de rede quando ela nao existe significa esperar o tempo limite
        inteiro, e ate ele voltar o robo ainda se acha conectado — a primeira
        pergunta de quem chegou perto do robo seria justamente a que paga a
        espera. A pergunta barata (`is_available`) resolve isso em segundos.

        **So aquece quem vai responder.** Antes os dois eram aquecidos, o que
        deixava o modelo do Pi residente 24 horas por dia para um caso que
        acontece raramente — mais de um giga de RAM parada num robo que tambem
        precisa dela para a face e para a escuta. Hoje o reserva e carregado no
        instante em que a rede cai (ver `_ajustar_memoria`), que e cedo o
        bastante: a sondagem descobre a queda em segundos, e ninguem esta
        esperando por uma resposta nesse meio-tempo.
        """
        self._prompt = messages
        no_ar = self._primary.is_available()
        self._set_primary(no_ar)
        # Tambem no arranque, e nao so nas trocas: numa reinicializacao o Ollama
        # local pode ter ficado com o modelo carregado da execucao anterior, e
        # `_set_primary` nao mexe em memoria quando nada mudou. Quando ha o que
        # carregar, e esta chamada que o carrega — dai o reserva nao aparecer
        # abaixo.
        self._ajustar_memoria(no_ar)

        # Um reserva que nao ocupa memoria desta maquina nao tem o que gerenciar,
        # e `_ajustar_memoria` nao o teria aquecido.
        alvo = self._primary if no_ar else (None if self._residente else self._backup)
        if alvo is not None:
            try:
                alvo.warm_up(messages)
            except Exception as exc:
                # Amplo de proposito: um modelo que nao carrega nao pode impedir
                # o robo de subir com o outro.
                logger.debug("aquecimento de %s falhou: %s", alvo.name, exc)

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
