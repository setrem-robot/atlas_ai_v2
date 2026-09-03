"""Testes do locutor assíncrono."""

from __future__ import annotations

from roboteye.core.events import ErrorOccurred, SpeechFinished, SpeechStarted
from roboteye.speech.base import SpeechError
from roboteye.speech.speaker import MAX_BATCH_CHARS, Speaker, _Utterance


class BrokenEngine:
    """Motor que sempre falha, para exercitar o tratamento de erro."""

    name = "broken"

    def synthesize(self, text: str):
        raise SpeechError("modelo ausente")
        yield  # pragma: no cover - torna a função um gerador

    def warm_up(self) -> None: ...

    def close(self) -> None: ...


class TestSpeaker:
    def test_fala_o_texto_enfileirado(self, make_speaker, engine, sink) -> None:
        speaker = make_speaker()
        speaker.say("Olá, sujeito de testes.")

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == ["Olá, sujeito de testes."]
        assert len(sink.written) > 0

    def test_publica_inicio_e_fim(self, make_speaker, recorder) -> None:
        speaker = make_speaker()
        speaker.say("Uma frase qualquer.")
        speaker.end_turn()

        assert recorder.wait_for(SpeechFinished, timeout=5)
        assert len(recorder.of_type(SpeechStarted)) == 1
        assert len(recorder.of_type(SpeechFinished)) == 1

    def test_texto_vazio_e_ignorado(self, make_speaker, engine) -> None:
        speaker = make_speaker()
        speaker.say("   ")
        speaker.say("")

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == []

    def test_markdown_e_removido_antes_de_falar(self, make_speaker, engine) -> None:
        speaker = make_speaker()
        speaker.say("**muito** importante")

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == ["muito importante"]

    def test_formato_do_audio_e_repassado_a_saida(self, make_speaker, sink) -> None:
        speaker = make_speaker()
        speaker.say("qualquer texto aqui")

        assert speaker.wait_until_idle(timeout=5)
        assert sink.starts and sink.starts[0].sample_rate == 22050

    def test_interrupcao_descarta_a_fila(self, make_speaker, engine, sink) -> None:
        # Sem iniciar a thread, nada é consumido: a fila fica inteira para descartar.
        speaker = make_speaker(start=False)
        speaker.say("primeira frase bem longa")
        speaker.say("segunda frase bem longa")
        speaker.interrupt()
        speaker.start()

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == [], "as frases descartadas não deveriam ser sintetizadas"
        assert sink.stops == 1

    def test_falas_novas_apos_interrupcao_sao_aceitas(self, make_speaker, engine) -> None:
        speaker = make_speaker()
        speaker.interrupt()
        speaker.say("depois da interrupção")

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == ["depois da interrupção"]

    def test_erro_de_sintese_vira_evento(self, make_speaker, recorder) -> None:
        speaker = make_speaker(BrokenEngine())
        speaker.say("qualquer coisa")

        assert recorder.wait_for(ErrorOccurred, timeout=5)
        erros = recorder.of_type(ErrorOccurred)
        assert "modelo ausente" in erros[0].message

    def test_erro_nao_derruba_a_thread(self, make_speaker, recorder) -> None:
        """Depois de falhar, o locutor tem de continuar aceitando trabalho.

        Não se conta erros aqui: frases que já estão na fila são sintetizadas
        juntas, então duas frases podem render um erro só. O que importa é que a
        thread sobreviveu — provado por ela ainda reagir ao que vem depois.
        """
        speaker = make_speaker(BrokenEngine())
        speaker.say("primeira")
        speaker.say("segunda")
        assert speaker.wait_until_idle(timeout=5)

        antes = len(recorder.of_type(ErrorOccurred))
        assert antes >= 1

        speaker.say("depois do erro")
        assert speaker.wait_until_idle(timeout=5)

        assert len(recorder.of_type(ErrorOccurred)) > antes, "a thread morreu no primeiro erro"

    # -- lote de frases ----------------------------------------------------
    def test_frases_que_ja_chegaram_sao_sintetizadas_juntas(self, make_speaker, engine) -> None:
        """Cada síntese cobra um custo fixo, e num motor de rede ele é uma ida
        e volta inteira — que vira silêncio entre uma frase e outra. Medindo com
        a voz online, o buraco passava de um segundo.

        Juntar o que já está na fila também soa melhor: o motor entoa a passagem
        de uma frase para a outra em vez de produzir duas leituras coladas.
        """
        speaker = make_speaker()
        speaker.start()
        speaker.say("Primeira frase.")
        speaker.say("Segunda frase.")

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == ["Primeira frase. Segunda frase."]

    def test_frase_sozinha_nao_espera_por_companhia(self, make_speaker, engine) -> None:
        """O lote leva só o que já chegou; nunca segura a fala esperando mais.

        É o que preserva o motivo de cortar em frases: começar a falar antes de
        o modelo terminar de escrever.
        """
        speaker = make_speaker()
        speaker.start()
        speaker.say("Sozinha.")
        assert speaker.wait_until_idle(timeout=5)

        speaker.say("Depois.")
        assert speaker.wait_until_idle(timeout=5)

        assert engine.spoken == ["Sozinha.", "Depois."]

    def test_o_lote_para_no_fim_do_turno(self, make_speaker, engine, recorder) -> None:
        """Duas respostas seguidas não podem virar uma fala só."""
        speaker = make_speaker()
        speaker.start()
        speaker.say("Resposta um.")
        speaker.end_turn()
        speaker.say("Resposta dois.")
        speaker.end_turn()

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == ["Resposta um.", "Resposta dois."]
        assert len(recorder.of_type(SpeechFinished)) == 2

    def test_o_lote_nao_ressuscita_fala_interrompida(self, make_speaker, engine) -> None:
        """Sobra de uma fala já descartada não pode entrar no lote da seguinte."""
        speaker = make_speaker()
        speaker.start()
        speaker.say("descartada")
        speaker.interrupt()
        speaker.say("a que vale")

        assert speaker.wait_until_idle(timeout=5)
        assert "descartada" not in " ".join(engine.spoken)

    def test_lote_respeita_o_teto_de_tamanho(self, make_speaker, engine) -> None:
        """Uma resposta longa não pode ser toda segurada até o fim da síntese."""
        speaker = make_speaker()
        speaker.start()
        for _ in range(12):
            speaker.say("Uma frase de tamanho razoavel para encher o lote.")

        assert speaker.wait_until_idle(timeout=10)
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

    def test_com_a_fila_vazia_e_nada_pendente_e_silencio(self, make_speaker) -> None:
        speaker = make_speaker(start=False)
        speaker._idle.clear()

        speaker._anunciar_silencio_se_acabou()

        assert speaker.wait_until_idle(timeout=0.1)
        assert not speaker.is_speaking

    def test_uma_fala_ja_sintetizada_segura_o_silencio(self, make_speaker) -> None:
        """`_pronto` e a proxima frase, com o audio na mao. Ainda ha o que dizer."""
        speaker = make_speaker(start=False)
        speaker._idle.clear()
        speaker._pronto = (_Utterance("a proxima frase", 0), None)

        speaker._anunciar_silencio_se_acabou()

        assert not speaker.wait_until_idle(timeout=0.1)

    def test_uma_fala_retida_segura_o_silencio(self, make_speaker) -> None:
        """`_held` guarda o que ja saiu da fila e ainda nao foi dito."""
        speaker = make_speaker(start=False)
        speaker._idle.clear()
        speaker._held.append(_Utterance("retida", 0))

        speaker._anunciar_silencio_se_acabou()

        assert not speaker.wait_until_idle(timeout=0.1)

    def test_a_ultima_fala_vindo_pronta_ainda_anuncia_silencio(self, make_speaker, engine) -> None:
        """O defeito exato, forcado sem depender de temporizacao.

        `_pronto` e o primeiro lugar que o laco olha. Deixando uma fala ali
        antes de o locutor arrancar, ele passa obrigatoriamente pelo caminho da
        sintese adiantada — que era justamente o que voltava para a fila sem
        anunciar nada.

        Com o defeito este teste falha sempre; com a correcao passa sempre. A
        versao anterior dependia de sorte e reprovava um terco do tempo, que e a
        pior coisa que um teste pode fazer: acusar sem apontar nada.
        """
        speaker = make_speaker(start=False)
        speaker._idle.clear()
        speaker._pronto = (_Utterance("ja sintetizada", speaker._state.generation), None)

        speaker.start()

        assert speaker.wait_until_idle(timeout=5), "o locutor nunca anunciou silencio"
        assert not speaker.is_speaking
        assert engine.spoken == ["ja sintetizada"]


class TestSpeakerEncerramento:
    def test_close_libera_recursos(self, engine, sink, bus) -> None:
        speaker = Speaker(engine, sink, bus)
        speaker.start()
        speaker.close()

        assert engine.closed
        assert sink.closed

    def test_close_e_idempotente(self, engine, sink, bus) -> None:
        speaker = Speaker(engine, sink, bus)
        speaker.start()
        speaker.close()
        speaker.close()  # não deve levantar

    def test_warm_up_delega_ao_motor(self, engine, sink, bus) -> None:
        Speaker(engine, sink, bus).warm_up()
        assert engine.warmed_up
