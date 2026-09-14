"""Testes dos números por extenso em português."""

from __future__ import annotations

import pytest

from roboteye.core.numbersPt import spell, spellDecimal, spellOrdinal


class TestBasico:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (0, "zero"),
            (1, "um"),
            (9, "nove"),
            (10, "dez"),
            (15, "quinze"),
            (19, "dezenove"),
            (20, "vinte"),
            (21, "vinte e um"),
            (42, "quarenta e dois"),
            (99, "noventa e nove"),
        ],
    )
    def testAteCem(self, valor: int, esperado: str) -> None:
        assert spell(valor) == esperado

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (100, "cem"),
            (101, "cento e um"),
            (137, "cento e trinta e sete"),
            (200, "duzentos"),
            (256, "duzentos e cinquenta e seis"),
            (999, "novecentos e noventa e nove"),
        ],
    )
    def testCentenas(self, valor: int, esperado: str) -> None:
        """ "cem" só é "cem" exato; 101 já vira "cento e um"."""
        assert spell(valor) == esperado


class TestMilhares:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (1000, "mil"),
            (1001, "mil e um"),
            (1020, "mil e vinte"),
            (1200, "mil e duzentos"),
            (1230, "mil duzentos e trinta"),
            (2000, "dois mil"),
            (2024, "dois mil e vinte e quatro"),
            (15000, "quinze mil"),
            (100000, "cem mil"),
        ],
    )
    def testOEApareceOndeDeve(self, valor: int, esperado: str) -> None:
        """A regra que quase todo mundo erra.

        O último grupo leva "e" quando é pequeno (< 100) ou redondo (múltiplo de
        cem); não leva quando é nem um nem outro. Daí "mil e duzentos" mas
        "mil duzentos e trinta".
        """
        assert spell(valor) == esperado

    def testMilNaoLevaUmNaFrente(self) -> None:
        assert spell(1000) == "mil"
        assert not spell(1000).startswith("um")

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (1_000_000, "um milhao"),
            (2_000_000, "dois milhoes"),
            (1_500_000, "um milhao quinhentos mil"),
            (1_000_000_000, "um bilhao"),
        ],
    )
    def testMilhoesEBilhoes(self, valor: int, esperado: str) -> None:
        assert spell(valor) == esperado


class TestGenero:
    """Português concorda número com gênero; inglês não, e é fácil esquecer."""

    @pytest.mark.parametrize(
        ("valor", "masculino", "feminino"),
        [
            (1, "um", "uma"),
            (2, "dois", "duas"),
            (21, "vinte e um", "vinte e uma"),
            (200, "duzentos", "duzentas"),
            (342, "trezentos e quarenta e dois", "trezentas e quarenta e duas"),
        ],
    )
    def testConcordaComOGenero(self, valor: int, masculino: str, feminino: str) -> None:
        assert spell(valor) == masculino
        assert spell(valor, feminine=True) == feminino

    def testMilhaoContaCoisaMasculina(self) -> None:
        """ "duas milhões" não existe, mesmo contando algo feminino."""
        assert spell(2_000_000, feminine=True).startswith("dois milhoes")


class TestOutrasFormas:
    def testNegativo(self) -> None:
        assert spell(-5) == "menos cinco"

    def testDecimalLeDigitoADigito(self) -> None:
        assert spellDecimal(3, "5") == "tres virgula cinco"
        assert spellDecimal(0, "75") == "zero virgula sete cinco"

    def testDecimalSemParteFracionaria(self) -> None:
        assert spellDecimal(7, "") == "sete"

    @pytest.mark.parametrize(
        ("valor", "esperado"), [(1, "primeiro"), (3, "terceiro"), (10, "decimo")]
    )
    def testOrdinais(self, valor: int, esperado: str) -> None:
        assert spellOrdinal(valor) == esperado

    def testOrdinalFeminino(self) -> None:
        assert spellOrdinal(1, feminine=True) == "primeira"

    def testOrdinalGrandeCaiNoCardinal(self) -> None:
        """Acima de dez ninguém diz "décimo primeiro" numa conversa falada."""
        assert spellOrdinal(42) == "quarenta e dois"
