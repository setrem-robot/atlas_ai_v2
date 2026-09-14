"""Testes das curvas de aceleração e do tween."""

from __future__ import annotations

from itertools import pairwise

import pytest

from roboteye.face import easing
from roboteye.face.easing import Tween

CURVAS = [
    easing.linear,
    easing.easeInQuad,
    easing.easeOutQuad,
    easing.easeOutCubic,
    easing.easeInOutCubic,
    easing.easeOutBack,
]


class TestCurvas:
    @pytest.mark.parametrize("curva", CURVAS)
    def testComecamEmZeroETerminamEmUm(self, curva) -> None:
        assert curva(0.0) == pytest.approx(0.0, abs=1e-6)
        assert curva(1.0) == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.parametrize(
        "curva",
        [easing.linear, easing.easeInQuad, easing.easeOutQuad, easing.easeInOutCubic],
    )
    def testSaoMonotonicas(self, curva) -> None:
        valores = [curva(i / 50) for i in range(51)]
        assert all(b >= a - 1e-9 for a, b in pairwise(valores))

    def testEaseInELentoNoComeco(self) -> None:
        assert easing.easeInQuad(0.25) < 0.25

    def testEaseOutERapidoNoComeco(self) -> None:
        assert easing.easeOutQuad(0.25) > 0.25

    def testEaseOutBackPassaDoAlvo(self) -> None:
        assert max(easing.easeOutBack(i / 100) for i in range(101)) > 1.0


class TestUtilitarios:
    def testLerp(self) -> None:
        assert easing.lerp(10.0, 20.0, 0.5) == pytest.approx(15.0)

    @pytest.mark.parametrize(("valor", "esperado"), [(-1.0, 0.0), (0.5, 0.5), (2.0, 1.0)])
    def testClamp(self, valor: float, esperado: float) -> None:
        assert easing.clamp(valor) == esperado

    def testApproachConvergeParaOAlvo(self) -> None:
        valor = 0.0
        for _ in range(200):
            valor = easing.approach(valor, 100.0, 1 / 60, 10.0)
        assert valor == pytest.approx(100.0, abs=0.1)

    def testApproachIndependeDaTaxaDeQuadros(self) -> None:
        """O mesmo tempo real deve levar ao mesmo lugar, a 30 ou a 120 FPS."""
        lento = 0.0
        for _ in range(30):
            lento = easing.approach(lento, 100.0, 1 / 30, 8.0)

        rapido = 0.0
        for _ in range(120):
            rapido = easing.approach(rapido, 100.0, 1 / 120, 8.0)

        assert lento == pytest.approx(rapido, abs=0.5)


class TestTween:
    def testChegaAoAlvoNoTempoPrevisto(self) -> None:
        tween = Tween(0.0)
        tween.to(10.0, 0.5)

        for _ in range(31):  # 31/60 s passa de 0,5 s
            tween.update(1 / 60)

        assert tween.value == pytest.approx(10.0)
        assert tween.done

    def testAindaNaoTerminouAntesDaHora(self) -> None:
        tween = Tween(0.0)
        tween.to(10.0, 0.5)
        tween.update(0.4)
        assert not tween.done

    def testEstaNoMeioDoCaminhoNaMetadeDoTempo(self) -> None:
        tween = Tween(0.0, easing.linear)
        tween.to(10.0, 1.0)
        tween.update(0.5)

        assert tween.value == pytest.approx(5.0, abs=0.01)

    def testNovoAlvoParteDeOndeEsta(self) -> None:
        tween = Tween(0.0, easing.linear)
        tween.to(10.0, 1.0)
        tween.update(0.5)
        meio = tween.value

        tween.to(0.0, 1.0)
        assert tween.value == pytest.approx(meio)

    def testSnapCancelaOMovimento(self) -> None:
        tween = Tween(0.0)
        tween.to(10.0, 1.0)
        tween.snap(3.0)

        assert tween.value == 3.0
        assert tween.done
        assert tween.update(1.0) == 3.0

    def testDuracaoZeroChegaNaHora(self) -> None:
        tween = Tween(0.0)
        tween.to(7.0, 0.0)
        assert tween.value == 7.0

    def testNaoPassaDoAlvoComDtGrande(self) -> None:
        tween = Tween(0.0, easing.linear)
        tween.to(10.0, 0.2)
        tween.update(5.0)
        assert tween.value == pytest.approx(10.0)
