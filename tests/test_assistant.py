"""Testes do orquestrador e da memória de conversa."""

from __future__ import annotations

from roboteye.core.events import (
    AssistantReply,
    ErrorOccurred,
    SpeechFinished,
    ThinkingStarted,
    UserMessage,
)
from roboteye.llm.base import LLMError
from roboteye.llm.memory import ConversationMemory


class BrokenLLM:
    """Cliente que sempre falha, para exercitar o tratamento de erro."""

    name = "broken"

    def streamReply(self, messages):
        raise LLMError("ollama fora do ar")
        yield  # pragma: no cover - torna a função um gerador

    def isAvailable(self) -> bool:
        return False

    def close(self) -> None: ...


class TestAssistant:
    def testTurnoCompletoNaOrdemCerta(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Que pergunta previsível. Tente de novo, com mais esforço.")
        assistant, _ = makeAssistant(llm)

        assistant.submit("olá")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        tipos = recorder.typeNames()
        assert tipos.index("UserMessage") < tipos.index("ThinkingStarted")
        assert tipos.index("ThinkingStarted") < tipos.index("SpeechStarted")
        assert "AssistantReply" in tipos

    def testRespostaEEntregueAVozFraseAFrase(
        self, makeAssistant, makeLlm, recorder
    ) -> None:
        """O assistente entrega cada frase assim que ela fecha.

        É o que permite começar a falar antes de o modelo terminar de escrever.
        A conferência é feita na fronteira com o locutor, e não no motor de voz:
        o que o motor recebe é decisão do locutor, que junta numa síntese só as
        frases que já chegaram — e é assim que deve ser.
        """
        llm = makeLlm("Primeira frase suficientemente longa. Segunda frase igualmente longa.")
        assistant, _ = makeAssistant(llm)

        entregues: list[str] = []
        speaker = assistant.speaker
        original = speaker.say
        speaker.say = lambda texto: (entregues.append(texto), original(texto))[1]  # type: ignore[method-assign]

        assistant.submit("olá")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        assert len(entregues) == 2, f"esperava 2 frases, recebi {entregues}"

    def testPerguntaDoUsuarioChegaAoModelo(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Uma resposta suficientemente longa para o teste.")
        assistant, _ = makeAssistant(llm)

        assistant.submit("qual é a resposta?")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        ultima = llm.prompts[-1][-1]
        assert ultima.role == "user"
        assert ultima.content == "qual é a resposta?"

    def testPromptDeSistemaVaiJunto(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Uma resposta suficientemente longa para o teste.")
        assistant, _ = makeAssistant(llm, systemPrompt="seja sarcástica")

        assistant.submit("olá")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        primeira = llm.prompts[-1][0]
        assert primeira.role == "system"
        assert primeira.content == "seja sarcástica"

    def testMensagemVaziaEIgnorada(self, makeAssistant, makeLlm, recorder) -> None:
        assistant, _ = makeAssistant(makeLlm())

        assistant.submit("   ")

        assert recorder.ofType(UserMessage) == []

    def testHistoricoGuardaPerguntaEResposta(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Uma resposta bastante longa para o teste funcionar.")
        assistant, memory = makeAssistant(llm)

        assistant.submit("qual é a resposta?")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        assert len(memory) == 2  # pergunta + resposta

    def testErroDoLlmViraEvento(self, makeAssistant, recorder) -> None:
        assistant, _ = makeAssistant(BrokenLLM())

        assistant.submit("olá")

        assert recorder.waitFor(ErrorOccurred, timeout=10)
        assert "ollama fora do ar" in recorder.ofType(ErrorOccurred)[0].message

    def testErroNaoDerrubaOAssistente(self, makeAssistant, makeLlm, recorder) -> None:
        # Depois de falhar, o assistente ainda deve atender a próxima mensagem.
        assistant, _ = makeAssistant(BrokenLLM())
        assistant.submit("primeira")
        assert recorder.waitFor(ErrorOccurred, timeout=10)

        llm = makeLlm("Agora sim, uma resposta suficientemente longa.")
        assistant2, _ = makeAssistant(llm)
        assistant2.submit("segunda")

        assert recorder.waitFor(SpeechFinished, timeout=10)

    def testSayDirectlyNaoUsaOLlm(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm()
        assistant, _ = makeAssistant(llm)

        assistant.sayDirectly("Bem-vindo de volta ao centro de testes.")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        assert llm.prompts == []
        assert recorder.ofType(ThinkingStarted) == []
        assert recorder.ofType(AssistantReply)

    def testInterruptSilenciaAFala(self, makeAssistant, makeLlm, sink) -> None:
        assistant, _ = makeAssistant(makeLlm())

        assistant.interrupt()

        assert sink.stops >= 1


class TestConversationMemory:
    def testPromptComecaComAMensagemDeSistema(self) -> None:
        memory = ConversationMemory("seja breve")
        memory.addUser("olá")

        prompt = memory.buildPrompt()

        assert prompt[0].role == "system"
        assert prompt[0].content == "seja breve"
        assert prompt[1].content == "olá"

    def testJanelaDescartaAsMensagensAntigas(self) -> None:
        memory = ConversationMemory("sistema", maxMessages=2)
        memory.addUser("primeira")
        memory.addUser("segunda")
        memory.addUser("terceira")

        conteudos = [m.content for m in memory.buildPrompt()[1:]]

        assert conteudos == ["segunda", "terceira"]

    def testMensagensVaziasSaoIgnoradas(self) -> None:
        memory = ConversationMemory("sistema")
        memory.addUser("   ")

        assert len(memory) == 0

    def testClearApagaOHistoricoMasMantemOSistema(self) -> None:
        memory = ConversationMemory("sistema")
        memory.addUser("olá")
        memory.clear()

        assert len(memory) == 0
        assert memory.buildPrompt()[0].role == "system"

    def testTrocaDoPromptDeSistema(self) -> None:
        memory = ConversationMemory("antigo")
        memory.replaceSystemPrompt("novo")

        assert memory.buildPrompt()[0].content == "novo"
