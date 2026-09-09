"""O caminho do Vosk, que passou a ser o padrão.

Este módulo não tinha teste nenhum, e foi assim que ele ficou meses **sem
conseguir abrir o microfone deste robô**: abria direto em 16 kHz, taxa que a
placa C-Media não anuncia quando o `dsnoop` está no caminho. O defeito só
apareceria no robô, no arranque, como "escuta indisponivel".

Os testes aqui cercam as três coisas que o Vosk não herdava do `Microfone` e que
o Whisper tinha de graça: negociação de taxa, reabertura depois de o dispositivo
sumir, e o aviso de fim de frase que toca o bipe.
"""

from __future__ import annotations

import json
import queue
import sys
import types

import numpy as np
import pytest

from roboteye.hearing.base import AvisaAoFecharFrase, HearingError
from roboteye.hearing.microfone import BLOCO, CapturaParou
from roboteye.hearing.vosk_ears import VoskEars


class ReconhecedorFalso:
    """Fecha uma frase a cada `a_cada` blocos, como o `KaldiRecognizer` faria."""

    def __init__(self, texto: str = "quantos alunos tem a setrem", a_cada: int = 3) -> None:
        self._texto = texto
        self._a_cada = a_cada
        self.blocos = 0

    def AcceptWaveform(self, bloco: bytes) -> bool:
        self.blocos += 1
        return self.blocos % self._a_cada == 0

    def Result(self) -> str:
        return json.dumps({"text": self._texto})


def ouvido(**kwargs) -> VoskEars:
    """Um `VoskEars` com o modelo já "carregado", sem tocar no disco."""
    ears = VoskEars(model_path=kwargs.pop("model_path", "/nao/existe"), **kwargs)
    ears._model = object()  # o `warm_up` real precisaria do pacote e do modelo
    return ears


class TestOFormatoQueOVoskLe:
    def test_converte_para_int16(self) -> None:
        bloco = np.array([0.0, 0.5, -0.5], dtype=np.float32)
        amostras = np.frombuffer(VoskEars._para_int16(bloco), dtype=np.int16)
        assert list(amostras) == [0, 16383, -16383]

    def test_um_pico_acima_de_um_nao_vira_estalo(self) -> None:
        """Sem o corte, 1,5 transborda o `int16` e sai negativo.

        O efeito é um estalo no meio da fala, bem onde o reconhecimento mais
        precisa de sinal limpo — e um estalo periódico o Vosk chega a
        transcrever como sílaba.
        """
        bloco = np.array([1.5, -1.5], dtype=np.float32)
        amostras = np.frombuffer(VoskEars._para_int16(bloco), dtype=np.int16)
        assert list(amostras) == [32767, -32767]
        assert all(a > 0 for a in amostras[:1]), "o pico positivo virou negativo"


class TestOAvisoDeFimDeFrase:
    """O bipe de "terminei de ouvir". O Vosk não passa pelo `Microfone`, então
    sem isto o robô trocaria de motor de escuta e emudeceria os dois sinais."""

    def test_o_vosk_sabe_avisar(self) -> None:
        assert isinstance(ouvido(), AvisaAoFecharFrase), (
            "o `app` só liga o bipe em quem satisfaz este protocolo"
        )

    def test_avisa_ao_fechar_cada_frase(self) -> None:
        ears = ouvido()
        avisos: list[int] = []
        ears.ao_fechar_frase(lambda: avisos.append(1))
        for _ in range(6):
            ears._blocos.put(b"\x00" * BLOCO)
        ears._blocos.put(None)

        frases = list(ears._reconhecer(ReconhecedorFalso(a_cada=3)))

        assert len(frases) == 2
        assert len(avisos) == 2

    def test_o_aviso_sai_antes_da_frase(self) -> None:
        """Tocar depois de entregar o texto poria o bipe atrás da resposta."""
        ears = ouvido()
        ordem: list[str] = []
        ears.ao_fechar_frase(lambda: ordem.append("bipe"))
        for _ in range(3):
            ears._blocos.put(b"\x00" * BLOCO)
        ears._blocos.put(None)

        for _ in ears._reconhecer(ReconhecedorFalso(a_cada=3)):
            ordem.append("frase")

        assert ordem == ["bipe", "frase"]

    def test_um_aviso_que_falha_nao_custa_a_frase(self) -> None:
        ears = ouvido()

        def explodir() -> None:
            raise RuntimeError("caixinha ocupada")

        ears.ao_fechar_frase(explodir)
        for _ in range(3):
            ears._blocos.put(b"\x00" * BLOCO)
        ears._blocos.put(None)

        frases = list(ears._reconhecer(ReconhecedorFalso(a_cada=3)))

        assert len(frases) == 1, "a frase reconhecida é o motivo de tudo isto existir"

    def test_sem_ninguem_registrado_nao_quebra(self) -> None:
        ears = ouvido()
        for _ in range(3):
            ears._blocos.put(b"\x00" * BLOCO)
        ears._blocos.put(None)

        assert len(list(ears._reconhecer(ReconhecedorFalso(a_cada=3)))) == 1


