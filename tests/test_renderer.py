"""Testes do desenho da face.

Rodam com o driver de vídeo `dummy` do SDL: exercitam o código de desenho de
verdade, sem precisar de tela.
"""

# ruff: noqa: E402 - o driver dummy do SDL precisa ser definido antes de importar pygame

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

pygame = pytest.importorskip("pygame")

from roboteye.face.animator import EyeFrame
from roboteye.face.expressions import Expression
from roboteye.face.layout import EyeLayout
from roboteye.face.renderer import HIGH, LOW, MEDIUM, EyeRenderer, qualityFor
from roboteye.face.shapes import EyeShape, presetFor
from roboteye.face.theme import Theme


@pytest.fixture(scope="module", autouse=True)
def pygameIniciado():
    pygame.init()
    pygame.display.set_mode((320, 240))
    yield
    pygame.quit()


def quadro(shape: EyeShape, expressao: Expression = Expression.NEUTRAL) -> EyeFrame:
    return EyeFrame(expression=expressao, left=shape, right=shape)


@pytest.fixture
def surface() -> pygame.Surface:
    return pygame.Surface((1280, 720))


@pytest.fixture
def renderer(surface: pygame.Surface) -> EyeRenderer:
    return EyeRenderer(surface, EyeLayout.forScreen(1280, 720), Theme())


class TestDesenho:
    @pytest.mark.parametrize("expressao", list(Expression))
    def testDesenhaTodasAsExpressoes(
        self, renderer: EyeRenderer, expressao: Expression
    ) -> None:
        renderer.draw(quadro(presetFor(expressao), expressao))

    @pytest.mark.parametrize("altura", [0.03, 0.1, 0.5, 1.0, 1.2])
    def testDesenhaEmQualquerAltura(self, renderer: EyeRenderer, altura: float) -> None:
        renderer.draw(quadro(EyeShape(height=altura)))

    @pytest.mark.parametrize("raio", [0.0, 0.15, 0.3, 0.5])
    def testDesenhaComQualquerRaio(self, renderer: EyeRenderer, raio: float) -> None:
        renderer.draw(quadro(EyeShape(radius=raio)))

    @pytest.mark.parametrize("inclinacao", [-1.0, -0.5, 0.0, 0.5, 1.0])
    def testDesenhaPalpebraEmQualquerInclinacao(
        self, renderer: EyeRenderer, inclinacao: float
    ) -> None:
        renderer.draw(quadro(EyeShape(topLid=0.3, topLidSlant=inclinacao)))

    def testDesenhaComOlharNosExtremos(self, renderer: EyeRenderer) -> None:
        renderer.draw(quadro(EyeShape(offsetX=-380, offsetY=-120)))
        renderer.draw(quadro(EyeShape(offsetX=380, offsetY=120)))

    def testOlhoFechadoNaoEDesenhado(self, renderer: EyeRenderer) -> None:
        renderer.draw(quadro(EyeShape(height=0.0)))

    def testDesenhaComLegendaLonga(self, renderer: EyeRenderer) -> None:
        renderer.draw(
            quadro(presetFor(Expression.SPEAKING), Expression.SPEAKING),
            caption="Uma legenda bem longa " * 20,
            hint="ESC sair",
        )

    @pytest.mark.parametrize("qualidade", [LOW, MEDIUM, HIGH])
    def testDesenhaEmTodosOsNiveisDeQualidade(
        self, surface: pygame.Surface, qualidade
    ) -> None:
        renderer = EyeRenderer(surface, EyeLayout.forScreen(1280, 720), Theme(), quality=qualidade)
        renderer.draw(quadro(presetFor(Expression.HAPPY), Expression.HAPPY))

    def testQualidadeAutoResolveParaUmNivelConhecido(self) -> None:
        assert qualityFor("auto") in (LOW, MEDIUM, HIGH)
        assert qualityFor("high") is HIGH
        # Um nome desconhecido nao deve derrubar a face.
        assert qualityFor("nao-existe") is MEDIUM

    def testResizeReconstroiOLayout(self, renderer: EyeRenderer) -> None:
        nova = pygame.Surface((800, 480))
        renderer.resize(nova, EyeLayout.forScreen(800, 480))
        renderer.draw(quadro(presetFor(Expression.HAPPY), Expression.HAPPY), caption="ok")


