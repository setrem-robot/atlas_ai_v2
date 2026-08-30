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
    def test_os_dois_formatos_viram_direcao(
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
    def test_o_que_nao_e_movimento_nao_entra(
        self, comandos: ComandosRecebidos, bruto: dict
    ) -> None:
        comandos.anotar(bruto, agora=100.0)
        assert comandos.instantaneo(agora=100.1)["total"] == 0


class TestOQueValeAgora:
    def test_comando_recente_e_o_atual(self, comandos: ComandosRecebidos) -> None:
        comandos.anotar({"cmd": "F"}, agora=100.0)
        estado = comandos.instantaneo(agora=101.0)
        assert estado["atual"] == "frente"
        assert estado["recebendo"] is True

    def test_movimento_antigo_deixa_de_valer(self, comandos: ComandosRecebidos) -> None:
        # Um "frente" de dez minutos atras aceso na tela diria que o robo esta
        # andando quando ele esta parado ha muito tempo.
        comandos.anotar({"cmd": "F"}, agora=100.0)
        estado = comandos.instantaneo(agora=100.0 + VALIDADE_S + 1)
        assert estado["atual"] is None
        assert estado["recebendo"] is False

    def test_parar_continua_valendo(self, comandos: ComandosRecebidos) -> None:
        # Ninguem mandou nada depois: o robo segue parado, e e isso que a
        # pagina deve mostrar.
        comandos.anotar({"cmd": "S"}, agora=100.0)
        estado = comandos.instantaneo(agora=100.0 + VALIDADE_S * 10)
        assert estado["atual"] == "parar"
        assert estado["recebendo"] is False

    def test_sem_nada_recebido(self, comandos: ComandosRecebidos) -> None:
        estado = comandos.instantaneo(agora=100.0)
        assert estado["atual"] is None
        assert estado["ultimos"] == []


class TestRastro:
    def test_o_mais_novo_vem_primeiro(self, comandos: ComandosRecebidos) -> None:
        # A fita da pagina desenha da esquerda para a direita, do novo ao velho.
        for i, cmd in enumerate(["F", "S", "L"]):
            comandos.anotar({"cmd": cmd}, agora=100.0 + i)
        direcoes = [u["direcao"] for u in comandos.instantaneo(agora=103.0)["ultimos"]]
        assert direcoes == ["esquerda", "parar", "frente"]

    def test_nao_cresce_sem_limite(self, comandos: ComandosRecebidos) -> None:
        # O processo fica ligado o dia inteiro, e um direcional gera dois
        # comandos por toque.
        for i in range(500):
            comandos.anotar({"cmd": "F"}, agora=float(i))
        assert comandos.instantaneo(agora=500.0)["total"] <= 40
