"""Testes do locutor assíncrono."""

from __future__ import annotations

from roboteye.core.events import ErrorOccurred, SpeechFinished, SpeechStarted
from roboteye.speech.base import SpeechError
from roboteye.speech.speaker import MAX_BATCH_CHARS, Speaker, Utterance


class BrokenEngine:
    """Motor que sempre falha, para exercitar o tratamento de erro."""

    name = "broken"

    def synthesize(self, text: str):
        raise SpeechError("modelo ausente")
        yield  # pragma: no cover - torna a função um gerador

    def warmUp(self) -> None: ...

    def close(self) -> None: ...


class TestSpeaker:
    def testFalaOTextoEnfileirado(self, makeSpeaker, engine, sink) -> None:
        speaker = makeSpeaker()
        speaker.say("Olá, sujeito de testes.")

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == ["Olá, sujeito de testes."]
        assert len(sink.written) > 0

    def testPublicaInicioEFim(self, makeSpeaker, recorder) -> None:
        speaker = makeSpeaker()
        speaker.say("Uma frase qualquer.")
        speaker.endTurn()

        assert recorder.waitFor(SpeechFinished, timeout=5)
        assert len(recorder.ofType(SpeechStarted)) == 1
        assert len(recorder.ofType(SpeechFinished)) == 1

    def testTextoVazioEIgnorado(self, makeSpeaker, engine) -> None:
        speaker = makeSpeaker()
        speaker.say("   ")
        speaker.say("")

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == []

    def testMarkdownERemovidoAntesDeFalar(self, makeSpeaker, engine) -> None:
        speaker = makeSpeaker()
        speaker.say("**muito** importante")

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == ["muito importante"]

    def testFormatoDoAudioERepassadoASaida(self, makeSpeaker, sink) -> None:
        speaker = makeSpeaker()
        speaker.say("qualquer texto aqui")

        assert speaker.waitUntilIdle(timeout=5)
        assert sink.starts and sink.starts[0].sampleRate == 22050

    def testInterrupcaoDescartaAFila(self, makeSpeaker, engine, sink) -> None:
        # Sem iniciar a thread, nada é consumido: a fila fica inteira para descartar.
        speaker = makeSpeaker(start=False)
        speaker.say("primeira frase bem longa")
        speaker.say("segunda frase bem longa")
        speaker.interrupt()
        speaker.start()

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == [], "as frases descartadas não deveriam ser sintetizadas"
        assert sink.stops == 1

    def testFalasNovasAposInterrupcaoSaoAceitas(self, makeSpeaker, engine) -> None:
        speaker = makeSpeaker()
        speaker.interrupt()
        speaker.say("depois da interrupção")

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == ["depois da interrupção"]

    def testErroDeSinteseViraEvento(self, makeSpeaker, recorder) -> None:
        speaker = makeSpeaker(BrokenEngine())
        speaker.say("qualquer coisa")

        assert recorder.waitFor(ErrorOccurred, timeout=5)
        erros = recorder.ofType(ErrorOccurred)
        assert "modelo ausente" in erros[0].message

    def testErroNaoDerrubaAThread(self, makeSpeaker, recorder) -> None:
        """Depois de falhar, o locutor tem de continuar aceitando trabalho.

        Não se conta erros aqui: frases que já estão na fila são sintetizadas
        juntas, então duas frases podem render um erro só. O que importa é que a
        thread sobreviveu — provado por ela ainda reagir ao que vem depois.
        """
        speaker = makeSpeaker(BrokenEngine())
        speaker.say("primeira")
        speaker.say("segunda")
        assert speaker.waitUntilIdle(timeout=5)

        antes = len(recorder.ofType(ErrorOccurred))
        assert antes >= 1

        speaker.say("depois do erro")
        assert speaker.waitUntilIdle(timeout=5)

        assert len(recorder.ofType(ErrorOccurred)) > antes, "a thread morreu no primeiro erro"

    # -- lote de frases ----------------------------------------------------
    def testFrasesQueJaChegaramSaoSintetizadasJuntas(self, makeSpeaker, engine) -> None:
        """Cada síntese cobra um custo fixo, e num motor de rede ele é uma ida
        e volta inteira — que vira silêncio entre uma frase e outra. Medindo com
        a voz online, o buraco passava de um segundo.

        Juntar o que já está na fila também soa melhor: o motor entoa a passagem
        de uma frase para a outra em vez de produzir duas leituras coladas.
        """
        speaker = makeSpeaker()
        speaker.start()
        speaker.say("Primeira frase.")
        speaker.say("Segunda frase.")

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == ["Primeira frase. Segunda frase."]

    def testFraseSozinhaNaoEsperaPorCompanhia(self, makeSpeaker, engine) -> None:
        """O lote leva só o que já chegou; nunca segura a fala esperando mais.

        É o que preserva o motivo de cortar em frases: começar a falar antes de
        o modelo terminar de escrever.
        """
        speaker = makeSpeaker()
        speaker.start()
        speaker.say("Sozinha.")
        assert speaker.waitUntilIdle(timeout=5)

        speaker.say("Depois.")
        assert speaker.waitUntilIdle(timeout=5)

        assert engine.spoken == ["Sozinha.", "Depois."]

    def testOLoteParaNoFimDoTurno(self, makeSpeaker, engine, recorder) -> None:
        """Duas respostas seguidas não podem virar uma fala só."""
        speaker = makeSpeaker()
        speaker.start()
        speaker.say("Resposta um.")
        speaker.endTurn()
        speaker.say("Resposta dois.")
        speaker.endTurn()

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == ["Resposta um.", "Resposta dois."]
        assert len(recorder.ofType(SpeechFinished)) == 2

    def testOLoteNaoRessuscitaFalaInterrompida(self, makeSpeaker, engine) -> None:
        """Sobra de uma fala já descartada não pode entrar no lote da seguinte."""
        speaker = makeSpeaker()
        speaker.start()
        speaker.say("descartada")
        speaker.interrupt()
        speaker.say("a que vale")

        assert speaker.waitUntilIdle(timeout=5)
        assert "descartada" not in " ".join(engine.spoken)

    def testLoteRespeitaOTetoDeTamanho(self, makeSpeaker, engine) -> None:
        """Uma resposta longa não pode ser toda segurada até o fim da síntese."""
        speaker = makeSpeaker()
        speaker.start()
        for _ in range(12):
            speaker.say("Uma frase de tamanho razoavel para encher o lote.")

        assert speaker.waitUntilIdle(timeout=10)
        assert len(engine.spoken) > 1, "juntou tudo e atrasaria o inicio da fala"
        assert all(len(fala) <= MAX_BATCH_CHARS + 80 for fala in engine.spoken)


