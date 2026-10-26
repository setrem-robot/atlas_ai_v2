"""Testes dos campos de distância da boca e do vórtice (lógica pura, sem pygame)."""

from __future__ import annotations

import numpy as np

from roboteye.face import mask
from roboteye.face.shapes import MouthShape


def mouthGeometry(width: float = 200.0, height: float = 120.0) -> mask.MouthGeometry:
    return mask.MouthGeometry(
        gridWidth=int(width) + 40,
        gridHeight=int(height),
        mouthWidth=width,
        mouthHeight=height,
    )


class TestBocaCampo:
    def testCentroFicaDentroDaBoca(self) -> None:
        """O centro de uma boca aberta e reta cai dentro da forma (campo < 0)."""
        geo = mouthGeometry()
        field = mask.mouthField(MouthShape(curve=0.0, openness=0.2), geo)
        centro = field[geo.gridHeight // 2, geo.gridWidth // 2]
        assert centro < 0.0

    def testPontasSaoArredondadas(self) -> None:
        """Alem do comprimento, nao ha boca: o campo e positivo (fora)."""
        geo = mouthGeometry()
        field = mask.mouthField(MouthShape(width=0.5), geo)
        meioY = geo.gridHeight // 2
        assert field[meioY, 2] > 0.0
        assert field[meioY, -2] > 0.0

    def testCurvaPositivaBaixaOMeio(self) -> None:
        """Sorriso: a linha central no meio fica mais para baixo que nas pontas."""
        geo = mouthGeometry()
        smile = mask.mouthField(MouthShape(curve=1.0, thickness=0.08), geo)
        # A linha da boca em cada coluna e onde o campo e minimo (o centro do traco).
        meio = int(np.argmin(smile[:, geo.gridWidth // 2]))
        quasePonta = int(np.argmin(smile[:, geo.gridWidth // 2 + geo.gridWidth // 4]))
        assert meio > quasePonta  # y cresce para baixo

    def testAberturaEngrossa(self) -> None:
        fechada = mask.mouthField(MouthShape(openness=0.0), mouthGeometry())
        aberta = mask.mouthField(MouthShape(openness=0.5), mouthGeometry())
        assert (aberta < 0).sum() > (fechada < 0).sum()


class TestDentesDeMonstro:
    def testOsDentesMudamABoca(self) -> None:
        geo = mouthGeometry()
        lisa = mask.mouthField(MouthShape(openness=0.6, teeth=0.0), geo)
        comDentes = mask.mouthField(MouthShape(openness=0.6, teeth=1.0), geo)
        assert not np.allclose(lisa, comDentes)

    def testOMawTemAberturaNoCentro(self) -> None:
        geo = mouthGeometry()
        field = mask.mouthField(MouthShape(openness=0.6, teeth=1.0), geo)
        assert field[geo.gridHeight // 2, geo.gridWidth // 2] < 0.0

    def testOsDentesCriamZigueZagueNaBorda(self) -> None:
        """A borda de cima do maw sobe e desce: e o que forma os dentes."""
        geo = mouthGeometry()
        field = mask.mouthField(MouthShape(openness=0.6, teeth=1.0, thickness=0.1), geo)
        # Para cada coluna do meio, a primeira linha "dentro" (campo < 0) e a borda.
        meio = geo.gridWidth // 2
        bordas = []
        for col in range(meio - 60, meio + 60, 4):
            dentro = np.where(field[:, col] < 0.0)[0]
            if dentro.size:
                bordas.append(int(dentro[0]))
        assert bordas and (max(bordas) - min(bordas)) > 4  # a borda sobe e desce


class TestVortice:
    def testFicaEntreZeroEUm(self) -> None:
        alpha = mask.spiralField(80, 80, phase=0.0)
        assert alpha.min() >= 0.0 and alpha.max() <= 1.0

    def testTemTintaEVazio(self) -> None:
        """A espiral de fato desenha algo, e tambem deixa fundo preto entre bracos."""
        alpha = mask.spiralField(80, 80, phase=0.0)
        assert alpha.max() > 0.5
        assert alpha.min() < 0.1

    def testForaDoCirculoEVazio(self) -> None:
        alpha = mask.spiralField(80, 80, phase=0.0)
        assert alpha[0, 0] == 0.0  # canto, fora do disco do olho

    def testAFaseGiraODesenho(self) -> None:
        a = mask.spiralField(80, 80, phase=0.0)
        b = mask.spiralField(80, 80, phase=1.5)
        assert not np.allclose(a, b)
