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
from roboteye.hearing.microfone import BLOCO, TAXA, CapturaParou
from roboteye.hearing.voskEars import SILENCIO_DE_PARTIDA_S, VoskEars


class ReconhecedorFalso:
    """Fecha uma frase a cada `a_cada` blocos, como o `KaldiRecognizer` faria."""

    def __init__(self, texto: str = "quantos alunos tem a setrem", aCada: int = 3) -> None:
        self.texto = texto
        self.aCada = aCada
        self.blocos = 0

    def AcceptWaveform(self, bloco: bytes) -> bool:
        self.blocos += 1
        return self.blocos % self.aCada == 0

    def Result(self) -> str:
        return json.dumps({"text": self.texto})


def ouvido(**kwargs) -> VoskEars:
    """Um `VoskEars` com o modelo já "carregado", sem tocar no disco."""
    ears = VoskEars(modelPath=kwargs.pop("model_path", "/nao/existe"), **kwargs)
    ears.model = object()  # o `warm_up` real precisaria do pacote e do modelo
    return ears


class TestOFormatoQueOVoskLe:
    def testConverteParaInt16(self) -> None:
        bloco = np.array([0.0, 0.5, -0.5], dtype=np.float32)
        amostras = np.frombuffer(VoskEars.paraInt16(bloco), dtype=np.int16)
        assert list(amostras) == [0, 16383, -16383]

    def testUmPicoAcimaDeUmNaoViraEstalo(self) -> None:
        """Sem o corte, 1,5 transborda o `int16` e sai negativo.

        O efeito é um estalo no meio da fala, bem onde o reconhecimento mais
        precisa de sinal limpo — e um estalo periódico o Vosk chega a
        transcrever como sílaba.
        """
        bloco = np.array([1.5, -1.5], dtype=np.float32)
        amostras = np.frombuffer(VoskEars.paraInt16(bloco), dtype=np.int16)
        assert list(amostras) == [32767, -32767]
        assert all(a > 0 for a in amostras[:1]), "o pico positivo virou negativo"


class TestOAvisoDeFimDeFrase:
    """O bipe de "terminei de ouvir". O Vosk não passa pelo `Microfone`, então
    sem isto o robô trocaria de motor de escuta e emudeceria os dois sinais."""

    def testOVoskSabeAvisar(self) -> None:
        assert isinstance(ouvido(), AvisaAoFecharFrase), (
            "o `app` só liga o bipe em quem satisfaz este protocolo"
        )

    def testAvisaAoFecharCadaFrase(self) -> None:
        ears = ouvido()
        avisos: list[int] = []
        ears.aoFecharFrase(lambda: avisos.append(1))
        for _ in range(6):
            ears.blocos.put(b"\x00" * BLOCO)
        ears.blocos.put(None)

        frases = list(ears.reconhecer(ReconhecedorFalso(aCada=3)))

        assert len(frases) == 2
        assert len(avisos) == 2

    def testOAvisoSaiAntesDaFrase(self) -> None:
        """Tocar depois de entregar o texto poria o bipe atrás da resposta."""
        ears = ouvido()
        ordem: list[str] = []
        ears.aoFecharFrase(lambda: ordem.append("bipe"))
        for _ in range(3):
            ears.blocos.put(b"\x00" * BLOCO)
        ears.blocos.put(None)

        for _ in ears.reconhecer(ReconhecedorFalso(aCada=3)):
            ordem.append("frase")

        assert ordem == ["bipe", "frase"]

    def testUmAvisoQueFalhaNaoCustaAFrase(self) -> None:
        ears = ouvido()

        def explodir() -> None:
            raise RuntimeError("caixinha ocupada")

        ears.aoFecharFrase(explodir)
        for _ in range(3):
            ears.blocos.put(b"\x00" * BLOCO)
        ears.blocos.put(None)

        frases = list(ears.reconhecer(ReconhecedorFalso(aCada=3)))

        assert len(frases) == 1, "a frase reconhecida é o motivo de tudo isto existir"

    def testSemNinguemRegistradoNaoQuebra(self) -> None:
        ears = ouvido()
        for _ in range(3):
            ears.blocos.put(b"\x00" * BLOCO)
        ears.blocos.put(None)

        assert len(list(ears.reconhecer(ReconhecedorFalso(aCada=3)))) == 1


