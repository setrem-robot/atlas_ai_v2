"""Testes do que a página mostra sobre o controle."""

from __future__ import annotations

import pytest

from roboteye.web.comandos import VALIDADE_S, ComandosRecebidos


@pytest.fixture
def comandos() -> ComandosRecebidos:
    return ComandosRecebidos()


class TestTraducao:
    @pytest.mark.parametrize(
        ("bruto", "esperado"),
        [
            ({"cmd": "F"}, "frente"),
            ({"cmd": "B"}, "tras"),
            ({"cmd": "L"}, "esquerda"),
            ({"cmd": "R"}, "direita"),
            ({"cmd": "S"}, "parar"),
            # Minuscula tambem: o formato e do app, mas o topico e publico.
            ({"cmd": "f"}, "frente"),
            # Formato expandido, do contrato MQTT.
            ({"tipo": "motor", "acao": "frente"}, "frente"),
            ({"tipo": "parada_emergencia"}, "parar"),
        ],
    )
    def testOsDoisFormatosViramDirecao(
        self, comandos: ComandosRecebidos, bruto: dict, esperado: str
    ) -> None:
        comandos.anotar(bruto, agora=100.0)
        assert comandos.instantaneo(agora=100.1)["atual"] == esperado

    @pytest.mark.parametrize(
        "bruto",
        [
            {"cmd": "X"},
            {"tipo": "voz", "texto": "ola"},
            {"nada": "a ver"},
            {},
        ],
    )
    def testOQueNaoEMovimentoNaoEntra(
        self, comandos: ComandosRecebidos, bruto: dict
    ) -> None:
        comandos.anotar(bruto, agora=100.0)
        assert comandos.instantaneo(agora=100.1)["total"] == 0


class TestOQueValeAgora:
    def testComandoRecenteEOAtual(self, comandos: ComandosRecebidos) -> None:
        comandos.anotar({"cmd": "F"}, agora=100.0)
        estado = comandos.instantaneo(agora=101.0)
        assert estado["atual"] == "frente"
        assert estado["recebendo"] is True

    def testMovimentoAntigoDeixaDeValer(self, comandos: ComandosRecebidos) -> None:
        # Um "frente" de dez minutos atras aceso na tela diria que o robo esta
        # andando quando ele esta parado ha muito tempo.
        comandos.anotar({"cmd": "F"}, agora=100.0)
        estado = comandos.instantaneo(agora=100.0 + VALIDADE_S + 1)
        assert estado["atual"] is None
        assert estado["recebendo"] is False

    def testPararContinuaValendo(self, comandos: ComandosRecebidos) -> None:
        # Ninguem mandou nada depois: o robo segue parado, e e isso que a
        # pagina deve mostrar.
        comandos.anotar({"cmd": "S"}, agora=100.0)
        estado = comandos.instantaneo(agora=100.0 + VALIDADE_S * 10)
        assert estado["atual"] == "parar"
        assert estado["recebendo"] is False

    def testSemNadaRecebido(self, comandos: ComandosRecebidos) -> None:
        estado = comandos.instantaneo(agora=100.0)
        assert estado["atual"] is None
        assert estado["ultimos"] == []


class TestRastro:
    def testOMaisNovoVemPrimeiro(self, comandos: ComandosRecebidos) -> None:
        # A fita da pagina desenha da esquerda para a direita, do novo ao velho.
        for i, cmd in enumerate(["F", "S", "L"]):
            comandos.anotar({"cmd": cmd}, agora=100.0 + i)
        direcoes = [u["direcao"] for u in comandos.instantaneo(agora=103.0)["ultimos"]]
        assert direcoes == ["esquerda", "parar", "frente"]

    def testNaoCresceSemLimite(self, comandos: ComandosRecebidos) -> None:
        # O processo fica ligado o dia inteiro, e um direcional gera dois
        # comandos por toque.
        for i in range(500):
            comandos.anotar({"cmd": "F"}, agora=float(i))
        assert comandos.instantaneo(agora=500.0)["total"] <= 40
