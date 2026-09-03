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

    def test_sao_sons_diferentes(self) -> None:
        assert sinal.escutando()[0].audio != sinal.ouvi()[0].audio

    def test_um_sobe_e_o_outro_desce(self) -> None:
        """Subindo se lê "pode falar"; descendo, "pronto, ouvi".

        Um som sozinho não diria qual dos dois momentos é — e saber qual é o
        pedido inteiro. Se um dia os dois virarem o mesmo, o robô passa a
        avisar duas vezes a mesma coisa.
        """
        assert _pico_no_fim(sinal.escutando()) > _pico_no_comeco(sinal.escutando())
        assert _pico_no_fim(sinal.ouvi()) < _pico_no_comeco(sinal.ouvi())

    def test_duram_o_mesmo(self) -> None:
        assert len(sinal.escutando()[0].audio) == len(sinal.ouvi()[0].audio)


def _frequencia_dominante(pcm: bytes) -> float:
    """Frequência aproximada, contando quantas vezes o sinal cruza o zero."""
    v = amostras(pcm)
    cruzamentos = sum(1 for a, b in pairwise(v) if (a >= 0) != (b >= 0))
    return cruzamentos / 2 / (len(v) / sinal.TAXA)


def _um_terco(pcm: bytes) -> int:
    """Corte alinhado à amostra: cada uma tem 2 bytes, e meio não existe."""
    return (len(pcm) // 3) // 2 * 2


def _pico_no_comeco(chunks) -> float:
    pcm = chunks[0].audio
    return _frequencia_dominante(pcm[: _um_terco(pcm)])


def _pico_no_fim(chunks) -> float:
    pcm = chunks[0].audio
    return _frequencia_dominante(pcm[len(pcm) - _um_terco(pcm) :])


class TestOSom:
    def test_e_curto_demais_para_virar_pergunta(self) -> None:
        """O microfone descarta trechos com menos de 0.4 s de voz.

        Este é o número que impede o robô de ouvir o próprio sinal e responder
        a ele. Se um dia o sinal crescer além disso, o robô passa a conversar
        consigo mesmo — e o sintoma (ele responde sozinho ao ser chamado) não
        aponta para cá.
        """
        minimo_do_microfone_s = 0.4
        assert sinal.duracao_s() < minimo_do_microfone_s

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def test_nao_comeca_nem_termina_com_estalo(self, qual: str) -> None:
        """Corte seco numa senoide vira clique, e clique se ouve mais que a nota."""
        valores = amostras(getattr(sinal, qual)()[0].audio)
        assert abs(valores[0]) < 100, "começa com degrau"
        assert abs(valores[-1]) < 100, "termina com degrau"

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def test_nao_estoura_a_escala(self, qual: str) -> None:
        valores = amostras(getattr(sinal, qual)()[0].audio)
        assert max(abs(v) for v in valores) < 32767

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def test_tem_som_de_verdade_no_meio(self, qual: str) -> None:
        """Um sinal silencioso passaria em todos os testes acima."""
        valores = amostras(getattr(sinal, qual)()[0].audio)
        energia = math.sqrt(sum(v * v for v in valores) / len(valores))
        assert energia > 1000, f"o sinal saiu quase mudo (rms {energia:.0f})"

    @pytest.mark.parametrize("qual", ["escutando", "ouvi"])
    def test_o_formato_e_o_que_a_placa_espera(self, qual: str) -> None:
        chunk = getattr(sinal, qual)()[0]
        assert chunk.format.channels == 1
        assert chunk.format.sample_width == 2
        assert chunk.format.sample_rate == sinal.TAXA


class TestOLocutorTocaSemAnunciarFala:
    """Um sinal não é uma frase, e a diferença tem consequência.

    Quem escuta `SpeechStarted` pausa o microfone (ver `app.py`). Um sinal que
    publicasse esse evento deixaria o robô surdo no exato instante em que
    anuncia que está ouvindo — e como `SpeechFinished` só vem no fim de um
    turno de conversa, a escuta não voltaria sozinha.
    """

    def test_o_som_chega_ao_dispositivo(self, make_speaker, sink) -> None:
        speaker = make_speaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.wait_until_idle(timeout=5)
        assert bytes(sink.written) == sinal.escutando()[0].audio

    def test_nao_publica_evento_de_fala(self, make_speaker, recorder) -> None:
        speaker = make_speaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.wait_until_idle(timeout=5)
        assert recorder.of_type(SpeechStarted) == []
        assert recorder.of_type(SpeechFinished) == []

    def test_nao_vira_texto_no_motor_de_voz(self, make_speaker, engine) -> None:
        """O áudio já vem pronto: mandá-lo ao motor sintetizaria texto vazio."""
        speaker = make_speaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == []

    def test_nao_se_mistura_com_a_fala_seguinte(self, make_speaker, engine) -> None:
        """O lote junta frases para economizar ida e volta. O sinal não é frase."""
        speaker = make_speaker()
        speaker.sinalizar(sinal.escutando())
        speaker.say("A pergunta chegou.")

        assert speaker.wait_until_idle(timeout=5)
        assert engine.spoken == ["A pergunta chegou."]

    def test_o_locutor_volta_a_ficar_ocioso(self, make_speaker) -> None:
        """Sem isto, o sinal deixaria `wait_until_idle` preso para sempre."""
        speaker = make_speaker()
        speaker.sinalizar(sinal.escutando())

        assert speaker.wait_until_idle(timeout=5)
        assert not speaker.is_speaking


class TestQuandoOSinalToca:
    """Só na abertura da janela de escuta."""

    def _app_falsa(self, bus, gravador: list):
        """Liga o mesmo handler que a `Application` liga, com um locutor de mentira."""
        from roboteye.app import Application

        class LocutorFalso:
            def sinalizar(self, chunks) -> None:
                gravador.append(chunks)

        app = object.__new__(Application)
        app.speaker = LocutorFalso()  # type: ignore[assignment]
        bus.subscribe(app._avisar_que_estou_ouvindo, event_type=ListeningChanged)
        return app

    def test_toca_quando_a_janela_abre(self, bus) -> None:
        tocados: list = []
        self._app_falsa(bus, tocados)

        bus.publish(ListeningChanged(active=True))

        assert len(tocados) == 1

    def test_nao_toca_quando_a_janela_fecha(self, bus) -> None:
        """Fechar é ou a pergunta chegando (a resposta avisa) ou o tempo passando."""
        tocados: list = []
        self._app_falsa(bus, tocados)

        bus.publish(ListeningChanged(active=False))

        assert tocados == []


class TestOSinalDeFimDeEscuta:
    """O segundo som do par: "terminei de ouvir, agora deixa comigo".

    Ele vem do **microfone**, e não do reconhecimento. A diferença é de quase
    dois segundos num Raspberry Pi: esperar a transcrição faria o aviso chegar
    depois de a pessoa já ter desistido de esperar por ele.
    """

    def _app_falsa(self, tocados: list, conversa):
        from roboteye.app import Application

        class LocutorFalso:
            def sinalizar(self, chunks) -> None:
                tocados.append(chunks)

        app = object.__new__(Application)
        app.speaker = LocutorFalso()  # type: ignore[assignment]
        app._conversa = conversa
        return app

    def test_toca_quando_a_janela_esta_aberta(self) -> None:
        from roboteye.hearing.gatilho import Conversa

        conversa = Conversa(8.0)
        conversa.abrir()
        tocados: list = []
        app = self._app_falsa(tocados, conversa)

        app._avisar_que_terminei_de_ouvir()

        assert tocados == [sinal.ouvi()]

    def test_nao_toca_com_a_janela_fechada(self) -> None:
        """Um microfone aberto numa sala fecha uma captura a cada frase que
        alguém diz por perto. Sem esta guarda o robô apitaria o dia inteiro."""
        from roboteye.hearing.gatilho import Conversa

        tocados: list = []
        app = self._app_falsa(tocados, Conversa(8.0))  # nunca aberta

        app._avisar_que_terminei_de_ouvir()

        assert tocados == []

    def test_nao_toca_antes_de_a_escuta_comecar(self) -> None:
        tocados: list = []
        app = self._app_falsa(tocados, None)

        app._avisar_que_terminei_de_ouvir()

        assert tocados == []


class TestOMicrofoneAvisaAoFecharAFrase:
    """O gancho que faz o aviso chegar antes da transcrição."""

    def _blocos(self, m, voz: int, silencio: int):
        import numpy as np

        from roboteye.hearing.microfone import BLOCO

        for _ in range(3):
            m._blocos.put_nowait(np.full(BLOCO, 0.001, dtype=np.float32))
        for _ in range(voz):
            m._blocos.put_nowait(np.full(BLOCO, 0.2, dtype=np.float32))
        for _ in range(silencio):
            m._blocos.put_nowait(np.full(BLOCO, 0.001, dtype=np.float32))
        m._blocos.put_nowait(None)

    def test_avisa_uma_vez_por_frase(self) -> None:
        from roboteye.hearing.microfone import Microfone

        m = Microfone(limiar=0.02, silencio_s=0.3, minimo_s=0.15, maximo_s=1.0)
        avisos: list[int] = []
        m.ao_fechar_frase(lambda: avisos.append(1))

        self._blocos(m, voz=20, silencio=15)
        frases = list(m._cortar_em_frases())

        assert len(frases) == 1
        assert len(avisos) == 1

    def test_nao_avisa_por_ruido_descartado(self) -> None:
        """Um estalo de porta não é pergunta, e não merece som de resposta."""
        from roboteye.hearing.microfone import Microfone

        m = Microfone(limiar=0.02, silencio_s=0.3, minimo_s=0.15, maximo_s=1.0)
        avisos: list[int] = []
        m.ao_fechar_frase(lambda: avisos.append(1))

        self._blocos(m, voz=2, silencio=15)  # curto demais para ser fala
        frases = list(m._cortar_em_frases())

        assert frases == []
        assert avisos == []

    def test_um_aviso_que_falha_nao_perde_a_frase(self) -> None:
        """O aviso é conforto; a frase é o que a pessoa acabou de dizer."""
        from roboteye.hearing.microfone import Microfone

        m = Microfone(limiar=0.02, silencio_s=0.3, minimo_s=0.15, maximo_s=1.0)

        def explodir() -> None:
            raise RuntimeError("o alto-falante sumiu")

        m.ao_fechar_frase(explodir)
        self._blocos(m, voz=20, silencio=15)

        assert len(list(m._cortar_em_frases())) == 1

    def test_o_ouvido_repassa_o_aviso_ao_microfone(self) -> None:
        """`WhisperEars` é quem a `Application` enxerga; o gancho passa por ele."""
        from roboteye.hearing import AvisaAoFecharFrase
        from roboteye.hearing.whisper_ears import WhisperEars

        ouvido = WhisperEars("tiny")
        assert isinstance(ouvido, AvisaAoFecharFrase)

        def avisar() -> None: ...

        ouvido.ao_fechar_frase(avisar)
        assert ouvido._microfone._ao_fechar_frase is avisar


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

    def _rodar_com_relogio(self, monkeypatch, roteiro) -> list[BaseException]:
        """Executa o corte em frases com um relógio que o teste move.

        `roteiro` recebe o microfone e a função que avança o relógio.
        """
        import threading
        import time as _time

        from roboteye.hearing import microfone as mic_mod
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

        monkeypatch.setattr(mic_mod, "time", RelogioDoTeste)
        monkeypatch.setattr(mic_mod, "SEM_AUDIO_S", 3.0)

        m = Microfone(limiar=0.02)
        erro: list[BaseException] = []

        def rodar() -> None:
            try:
                list(m._cortar_em_frases())
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

    def test_uma_fala_longa_nao_derruba_a_captura(self, monkeypatch) -> None:
        def roteiro(m, avancar) -> None:
            avancar(0.1)  # o laço arranca e encosta na fila vazia
            m.pausar()  # a Atlas começou a falar
            avancar(10.0)  # dez segundos de resposta, muito além do teto
            m.retomar()  # ela calou; os blocos voltam em seguida
            avancar(0.1)  # o laço confere o vigia logo depois da retomada

        erro = self._rodar_com_relogio(monkeypatch, roteiro)
        assert not erro, f"o vigia derrubou a captura por causa de uma fala longa: {erro}"

    def test_mas_continua_percebendo_o_dispositivo_morto(self, monkeypatch) -> None:
        """A correção desconta o tempo pausado; não desliga o vigia."""
        from roboteye.hearing import microfone as mic_mod

        def roteiro(m, avancar) -> None:
            avancar(0.1)
            avancar(10.0)  # dez segundos de silêncio SEM estar pausada

        erro = self._rodar_com_relogio(monkeypatch, roteiro)
        assert erro and isinstance(erro[0], mic_mod._CapturaParou), (
            f"o vigia deixou passar um dispositivo morto: {erro}"
        )


def test_o_sinal_cabe_num_bloco_de_escuta() -> None:
    """Contexto para quem for mexer no tamanho: o sinal em blocos de microfone."""
    blocos = sinal.duracao_s() * TAXA / BLOCO
    assert 3 < blocos < 14, f"o sinal ocupa {blocos:.0f} blocos de escuta"
