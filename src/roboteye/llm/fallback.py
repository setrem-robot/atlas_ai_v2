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
from roboteye.loggingSetup import getLogger

logger = getLogger(__name__)

#: De quanto em quanto tempo a thread de fundo pergunta se a rede voltou.
DEFAULT_PROBE_INTERVAL = 10.0

#: Quanto tempo o modelo de reserva fica residente **enquanto ele e quem
#: responde**. Nao e o mesmo que o `fallback_keep_alive` da configuracao, que
#: vale para o estado normal (rede de pe, reserva fora da memoria).
#:
#: Qualquer duracao negativa e "nao descarregue" para o Ollama. **Com
#: unidade**: ele le este campo como duracao do Go, e `"-1"` sozinho e
#: recusado com `time: missing unit in duration "-1"` e um 400 na requisicao
#: inteira. Nao e o `keep_alive` que falha — e a pergunta.
#:
#: Eram cinco minutos, e cinco minutos jogavam fora justamente o que este
#: modulo se esforca para conseguir. Descarregar o modelo
#: leva junto o **cache do prompt**, e reler o prompt custa mais que responder:
#: medido neste robo, com a persona de 1968 tokens,
#:
#:     prompt processing   512/1968   39 tokens/s
#:     prompt processing  1024/1968   34 tokens/s
#:     [GIN] 500 | 1m0s | POST "/api/chat"
#:
#: sessenta segundos **sem chegar ao primeiro token** — o tempo limite estourou
#: ainda na leitura. Quem paga isso e sempre a pergunta seguinte a uma pausa de
#: cinco minutos, que e exatamente a primeira pergunta de quem chegou perto do
#: robo. O `warm_up` do arranque ja aquece esse cache; descarregar depois e
#: refazer o trabalho no pior momento possivel.
#:
#: O custo e um giga e pouco de RAM preso enquanto a rede estiver fora. Num Pi
#: de 8 GB com 4,4 livres, e o lado certo da troca.
KEEP_ALIVE_EM_USO = "-1s"


