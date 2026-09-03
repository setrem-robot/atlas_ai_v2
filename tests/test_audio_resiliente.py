"""O áudio precisa voltar sozinho quando a placa some e reaparece.

Estes testes existem por um incidente real, e não por zelo genérico. No robô de
produção o `dmesg` registrou:

    usb 1-1: USB disconnect, device number 2
    usb 1-1: new full-speed USB device number 3 using xhci-hcd

A placa C-Media se desconectou e voltou com outro número. A partir dali, sem as
correções que estes testes protegem:

- **a voz sumia para sempre.** O `SoundDeviceSink` guardava o stream morto;
  `start()` via o formato igual e voltava sem reabrir, então toda fala seguinte
  falhava com `ALSA write failed (unrecoverable)`;
- **a escuta sumia para sempre, gastando um núcleo inteiro.** A captura era
  aberta uma vez só; o PortAudio ficava girando no `poll` do ALSA sobre um
  dispositivo que não existia mais — 105% de CPU medidos no robô, contra ~28%
  depois de reiniciar o serviço.

Nada aqui toca hardware: os dublês falham na hora escolhida.
"""

from __future__ import annotations

import queue
import threading

import numpy as np
import pytest

from roboteye.hearing import microfone as mic_mod
from roboteye.hearing.microfone import BLOCO, Microfone
from roboteye.speech.base import AudioFormat, SpeechError
from roboteye.speech.player import AplaySink, SoundDeviceSink

FORMATO = AudioFormat(sample_rate=22050, channels=1, sample_width=2)


# ---------------------------------------------------------------------------
# Saída: a voz volta depois de o dispositivo falhar
# ---------------------------------------------------------------------------
class StreamFalso:
    """Um stream do sounddevice que morre quando mandarem."""

    def __init__(self, morto: bool = False) -> None:
        self.morto = morto
        self.escrito = bytearray()
        self.fechado = False

    def start(self) -> None:
        return None

    def write(self, audio: bytes) -> None:
        if self.morto:
            raise OSError("write failed (unrecoverable): No such device")
        self.escrito.extend(audio)

    def stop(self) -> None:
        return None

    def close(self) -> None:
        self.fechado = True


class TestSaidaVoltaSozinha:
    def _sink_com(self, streams: list[StreamFalso]) -> SoundDeviceSink:
        """Um sink cujo `start()` entrega os streams desta lista, em ordem."""
        sink = SoundDeviceSink()
        restantes = list(streams)

        def abrir(audio_format: AudioFormat) -> None:
            if sink._stream is not None and sink._format == audio_format:
                return
            sink.close()
            sink._stream = restantes.pop(0)
            sink._stream.start()
            sink._format = audio_format

        sink.start = abrir  # type: ignore[method-assign]
        return sink

    def test_o_stream_morto_e_solto_no_erro(self) -> None:
        morto = StreamFalso(morto=True)
        sink = self._sink_com([morto, StreamFalso()])

        sink.start(FORMATO)
        with pytest.raises(SpeechError):
            sink.write(b"\x00\x00")

        # É este `close` que faz a diferença: sem ele o stream morto continuaria
        # guardado e o `start()` seguinte não reabriria nada.
        assert morto.fechado
        assert sink._stream is None

    def test_a_fala_seguinte_reabre_e_sai(self) -> None:
        vivo = StreamFalso()
        sink = self._sink_com([StreamFalso(morto=True), vivo])

        sink.start(FORMATO)
        with pytest.raises(SpeechError):
            sink.write(b"\x00\x00")

        # O robô tenta falar de novo — e agora sai som.
        sink.start(FORMATO)
        sink.write(b"\x01\x02")
        assert bytes(vivo.escrito) == b"\x01\x02"

    def test_o_aplay_morto_tambem_e_solto(self) -> None:
        sink = AplaySink()

        class ProcessoFalso:
            def __init__(self) -> None:
                self.stdin = self

            def write(self, _audio: bytes) -> None:
                raise OSError("Broken pipe")

            def flush(self) -> None:
                raise OSError("Broken pipe")

            def close(self) -> None:
                return None

            def wait(self, timeout: float | None = None) -> int:
                return 0

        sink._process = ProcessoFalso()  # type: ignore[assignment]
        sink._format = FORMATO

        with pytest.raises(SpeechError):
            sink.write(b"\x00\x00")
        assert sink._process is None
        assert sink._format is None


