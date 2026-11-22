"""Orquestrador: liga mensagem do usuario, LLM e voz.

Roda numa thread propria para que a interface (face ou terminal) nunca bloqueie
esperando o modelo. Cada mensagem recebida vira um "turno":

    usuario -> ThinkingStarted -> LLM (streaming) -> frases -> voz -> SpeechFinished

Como o texto e cortado em frases assim que elas fecham, a primeira frase ja esta
sendo falada enquanto o modelo ainda escreve o resto.
"""

from __future__ import annotations

import queue
import threading
import time

from roboteye.core.braveza import Braveza
from roboteye.core.contas import responder as responderConta
from roboteye.core.events import (
    AssistantReply,
    ErrorOccurred,
    EventBus,
    ThinkingStarted,
    UserMessage,
)
from roboteye.core.humor import simplificar
from roboteye.core.neutroPt import neutralize
from roboteye.core.piadas import Piadas
from roboteye.core.text import cortarLaco, pararNoLaco, streamSentences, truncate
from roboteye.llm.base import LLMClient, LLMError
from roboteye.llm.fallback import FallbackLLMClient
from roboteye.llm.memory import ConversationMemory
from roboteye.llm.persona import PersonaStore
from roboteye.loggingSetup import getLogger
from roboteye.speech.speaker import Speaker

logger = getLogger(__name__)

#: Depois de tanto tempo sem pergunta, a conversa recomeça do zero. Num robô de
#: corredor, quem pergunta agora quase nunca é quem perguntou antes; e uma
#: resposta ruim no histórico vira molde para as seguintes num modelo de 1B.
ESQUECER_APOS_S = 120.0


