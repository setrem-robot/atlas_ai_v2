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
        microfone._blocos.put_nowait(bloco)
    # `None` e o sinal de fim de captura. Chamar `fechar()` aqui faria o laco
    # nem comecar, e o teste passaria a nao testar nada.
    microfone._blocos.put_nowait(None)
    return list(microfone._cortar_em_frases())


@pytest.fixture
def mic() -> Microfone:
    # `limiar` explicito: sem ele o microfone mede a sala no arranque, e aqui
    # nao ha sala — os blocos vem da fila, na mao.
    return Microfone(limiar=0.02, silencio_s=0.3, minimo_s=0.15, maximo_s=1.0)


class TestUmaFrase:
    def test_fala_seguida_de_silencio_vira_uma_frase(self, mic: Microfone) -> None:
        frases = escutar(mic, silencio(3) + voz(20) + silencio(15))
        assert len(frases) == 1

    def test_o_comeco_da_fala_nao_se_perde(self, mic: Microfone) -> None:
        # A primeira silaba ja passou quando o som cruza o limiar; o trecho
        # entregue tem de ser maior que os blocos de voz sozinhos.
        frases = escutar(mic, silencio(8) + voz(20) + silencio(15))
        assert len(frases[0]) > 20 * BLOCO


class TestDuasFrases:
    def test_pausa_curta_nao_parte_a_frase(self, mic: Microfone) -> None:
        # A virgula de "Atlas, quantos alunos tem?" nao pode virar duas frases.
        frases = escutar(mic, voz(10) + silencio(4) + voz(10) + silencio(15))
        assert len(frases) == 1

    def test_pausa_longa_separa_duas_perguntas(self, mic: Microfone) -> None:
        frases = escutar(mic, voz(10) + silencio(15) + voz(10) + silencio(15))
        assert len(frases) == 2


class TestRuido:
    def test_estalo_curto_e_descartado(self, mic: Microfone) -> None:
        # Uma porta batendo, uma cadeira arrastando: som alto e curto demais
        # para ser pergunta.
        assert escutar(mic, silencio(3) + voz(2) + silencio(15)) == []

    def test_sala_quieta_nao_produz_nada(self, mic: Microfone) -> None:
        assert escutar(mic, silencio(50)) == []


class TestTetoDeSeguranca:
    def test_som_continuo_e_cortado_em_vez_de_crescer_para_sempre(self, mic: Microfone) -> None:
        # Um ventilador que liga nao pode gravar ate a memoria acabar.
        frases = escutar(mic, voz(120))
        assert frases
        assert all(len(f) <= 1.0 * 16000 + BLOCO * 10 for f in frases)


class TestPausa:
    def test_pausado_nao_e_o_mesmo_que_fechado(self, mic: Microfone) -> None:
        mic.pausar()
        mic.retomar()
        frases = escutar(mic, voz(20) + silencio(15))
        assert len(frases) == 1