class TestONuncaFicarSurdo:
    """A placa USB deste robô se desconecta e volta com outro número.

    Sem reabrir, o PortAudio gira no `poll` do ALSA sobre um dispositivo que não
    existe mais: um núcleo a 100%, o robô surdo, e nada no log.
    """

    def test_silencio_longo_demais_derruba_a_captura(self, monkeypatch) -> None:
        ears = ouvido()
        relogio = iter([0.0, 0.0, 10.0])
        monkeypatch.setattr(
            "roboteye.hearing.vosk_ears.time.monotonic", lambda: next(relogio, 10.0)
        )

        with pytest.raises(CapturaParou):
            list(ears._reconhecer(ReconhecedorFalso()))

    def test_pausada_nao_conta_como_dispositivo_morto(self, monkeypatch) -> None:
        """A Atlas falando por mais de três segundos não é microfone quebrado.

        Sem esta guarda, toda resposta longa reabriria o dispositivo — e a
        reabertura acontece justo quando ela termina de falar, que é quando a
        pessoa vai perguntar de novo.
        """
        ears = ouvido()
        ears.pausar()
        agora = [0.0]

        def relogio() -> float:
            agora[0] += 10.0  # muito além do limite, a cada consulta
            return agora[0]

        monkeypatch.setattr("roboteye.hearing.vosk_ears.time.monotonic", relogio)

        def parar_depois(*_a, **_k):
            ears._fechado.set()
            raise queue.Empty

        monkeypatch.setattr(ears._blocos, "get", parar_depois)

        assert list(ears._reconhecer(ReconhecedorFalso())) == []

    def test_a_fila_velha_e_descartada_antes_de_reabrir(self) -> None:
        """Áudio de antes da queda colaria meia frase velha na próxima."""
        ears = ouvido()
        for _ in range(5):
            ears._blocos.put(b"\x00" * BLOCO)

        ears._descartar_pendentes()

        assert ears._blocos.empty()


class TestATaxaDaPlaca:
    """O defeito que motivou estes testes.

    A placa deste robô grava a 48 kHz e, com `dsnoop`, não anuncia 16 kHz.
    Abrir direto na taxa do reconhecimento morre com `Invalid sample rate`.
    """

    def _sd_falso(self, aceitas: set[int]):
        abertas: list[int] = []

        class Stream:
            def __init__(self, *, samplerate, **_kwargs) -> None:
                abertas.append(samplerate)
                if samplerate not in aceitas:
                    raise ValueError("Invalid sample rate")

            def __enter__(self):
                return self

            def __exit__(self, *_exc) -> None: ...

        return types.SimpleNamespace(InputStream=Stream), abertas

    def test_placa_de_48k_e_negociada_e_nao_derruba_a_escuta(self, monkeypatch) -> None:
        sd, abertas = self._sd_falso(aceitas={48000})
        monkeypatch.setitem(sys.modules, "sounddevice", sd)
        monkeypatch.setitem(
            sys.modules, "vosk", types.SimpleNamespace(KaldiRecognizer=lambda *_a: None)
        )
        ears = ouvido()
        # Encerra na primeira leitura: o teste é sobre a abertura, e `close()`
        # antes de `escutar()` impediria o laço de chegar até ela.
        ears._blocos.put(None)

        list(ears.escutar())

        assert 48000 in abertas, "não tentou a taxa que a placa aceita"

    def test_nenhuma_taxa_util_avisa_em_vez_de_ficar_calado(self, monkeypatch) -> None:
        sd, _ = self._sd_falso(aceitas=set())
        monkeypatch.setitem(sys.modules, "sounddevice", sd)
        monkeypatch.setitem(
            sys.modules, "vosk", types.SimpleNamespace(KaldiRecognizer=lambda *_a: None)
        )
        ears = ouvido()

        with pytest.raises(HearingError, match="nenhuma taxa util"):
            list(ears.escutar())


class TestOModeloAusente:
    def test_diz_o_caminho_e_o_comando(self) -> None:
        ears = VoskEars(model_path="/models/escuta/vosk-pt")

        with pytest.raises(HearingError) as erro:
            list(ears.escutar())

        assert "/models/escuta/vosk-pt" in str(erro.value)
        assert "baixar-modelo-escuta.sh" in str(erro.value)