class TestOSilencioQueDaContextoAoReconhecedor:
    """O Vosk come a primeira palavra se o áudio começa nela.

    Medido com o modelo real e fala sintetizada, entregando o áudio ao
    reconhecedor sem nada antes:

        "Atlas"                            ->  ""
        "Atlas, quanto e dois mais dois?"  ->  "quanto e dois mais dois"
        "Atlas, qual o seu nome?"          ->  "qual o seu nome"

    Com meio segundo de silêncio na frente, os três saem inteiros. Numa sala
    isso nunca aparece — silêncio é o que mais chega ao microfone. **Aparece ao
    retomar depois de a Atlas falar**, porque enquanto pausada nada é entregue
    ao reconhecedor: para ele a fala seguinte começa no primeiro quadro que
    existe. E a palavra comida é o nome dela, então o robô ouviria a pergunta
    inteira e concluiria que não era com ele.
    """

    def testRetomarEnfileiraSilencioAntesDaFala(self) -> None:
        ears = ouvido()
        ears.pausar()

        ears.retomar()

        assert ears.blocos.qsize() > 0, "o reconhecimento recomecaria direto na fala"

    def testOSilencioESilencioMesmo(self) -> None:
        """Ruído no lugar do silêncio seria pior que não ter nada."""
        ears = ouvido()
        ears.pausar()
        ears.retomar()

        bloco = ears.blocos.get_nowait()
        assert set(np.frombuffer(bloco, dtype=np.int16)) == {0}

    def testMeioSegundoEOQueFoiMedido(self) -> None:
        ears = ouvido()
        ears.pausar()
        ears.retomar()

        blocos = ears.blocos.qsize()
        segundos = blocos * BLOCO / TAXA
        assert segundos == pytest.approx(SILENCIO_DE_PARTIDA_S, abs=0.05), (
            f"{blocos} blocos = {segundos:.2f}s; a medida que corrigiu o defeito foi "
            f"{SILENCIO_DE_PARTIDA_S}s"
        )

    def testRetomarSemTerPausadoNaoEncheAFila(self) -> None:
        """`retomar` é idempotente, e o `app` chama em mais de um evento.

        Sem a guarda, um turno com erro (que publica `ErrorOccurred` e
        `SpeechFinished`) empilharia silêncio na frente da próxima pergunta.
        """
        ears = ouvido()

        ears.retomar()
        ears.retomar()

        assert ears.blocos.empty()

    def testAFilaCheiaNaoTravaQuemRetoma(self) -> None:
        """`retomar` roda na thread do barramento de eventos.

        Se ela bloqueasse numa fila cheia, a Atlas terminaria de falar e o robô
        inteiro pararia ali.
        """
        ears = ouvido()
        ears.pausar()
        while True:
            try:
                ears.blocos.put_nowait(b"\x00" * BLOCO)
            except queue.Full:
                break

        ears.retomar()  # não deve levantar nem bloquear

        assert ears.blocos.full()


class TestONuncaFicarSurdo:
    """A placa USB deste robô se desconecta e volta com outro número.

    Sem reabrir, o PortAudio gira no `poll` do ALSA sobre um dispositivo que não
    existe mais: um núcleo a 100%, o robô surdo, e nada no log.
    """

    def testSilencioLongoDemaisDerrubaACaptura(self, monkeypatch) -> None:
        ears = ouvido()
        relogio = iter([0.0, 0.0, 10.0])
        monkeypatch.setattr(
            "roboteye.hearing.voskEars.time.monotonic", lambda: next(relogio, 10.0)
        )

        with pytest.raises(CapturaParou):
            list(ears.reconhecer(ReconhecedorFalso()))

    def testPausadaNaoContaComoDispositivoMorto(self, monkeypatch) -> None:
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

        monkeypatch.setattr("roboteye.hearing.voskEars.time.monotonic", relogio)

        def pararDepois(*a, **k):
            ears.fechado.set()
            raise queue.Empty

        monkeypatch.setattr(ears.blocos, "get", pararDepois)

        assert list(ears.reconhecer(ReconhecedorFalso())) == []

    def testAFilaVelhaEDescartadaAntesDeReabrir(self) -> None:
        """Áudio de antes da queda colaria meia frase velha na próxima."""
        ears = ouvido()
        for _ in range(5):
            ears.blocos.put(b"\x00" * BLOCO)

        ears.descartarPendentes()

        assert ears.blocos.empty()


class TestATaxaDaPlaca:
    """O defeito que motivou estes testes.

    A placa deste robô grava a 48 kHz e, com `dsnoop`, não anuncia 16 kHz.
    Abrir direto na taxa do reconhecimento morre com `Invalid sample rate`.
    """

    def sdFalso(self, aceitas: set[int]):
        abertas: list[int] = []

        class Stream:
            def __init__(self, *, samplerate, **kwargs) -> None:
                abertas.append(samplerate)
                if samplerate not in aceitas:
                    raise ValueError("Invalid sample rate")

            def __enter__(self):
                return self

            def __exit__(self, *exc) -> None: ...

        return types.SimpleNamespace(InputStream=Stream), abertas

    def testPlacaDe48kENegociadaENaoDerrubaAEscuta(self, monkeypatch) -> None:
        sd, abertas = self.sdFalso(aceitas={48000})
        monkeypatch.setitem(sys.modules, "sounddevice", sd)
        monkeypatch.setitem(
            sys.modules, "vosk", types.SimpleNamespace(KaldiRecognizer=lambda *a: None)
        )
        ears = ouvido()
        # Encerra na primeira leitura: o teste é sobre a abertura, e `close()`
        # antes de `escutar()` impediria o laço de chegar até ela.
        ears.blocos.put(None)

        list(ears.escutar())

        assert 48000 in abertas, "não tentou a taxa que a placa aceita"

    def testNenhumaTaxaUtilAvisaEmVezDeFicarCalado(self, monkeypatch) -> None:
        sd, _ = self.sdFalso(aceitas=set())
        monkeypatch.setitem(sys.modules, "sounddevice", sd)
        monkeypatch.setitem(
            sys.modules, "vosk", types.SimpleNamespace(KaldiRecognizer=lambda *a: None)
        )
        ears = ouvido()

        with pytest.raises(HearingError, match="nenhuma taxa util"):
            list(ears.escutar())


class TestOModeloAusente:
    def testDizOCaminhoEOComando(self) -> None:
        ears = VoskEars(modelPath="/models/escuta/vosk-pt")

        with pytest.raises(HearingError) as erro:
            list(ears.escutar())

        assert "/models/escuta/vosk-pt" in str(erro.value)
        assert "baixar-modelo-escuta.sh" in str(erro.value)
