"""Testes do corte do audio em frases.

Nao precisam de microfone: os blocos sao empurrados na fila na mao, que e
exatamente o que a captura faria.
"""

from __future__ import annotations

import numpy as np
import pytest

from roboteye.hearing.microfone import BLOCO, Microfone


def voz(blocos: int, volume: float = 0.2) -> list[np.ndarray]:
    """Blocos com energia acima do limiar."""
    return [np.full(BLOCO, volume, dtype=np.float32) for _ in range(blocos)]


def silencio(blocos: int) -> list[np.ndarray]:
    """Blocos com o ruido de uma sala quieta."""
    return [np.full(BLOCO, 0.001, dtype=np.float32) for _ in range(blocos)]


def escutar(microfone: Microfone, entrada: list[np.ndarray]) -> list[np.ndarray]:
    for bloco in entrada:
        microfone.blocos.put_nowait(bloco)
    # `None` e o sinal de fim de captura. Chamar `fechar()` aqui faria o laco
    # nem comecar, e o teste passaria a nao testar nada.
    microfone.blocos.put_nowait(None)
    return list(microfone.cortarEmFrases())


@pytest.fixture
def mic() -> Microfone:
    # `limiar` explicito: sem ele o microfone mede a sala no arranque, e aqui
    # nao ha sala — os blocos vem da fila, na mao.
    return Microfone(limiar=0.02, silencioS=0.3, minimoS=0.15, maximoS=1.0)


class TestUmaFrase:
    def testFalaSeguidaDeSilencioViraUmaFrase(self, mic: Microfone) -> None:
        frases = escutar(mic, silencio(3) + voz(20) + silencio(15))
        assert len(frases) == 1

    def testOComecoDaFalaNaoSePerde(self, mic: Microfone) -> None:
        # A primeira silaba ja passou quando o som cruza o limiar; o trecho
        # entregue tem de ser maior que os blocos de voz sozinhos.
        frases = escutar(mic, silencio(8) + voz(20) + silencio(15))
        assert len(frases[0]) > 20 * BLOCO


class TestDuasFrases:
    def testPausaCurtaNaoParteAFrase(self, mic: Microfone) -> None:
        # A virgula de "Atlas, quantos alunos tem?" nao pode virar duas frases.
        frases = escutar(mic, voz(10) + silencio(4) + voz(10) + silencio(15))
        assert len(frases) == 1

    def testPausaLongaSeparaDuasPerguntas(self, mic: Microfone) -> None:
        frases = escutar(mic, voz(10) + silencio(15) + voz(10) + silencio(15))
        assert len(frases) == 2


class TestRuido:
    def testEstaloCurtoEDescartado(self, mic: Microfone) -> None:
        # Uma porta batendo, uma cadeira arrastando: som alto e curto demais
        # para ser pergunta.
        assert escutar(mic, silencio(3) + voz(2) + silencio(15)) == []

    def testSalaQuietaNaoProduzNada(self, mic: Microfone) -> None:
        assert escutar(mic, silencio(50)) == []


class TestTetoDeSeguranca:
    def testSomContinuoECortadoEmVezDeCrescerParaSempre(self, mic: Microfone) -> None:
        # Um ventilador que liga nao pode gravar ate a memoria acabar.
        frases = escutar(mic, voz(120))
        assert frases
        assert all(len(f) <= 1.0 * 16000 + BLOCO * 10 for f in frases)


class TestPausa:
    def testPausadoNaoEOMesmoQueFechado(self, mic: Microfone) -> None:
        mic.pausar()
        mic.retomar()
        frases = escutar(mic, voz(20) + silencio(15))
        assert len(frases) == 1


class TestAFraseQueNaoFechava:
    """Voz oscilando em volta do limiar não pode segurar a gravação aberta.

    Visto no robô de produção, uma pergunta curta virando uma captura de 15
    segundos — o teto — com o reconhecimento descartando dez deles como
    não-fala:

        Processing audio with duration 00:15.000
        VAD filter removed 00:10.288 of audio
        ouvi: qual seu nome? Atlas, qual seu nome

    Quinze segundos de espera antes de a transcrição sequer começar, e duas
    perguntas grudadas numa só. A causa era `quieto = 0` a cada bloco isolado
    acima do limiar: as sílabas cruzavam, as pausas não, e a contagem de
    silêncio nunca chegava ao fim.
    """

    def blocosAlternados(self, quantos: int) -> list[np.ndarray]:
        """Um bloco acima do limiar a cada quatro — o padrão que travava tudo.

        É o que uma voz baixa produz quando o limiar ficou alto demais: picos
        de sílaba passando, o resto não.
        """
        saida = []
        for i in range(quantos):
            volume = 0.2 if i % 4 == 0 else 0.001
            saida.append(np.full(BLOCO, volume, dtype=np.float32))
        return saida

    def testPicosIsoladosNaoSeguramAGravacao(self, mic: Microfone) -> None:
        # `maximo_s=1.0` na fixture: 33 blocos. Sem a correção, os picos
        # isolados impedem o fechamento e a frase só sai no teto.
        frases = escutar(mic, voz(6) + self.blocosAlternados(60) + silencio(15))

        assert frases, "nada saiu"
        assert len(frases[0]) < 33 * BLOCO, (
            "a frase foi até o teto: um pico isolado ainda está zerando o silêncio"
        )

    def testUmaPausaDeVerdadeContinuaFechandoAFrase(self, mic: Microfone) -> None:
        """A correção não pode deixar a frase fechar tarde demais."""
        frases = escutar(mic, voz(20) + silencio(15))
        assert len(frases) == 1

    def testUmaVirgulaContinuaNaoPartindoAFrase(self, mic: Microfone) -> None:
        """O motivo de `silencio_s` ser 0,8: "Atlas, quantos alunos tem?"."""
        frases = escutar(mic, voz(10) + silencio(4) + voz(10) + silencio(15))
        assert len(frases) == 1

    def testDoisBlocosSeguidosAindaContamComoFala(self, mic: Microfone) -> None:
        """Sílaba de verdade tem mais que um bloco de 30 ms."""
        pares = []
        for _ in range(15):
            pares += [np.full(BLOCO, 0.2, dtype=np.float32)] * 2
            pares += [np.full(BLOCO, 0.001, dtype=np.float32)] * 2
        frases = escutar(mic, voz(6) + pares + silencio(15))
        assert frases, "fala com pausas curtas entre sílabas foi descartada"
