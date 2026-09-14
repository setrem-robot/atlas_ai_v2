"""Testes do acabamento aplicado ao áudio antes de tocar."""

from __future__ import annotations

import numpy as np
import pytest

from roboteye.speech.base import AudioFormat, SpeechChunk
from roboteye.speech.polish import AudioPolish, silence, toFloat, toPcm16

FORMATO = AudioFormat(sampleRate=16000, channels=1, sampleWidth=2)


def bloco(segundos: float, valor: float = 0.8) -> SpeechChunk:
    """Um bloco de nível constante — o pior caso para estalo nas pontas."""
    n = int(FORMATO.sampleRate * segundos)
    return SpeechChunk(audio=toPcm16(np.full(n, valor, dtype=np.float32)), format=FORMATO)


def amostras(chunks: list[SpeechChunk]) -> np.ndarray:
    return np.concatenate([toFloat(c.audio) for c in chunks]) if chunks else np.empty(0)


class TestRampas:
    def testAFalaComecaDoZero(self) -> None:
        """Começar num valor longe de zero é um degrau, e um degrau é um clique."""
        saida = list(AudioPolish().process([bloco(0.3)]))
        assert abs(amostras(saida)[0]) < 0.05

    def testAFalaTerminaEmZero(self) -> None:
        saida = list(AudioPolish(tail=0.0).process([bloco(0.3)]))
        assert abs(amostras(saida)[-1]) < 0.05

    def testOMioloNaoETocado(self) -> None:
        """As rampas são curtas de propósito: não podem comer o corpo da fala."""
        saida = amostras(list(AudioPolish().process([bloco(0.5)])))
        meio = saida[len(saida) // 3 : len(saida) // 2]
        assert np.allclose(meio, 0.8, atol=0.01)

    def testSoAPrimeiraEAUltimaPontaGanhamRampa(self) -> None:
        """Uma fala em vários blocos é uma coisa só; rampar cada emenda a picotaria."""
        saida = amostras(list(AudioPolish(tail=0.0).process([bloco(0.2) for _ in range(3)])))

        # A emenda entre o 1º e o 2º bloco fica a um terço do total.
        emenda = len(saida) // 3
        vizinhanca = saida[emenda - 20 : emenda + 20]
        assert np.allclose(vizinhanca, 0.8, atol=0.01)


class TestRespiro:
    def testCadaFalaTerminaComSilencio(self) -> None:
        """É o respiro que separa uma frase da seguinte."""
        saida = list(AudioPolish(tail=0.1).process([bloco(0.2)]))
        cauda = toFloat(saida[-1].audio)
        assert cauda.size == pytest.approx(0.1 * FORMATO.sampleRate, rel=0.01)
        assert np.all(cauda == 0.0)

    def testSemRespiroQuandoDesligado(self) -> None:
        saida = list(AudioPolish(tail=0.0).process([bloco(0.2)]))
        assert len(saida) == 1


class TestStreaming:
    def testNaoSeguraAFalaInteiraParaComecar(self) -> None:
        """Segurar tudo mataria a maior vantagem do projeto: tocar antes de acabar.

        Um bloco de atraso basta para saber onde a fala termina.
        """
        entregues: list[int] = []

        def fonte():
            for indice in range(4):
                entregues.append(indice)
                yield bloco(0.1)

        saida = AudioPolish().process(fonte())
        next(saida)  # primeiro bloco já disponível
        assert len(entregues) == 2, "o acabamento olhou mais de um bloco à frente"

    def testFalaVaziaNaoProduzNada(self) -> None:
        assert list(AudioPolish().process([])) == []


class TestGanho:
    def testGanhoMultiplicaOSinal(self) -> None:
        saida = amostras(list(AudioPolish(tail=0.0, gain=0.5).process([bloco(0.3, valor=0.6)])))
        assert saida[len(saida) // 2] == pytest.approx(0.3, abs=0.01)

    def testGanhoAltoNaoFazOSinalDarAVolta(self) -> None:
        """Sem limite, um pico estourado vira o valor mais negativo possível.

        Isso se ouve como um estalo seco no meio da palavra — o oposto do que
        um controle de volume deveria fazer.
        """
        saida = amostras(list(AudioPolish(tail=0.0, gain=4.0).process([bloco(0.3, valor=0.9)])))
        assert saida.max() <= 1.0
        assert saida.min() >= -1.0
        assert np.all(saida[100:-100] > 0.0), "o sinal inverteu de sinal ao estourar"


class TestConversao:
    def testIdaEVoltaPreservaOSinal(self) -> None:
        original = np.linspace(-0.9, 0.9, 500, dtype=np.float32)
        assert np.allclose(toFloat(toPcm16(original)), original, atol=1e-4)

    def testSilencioTemADuracaoPedida(self) -> None:
        dados = silence(FORMATO, 0.25)
        assert len(dados) == int(0.25 * FORMATO.sampleRate) * 2
