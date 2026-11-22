"""Testes do modelo paramétrico do olho."""

from __future__ import annotations

from itertools import pairwise

import pytest

from roboteye.face import shapes
from roboteye.face.expressions import Expression
from roboteye.face.layout import EYE_WIDTH, MOUTH_WIDTH
from roboteye.face.shapes import (
    HIDDEN_MOUTH,
    EyeShape,
    MouthShape,
    accentFor,
    mouthFor,
    presetFor,
)


class TestEyeShape:
    def testPadraoEUmOlhoAbertoENeutro(self) -> None:
        shape = EyeShape()
        assert shape.width == 1.0
        assert shape.height == 1.0
        assert shape.topLid == 0.0
        assert shape.bottomLid == 0.0
        assert not shape.isClosed

    def testOlhoSemAlturaContaComoFechado(self) -> None:
        assert EyeShape(height=0.0).isClosed
        assert EyeShape(width=0.0).isClosed

    def testScaledMultiplica(self) -> None:
        shape = EyeShape(width=1.0, height=2.0).scaled(width=0.5, height=0.5)
        assert shape.width == 0.5
        assert shape.height == 1.0

    def testMovedSoma(self) -> None:
        shape = EyeShape(offsetX=10.0).moved(dx=5.0, dy=-3.0)
        assert shape.offsetX == 15.0
        assert shape.offsetY == -3.0

    def testEImutavel(self) -> None:
        shape = EyeShape()
        with pytest.raises((AttributeError, TypeError)):
            shape.height = 0.5  # type: ignore[misc]


class TestInterpolacao:
    def testExtremosDevolvemAsPontas(self) -> None:
        a, b = EyeShape(height=1.0), EyeShape(height=0.0)
        assert a.lerp(b, 0.0) is a
        assert a.lerp(b, 1.0) is b

    def testMeioDoCaminho(self) -> None:
        a = EyeShape(height=1.0, topLid=0.0)
        b = EyeShape(height=0.0, topLid=0.4)
        meio = a.lerp(b, 0.5)

        assert meio.height == pytest.approx(0.5)
        assert meio.topLid == pytest.approx(0.2)

    def testInterpolaTodosOsCampos(self) -> None:
        """Se um campo novo ficar de fora do lerp, a transição dele fica seca."""
        a = EyeShape(1.0, 1.0, 0.3, 0.0, 0.0, 0.0, 0.0, 0.0)
        b = EyeShape(2.0, 2.0, 0.5, 10.0, 20.0, 0.5, 1.0, 0.6)
        meio = a.lerp(b, 0.5)

        assert meio.width == pytest.approx(1.5)
        assert meio.radius == pytest.approx(0.4)
        assert meio.offsetX == pytest.approx(5.0)
        assert meio.offsetY == pytest.approx(10.0)
        assert meio.topLidSlant == pytest.approx(0.5)
        assert meio.bottomLid == pytest.approx(0.3)

    def testCaminhoEntreExpressoesEContinuo(self) -> None:
        """Bravo vira feliz sem nenhum salto pelo caminho."""
        origem = presetFor(Expression.ANGRY)
        destino = presetFor(Expression.HAPPY)

        passos = [origem.lerp(destino, i / 40) for i in range(41)]
        for anterior, atual in pairwise(passos):
            assert abs(atual.topLid - anterior.topLid) < 0.05
            assert abs(atual.bottomLid - anterior.bottomLid) < 0.05


class TestPresets:
    @pytest.mark.parametrize("expressao", list(Expression))
    def testTodaExpressaoTemForma(self, expressao: Expression) -> None:
        assert isinstance(presetFor(expressao), EyeShape)

    def testFelizUsaPalpebraInferior(self) -> None:
        assert presetFor(Expression.HAPPY).bottomLid > 0.2

    def testBravoBaixaOCantoInterno(self) -> None:
        bravo = presetFor(Expression.ANGRY)
        assert bravo.topLid > 0.2
        assert bravo.topLidSlant > 0

    def testCansadoEOOpostoDeBravo(self) -> None:
        assert presetFor(Expression.TIRED).topLidSlant < 0

    def testDormindoEQuaseUmaLinha(self) -> None:
        assert presetFor(Expression.SLEEP).height < 0.1

    def testRindoSorriMaisQueFeliz(self) -> None:
        assert presetFor(Expression.LAUGH).bottomLid > presetFor(Expression.HAPPY).bottomLid

    def testRaioPadraoEQuadradoDeCantosMacios(self) -> None:
        # 0.5 seria um círculo; o projeto pede canto arredondado, não redondo.
        assert 0.15 < shapes.DEFAULT_RADIUS < 0.45


