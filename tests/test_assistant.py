"""Testes do orquestrador e da memória de conversa."""

from __future__ import annotations

import time

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

    def testRespostaEEntregueAVozFraseAFrase(self, makeAssistant, makeLlm, recorder) -> None:
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

    def testConversaFicaAquecidaComARespostaNoFim(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Uma resposta suficientemente longa para o teste.")
        assistant, _ = makeAssistant(llm)

        assistant.submit("qual é a resposta?")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        for _ in range(100):  # o aquecimento vem depois do turno, na mesma thread
            if llm.aquecidas:
                break
            time.sleep(0.02)
        ultima = llm.aquecidas[-1][-1]
        assert ultima.role == "assistant"
        assert ultima.content == "Uma resposta suficientemente longa para o teste."
        assert not assistant.isBusy

    def testConversaParadaRecomecaDoZero(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Uma resposta suficientemente longa para o teste.")
        assistant, _ = makeAssistant(llm, esquecerAposS=0.0)

        assistant.submit("primeira")
        assert recorder.waitFor(SpeechFinished, timeout=10)
        recorder.events.clear()
        time.sleep(0.01)
        assistant.submit("segunda")
        assert recorder.waitFor(SpeechFinished, timeout=10)

        conteudos = [m.content for m in llm.prompts[-1][1:]]
        assert conteudos == ["segunda"]

    def testConversaSeguidaGuardaOHistorico(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Uma resposta suficientemente longa para o teste.")
        assistant, _ = makeAssistant(llm)

        assistant.submit("primeira")
        assert recorder.waitFor(SpeechFinished, timeout=10)
        recorder.events.clear()
        assistant.submit("segunda")
        assert recorder.waitFor(SpeechFinished, timeout=10)

        assert llm.prompts[-1][1].content == "primeira"

    def testPromptDeSistemaVaiJunto(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Uma resposta suficientemente longa para o teste.")
        assistant, _ = makeAssistant(llm, systemPrompt="seja sarcástica")

        assistant.submit("olá")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        primeira = llm.prompts[-1][0]
        assert primeira.role == "system"
        assert primeira.content.startswith("seja sarcástica\n\nHoje e ")

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


class TestLinguagemNeutra:
    """O modelo pequeno espelha o gênero da pergunta; a resposta sai neutra mesmo assim."""

    def testRespostaSaiNeutraNaTelaNaVozENoHistorico(
        self, makeAssistant, makeLlm, recorder, engine
    ) -> None:
        llm = makeLlm("Sim, estou pronta para ajudar. Muito obrigada pela pergunta!")
        assistant, memory = makeAssistant(llm, language="pt", linguagemNeutra=True)

        assistant.submit("Você está pronta?")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        neutra = "Sim, estou à disposição para ajudar. Agradeço muito pela pergunta!"
        assert recorder.ofType(AssistantReply)[-1].text == neutra
        assert " ".join(engine.spoken) == neutra
        assert memory.buildPrompt()[-1].content == neutra

    def testDesligadaNaoMexe(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Sim, estou pronta para ajudar.")
        assistant, _ = makeAssistant(llm, language="pt", linguagemNeutra=False)

        assistant.submit("Você está pronta?")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        assert recorder.ofType(AssistantReply)[-1].text == "Sim, estou pronta para ajudar."

    def testSoValeParaPortugues(self, makeAssistant, makeLlm) -> None:
        assistant, _ = makeAssistant(makeLlm(), language="en", linguagemNeutra=True)
        assert not assistant.linguagemNeutra


class TestConversationMemory:
    def testPrefixoAquecidoEOComecoDaProximaPergunta(self) -> None:
        for trocas in range(6):  # vazia, enchendo e já descartando (janela de 4)
            memory = ConversationMemory("sistema", maxMessages=4)
            for i in range(trocas):
                memory.addUser(f"pergunta {i}")
                memory.addAssistant(f"resposta {i}")
            prefixo = memory.buildNextPrefix()
            memory.addUser("a próxima")
            assert memory.buildPrompt()[: len(prefixo)] == prefixo, trocas

    def testPromptComecaComAMensagemDeSistema(self) -> None:
        memory = ConversationMemory("seja breve")
        memory.addUser("olá")

        prompt = memory.buildPrompt()

        assert prompt[0].role == "system"
        assert prompt[0].content.startswith("seja breve\n\nHoje e ")
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

        assert memory.buildPrompt()[0].content.startswith("novo\n\nHoje e ")


class TestPiadas:
    def testPiadaRespondeSemOModelo(self, makeAssistant, makeLlm, recorder) -> None:
        """O modelo nao entende graca; a piada pedida sai pronta e sem pensar."""
        llm = makeLlm("Não sei contar piadas.")
        assistant, _ = makeAssistant(llm, language="pt")

        assistant.submit("me conta uma piada")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        assert llm.prompts == []
        assert "ThinkingStarted" not in recorder.typeNames()
        resposta = recorder.ofType(AssistantReply)[0].text  # type: ignore[attr-defined]
        assert "Hahaha" in resposta

    def testConversaNormalVaiAoModelo(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm("Sou a Atlas.")
        assistant, _ = makeAssistant(llm, language="pt")

        assistant.submit("qual é o seu nome")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        assert len(llm.prompts) == 1


class TestRespostasSemModelo:
    def testContaSaiCertaSemOModelo(self, makeAssistant, makeLlm, recorder) -> None:
        """O modelo pequeno chuta aritmetica; a conta sai calculada."""
        llm = makeLlm("A raiz quadrada de dezesseis é oito.")
        assistant, _ = makeAssistant(llm, language="pt")

        assistant.submit("qual a raiz quadrada de dezesseis")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        assert llm.prompts == []
        assert recorder.ofType(AssistantReply)[0].text.rstrip(".").endswith("4")  # type: ignore[attr-defined]

    def testFraseRepetidaPeloModeloSaiUmaVez(self, makeAssistant, makeLlm, recorder) -> None:
        llm = makeLlm(
            "O céu é azul por causa da luz do sol. "
            "O céu é azul por causa da luz do sol. Ela espalha mais o azul."
        )
        assistant, _ = makeAssistant(llm, language="pt")

        assistant.submit("por que o céu é azul")

        assert recorder.waitFor(SpeechFinished, timeout=10)
        resposta = recorder.ofType(AssistantReply)[0].text  # type: ignore[attr-defined]
        assert resposta == "O céu é azul por causa da luz do sol. Ela espalha mais o azul."