class TestOSilencioSoValeQuandoAcabou:
    """Quem anuncia silencio precisa olhar os TRES lugares onde uma fala espera.

    A fila nao e o unico: `_held` guarda o que saiu dela e ainda nao foi dito, e
    `_pronto` guarda o audio ja sintetizado da proxima frase. Anunciar silencio
    com qualquer um dos dois cheio faz a face parar de falar antes da voz.

    Esta classe existe por um defeito que se manifestava como teste instavel: o
    caminho da fala ja preparada terminava em `continue` e pulava o `finally`
    que anuncia o silencio. Quando a ULTIMA fala de uma resposta vinha pronta —
    o caso comum, porque a sintese se adianta —, o locutor a dizia e voltava a
    esperar na fila sem nunca ter anunciado nada. `wait_until_idle` esperava
    para sempre.
    """

    def testComAFilaVaziaENadaPendenteESilencio(self, makeSpeaker) -> None:
        speaker = makeSpeaker(start=False)
        speaker.idle.clear()

        speaker.anunciarSilencioSeAcabou()

        assert speaker.waitUntilIdle(timeout=0.1)
        assert not speaker.isSpeaking

    def testUmaFalaJaSintetizadaSeguraOSilencio(self, makeSpeaker) -> None:
        """`_pronto` e a proxima frase, com o audio na mao. Ainda ha o que dizer."""
        speaker = makeSpeaker(start=False)
        speaker.idle.clear()
        speaker.pronto = (Utterance("a proxima frase", 0), None)

        speaker.anunciarSilencioSeAcabou()

        assert not speaker.waitUntilIdle(timeout=0.1)

    def testUmaFalaRetidaSeguraOSilencio(self, makeSpeaker) -> None:
        """`_held` guarda o que ja saiu da fila e ainda nao foi dito."""
        speaker = makeSpeaker(start=False)
        speaker.idle.clear()
        speaker.held.append(Utterance("retida", 0))

        speaker.anunciarSilencioSeAcabou()

        assert not speaker.waitUntilIdle(timeout=0.1)

    def testAUltimaFalaVindoProntaAindaAnunciaSilencio(self, makeSpeaker, engine) -> None:
        """O defeito exato, forcado sem depender de temporizacao.

        `_pronto` e o primeiro lugar que o laco olha. Deixando uma fala ali
        antes de o locutor arrancar, ele passa obrigatoriamente pelo caminho da
        sintese adiantada — que era justamente o que voltava para a fila sem
        anunciar nada.

        Com o defeito este teste falha sempre; com a correcao passa sempre. A
        versao anterior dependia de sorte e reprovava um terco do tempo, que e a
        pior coisa que um teste pode fazer: acusar sem apontar nada.
        """
        speaker = makeSpeaker(start=False)
        speaker.idle.clear()
        speaker.pronto = (Utterance("ja sintetizada", speaker.state.generation), None)

        speaker.start()

        assert speaker.waitUntilIdle(timeout=5), "o locutor nunca anunciou silencio"
        assert not speaker.isSpeaking
        assert engine.spoken == ["ja sintetizada"]


class TestSpeakerEncerramento:
    def testCloseLiberaRecursos(self, engine, sink, bus) -> None:
        speaker = Speaker(engine, sink, bus)
        speaker.start()
        speaker.close()

        assert engine.closed
        assert sink.closed

    def testCloseEIdempotente(self, engine, sink, bus) -> None:
        speaker = Speaker(engine, sink, bus)
        speaker.start()
        speaker.close()
        speaker.close()  # não deve levantar

    def testWarmUpDelegaAoMotor(self, engine, sink, bus) -> None:
        Speaker(engine, sink, bus).warmUp()
        assert engine.warmedUp