class TestBoca:
    def testLerpInterpolaTodosOsCampos(self) -> None:
        a = MouthShape(width=0.4, openness=0.0, curve=-1.0, thickness=0.1, alpha=0.5)
        b = MouthShape(width=0.8, openness=0.4, curve=1.0, thickness=0.2, alpha=1.0)
        meio = a.lerp(b, 0.5)
        assert meio.width == pytest.approx(0.6)
        assert meio.openness == pytest.approx(0.2)
        assert meio.curve == pytest.approx(0.0)
        assert meio.thickness == pytest.approx(0.15)
        assert meio.alpha == pytest.approx(0.75)

    def testLerpNosExtremos(self) -> None:
        a, b = MouthShape(alpha=0.0), MouthShape(alpha=1.0)
        assert a.lerp(b, 0.0) is a
        assert a.lerp(b, 1.0) is b

    @pytest.mark.parametrize("expressao", list(Expression))
    def testTodaExpressaoTemBoca(self, expressao: Expression) -> None:
        assert isinstance(mouthFor(expressao), MouthShape)

    def testNeutroEDiscreto(self) -> None:
        """No repouso a boca e um traco curto, fino e fechado."""
        boca = mouthFor(Expression.NEUTRAL)
        assert boca.width < mouthFor(Expression.HAPPY).width
        assert boca.thickness <= 0.07
        assert abs(boca.curve) < 0.2
        assert boca.openness == pytest.approx(0.0)

    @pytest.mark.parametrize("expressao", list(Expression))
    def testBocaNuncaMaisLargaQueUmOlho(self, expressao: Expression) -> None:
        """A boca larga (ate 860 unidades) competia com o olhar em vez de segui-lo."""
        assert mouthFor(expressao).width * MOUTH_WIDTH <= EYE_WIDTH

    def testBravoEBocaDoMal(self) -> None:
        """Virada para baixo nas pontas (curve negativo) e bem visivel."""
        boca = mouthFor(Expression.ANGRY)
        assert boca.curve < -0.5
        assert boca.alpha == pytest.approx(1.0)

    def testFelizSorri(self) -> None:
        assert mouthFor(Expression.HAPPY).curve > 0.5

    def testBocaEscondidaSeEscondeSozinha(self) -> None:
        assert HIDDEN_MOUTH.isHidden
        assert not mouthFor(Expression.HAPPY).isHidden

    def testLerpInterpolaOsDentes(self) -> None:
        a, b = MouthShape(teeth=0.0), MouthShape(teeth=1.0)
        assert a.lerp(b, 0.5).teeth == pytest.approx(0.5)


class TestMonstro:
    def testRageEMaisFeraQueBravo(self) -> None:
        """O monstro cerra mais o olho e inclina mais que o bravo comum."""
        rage = presetFor(Expression.RAGE)
        angry = presetFor(Expression.ANGRY)
        assert rage.topLid > angry.topLid
        assert rage.topLidSlant >= angry.topLidSlant > 0

    def testRageTemDentes(self) -> None:
        boca = mouthFor(Expression.RAGE)
        assert boca.teeth > 0.5
        assert boca.openness > 0.3  # um maw aberto, nao um traco

    def testRageEMaisTenebrosoQueBravo(self) -> None:
        rage = accentFor(Expression.RAGE)
        angry = accentFor(Expression.ANGRY)
        assert rage.background is not None and angry.background is not None
        assert sum(rage.background) < sum(angry.background)  # fundo mais escuro
        assert rage.background[0] > rage.background[1]  # ainda vermelho
        assert rage.eye is not None and min(rage.eye) > 200  # olhos palidos


class TestAcentoDeCor:
    def testBravoFicaBrancoNoVermelho(self) -> None:
        acento = accentFor(Expression.ANGRY)
        assert acento.eye is not None and min(acento.eye) > 200  # olho branco
        assert acento.background is not None
        r, g, b = acento.background
        assert r > 100 and g < 60 and b < 60  # fundo vermelho

    @pytest.mark.parametrize("expressao", [Expression.NEUTRAL, Expression.HAPPY, Expression.TIRED])
    def testOutrasMantemAPaletaBase(self, expressao: Expression) -> None:
        acento = accentFor(expressao)
        assert acento.eye is None
        assert acento.background is None