class FallbackLLMClient:
    """Responde pela IA de rede; cai para a local quando ela some."""

    def __init__(
        self,
        primary: LLMClient,
        backup: LLMClient,
        *,
        probeInterval: float = DEFAULT_PROBE_INTERVAL,
        onSwitch: Callable[[str], None] | None = None,
        keepAliveOcioso: str = "0",
    ) -> None:
        self.primary = primary
        self.backup = backup
        self.probeInterval = max(0.0, probeInterval)
        self.onSwitch = onSwitch
        #: O mesmo objeto de `_backup`, quando ele sabe soltar a propria
        #: memoria. None para um reserva que nao ocupa RAM desta maquina —
        #: o `EchoClient` dos testes, por exemplo.
        self.residente = backup if isinstance(backup, ModeloResidente) else None
        #: Ultima troca de memoria pedida, para nao repetir o mesmo pedido a
        #: cada sondagem quando o estado nao mudou.
        self.memoria: threading.Thread | None = None
        #: Ultimo arranjo de memoria efetivamente aplicado. None enquanto
        #: nenhum foi — e o que faz o arranque valer como uma aplicacao.
        self.memoriaEstado: bool | None = None
        #: Serializa o carregar/descarregar do reserva. Sem ele, uma rede que
        #: pisca (cai, volta, cai) em segundos poe `_segurar_reserva` e
        #: `_soltar_reserva` correndo juntas no mesmo modelo, e o estado final
        #: vira o de quem terminar por ultimo — o oposto do pedido.
        self.memoriaLock = threading.Lock()
        #: Quanto tempo o reserva fica residente quando *nao* e ele quem
        #: responde. "0" devolve a memoria assim que ele termina de falar.
        self.keepAliveOcioso = keepAliveOcioso
        #: A persona, guardada no aquecimento. E o que o reserva precisa
        #: reprocessar se um dia tiver de assumir — sao ~500 tokens, e num Pi
        #: le-los custa segundos que ninguem quer pagar no meio de uma pergunta.
        self.prompt: Sequence[ChatMessage] = ()
        #: Atributo, e nao propriedade: o protocolo `LLMClient` declara `name`
        #: como variavel, e uma propriedade so de leitura nao o satisfaz.
        self.name = "rede+local"

        # Comeca otimista. O `warm_up` corrige em seguida, e uma pergunta feita
        # antes dele apenas cai para o modelo local sozinha.
        self.primaryUp = True
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.watcher: threading.Thread | None = None

    # -- estado ------------------------------------------------------------
    @property
    def usingPrimary(self) -> bool:
        """Quem responderia agora. Lido pelo `doctor` e pela pagina web."""
        with self.lock:
            return self.primaryUp

    def setPrimary(self, up: bool) -> None:
        with self.lock:
            mudou = up != self.primaryUp
            self.primaryUp = up
        if not mudou:
            return
        self.ajustarMemoria(up)
        # Uma resposta que vem do modelo pequeno e mais curta e mais simples que
        # a de costume. Sem aviso, isso passa por "a IA ficou burra" — e quem
        # esta vendo vai procurar o erro no modelo, que e o lugar onde ele nao esta.
        if up:
            logger.info("IA de rede de volta")
            self.notify("IA de rede de volta")
        else:
            logger.warning("IA de rede indisponivel; respondendo pelo modelo local")
            self.notify("respondendo pelo modelo local: a IA de rede nao respondeu")

    def notify(self, message: str) -> None:
        if self.onSwitch is not None:
            self.onSwitch(message)

    # -- memoria do reserva -------------------------------------------------
    def ajustarMemoria(self, primariaNoAr: bool) -> None:
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
        if self.residente is None:
            return
        # Idempotente de proposito: e chamado tanto pela troca de estado quanto
        # pelo arranque, e repetir o pedido significaria descarregar um modelo
        # que a chamada anterior acabou de mandar carregar.
        if self.memoriaEstado is primariaNoAr:
            return
        self.memoriaEstado = primariaNoAr

        # A aplicacao roda numa thread para nao segurar a sondagem, mas serializada
        # pelo lock: uma troca so comeca quando a anterior terminou. E, antes de
        # agir, ela confere se ainda e a troca mais recente — se a rede mudou de
        # novo enquanto esta esperava o lock, quem manda e a mais nova, e esta
        # aqui sai sem tocar no modelo. E o que garante que o estado final e
        # sempre o ultimo pedido, e nao o da thread que por acaso terminou depois.
        thread = threading.Thread(
            target=self.aplicarMemoria,
            args=(primariaNoAr,),
            name="llm-memoria-reserva",
            daemon=True,
        )
        self.memoria = thread
        thread.start()

    def aplicarMemoria(self, primariaNoAr: bool) -> None:
        with self.memoriaLock:
            if self.memoriaEstado is not primariaNoAr:
                # Uma troca mais nova ja mudou o alvo; ela aplica o certo.
                return
            if primariaNoAr:
                self.soltarReserva()
            else:
                self.segurarReserva()

    def segurarReserva(self) -> None:
        """A rede caiu: o modelo local passa a valer a RAM que ocupa."""
        assert self.residente is not None
        self.residente.setKeepAlive(KEEP_ALIVE_EM_USO)
        try:
            self.backup.warmUp(self.prompt)
        except Exception as exc:
            # Amplo de proposito: se o reserva nao carregar agora, ele ainda
            # sera tentado na pergunta seguinte — so mais devagar.
            logger.debug("nao consegui preparar o modelo local: %s", exc)

    def soltarReserva(self) -> None:
        """A rede voltou: o modelo local devolve a memoria."""
        assert self.residente is not None
        self.residente.setKeepAlive(self.keepAliveOcioso)
        self.residente.unload()

    # -- ciclo de vida -----------------------------------------------------
    def warmUp(self, messages: Sequence[ChatMessage] = ()) -> None:
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
        self.prompt = messages
        noAr = self.primary.isAvailable()
        self.setPrimary(noAr)
        # Tambem no arranque, e nao so nas trocas: numa reinicializacao o Ollama
        # local pode ter ficado com o modelo carregado da execucao anterior, e
        # `_set_primary` nao mexe em memoria quando nada mudou. Quando ha o que
        # carregar, e esta chamada que o carrega — dai o reserva nao aparecer
        # abaixo.
        self.ajustarMemoria(noAr)

        # Um reserva que nao ocupa memoria desta maquina nao tem o que gerenciar,
        # e `_ajustar_memoria` nao o teria aquecido.
        alvo = self.primary if noAr else (None if self.residente else self.backup)
        if alvo is not None:
            try:
                alvo.warmUp(messages)
            except Exception as exc:
                # Amplo de proposito: um modelo que nao carrega nao pode impedir
                # o robo de subir com o outro.
                logger.debug("aquecimento de %s falhou: %s", alvo.name, exc)

        if self.watcher is None and self.probeInterval > 0:
            self.stop.clear()
            self.watcher = threading.Thread(
                target=self.watch, name="llm-fallback-probe", daemon=True
            )
            self.watcher.start()

    def close(self) -> None:
        self.stop.set()
        if self.watcher is not None:
            self.watcher.join(timeout=2.0)
            self.watcher = None
        self.primary.close()
        self.backup.close()

    def isAvailable(self) -> bool:
        return self.primary.isAvailable() or self.backup.isAvailable()

    def watch(self) -> None:
        while not self.stop.wait(self.probeInterval):
            self.setPrimary(self.primary.isAvailable())

    # -- inferencia --------------------------------------------------------
    def streamReply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        if self.usingPrimary:
            stream = self.tryPrimary(messages)
            if stream is not None:
                yield from stream
                return

        yield from self.backup.streamReply(messages)

    def tryPrimary(self, messages: Sequence[ChatMessage]) -> Iterator[str] | None:
        """Devolve a resposta da rede, ou None se ela nao veio.

        O primeiro pedaco e forcado aqui dentro — a conexao so acontece nele — e
        e o que garante que a escolha entre um modelo e outro seja feita antes
        de qualquer palavra ir para a voz.
        """
        stream = self.primary.streamReply(messages)
        try:
            first = next(stream)
        except StopIteration:
            return iter(())
        except LLMError as exc:
            logger.warning("IA de rede falhou (%s); usando o modelo local", exc)
            self.setPrimary(False)
            return None

        return self.resume(first, stream)

    def resume(self, first: str, stream: Iterator[str]) -> Iterator[str]:
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
            self.setPrimary(False)
            raise