class Assistant:
    """Consome mensagens do usuario e produz resposta falada."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        memory: ConversationMemory,
        speaker: Speaker,
        bus: EventBus,
        persona: PersonaStore | None = None,
        language: str = "en",
        linguagemNeutra: bool = False,
        esquecerAposS: float = ESQUECER_APOS_S,
    ) -> None:
        self.llm = llm
        self.memoryStore = memory
        self.speaker = speaker
        self.bus = bus
        self.persona = persona
        self.language = language
        #: Reescreve o que o robo diz de si sem marcar genero (`core/neutroPt.py`).
        #: So existe a versao em portugues: e a lingua em que quase todo
        #: adjetivo flexiona, e a unica em que o robo fala hoje.
        self.linguagemNeutra = linguagemNeutra and language.lower().startswith("pt")

        self.esquecerAposS = esquecerAposS
        self.ultimoTurno: float | None = None
        #: Piadas respondidas sem o modelo, que nao entende graca (`core/piadas.py`).
        #: So em portugues: as formas que ela reconhece sao as daqui.
        self.piadas = Piadas() if language.lower().startswith("pt") else None
        #: Xingamento respondido bravo, sem o modelo (`core/braveza.py`).
        self.braveza = Braveza()

        self.inbox: queue.Queue[str | None] = queue.Queue()
        self.thread: threading.Thread | None = None
        self.busy = threading.Event()
        self.closing = threading.Event()

    # -- ciclo de vida -----------------------------------------------------
    def start(self) -> None:
        """Inicia a thread do assistente. Idempotente."""
        if self.thread is not None:
            return
        self.thread = threading.Thread(target=self.run, name="assistant", daemon=True)
        self.thread.start()

    def close(self, *, timeout: float = 5.0) -> None:
        if self.thread is None:
            return

        # Sinaliza antes do join: se o modelo ainda estiver respondendo, fechar o
        # cliente HTTP aborta o stream de proposito, e o erro daí decorrente nao
        # deve virar uma mensagem de falha na tela do usuario.
        self.closing.set()
        self.inbox.put(None)
        self.thread.join(timeout=timeout)
        self.thread = None
        self.llm.close()

    def __enter__(self) -> Assistant:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- entrada -----------------------------------------------------------
    def submit(self, text: str) -> None:
        """Envia uma mensagem do usuario. Interrompe a fala em andamento."""
        message = text.strip()
        if not message:
            return

        # Barge-in: quem fala por ultimo e o usuario.
        self.speaker.interrupt()
        self.bus.publish(UserMessage(text=message))
        self.inbox.put(message)

    def sayDirectly(self, text: str) -> None:
        """Faz o robo falar um texto fixo, sem passar pelo modelo.

        Usado para saudacoes e falas ociosas.
        """
        # A saudacao vem do `.env`, escrita a mao, e escapa da persona.
        if self.linguagemNeutra:
            text = neutralize(text)
        self.bus.publish(AssistantReply(text=text))
        self.speaker.say(text)
        self.speaker.endTurn()

    def interrupt(self) -> None:
        """Cala a fala em andamento sem descartar o historico."""
        self.speaker.interrupt()

    @property
    def memory(self) -> ConversationMemory:
        """Historico da conversa (usado pelo comando `/limpar`)."""
        return self.memoryStore

    # -- ensinar -----------------------------------------------------------
    def teach(self, fact: str) -> bool:
        """Ensina um fato, que passa a valer da proxima resposta em diante."""
        if self.persona is None:
            return False
        if not self.persona.remember(fact):
            return False
        self.reloadPersona()
        return True

    def forget(self, needle: str) -> int:
        """Esquece os fatos que contenham `needle`. Devolve quantos sairam."""
        if self.persona is None:
            return 0
        removidos = self.persona.forget(needle)
        if removidos:
            self.reloadPersona()
        return removidos

    def facts(self) -> tuple[str, ...]:
        """Tudo que ela aprendeu ate agora."""
        return self.persona.loadFacts() if self.persona else ()

    def reloadPersona(self) -> None:
        """Rele a persona do disco e troca o prompt de sistema em uso.

        Permite editar o arquivo com o robo rodando e ver o efeito na proxima
        resposta, sem reiniciar nada.
        """
        if self.persona is None:
            return
        persona = self.persona.load(self.language)
        self.memoryStore.replaceSystemPrompt(persona.systemPrompt())
        logger.info("persona recarregada (%d fatos)", len(persona.facts))

    @property
    def isBusy(self) -> bool:
        return self.busy.is_set()

    # -- troca de IA -------------------------------------------------------
    def definirModoIa(self, modo: str) -> None:
        """Aplica o switch de IA do app: "local" (Pi) ou "nuvem" (rede).

        So o cliente com reserva (`FallbackLLMClient`) sabe trocar. Sem reserva
        configurada — um `.env` que so tem a IA de rede, ou so a local — nao ha
        o que alternar, e o pedido apenas vira uma linha de log.
        """
        if isinstance(self.llm, FallbackLLMClient):
            self.llm.definirModo(modo)
        else:
            logger.info("switch de IA ignorado: sem reserva local configurada (modo=%s)", modo)

    # -- thread ------------------------------------------------------------
    def run(self) -> None:
        logger.debug("assistente iniciado (llm=%s)", self.llm.name)
        while True:
            message = self.inbox.get()
            if message is None:
                break

            # Se o usuario mandou varias mensagens de uma vez, responde so a ultima.
            message = self.latest(message)

            self.busy.set()
            respondeu = False
            try:
                self.handleTurn(message)
                respondeu = True
            except LLMError as exc:
                self.report(exc, source="llm")
            except Exception as exc:
                self.report(exc, source="assistant")
            finally:
                self.busy.clear()

            # O Gemma 3 no Ollama só reaproveita o cache até o último checkpoint,
            # e a resposta guardada (neutralizada, em frases) não é o texto que o
            # modelo gerou: sem isto, cada pergunta relia o histórico inteiro
            # (medido no Pi: de 4 a 8 s, crescendo a cada turno). Aquecido aqui,
            # com a Atlas ainda falando, a próxima paga só a pergunta nova. Fora
            # do `busy`, para não calar o "Oi?" de quem chama nesse meio-tempo;
            # e só se ninguém já perguntou de novo, que aí é ela que aquece.
            if respondeu and self.inbox.empty():
                self.llm.warmConversation(self.memoryStore.buildNextPrefix())

        logger.debug("assistente encerrado")

    def report(self, exc: Exception, *, source: str) -> None:
        """Registra uma falha do turno, exceto quando ela vem do encerramento."""
        if self.closing.is_set():
            # Fechar o cliente HTTP durante um stream levanta erro de socket:
            # e o mecanismo de cancelamento, nao um problema a relatar.
            logger.debug("falha durante o encerramento, ignorada: %s", exc)
            return

        logger.error("falha em %s: %s", source, exc)
        self.bus.publish(ErrorOccurred(message=str(exc), source=source))

    def latest(self, message: str) -> str:
        """Descarta mensagens enfileiradas mais antigas, mantendo a ultima."""
        while True:
            try:
                queued = self.inbox.get_nowait()
            except queue.Empty:
                return message
            if queued is None:
                self.inbox.put(None)
                return message
            message = queued

    def handleTurn(self, message: str) -> None:
        logger.info("usuario: %s", truncate(message))
        agora = time.monotonic()
        if self.ultimoTurno is not None and agora - self.ultimoTurno > self.esquecerAposS:
            if len(self.memoryStore):
                logger.info(
                    "conversa parada ha %.0f s; comecando do zero", agora - self.ultimoTurno
                )
            self.memoryStore.clear()
        self.ultimoTurno = agora
        self.memoryStore.addUser(message)

        pronta = None
        if self.piadas:  # so em portugues; conta antes de piada (`core/contas.py`)
            pronta = (
                self.braveza.responder(message)
                or responderConta(message)
                or self.piadas.responder(message, agora)
            )
        if pronta is not None:
            # Sem `ThinkingStarted`: nao ha o que pensar, e a cara de pensativa
            # antes de rir de uma piada desmancharia a graca. O microfone pausa
            # do mesmo jeito, no `SpeechStarted` da fala.
            self.speaker.say(pronta)
            self.memoryStore.addAssistant(pronta)
            self.bus.publish(AssistantReply(text=pronta))
            self.speaker.endTurn()
            logger.info("assistente: %s [pronta]", truncate(pronta))
            return

        self.bus.publish(ThinkingStarted())

        spoken: list[str] = []
        ditas: set[str] = set()
        tokens = pararNoLaco(self.llm.streamReply(self.memoryStore.buildPrompt()))
        for sentence in streamSentences(tokens):
            sentence = cortarLaco(sentence)
            # O modelo pequeno as vezes entra em laco e repete a mesma frase:
            # dita uma vez, a repeticao so atrasa e soa quebrada.
            chave = simplificar(sentence)
            if chave in ditas:
                logger.info("frase repetida pelo modelo, pulada: %s", truncate(sentence))
                continue
            ditas.add(chave)
            # Antes da voz e da legenda, e tambem do historico: guardar a versao
            # com genero ensinaria o modelo a repeti-la na resposta seguinte.
            if self.linguagemNeutra:
                sentence = neutralize(sentence)
            spoken.append(sentence)
            self.speaker.say(sentence)

        reply = " ".join(spoken).strip()
        if not reply:
            logger.warning("o modelo devolveu uma resposta vazia")
            self.speaker.endTurn()
            return

        self.memoryStore.addAssistant(reply)
        self.bus.publish(AssistantReply(text=reply))
        self.speaker.endTurn()
        logger.info("assistente: %s", truncate(reply))