class TestPixels:
    """Confere o que efetivamente foi parar na tela.

    Estes testes falam de *forma*, entao desenham no nivel baixo: sem halo e sem
    degrade, um pixel fora do olho e exatamente preto e um pixel dentro e
    exatamente a cor do tema. O halo tem os seus proprios testes mais abaixo.
    """

    def render(self, shape: EyeShape, **kwargs) -> tuple[pygame.Surface, EyeLayout]:
        surface = pygame.Surface((1280, 720))
        layout = EyeLayout.forScreen(1280, 720)
        kwargs.setdefault("quality", LOW)
        EyeRenderer(surface, layout, Theme(), **kwargs).draw(quadro(shape))
        return surface, layout

    def testPintaOFundo(self) -> None:
        surface, _ = self.render(EyeShape())
        assert surface.get_at((0, 0))[:3] == (0, 0, 0)

    def testDesenhaOOlhoNaCorDoTema(self) -> None:
        surface, layout = self.render(EyeShape())
        assert surface.get_at((layout.leftEyeX, layout.eyeCenterY))[:3] == (4, 201, 253)

    def testDegradePreservaACorPedidaNoCentro(self) -> None:
        """O degrade clareia o topo tanto quanto escurece a base.

        Sem isso, quem configura uma cor nunca a ve na tela: o olho inteiro sai
        um pouco mais escuro do que foi pedido.
        """
        surface, layout = self.render(EyeShape(), quality=HIGH)
        centro = surface.get_at((layout.leftEyeX, layout.eyeCenterY))[:3]
        assert all(abs(a - b) <= 2 for a, b in zip(centro, (4, 201, 253), strict=True))

    def testPalpebraSuperiorApagaOAltoDoOlho(self) -> None:
        layout = EyeLayout.forScreen(1280, 720)
        alto = layout.eyeCenterY - layout.eyeHeight // 2 + 4

        semLid, _ = self.render(EyeShape())
        comLid, _ = self.render(EyeShape(topLid=0.45))

        assert semLid.get_at((layout.leftEyeX, alto))[:3] != (0, 0, 0)
        assert comLid.get_at((layout.leftEyeX, alto))[:3] == (0, 0, 0)

    def testPalpebraInferiorApagaABaseDoOlho(self) -> None:
        layout = EyeLayout.forScreen(1280, 720)
        base = layout.eyeCenterY + layout.eyeHeight // 2 - 4

        semLid, _ = self.render(EyeShape())
        comLid, _ = self.render(EyeShape(bottomLid=0.5))

        assert semLid.get_at((layout.leftEyeX, base))[:3] != (0, 0, 0)
        assert comLid.get_at((layout.leftEyeX, base))[:3] == (0, 0, 0)

    def testInclinacaoDaPalpebraEAssimetricaEntreOsOlhos(self) -> None:
        """Bravo baixa o canto interno dos dois olhos, que são lados opostos."""
        surface = pygame.Surface((1280, 720))
        layout = EyeLayout.forScreen(1280, 720)
        shape = EyeShape(topLid=0.35, topLidSlant=1.0)
        EyeRenderer(surface, layout, Theme()).draw(quadro(shape))

        topo = layout.eyeCenterY - layout.eyeHeight // 2
        margem = layout.eyeWidth // 2 - 6

        def coberto(x: int) -> bool:
            for dy in range(0, layout.eyeHeight // 2):
                if surface.get_at((x, topo + dy))[:3] != (0, 0, 0):
                    return dy > layout.eyeHeight * 0.12
            return True

        # No olho esquerdo o canto interno é o direito; no direito, o esquerdo.
        assert coberto(layout.leftEyeX + margem)
        assert coberto(layout.rightEyeX - margem)

    def alturaCoberta(self, surface: pygame.Surface, x: int, layout: EyeLayout) -> int:
        """Quantos pixels da palpebra cobrem o olho na coluna `x`."""
        topo = layout.eyeCenterY - layout.eyeHeight // 2
        for dy in range(layout.eyeHeight):
            if surface.get_at((x, topo + dy))[:3] != (0, 0, 0):
                return dy
        return layout.eyeHeight

    def testCansadoBaixaOCantoExternoDosDoisOlhos(self) -> None:
        """Cansado e o espelho exato de bravo, e o espelho e por olho.

        Bravo ja tinha teste; sem o par, uma troca de sinal passaria despercebida
        num dos dois casos — e e justamente o tipo de erro que nao da pra ver
        olhando, porque os dois olhos continuam simetricos entre si.
        """
        surface = pygame.Surface((1280, 720))
        layout = EyeLayout.forScreen(1280, 720)
        shape = EyeShape(topLid=0.35, topLidSlant=-1.0)
        EyeRenderer(surface, layout, Theme(), quality=LOW).draw(quadro(shape))

        margem = layout.eyeWidth // 2 - 6
        # No olho esquerdo o canto externo e o esquerdo; no direito, o direito.
        esquerdoFora = self.alturaCoberta(surface, layout.leftEyeX - margem, layout)
        esquerdoDentro = self.alturaCoberta(surface, layout.leftEyeX + margem, layout)
        direitoFora = self.alturaCoberta(surface, layout.rightEyeX + margem, layout)
        direitoDentro = self.alturaCoberta(surface, layout.rightEyeX - margem, layout)

        assert esquerdoFora > esquerdoDentro
        assert direitoFora > direitoDentro

    def testRaioMaiorArredondaMaisOsCantos(self) -> None:
        layout = EyeLayout.forScreen(1280, 720)
        cantoX = layout.leftEyeX - layout.eyeWidth // 2 + 3
        cantoY = layout.eyeCenterY - layout.eyeHeight // 2 + 3

        quadrado, _ = self.render(EyeShape(radius=0.0))
        redondo, _ = self.render(EyeShape(radius=0.5))

        assert quadrado.get_at((cantoX, cantoY))[:3] != (0, 0, 0)
        assert redondo.get_at((cantoX, cantoY))[:3] == (0, 0, 0)

    def testConfiguracaoDeRaioReescalaAsFormas(self) -> None:
        layout = EyeLayout.forScreen(1280, 720)
        cantoX = layout.leftEyeX - layout.eyeWidth // 2 + 3
        cantoY = layout.eyeCenterY - layout.eyeHeight // 2 + 3

        surface, _ = self.render(EyeShape(), cornerRadius=0.02)
        assert surface.get_at((cantoX, cantoY))[:3] != (0, 0, 0)


class TestHalo:
    """O brilho ao redor do olho."""

    def render(self, shape: EyeShape, quality) -> tuple[pygame.Surface, EyeLayout]:
        surface = pygame.Surface((1280, 720))
        layout = EyeLayout.forScreen(1280, 720)
        EyeRenderer(surface, layout, Theme(), quality=quality).draw(quadro(shape))
        return surface, layout

    def testHaloAcendeAoRedorDoOlho(self) -> None:
        foraX = 40  # bem fora do olho, mas dentro do alcance do halo
        layout = EyeLayout.forScreen(1280, 720)
        ponto = (layout.leftEyeX - layout.eyeWidth // 2 - foraX, layout.eyeCenterY)

        semHalo, _ = self.render(EyeShape(), LOW)
        comHalo, _ = self.render(EyeShape(), HIGH)

        assert semHalo.get_at(ponto)[:3] == (0, 0, 0)
        assert comHalo.get_at(ponto)[:3] != (0, 0, 0)

    def testHaloNaoVazaOndeAPalpebraCortou(self) -> None:
        """Regressao: o halo saia de uma borda que a palpebra havia removido.

        Tirar o halo do campo de distancia parecia economico — o campo ja estava
        calculado — mas uma interseccao feita com `max` so e exata *dentro* da
        forma. Do lado de fora ela subestima a distancia, e o brilho continuava
        saindo da base do olho mesmo depois de o sorriso te-la cortado, o que
        pintava um bloco retangular logo abaixo dos olhos.
        """
        layout = EyeLayout.forScreen(1280, 720)
        surface, _ = self.render(EyeShape(bottomLid=0.5), HIGH)

        # Uma faixa larga bem abaixo do olho, onde nao ha superficie nenhuma.
        base = layout.eyeCenterY + layout.eyeHeight // 2 + 30
        for x in range(layout.leftEyeX - 200, layout.leftEyeX + 200, 7):
            assert surface.get_at((x, base))[:3] == (0, 0, 0), f"halo vazou em x={x}"


class TestSubPixel:
    """Movimento menor que um pixel precisa aparecer na tela."""

    def render(self, offsetX: float) -> pygame.Surface:
        surface = pygame.Surface((1280, 720))
        layout = EyeLayout.forScreen(1280, 720)
        EyeRenderer(surface, layout, Theme(), quality=LOW).draw(quadro(EyeShape(offsetX=offsetX)))
        return surface

    def testDeslocamentoFracionarioMudaOsPixels(self) -> None:
        """Antes, `int()` engolia qualquer movimento menor que um pixel.

        Era o que fazia a respiracao e as microssacadas andarem aos pulos: o
        olho ficava parado varios quadros e depois saltava um pixel inteiro.
        """
        layout = EyeLayout.forScreen(1280, 720)
        # Meia unidade base e bem menos que um pixel na tela.
        meioPixel = 0.5 / layout.scale

        parado = pygame.image.tostring(self.render(0.0), "RGB")
        movido = pygame.image.tostring(self.render(meioPixel), "RGB")
        assert parado != movido