# ---------------------------------------------------------------------------
# Entrada: a escuta percebe que o dispositivo emudeceu
# ---------------------------------------------------------------------------
def bloco(volume: float = 0.001) -> np.ndarray:
    return np.full(BLOCO, volume, dtype=np.float32)


class TestEscutaPercebeODispositivoMudo:
    def test_silencio_de_verdade_nao_dispara_o_alarme(self, monkeypatch) -> None:
        """Sala quieta produz bloco. Só a ausência de bloco é defeito."""
        monkeypatch.setattr(mic_mod, "SEM_AUDIO_S", 0.05)
        m = Microfone(limiar=0.02, silencio_s=0.3, minimo_s=0.15, maximo_s=1.0)
        for _ in range(40):
            m._blocos.put_nowait(bloco())
        m._blocos.put_nowait(None)

        # Termina pelo `None` (fim de captura), sem levantar.
        assert list(m._cortar_em_frases()) == []

    def test_fila_vazia_por_tempo_demais_e_dispositivo_morto(self, monkeypatch) -> None:
        monkeypatch.setattr(mic_mod, "SEM_AUDIO_S", 0.05)
        m = Microfone(limiar=0.02)

        with pytest.raises(mic_mod._CapturaParou):
            list(m._cortar_em_frases())

    def test_enquanto_a_atlas_fala_o_silencio_e_esperado(self, monkeypatch) -> None:
        """Pausada, a captura não enfileira nada — e isso não é defeito."""
        monkeypatch.setattr(mic_mod, "SEM_AUDIO_S", 0.05)
        m = Microfone(limiar=0.02)
        m.pausar()

        # Roda o corte numa thread: pausado, ele deve ficar esperando em paz.
        erro: list[BaseException] = []

        def rodar() -> None:
            try:
                list(m._cortar_em_frases())
            except BaseException as exc:
                erro.append(exc)

        t = threading.Thread(target=rodar, daemon=True)
        t.start()
        t.join(timeout=1.0)
        m.fechar()
        t.join(timeout=2.0)

        assert not erro, f"acusou dispositivo morto durante uma fala: {erro}"

    def test_reabre_e_volta_a_entregar_frases(self, monkeypatch) -> None:
        """O contrato que importa: quem consome `frases()` nem percebe a queda."""
        monkeypatch.setattr(mic_mod, "SEM_AUDIO_S", 0.05)
        monkeypatch.setattr(mic_mod, "ESPERA_INICIAL_S", 0.01)
        monkeypatch.setattr(mic_mod, "ESPERA_MAXIMA_S", 0.01)

        m = Microfone(limiar=0.02, silencio_s=0.3, minimo_s=0.15, maximo_s=1.0)
        aberturas: list[int] = []

        def captura_falsa(_sd):
            aberturas.append(1)
            if len(aberturas) == 1:
                # Primeira sessão: o dispositivo morre sem entregar nada.
                raise mic_mod._CapturaParou("a placa sumiu")
            # Segunda: entrega uma frase e encerra.
            for pedaco in [bloco()] * 3 + [bloco(0.2)] * 20 + [bloco()] * 15:
                m._blocos.put_nowait(pedaco)
            m._blocos.put_nowait(None)
            yield from m._cortar_em_frases()

        m._uma_captura = captura_falsa  # type: ignore[method-assign]

        frases = list(m.frases())
        assert len(aberturas) == 2, "não reabriu o dispositivo"
        assert len(frases) == 1, "a frase da segunda sessão não chegou a quem escuta"

    def test_o_que_sobrou_da_sessao_morta_e_descartado(self, monkeypatch) -> None:
        """Resto de fila é pedaço de frase velha; colá-lo na próxima é pior que perdê-lo."""
        monkeypatch.setattr(mic_mod, "ESPERA_INICIAL_S", 0.01)
        monkeypatch.setattr(mic_mod, "ESPERA_MAXIMA_S", 0.01)

        m = Microfone(limiar=0.02)
        m._blocos.put_nowait(bloco(0.2))
        m._blocos.put_nowait(bloco(0.2))

        m._descartar_pendentes()
        with pytest.raises(queue.Empty):
            m._blocos.get_nowait()
