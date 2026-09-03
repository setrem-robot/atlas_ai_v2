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

from roboteye.core.events import ListeningChanged, SpeechFinished, SpeechStarted
from roboteye.hearing.microfone import BLOCO, TAXA
from roboteye.speech import sinal


def amostras(pcm: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(pcm) // 2}h", pcm))


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

    def test_nao_comeca_nem_termina_com_estalo(self) -> None:
        """Corte seco numa senoide vira clique, e clique se ouve mais que a nota."""
        valores = amostras(sinal.escutando()[0].audio)
        assert abs(valores[0]) < 100, "começa com degrau"
        assert abs(valores[-1]) < 100, "termina com degrau"

    def test_nao_estoura_a_escala(self) -> None:
        valores = amostras(sinal.escutando()[0].audio)
        assert max(abs(v) for v in valores) < 32767

    def test_tem_som_de_verdade_no_meio(self) -> None:
        """Um sinal silencioso passaria em todos os testes acima."""
        valores = amostras(sinal.escutando()[0].audio)
        energia = math.sqrt(sum(v * v for v in valores) / len(valores))
        assert energia > 1000, f"o sinal saiu quase mudo (rms {energia:.0f})"

    def test_sobe(self) -> None:
        """Subir soa como "pode falar"; descer soa como "acabou"."""
        assert sinal.NOTA_AGUDA_HZ > sinal.NOTA_GRAVE_HZ

    def test_o_formato_e_o_que_a_placa_espera(self) -> None:
        chunk = sinal.escutando()[0]
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
