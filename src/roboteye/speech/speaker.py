"""Locutor assincrono.

O `Speaker` roda em sua propria thread e consome uma fila de frases. Assim o LLM
continua gerando texto enquanto a frase anterior ainda esta tocando, e a face
continua animando a 60 FPS sem engasgar.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace

from roboteye.core.events import ErrorOccurred, EventBus, SpeechFinished, SpeechStarted
from roboteye.core.text import clean_for_speech, truncate
from roboteye.logging_setup import get_logger
from roboteye.speech.base import SpeechChunk, SpeechError, TTSEngine
from roboteye.speech.envelope import SpeechEnvelope
from roboteye.speech.player import AudioSink
from roboteye.speech.polish import AudioPolish

logger = get_logger(__name__)

#: Teto de caracteres que o locutor junta numa sintese so.
#:
#: Existe para o caso de uma resposta longa: juntar tudo faria a fala demorar a
#: comecar, que e exatamente o problema que cortar em frases resolve. O valor da
#: folga para as duas ou tres frases de uma resposta falada normal.
MAX_BATCH_CHARS = 480

#: Quanto o locutor espera pela proxima frase antes de fechar o lote.
#:
#: Cortar em frases existe para comecar a falar antes de o modelo terminar. Mas
#: com o modelo numa placa de video as frases saem quase juntas — separadas por
#: fracoes de segundo —, e fechar o lote no instante exato em que a primeira
#: fica pronta desperdica isso: cada frase vira uma sintese, e cada sintese de
#: rede vira uma pausa audivel no meio da resposta.
#:
#: Um quarto de segundo e barato no comeco (ninguem percebe) e paga caro em
#: fluidez: duas frases numa sintese so sao lidas com a entoacao de quem fala,
#: com a pausa e a respiracao no lugar, em vez de duas leituras emendadas.
ESPERA_LOTE_S = 0.25


def synthesize_polished(
    engine: TTSEngine,
    text: str,
    *,
    language: str = "",
    polish: AudioPolish | None = None,
) -> Iterator[SpeechChunk]:
    """Texto cru em audio pronto para tocar.

    Reune os tres passos que sempre andam juntos: limpar e normalizar o texto,
    sintetizar, e dar o acabamento no audio. Existe como funcao — e nao so como
    parte do locutor — para que quem sintetiza fora dele (o comando `say`) ouca
    exatamente o mesmo resultado que o robo produz. Quando os dois caminhos eram
    separados, `say` pulava a normalizacao e o acabamento, e servia mal como
    ferramenta de conferencia justamente por isso.
    """
    cleaned = clean_for_speech(text, language=language)
    if not cleaned:
        return
    yield from (polish or AudioPolish()).process(engine.synthesize(cleaned))


@dataclass(frozen=True, slots=True)
class _Utterance:
    """Uma frase a ser falada, marcada com a geracao em que foi enfileirada."""

    text: str
    generation: int
    end_of_turn: bool = False


@dataclass(slots=True)
class _State:
    """Estado compartilhado entre a thread do locutor e quem o comanda."""

    generation: int = 0
    speaking: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)


class Speaker:
    """Fala textos em segundo plano, publicando eventos de inicio e fim."""

    def __init__(
        self,
        engine: TTSEngine,
        sink: AudioSink,
        bus: EventBus,
        envelope: SpeechEnvelope | None = None,
        polish: AudioPolish | None = None,
        language: str = "",
    ) -> None:
        self._engine = engine
        self._sink = sink
        self._bus = bus
        #: Medidor lido pela face para animar a fala. Opcional: sem ele o
        #: locutor funciona igual, e a face cai no movimento sintetico.
        self._envelope = envelope
        #: Rampas nas pontas e respiro entre as frases.
        self._polish = polish or AudioPolish()
        #: Idioma da voz, que decide como numeros e abreviacoes sao lidos.
        self._language = language

        self._queue: queue.Queue[_Utterance | None] = queue.Queue()
        #: Item retirado da fila que nao coube no lote atual. So a thread do
        #: locutor mexe aqui, entao nao precisa de cadeado.
        #: Itens ja tirados da fila que ainda nao foram tratados. E uma FILA,
        #: nao uma pilha: o adiantamento pode devolver mais de um, e a ordem
        #: deles e a ordem da resposta.
        self._held: deque[_Utterance | None] = deque()
        self._state = _State()
        self._idle = threading.Event()
        self._idle.set()
        self._thread: threading.Thread | None = None
        #: A proxima fala, ja sintetizada enquanto a atual tocava. Ver
        #: `_adiantar`: e o que tira o silencio de entre uma frase e outra.
        #: `None` no audio significa "a sintese adiantada falhou, sintetize
        #: normalmente". Escrito pela thread de adiantamento sob o mesmo lock
        #: do estado, lido so pela thread do locutor.
        self._pronto: tuple[_Utterance, list[SpeechChunk] | None] | None = None
        self._adiantando: threading.Thread | None = None

    # -- ciclo de vida -----------------------------------------------------
    def start(self) -> None:
        """Inicia a thread do locutor. Idempotente."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="speaker", daemon=True)
        self._thread.start()

    def warm_up(self) -> None:
        """Pre-carrega o modelo de voz para que a primeira fala nao gaste esse tempo."""
        self._engine.warm_up()

    @property
    def engine_name(self) -> str:
        return self._engine.name

    def close(self, *, timeout: float = 5.0) -> None:
        """Encerra a thread e libera o dispositivo de audio."""
        if self._thread is None:
            return
        self.interrupt()
        self._queue.put(None)
        self._thread.join(timeout=timeout)
        self._thread = None
        self._sink.close()
        self._engine.close()

    def __enter__(self) -> Speaker:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- comandos ----------------------------------------------------------
    def say(self, text: str) -> None:
        """Enfileira uma frase. Retorna imediatamente.

        Aqui o texto so perde marcacao e emojis. A normalizacao de numeros fica
        para a hora da sintese, de proposito: este texto tambem vira legenda na
        tela, e "15:30" se le melhor do que "quinze e trinta".
        """
        cleaned = clean_for_speech(text)
        if not cleaned:
            return
        with self._state.lock:
            generation = self._state.generation
        self._idle.clear()
        self._queue.put(_Utterance(cleaned, generation))

    def end_turn(self) -> None:
        """Marca o fim de uma resposta: dispara `SpeechFinished` apos a ultima frase."""
        with self._state.lock:
            generation = self._state.generation
        self._queue.put(_Utterance("", generation, end_of_turn=True))

    def interrupt(self) -> None:
        """Cala a boca agora: descarta a fila e corta o audio em reproducao."""
        with self._state.lock:
            self._state.generation += 1

        # O que estava preparado era da fala que acabou de ser cortada.
        self._pronto = None

        drained = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:  # preserva o pedido de encerramento
                self._queue.put(None)
                break
            drained += 1

        try:
            self._sink.stop()
        except SpeechError:
            logger.debug("falha ao interromper a saida de audio", exc_info=True)

        if self._envelope is not None:
            # O audio em buffer foi descartado; o envelope que o descrevia
            # tambem precisa ir, senao a face continua falando sozinha.
            self._envelope.end()

        # Todo o trabalho pendente foi descartado e a fala em curso sera abortada
        # no proximo bloco de audio: quem esperava o silencio pode seguir.
        self._idle.set()

        if drained:
            logger.debug("fala interrompida (%d frases descartadas)", drained)

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Bloqueia ate a fila esvaziar. Retorna False se estourar o tempo."""
        return self._idle.wait(timeout)

    @property
    def is_speaking(self) -> bool:
        with self._state.lock:
            return self._state.speaking

    # -- thread ------------------------------------------------------------
    def _run(self) -> None:
        logger.debug("locutor iniciado (motor=%s, saida=%s)", self._engine.name, self._sink.name)
        while True:
            # Uma fala ja preparada vem antes de qualquer coisa nova: ela e
            # anterior na resposta. Tratar o proximo item da fila primeiro
            # faria, entre outras coisas, o fim de turno ser anunciado com uma
            # frase ainda por dizer — e a face pararia de falar antes da voz.
            preparada = self._tomar_preparada()
            # Um adiantamento em andamento é a próxima fala, na ordem — a frase
            # dele já saiu da fila. Esperá-lo aqui, antes de puxar qualquer outra
            # coisa, resolve dois defeitos de uma vez: puxar da fila uma frase
            # mais nova falaria fora de ordem (A, C, B), e cair no `get()` com o
            # áudio já pronto em `_pronto` deixaria a última frase presa até a
            # próxima interação enfileirar algo.
            if preparada is None and self._adiantando is not None and self._adiantando.is_alive():
                self._adiantando.join()
                preparada = self._tomar_preparada()
            if preparada is not None:
                lote, chunks = preparada
                try:
                    self._speak(lote, chunks)
                except SpeechError as exc:
                    logger.error("falha ao falar: %s", exc)
                    self._bus.publish(ErrorOccurred(message=str(exc), source="speech"))
                continue

            item = self._held.popleft() if self._held else self._queue.get()
            if item is None:
                break

            try:
                if not self._is_current(item.generation):
                    continue  # sobra de uma fala interrompida
                if item.end_of_turn:
                    if self._envelope is not None:
                        self._envelope.end()
                    self._bus.publish(SpeechFinished())
                    continue
                self._speak(self._batch(item))
            except SpeechError as exc:
                logger.error("falha ao falar: %s", exc)
                self._bus.publish(ErrorOccurred(message=str(exc), source="speech"))
            except Exception as exc:
                logger.exception("erro inesperado no locutor")
                self._bus.publish(ErrorOccurred(message=str(exc), source="speech"))
            finally:
                # `_held` conta junto com a fila: itens ja tirados dela ainda
                # nao foram ditos, e anunciar silencio com um fim de turno por
                # tratar faz a face parar de falar antes da voz.
                if self._queue.empty() and not self._held and self._pronto is None:
                    self._set_speaking(False)
                    self._idle.set()

        self._set_speaking(False)
        self._idle.set()
        logger.debug("locutor encerrado")

    def _tomar_preparada(self) -> tuple[_Utterance, list[SpeechChunk] | None] | None:
        """A fala adiantada, se houver uma valida esperando."""
        with self._state.lock:
            preparada, self._pronto = self._pronto, None

        if preparada is None:
            return None
        if not self._is_current(preparada[0].generation):
            # Alguem interrompeu entre preparar e falar.
            logger.debug("audio adiantado descartado: a fala foi interrompida")
            return None
        return preparada

    def _adiantar(self, geracao: int) -> None:
        """Sintetiza a proxima fala enquanto a atual ainda esta tocando.

        E daqui que vem o silencio entre uma frase e outra: ate agora a sintese
        da segunda so comecava depois de a primeira terminar de tocar, e num
        motor de rede isso e uma ida e volta inteira parada no meio da resposta.
        Medido no robo, com a resposta ja escrita pelo modelo: **8 segundos**
        entre o inicio de uma frase e o da seguinte, dos quais quatro eram
        silencio.

        Sintetizar adiantado troca esse silencio por trabalho feito em paralelo.
        So um item de cada vez: adiantar demais gastaria sintese que uma
        interrupcao jogaria fora, e prenderia memoria de audio sem necessidade.
        """
        if self._adiantando is not None and self._adiantando.is_alive():
            return
        with self._state.lock:
            if self._pronto is not None:
                return

        try:
            proximo = self._held.popleft() if self._held else self._queue.get_nowait()
        except queue.Empty:
            return

        # Sentinelas e fim de turno nao se sintetizam; voltam para o laco.
        if proximo is None or proximo.end_of_turn or proximo.generation != geracao:
            # Nao se adianta fim de turno nem sentinela. Volta para a frente da
            # fila, que e de onde saiu.
            self._held.appendleft(proximo)
            return

        # `esperar=False`: este `_batch` roda na thread do locutor, entre duas
        # escritas de audio da fala atual. A espera de 0,25 s por mais uma frase
        # ali vira silencio no meio da fala — o engasgo que o adiantamento
        # existe para tirar. Aqui ele so junta o que ja esta na fila agora; o que
        # chegar depois sai como o proximo adiantamento, sem custo nenhum.
        lote = self._batch(proximo, esperar=False)

        def trabalhar() -> None:
            chunks: list[SpeechChunk] | None
            try:
                chunks = list(
                    synthesize_polished(
                        self._engine,
                        lote.text,
                        language=self._language,
                        polish=self._polish,
                    )
                )
            except Exception as exc:
                # Falhar aqui nao pode calar o robo. A fala volta ao laco
                # principal sem audio, e ele a sintetiza do jeito de sempre —
                # com o tratamento de erro que sempre teve.
                logger.debug("adiantamento falhou (%s); segue pelo caminho normal", exc)
                chunks = None
            else:
                logger.debug("proxima fala pronta enquanto esta ainda toca")

            # Uma so escrita, e a thread do locutor e a unica que le: sem isto,
            # duas threads mexeriam na fila e em `_held` ao mesmo tempo, e o
            # resultado dependeria de quem chegasse primeiro.
            with self._state.lock:
                self._pronto = (lote, chunks)

        self._adiantando = threading.Thread(target=trabalhar, name="speaker-adiantar", daemon=True)
        self._adiantando.start()

    def _batch(self, first: _Utterance, *, esperar: bool = True) -> _Utterance:
        """Junta numa unica sintese as frases que ja estao esperando na fila.

        Cortar a resposta em frases serve para comecar a falar antes de o modelo
        terminar de escrever. Mas quando as frases *ja chegaram*, sintetizar uma
        de cada vez so cobra caro: cada frase paga o custo fixo do motor — que
        num motor de rede e uma ida e volta inteira — e esse custo vira silencio
        entre uma e outra. Medindo com a voz online, o buraco passava de um
        segundo.

        Juntar tambem melhora o que se ouve, e nao so o tempo. Um motor de voz
        que recebe as duas frases de uma vez entoa a passagem de uma para a
        outra como quem fala, com a pausa e a respiracao no lugar; recebendo uma
        de cada vez, ele produz duas leituras separadas, e da para ouvir a
        emenda.

        O lote leva so o que ja esta na fila: se o modelo ainda nao escreveu a
        proxima frase, esta sai sozinha e a fala comeca na hora, como antes.
        """
        parts = [first.text]
        length = len(first.text)
        # Só a primeira espera: depois dela, o que já chegou entra sem custo, e
        # o que não chegou fica para o adiantamento, que roda enquanto esta fala
        # já está tocando. `esperar=False` zera até essa primeira espera — é o
        # que o adiantamento usa para não bloquear a thread do áudio.
        espera = ESPERA_LOTE_S if esperar else 0.0

        while length < MAX_BATCH_CHARS:
            try:
                item = self._queue.get(timeout=espera) if espera else self._queue.get_nowait()
            except queue.Empty:
                break
            espera = 0.0

            # Fim de turno, encerramento ou sobra de uma fala ja interrompida:
            # nada disso entra no lote. Guarda para o laco principal tratar.
            if item is None or item.end_of_turn or item.generation != first.generation:
                self._held.appendleft(item)
                break

            parts.append(item.text)
            length += len(item.text) + 1

        if len(parts) == 1:
            return first

        logger.debug("%d frases sintetizadas juntas", len(parts))
        return replace(first, text=" ".join(parts))

    def _speak(self, item: _Utterance, pronto: list[SpeechChunk] | None = None) -> None:
        logger.info("falando: %s", truncate(item.text))
        self._set_speaking(True)
        self._bus.publish(SpeechStarted(text=item.text))
        if self._envelope is not None:
            self._envelope.begin()

        if pronto is not None:
            stream: Iterable[SpeechChunk] = pronto
        else:
            stream = synthesize_polished(
                self._engine,
                item.text,
                language=self._language,
                polish=self._polish,
            )

        # Cronometro do TTS: a sintese e preguicosa, o custo real e o tempo ate
        # o primeiro bloco de audio ficar pronto. So vale medir quando a fala foi
        # sintetizada aqui; a adiantada ja veio pronta, com latencia zero.
        inicio = time.monotonic()
        primeiro = True

        for chunk in stream:
            if not self._is_current(item.generation):
                logger.debug("fala abortada no meio do audio")
                return

            if primeiro:
                primeiro = False
                if pronto is None:
                    logger.info(
                        "TTS: primeiro audio em %.0f ms", (time.monotonic() - inicio) * 1000.0
                    )

            # A cada bloco, e nao so no comeco: quando esta fala arranca, o
            # modelo em geral **ainda nao escreveu** a proxima, entao tentar uma
            # vez so nunca encontrava nada na fila. Tentando enquanto o
            # alto-falante trabalha, a sintese seguinte comeca no instante em
            # que a frase fica pronta. As guardas de `_adiantar` fazem disto uma
            # comparacao barata nas outras vezes.
            self._adiantar(item.generation)
            self._sink.start(chunk.format)
            # O medidor e alimentado antes da escrita: `write` bloqueia ate o
            # bloco caber no buffer, e medir depois disso jogaria o envelope
            # para tras justamente nos trechos longos.
            if self._envelope is not None:
                self._envelope.feed(chunk.audio, chunk.format)
            self._sink.write(chunk.audio)

    def _is_current(self, generation: int) -> bool:
        with self._state.lock:
            return generation == self._state.generation

    def _set_speaking(self, value: bool) -> None:
        with self._state.lock:
            self._state.speaking = value
