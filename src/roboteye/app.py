"""Raiz de composicao.

Este e o unico lugar que sabe como as pecas se encaixam. Os subsistemas recebem
suas dependencias prontas e nunca constroem umas as outras, o que mantem cada um
substituivel e testavel isoladamente.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from types import TracebackType

from roboteye.config import Settings
from roboteye.core.assistant import Assistant
from roboteye.core.events import (
    ErrorOccurred,
    Event,
    EventBus,
    ListeningChanged,
    Notice,
    Shutdown,
    SpeechFinished,
    SpeechHeard,
    SpeechStarted,
)
from roboteye.face.app import FaceApp
from roboteye.hearing import HearingError, Ouvido, create_ears, dirigido_ao_robo
from roboteye.hearing.gatilho import Conversa
from roboteye.llm.base import LLMClient
from roboteye.llm.factory import create_llm_client
from roboteye.llm.memory import ConversationMemory
from roboteye.llm.persona import PersonaStore
from roboteye.logging_setup import get_logger
from roboteye.speech import sinal
from roboteye.speech.base import SpeechError
from roboteye.speech.envelope import SpeechEnvelope
from roboteye.speech.factory import create_tts_engine
from roboteye.speech.player import create_audio_sink
from roboteye.speech.polish import AudioPolish
from roboteye.speech.speaker import Speaker
from roboteye.ui.console import ConsoleChat

logger = get_logger(__name__)


@dataclass(slots=True)
class Application:
    """Aplicacao montada e pronta para rodar."""

    settings: Settings
    bus: EventBus
    llm: LLMClient
    memory: ConversationMemory
    speaker: Speaker
    assistant: Assistant
    #: Ponte entre o audio que toca e a face que o anima. O locutor escreve,
    #: a face le; e por isso que ele nasce aqui, e nao dentro de um dos dois.
    envelope: SpeechEnvelope
    #: None quando a escuta esta desligada, que e o padrao.
    ears: Ouvido | None = None
    _ouvindo: threading.Thread | None = None
    #: Relogio do "Oi?" — armado ao ser chamada, cancelado quando a pergunta vem.
    _chamado: threading.Timer | None = None

    # -- construcao --------------------------------------------------------
    @classmethod
    def build(cls, settings: Settings) -> Application:
        """Instancia todos os subsistemas sem ainda carregar modelos."""
        bus = EventBus()

        persona_store = PersonaStore(settings.llm.persona_dir, settings.llm.persona)
        persona = persona_store.load(settings.llm.reply_language)
        logger.info("persona %r carregada (%d fatos aprendidos)", persona.name, len(persona.facts))

        memory = ConversationMemory(
            persona.system_prompt(),
            max_messages=settings.llm.history_messages,
        )

        llm = create_llm_client(settings.llm)
        envelope = SpeechEnvelope()

        def announce_voice_switch(message: str) -> None:
            # Aviso, nao erro: a fala continua, entao a face nao deve ficar brava
            # nem interromper o que esta dizendo. Mas precisa aparecer — trocar
            # de voz em silencio faz quem ouve procurar o problema na
            # configuracao, que e o unico lugar onde ele nao esta.
            logger.warning("%s", message)
            bus.publish(Notice(message=message, source="speech"))

        speaker = Speaker(
            engine=create_tts_engine(settings.voice, on_voice_switch=announce_voice_switch),
            sink=create_audio_sink(settings.voice),
            bus=bus,
            envelope=envelope,
            language=settings.voice.language,
            polish=AudioPolish(gain=settings.voice.gain),
        )
        assistant = Assistant(
            llm=llm,
            memory=memory,
            speaker=speaker,
            bus=bus,
            persona=persona_store,
            language=settings.llm.reply_language,
        )

        return cls(
            settings=settings,
            bus=bus,
            llm=llm,
            memory=memory,
            speaker=speaker,
            assistant=assistant,
            envelope=envelope,
            ears=create_ears(settings.hearing),
        )

    # -- ciclo de vida -----------------------------------------------------
    def start(self, *, warm_up: bool = True) -> None:
        """Sobe as threads de trabalho e, opcionalmente, pre-carrega a voz."""
        self.speaker.start()
        self.assistant.start()

        if warm_up:
            try:
                self.speaker.warm_up()
            except SpeechError as exc:
                logger.warning("voz indisponivel: %s", exc)
                self.bus.publish(ErrorOccurred(message=str(exc), source="speech"))

            # O LLM aquece em segundo plano: nao ha razao para segurar a face
            # esperando o modelo subir na GPU. Vai junto a persona, que e o que
            # a conversa vai usar de verdade — ver `OllamaClient.warm_up`.
            threading.Thread(
                target=self.llm.warm_up,
                args=(self.assistant.memory.build_prompt(),),
                name="llm-warmup",
                daemon=True,
            ).start()

        self._abrir_ouvidos()
        self._dar_bom_dia()

    def _dar_bom_dia(self) -> None:
        """Fala a primeira frase, se houver uma configurada.

        Numa thread porque a sintese da primeira frase carrega o motor de voz, e
        segurar o arranque nela deixaria a tela preta por segundos.
        """
        frase = self.settings.llm.saudacao.strip()
        if not frase:
            return

        def falar() -> None:
            try:
                self.assistant.say_directly(frase)
            except Exception as exc:
                # Sem passar pelo LLM: e uma frase fixa, e ela precisa sair
                # mesmo com a IA fora do ar. Falhando, o robo sobe calado — o
                # que ja e a informacao que a saudacao existe para dar.
                logger.warning("nao consegui dar bom dia: %s", exc)

        threading.Thread(target=falar, name="saudacao", daemon=True).start()

    def _abrir_ouvidos(self) -> None:
        """Poe o robo para escutar, se houver microfone configurado."""
        if self.ears is None or self._ouvindo is not None:
            return

        # A Atlas nao pode se ouvir: o microfone esta a centimetros da caixinha,
        # e sem isto ela transcreve a propria voz e responde a si mesma, em laco.
        # Os eventos de fala ja existem — so faltava alguem escutar por eles.
        ouvido = self.ears
        self.bus.subscribe(lambda _e: ouvido.pausar(), event_type=SpeechStarted)
        self.bus.subscribe(lambda _e: ouvido.retomar(), event_type=SpeechFinished)

        # Chamar o nome e ficar no silencio e a pior parte de conversar com este
        # robo: quem falou nao sabe se foi ouvido, entao repete o nome — e a
        # repeticao chega justo enquanto a primeira ainda esta sendo tratada. Um
        # som curto fecha esse buraco na hora, sem esperar sintese nenhuma.
        self.bus.subscribe(self._avisar_que_estou_ouvindo, event_type=ListeningChanged)

        self._ouvindo = threading.Thread(target=self._escutar, name="ouvidos", daemon=True)
        self._ouvindo.start()

    def _escutar(self) -> None:
        """Roda a escuta e entrega ao assistente o que foi dirigido ao robo."""
        assert self.ears is not None
        # Chamar o nome abre uma janela em que a frase seguinte e aceita sem
        # ele — que e como as pessoas falam: "Atlas!" ... "quanto e dois mais dois?"
        conversa = Conversa(self.settings.hearing.janela_s)
        try:
            for transcricao in self.ears.escutar():
                pergunta = dirigido_ao_robo(
                    transcricao.texto, self.settings.hearing.wake_word, conversa=conversa
                )
                # Publicado para toda transcricao, dirigida ou nao: a tela de
                # debug mostra ate o que o robo ouviu e ignorou, que e metade do
                # trabalho de descobrir por que ele nao respondeu.
                self.bus.publish(
                    SpeechHeard(
                        raw=transcricao.texto,
                        accepted=pergunta,
                        ms=transcricao.ms,
                        confidence=transcricao.confianca,
                        no_speech=transcricao.sem_fala,
                    )
                )
                if pergunta is None:
                    logger.debug("ouvi %r, mas nao era comigo", transcricao.texto)
                    # Chamada sem pergunta ("Atlas!") abre a janela: a face
                    # mostra que esta esperando, que e o unico jeito de quem
                    # falou saber que foi ouvido antes de fazer a pergunta.
                    if conversa.aberta():
                        self.bus.publish(ListeningChanged(active=True))
                        self._perguntar_se_ficou_no_ar()
                    continue
                logger.info("ouvi: %s", pergunta)
                self._cancelar_pergunta()
                self.bus.publish(ListeningChanged(active=False))
                self.assistant.submit(pergunta)
        except HearingError as exc:
            logger.warning("escuta indisponivel: %s", exc)
            self.bus.publish(ErrorOccurred(message=str(exc), source="hearing"))
        except Exception:
            logger.exception("a escuta parou")

    def _avisar_que_estou_ouvindo(self, evento: Event) -> None:
        """Toca o sinal quando a janela de escuta abre. So na abertura.

        Fechar a janela nao merece som: ou veio a pergunta — e a resposta e o
        aviso —, ou o tempo passou, e um som para "desisti de esperar" so
        atrapalha quem ja voltou a fazer outra coisa.
        """
        if not isinstance(evento, ListeningChanged) or not evento.active:
            return
        try:
            self.speaker.sinalizar(sinal.escutando())
        except Exception as exc:
            # O sinal e conforto, nao funcao: falhar aqui nao pode impedir o
            # robo de ouvir a pergunta que vem em seguida.
            logger.debug("nao consegui tocar o sinal de escuta: %s", exc)

    def _perguntar_se_ficou_no_ar(self) -> None:
        """Diz "Oi?" se chamarem o nome e a pergunta nao vier.

        Ser chamada e nao responder nada parece robo quebrado — e quem chamou
        repete o nome, em vez de perguntar. Um "Oi?" fecha esse silencio.
        """
        frase = self.settings.hearing.resposta_ao_chamado.strip()
        if not frase:
            return

        self._cancelar_pergunta()
        timer = threading.Timer(
            self.settings.hearing.espera_do_chamado_s,
            self._dizer_oi,
            args=(frase,),
        )
        timer.daemon = True
        self._chamado = timer
        timer.start()

    def _cancelar_pergunta(self) -> None:
        if self._chamado is not None:
            self._chamado.cancel()
            self._chamado = None

    def _dizer_oi(self, frase: str) -> None:
        # A pergunta pode ter chegado enquanto o relogio corria; responder
        # "Oi?" por cima dela seria falar junto com quem perguntou.
        if self.assistant.is_busy:
            return
        try:
            self.assistant.say_directly(frase)
        except Exception as exc:
            logger.debug("nao consegui responder ao chamado: %s", exc)

    def shutdown(self) -> None:
        """Encerra tudo na ordem inversa da criacao."""
        logger.debug("encerrando aplicacao")
        self._cancelar_pergunta()
        if self.ears is not None:
            self.ears.close()
        self.assistant.close()
        self.speaker.close()

    def __enter__(self) -> Application:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.shutdown()

    # -- modos de execucao -------------------------------------------------
    def run_chat(self) -> None:
        """Somente terminal: sem janela, sem pygame."""
        self.start()
        console = ConsoleChat(self.assistant, self.bus)
        try:
            console.run()
        finally:
            self.shutdown()

    def run_face(self) -> None:
        """A face animada, sem chat no terminal.

        Aquece assim mesmo. Antes nao aquecia — sem entrada de texto nao havia
        conversa a preparar —, mas hoje ha: a pagina do celular conversa, e e
        justamente por ela que alguem fala com o robo instalado. Sem aquecer, a
        primeira pergunta feita ali pagaria os segundos de carregar o modelo e
        ler a persona (ver `OllamaClient.warm_up`), que e o custo que este
        projeto passou a pagar no arranque de proposito.
        """
        self.start()
        face = FaceApp(self.settings.face, self.bus, envelope=self.envelope)
        try:
            face.run()
        finally:
            self.shutdown()

    def run_interactive(self) -> None:
        """Face na thread principal e chat de texto em segundo plano."""
        if not self.settings.face.enabled:
            self.run_chat()
            return

        self.start()

        face = FaceApp(self.settings.face, self.bus, envelope=self.envelope)
        console = ConsoleChat(self.assistant, self.bus)

        # Fechar a janela deve encerrar o chat, e vice-versa.
        self.bus.subscribe(_stop_on_shutdown(face), event_type=Shutdown)

        console.start_background()
        try:
            face.run()
        finally:
            console.stop()
            self.shutdown()


def _stop_on_shutdown(face: FaceApp):
    def handler(_: Event) -> None:
        face.request_stop()

    return handler
