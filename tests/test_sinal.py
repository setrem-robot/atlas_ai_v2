"""O som que diz "estou ouvindo".

Um bipe parece pequeno demais para ter teste. Mas ele toca com o microfone
aberto, pelo mesmo dispositivo da voz, e as duas coisas dão errado de um jeito
que ninguém percebe olhando o código: o robô ouvindo o próprio sinal e o
tratando como pergunta, e o sinal pausando a escuta que ele existe para
anunciar.
"""

from __future__ import annotations

import math
import struct
from itertools import pairwise

import pytest

from roboteye.core.events import ListeningChanged, SpeechFinished, SpeechStarted
from roboteye.hearing.microfone import BLOCO, TAXA
from roboteye.speech import sinal


def amostras(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


class TestOPar:
    """Os dois sons são um par, e é o par que carrega o significado."""

    def testSaoSonsDiferentes(self) -> None:
        assert sinal.escutando()[0].audio != sinal.ouvi()[0].audio

    def testUmSobeEOOutroDesce(self) -> None:
        """Subindo se lê "pode falar"; descendo, "pronto, ouvi".

        Um som sozinho não diria qual dos dois momentos é — e saber qual é o
        pedido inteiro. Se um dia os dois virarem o mesmo, o robô passa a
        avisar duas vezes a mesma coisa.
        """
        assert picoNoFim(sinal.escutando()) > picoNoComeco(sinal.escutando())
        assert picoNoFim(sinal.ouvi()) < picoNoComeco(sinal.ouvi())

    def testDuramOMesmo(self) -> None:
        assert len(sinal.escutando()[0].audio) == len(sinal.ouvi()[0].audio)


def frequenciaDominante(pcm: bytes) -> float:
    """Frequência aproximada, contando quantas vezes o sinal cruza o zero."""
    v = amostras(pcm)
    cruzamentos = sum(1 for a, b in pairwise(v) if (a >= 0) != (b >= 0))
    return cruzamentos / 2 / (len(v) / sinal.TAXA)


def umTerco(pcm: bytes) -> int:
    """Corte alinhado à amostra: cada uma tem 2 bytes, e meio não existe."""
    return (len(pcm) // 3) // 2 * 2


def picoNoComeco(chunks) -> float:
    pcm = chunks[0].audio
    return frequenciaDominante(pcm[: umTerco(pcm)])


def picoNoFim(chunks) -> float:
    pcm = chunks[0].audio
    return frequenciaDominante(pcm[len(pcm) - umTerco(pcm) :])


class TestOSom:
    def testECurtoDemaisParaVirarPergunta(self) -> None:
        """O microfone descarta trechos com menos de 0.4 s de voz.

        Este é o número que impede o robô de ouvir o próprio sinal e responder
        a ele. Se um dia o sinal crescer além disso, o robô passa a conversar
        consigo mesmo — e o sintoma (ele responde sozinho ao ser chamado) não
        aponta para cá.
        """
        minimoDoMicrofoneS = 0.4
        assert sinal.duracaoS() < minimoDoMicrofoneS

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def testNaoComecaNemTerminaComEstalo(self, qual: str) -> None:
        """Corte seco numa senoide vira clique, e clique se ouve mais que a nota."""
        valores = amostras(getattr(sinal, qual)()[0].audio)
        assert abs(valores[0]) < 100, "começa com degrau"
        assert abs(valores[-1]) < 100, "termina com degrau"

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def testNaoEstouraAEscala(self, qual: str) -> None:
        valores = amostras(getattr(sinal, qual)()[0].audio)
        assert max(abs(v) for v in valores) < 32767

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def testTemSomDeVerdadeNoMeio(self, qual: str) -> None:
        """Um sinal silencioso passaria em todos os testes acima."""
        valores = amostras(getattr(sinal, qual)()[0].audio)
        energia = math.sqrt(sum(v * v for v in valores) / len(valores))
        assert energia > 1000, f"o sinal saiu quase mudo (rms {energia:.0f})"

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def testOFormatoEOQueAPlacaEspera(self, qual: str) -> None:
        chunk = getattr(sinal, qual)()[0]
        assert chunk.format.channels == 1
        assert chunk.format.sampleWidth == 2
        assert chunk.format.sampleRate == sinal.TAXA


class TestOLocutorTocaSemAnunciarFala:
    """Um sinal não é uma frase, e a diferença tem consequência.

    Quem escuta `SpeechStarted` pausa o microfone (ver `app.py`). Um sinal que
    publicasse esse evento deixaria o robô surdo no exato instante em que
    anuncia que está ouvindo — e como `SpeechFinished` só vem no fim de um
    turno de conversa, a escuta não voltaria sozinha.
    """

    def testOSomChegaAoDispositivo(self, makeSpeaker, sink) -> None:
        speaker = makeSpeaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.waitUntilIdle(timeout=5)
        assert bytes(sink.written) == sinal.escutando()[0].audio

    def testNaoPublicaEventoDeFala(self, makeSpeaker, recorder) -> None:
        speaker = makeSpeaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.waitUntilIdle(timeout=5)
        assert recorder.ofType(SpeechStarted) == []
        assert recorder.ofType(SpeechFinished) == []

    def testNaoViraTextoNoMotorDeVoz(self, makeSpeaker, engine) -> None:
        """O áudio já vem pronto: mandá-lo ao motor sintetizaria texto vazio."""
        speaker = makeSpeaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == []

    def testNaoSeMisturaComAFalaSeguinte(self, makeSpeaker, engine) -> None:
        """O lote junta frases para economizar ida e volta. O sinal não é frase."""
        speaker = makeSpeaker()
        speaker.sinalizar(sinal.escutando())
        speaker.say("A pergunta chegou.")

        assert speaker.waitUntilIdle(timeout=5)
        assert engine.spoken == ["A pergunta chegou."]

    def testOLocutorVoltaAFicarOcioso(self, makeSpeaker) -> None:
        """Sem isto, o sinal deixaria `wait_until_idle` preso para sempre."""
        speaker = makeSpeaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.waitUntilIdle(timeout=5)
        assert not speaker.isSpeaking


class TestQuandoOSinalToca:
    """Só na abertura da janela de escuta."""

    def appFalsa(self, bus, gravador: list):
        """Liga o mesmo handler que a `Application` liga, com um locutor de mentira."""
        from roboteye.app import Application

        class LocutorFalso:
            def sinalizar(self, chunks) -> None:
                gravador.append(chunks)

        app = object.__new__(Application)
        app.speaker = LocutorFalso()  # type: ignore[assignment]
        bus.subscribe(app.avisarQueEstouOuvindo, eventType=ListeningChanged)
        return app

    def testTocaQuandoAJanelaAbre(self, bus) -> None:
        tocados: list = []
        self.appFalsa(bus, tocados)

        bus.publish(ListeningChanged(active=True))

        assert len(tocados) == 1

    def testNaoTocaQuandoAJanelaFecha(self, bus) -> None:
        """Fechar é ou a pergunta chegando (a resposta avisa) ou o tempo passando."""
        tocados: list = []
        self.appFalsa(bus, tocados)

        bus.publish(ListeningChanged(active=False))

        assert tocados == []


class TestOSinalDeFimDeEscuta:
    """O segundo som do par: "terminei de ouvir, agora deixa comigo".

    Ele vem do **microfone**, e não do reconhecimento. A diferença é de quase
    dois segundos num Raspberry Pi: esperar a transcrição faria o aviso chegar
    depois de a pessoa já ter desistido de esperar por ele.
    """

    def appFalsa(self, tocados: list, conversa):
        from roboteye.app import Application

        class LocutorFalso:
            def sinalizar(self, chunks) -> None:
                tocados.append(chunks)

        app = object.__new__(Application)
        app.speaker = LocutorFalso()  # type: ignore[assignment]
        app.conversa = conversa
        return app

    def testTocaQuandoAJanelaEstaAberta(self) -> None:
        from roboteye.hearing.gatilho import Conversa

        conversa = Conversa(8.0)
        conversa.abrir()
        tocados: list = []
        app = self.appFalsa(tocados, conversa)

        app.avisarQueTermineiDeOuvir()

        assert tocados == [sinal.ouvi()]

    def testNaoTocaComAJanelaFechada(self) -> None:
        """Um microfone aberto numa sala fecha uma captura a cada frase que
        alguém diz por perto. Sem esta guarda o robô apitaria o dia inteiro."""
        from roboteye.hearing.gatilho import Conversa

        tocados: list = []
        app = self.appFalsa(tocados, Conversa(8.0))  # nunca aberta

        app.avisarQueTermineiDeOuvir()

        assert tocados == []

    def testNaoTocaAntesDeAEscutaComecar(self) -> None:
        tocados: list = []
        app = self.appFalsa(tocados, None)

        app.avisarQueTermineiDeOuvir()

        assert tocados == []


class TestOMicrofoneAvisaAoFecharAFrase:
    """O gancho que faz o aviso chegar antes da transcrição."""

    def blocos(self, m, voz: int, silencio: int):
        import numpy as np

        from roboteye.hearing.microfone import BLOCO

        for _ in range(3):
            m.blocos.put_nowait(np.full(BLOCO, 0.001, dtype=np.float32))
        for _ in range(voz):
            m.blocos.put_nowait(np.full(BLOCO, 0.2, dtype=np.float32))
        for _ in range(silencio):
            m.blocos.put_nowait(np.full(BLOCO, 0.001, dtype=np.float32))
        m.blocos.put_nowait(None)

    def testAvisaUmaVezPorFrase(self) -> None:
        from roboteye.hearing.microfone import Microfone

        m = Microfone(limiar=0.02, silencioS=0.3, minimoS=0.15, maximoS=1.0)
        avisos: list[int] = []
        m.aoFecharFrase(lambda: avisos.append(1))

        self.blocos(m, voz=20, silencio=15)
        frases = list(m.cortarEmFrases())

        assert len(frases) == 1
        assert len(avisos) == 1

    def testNaoAvisaPorRuidoDescartado(self) -> None:
        """Um estalo de porta não é pergunta, e não merece som de resposta."""
        from roboteye.hearing.microfone import Microfone

        m = Microfone(limiar=0.02, silencioS=0.3, minimoS=0.15, maximoS=1.0)
        avisos: list[int] = []
        m.aoFecharFrase(lambda: avisos.append(1))

        self.blocos(m, voz=2, silencio=15)  # curto demais para ser fala
        frases = list(m.cortarEmFrases())

        assert frases == []
        assert avisos == []

    def testUmAvisoQueFalhaNaoPerdeAFrase(self) -> None:
        """O aviso é conforto; a frase é o que a pessoa acabou de dizer."""
        from roboteye.hearing.microfone import Microfone

        m = Microfone(limiar=0.02, silencioS=0.3, minimoS=0.15, maximoS=1.0)

        def explodir() -> None:
            raise RuntimeError("o alto-falante sumiu")

        m.aoFecharFrase(explodir)
        self.blocos(m, voz=20, silencio=15)

        assert len(list(m.cortarEmFrases())) == 1

    def testOOuvidoRepassaOAvisoAoMicrofone(self) -> None:
        """`WhisperEars` é quem a `Application` enxerga; o gancho passa por ele."""
        from roboteye.hearing import AvisaAoFecharFrase
        from roboteye.hearing.whisperEars import WhisperEars

        ouvido = WhisperEars("tiny")
        assert isinstance(ouvido, AvisaAoFecharFrase)

        def avisar() -> None: ...

        ouvido.aoFecharFrase(avisar)
        assert ouvido.microfone.callbackFimFrase is avisar


class TestOVigiaDoMicrofoneNaoContaOTempoDeFala:
    """Enquanto a Atlas fala, a captura descarta o que chega — de propósito.

    O vigia existe para perceber um dispositivo morto. Se ele contasse também o
    tempo em que a escuta está pausada, toda resposta com mais de três segundos
    terminaria numa reabertura do microfone que ninguém pediu — e o robô ficaria
    cerca de um segundo surdo justo depois de responder, que é quando a pessoa
    costuma emendar a próxima pergunta. Foi o que aconteceu no robô:

        14:08:36  falando: Atualmente, o curso de Engenharia ...
        14:08:44  o microfone parou de entregar audio (nada ha 3s); reabrindo
        14:08:45  escutando pelo microfone

    O relógio é controlado pelo teste: sem isso, a diferença entre "conta o
    tempo pausado" e "não conta" viraria uma corrida com o agendador.
    """

    def rodarComRelogio(self, monkeypatch, roteiro) -> list[BaseException]:
        """Executa o corte em frases com um relógio que o teste move.

        `roteiro` recebe o microfone e a função que avança o relógio.
        """
        import threading
        import time as _time

        from roboteye.hearing import microfone as micMod
        from roboteye.hearing.microfone import Microfone

        agora = [1000.0]

        class RelogioDoTeste:
            """Só o `microfone` enxerga este relógio.

            Trocar `time.monotonic` no módulo `time` de verdade afetaria o
            `queue.get(timeout=...)` deste mesmo laço — e o teste passaria a
            medir outra coisa.
            """

            @staticmethod
            def monotonic() -> float:
                return agora[0]

            @staticmethod
            def sleep(segundos: float) -> None:
                _time.sleep(segundos)

        monkeypatch.setattr(micMod, "time", RelogioDoTeste)
        monkeypatch.setattr(micMod, "SEM_AUDIO_S", 3.0)

        m = Microfone(limiar=0.02)
        erro: list[BaseException] = []

        def rodar() -> None:
            try:
                list(m.cortarEmFrases())
            except BaseException as exc:
                erro.append(exc)

        t = threading.Thread(target=rodar, daemon=True)
        t.start()

        def avancar(segundos: float) -> None:
            agora[0] += segundos
            # O `get` da fila usa o relógio de verdade: esta espera dá ao laço
            # tempo de estourar o timeout e chegar na conferência do vigia.
            _time.sleep(0.7)

        try:
            roteiro(m, avancar)
        finally:
            m.fechar()
            t.join(timeout=2.0)
        return erro

    def testUmaFalaLongaNaoDerrubaACaptura(self, monkeypatch) -> None:
        def roteiro(m, avancar) -> None:
            avancar(0.1)  # o laço arranca e encosta na fila vazia
            m.pausar()  # a Atlas começou a falar
            avancar(10.0)  # dez segundos de resposta, muito além do teto
            m.retomar()  # ela calou; os blocos voltam em seguida
            avancar(0.1)  # o laço confere o vigia logo depois da retomada

        erro = self.rodarComRelogio(monkeypatch, roteiro)
        assert not erro, f"o vigia derrubou a captura por causa de uma fala longa: {erro}"

    def testMasContinuaPercebendoODispositivoMorto(self, monkeypatch) -> None:
        """A correção desconta o tempo pausado; não desliga o vigia."""
        from roboteye.hearing import microfone as micMod

        def roteiro(m, avancar) -> None:
            avancar(0.1)
            avancar(10.0)  # dez segundos de silêncio SEM estar pausada

        erro = self.rodarComRelogio(monkeypatch, roteiro)
        assert erro and isinstance(erro[0], micMod.capturaParou), (
            f"o vigia deixou passar um dispositivo morto: {erro}"
        )


def testOSinalCabeNumBlocoDeEscuta() -> None:
    """Contexto para quem for mexer no tamanho: o sinal em blocos de microfone."""
    blocos = sinal.duracaoS() * TAXA / BLOCO
    assert 3 < blocos < 14, f"o sinal ocupa {blocos:.0f} blocos de escuta"
