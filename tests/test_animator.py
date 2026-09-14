"""Testes da animação dos olhos (lógica pura, sem pygame)."""

from __future__ import annotations

import random
from itertools import pairwise

import pytest

from roboteye.face.animator import EyeAnimator, EyeFrame
from roboteye.face.expressions import Expression
from roboteye.face.layout import EyeLayout

PASSO = 1 / 60


def avancar(animator: EyeAnimator, segundos: float) -> EyeFrame:
    """Roda a animação por um tempo e devolve o último quadro."""
    frame = animator.update(PASSO)
    decorrido = PASSO
    while decorrido < segundos:
        frame = animator.update(PASSO)
        decorrido += PASSO
    return frame


def coletar(animator: EyeAnimator, segundos: float) -> list[EyeFrame]:
    """Todos os quadros de um intervalo."""
    return [animator.update(PASSO) for _ in range(int(segundos * 60))]


@pytest.fixture
def animator() -> EyeAnimator:
    return EyeAnimator(idleAnimations=False, rng=random.Random(42))


class TestPiscada:
    def testOlhosComecamAbertos(self, animator: EyeAnimator) -> None:
        frame = animator.update(PASSO)
        assert frame.left.openness > 0.9

    def testPiscadaFechaOsOlhos(self, animator: EyeAnimator) -> None:
        animator.blinkNow()
        alturas = [f.left.openness for f in coletar(animator, 0.15)]
        assert min(alturas) < 0.1

    def testOlhosReabremDepois(self, animator: EyeAnimator) -> None:
        animator.blinkNow()
        frame = avancar(animator, 0.5)
        assert frame.left.openness > 0.9

    def testFechaMaisRapidoDoQueAbre(self, animator: EyeAnimator) -> None:
        """Assimetria proposital: é assim que uma piscada de verdade acontece."""
        animator.blinkNow()
        alturas = [f.left.openness for f in coletar(animator, 0.4)]

        fundo = alturas.index(min(alturas))
        reaberto = next(i for i, h in enumerate(alturas[fundo:], fundo) if h > 0.95)

        assert fundo < (reaberto - fundo), "abrir deveria levar mais tempo que fechar"

    def testOsDoisOlhosPiscamJuntos(self, animator: EyeAnimator) -> None:
        animator.blinkNow()
        for frame in coletar(animator, 0.3):
            assert frame.left.openness == pytest.approx(frame.right.openness, abs=0.02)

    def testAReaberturaESuave(self, animator: EyeAnimator) -> None:
        """O que estraga uma animação não é a velocidade, é a mudança brusca dela.

        A pálpebra pode percorrer bastante altura num quadro — é uma piscada,
        deve ser rápida. O que não pode é a velocidade saltar de um quadro para
        o outro. A reabertura é a fase longa e visível, onde isso apareceria.
        """
        animator.blinkNow()
        alturas = [f.left.openness for f in coletar(animator, 0.6)]

        fundo = alturas.index(min(alturas))
        reabertura = alturas[fundo:]

        velocidades = [b - a for a, b in pairwise(reabertura)]
        aceleracoes = [abs(b - a) for a, b in pairwise(velocidades)]

        # 0,08 passa folgado numa curva que arranca do repouso e aperta uma que
        # comece na velocidade maxima (essa chegava a 0,16).
        assert max(aceleracoes) < 0.08

    def testFicaUmInstanteFechada(self, animator: EyeAnimator) -> None:
        """A pausa no fundo evita que a pálpebra inverta o sentido num quadro só."""
        animator.blinkNow()
        alturas = [f.left.openness for f in coletar(animator, 0.6)]
        assert sum(1 for h in alturas if h < 0.08) >= 2


class TestPiscadaComExpressao:
    """A piscada tem de funcionar a partir de qualquer expressão, não só do neutro."""

    @pytest.mark.parametrize(
        "expressao",
        [Expression.NEUTRAL, Expression.HAPPY, Expression.ANGRY, Expression.TIRED],
    )
    def testFechaAPartirDeQualquerExpressao(
        self, animator: EyeAnimator, expressao: Expression
    ) -> None:
        animator.setMood(expressao)
        avancar(animator, 0.6)  # deixa o morph terminar

        animator.blinkNow()
        assert min(f.left.openness for f in coletar(animator, 0.3)) < 0.1

    @pytest.mark.parametrize("expressao", [Expression.HAPPY, Expression.LAUGH])
    def testAPalpebraDeBaixoNuncaRecua(
        self, animator: EyeAnimator, expressao: Expression
    ) -> None:
        """O sorriso mora na pálpebra de baixo; piscar não pode desmanchá-lo.

        Era o defeito: com alvo fixo, a pálpebra inferior *descia* de 0,44 para
        0,16 durante a piscada, e o sorriso se refazia depois. Ao vivo, isso
        aparecia como a expressão piscando junto com o olho.
        """
        animator.setMood(expressao)
        repouso = avancar(animator, 0.6).left.bottomLid

        animator.blinkNow()
        for frame in coletar(animator, 0.5):
            assert frame.left.bottomLid >= repouso - 0.01

    def testAFrestaFinalIndependeDaExpressao(self, animator: EyeAnimator) -> None:
        """O traço que sobra no fundo tem a mesma espessura em qualquer expressão."""

        def fundo(expressao: Expression) -> float:
            face = EyeAnimator(idleAnimations=False, rng=random.Random(42))
            face.setMood(expressao)
            avancar(face, 0.6)
            face.blinkNow()
            return min(f.left.openness for f in coletar(face, 0.5))

        neutro = fundo(Expression.NEUTRAL)
        for expressao in (Expression.HAPPY, Expression.ANGRY, Expression.TIRED):
            assert fundo(expressao) == pytest.approx(neutro, abs=0.02)

    @pytest.mark.parametrize("expressao", [Expression.ANGRY, Expression.TIRED])
    def testAInclinacaoAfrouxaAteFechar(
        self, animator: EyeAnimator, expressao: Expression
    ) -> None:
        """Olho fechado não tem canto caído — senão a piscada vira um corte em diagonal."""
        animator.setMood(expressao)
        repouso = avancar(animator, 0.6).left
        assert abs(repouso.topLidSlant) > 0.5  # a expressão realmente inclina

        animator.blinkNow()
        quadros = coletar(animator, 0.5)
        fundo = min(quadros, key=lambda f: f.left.openness)
        assert abs(fundo.left.topLidSlant) < abs(repouso.topLidSlant) * 0.2


class TestSono:
    def testDormirFechaOsOlhos(self, animator: EyeAnimator) -> None:
        animator.sleep()
        frame = avancar(animator, 1.0)

        assert frame.left.openness < 0.1
        assert frame.expression is Expression.SLEEP

    def testAcordarReabre(self, animator: EyeAnimator) -> None:
        animator.sleep()
        avancar(animator, 1.0)
        animator.wake()
        frame = avancar(animator, 2.0)

        assert not animator.isSleeping
        assert frame.left.openness > 0.8

    def testToggleAlterna(self, animator: EyeAnimator) -> None:
        animator.toggleSleep()
        assert animator.isSleeping
        animator.toggleSleep()
        assert not animator.isSleeping

    def testDormirCentralizaOOlhar(self, animator: EyeAnimator) -> None:
        animator.sleep()
        frame = avancar(animator, 1.0)
        assert abs(frame.left.offsetX) < 20

    def testDormindoNaoPisca(self, animator: EyeAnimator) -> None:
        """Pálpebra descendo sobre um olho já fechado não lê como piscar, lê como defeito."""
        animator.sleep()
        avancar(animator, 1.0)

        repouso = animator.update(PASSO).left.openness
        animator.blinkNow()

        for frame in coletar(animator, 0.5):
            assert frame.left.openness == pytest.approx(repouso, abs=0.01)

    def testDormindoNaoPiscaSozinha(self, animator: EyeAnimator) -> None:
        animator.sleep()
        avancar(animator, 1.0)

        repouso = animator.update(PASSO).left.openness
        for frame in coletar(animator, 20.0):  # muito além do intervalo de piscada
            assert frame.left.openness == pytest.approx(repouso, abs=0.01)

    def testPiscadaDobradaNaoSobreviveAoSono(self, animator: EyeAnimator) -> None:
        """A fila de piscadas morre ao dormir, em vez de disparar já com ela dormindo."""
        animator.blinkNow()
        animator.queuedBlinks = 1  # como se o sorteio tivesse pedido a dobrada
        animator.sleep()

        avancar(animator, 1.0)
        repouso = animator.update(PASSO).left.openness
        for frame in coletar(animator, 2.0):
            assert frame.left.openness == pytest.approx(repouso, abs=0.01)


class TestAtividades:
    def testPensarOlhaParaCima(self, animator: EyeAnimator) -> None:
        animator.setActivity(Expression.THINKING)
        frame = avancar(animator, 1.0)

        assert frame.left.offsetY < -40
        assert frame.expression is Expression.THINKING

    def testPensarComecaComAntecipacao(self, animator: EyeAnimator) -> None:
        """O olhar dá uma caída antes de subir — princípio de antecipação."""
        animator.setActivity(Expression.THINKING)
        alturas = [f.left.offsetY for f in coletar(animator, 0.2)]
        assert max(alturas) > 5, "faltou a caída inicial"

    def testPensarDeixaOsOlhosDiferentes(self, animator: EyeAnimator) -> None:
        """A assimetria é o que transforma a forma em intenção."""
        animator.setActivity(Expression.THINKING)
        frame = avancar(animator, 1.0)
        assert abs(frame.left.topLid - frame.right.topLid) > 0.05

    def testPensarMoveOOlharDeUmLadoAOutro(self, animator: EyeAnimator) -> None:
        animator.setActivity(Expression.THINKING)
        posicoes = [f.left.offsetX for f in coletar(animator, 5.0)]
        assert max(posicoes) > 50 and min(posicoes) < -50

    def testFalarFazOsOlhosPulsarem(self, animator: EyeAnimator) -> None:
        animator.setActivity(Expression.SPEAKING)
        alturas = [f.left.height for f in coletar(animator, 2.0)]
        assert max(alturas) - min(alturas) > 0.03

    def testPulsoDaFalaEDiscreto(self, animator: EyeAnimator) -> None:
        """Acima de ~15% de variação a face treme em vez de respirar."""
        animator.setActivity(Expression.SPEAKING)
        alturas = [f.left.height for f in coletar(animator, 3.0)]
        assert max(alturas) - min(alturas) < 0.20

    def testFalarEsticaEAchata(self, animator: EyeAnimator) -> None:
        """Quando o olho achata, ele alarga: squash and stretch."""
        animator.setActivity(Expression.SPEAKING)
        quadros = coletar(animator, 2.0)[30:]  # ignora o "pop" de entrada

        maisAlto = max(quadros, key=lambda f: f.left.height)
        maisBaixo = min(quadros, key=lambda f: f.left.height)

        assert maisAlto.left.width < maisBaixo.left.width

    def testOOlhoSegueAAmplitudeDoAudio(self, animator: EyeAnimator) -> None:
        """Falar alto abre mais o olho do que falar baixo.

        E a diferenca entre uma face que se move *enquanto* fala e uma que se
        move *junto com* a fala: sem isso o pulso e sempre o mesmo, tanto numa
        palavra longa quanto numa pausa.
        """
        animator.setActivity(Expression.SPEAKING)

        animator.setSpeechLevel(0.05)
        baixo = [f.left.height for f in coletar(animator, 1.0)][-10:]

        animator.setSpeechLevel(1.0)
        alto = [f.left.height for f in coletar(animator, 1.0)][-10:]

        assert max(alto) > max(baixo)

    def testSilencioNoMeioDaFalaParaOOlho(self, animator: EyeAnimator) -> None:
        """Numa pausa entre frases o olho descansa, em vez de seguir pulsando."""
        animator.setActivity(Expression.SPEAKING)
        animator.setSpeechLevel(0.0)
        coletar(animator, 1.0)  # deixa o suavizador assentar

        alturas = [f.left.height for f in coletar(animator, 1.0)]
        assert max(alturas) - min(alturas) < 0.01

    def testSemMedicaoOOlhoVoltaAPulsarSozinho(self, animator: EyeAnimator) -> None:
        """Um motor que nao produz PCM nao pode deixar a face imovel.

        `None` (ninguem esta medindo) tem de ser tratado diferente de `0.0`
        (esta em silencio) — senao a face congela ao falar por um caminho de
        audio que nao informa amplitude.
        """
        animator.setActivity(Expression.SPEAKING)
        animator.setSpeechLevel(None)

        alturas = [f.left.height for f in coletar(animator, 2.0)]
        assert max(alturas) - min(alturas) > 0.03

    def testAtividadeTemPrioridadeSobreOHumor(self, animator: EyeAnimator) -> None:
        animator.setMood(Expression.HAPPY)
        animator.setActivity(Expression.SPEAKING)
        assert animator.currentExpression is Expression.SPEAKING

    def testHumorVoltaAoFimDaAtividade(self, animator: EyeAnimator) -> None:
        animator.setMood(Expression.HAPPY)
        animator.setActivity(Expression.SPEAKING)
        animator.setActivity(None)
        assert animator.currentExpression is Expression.HAPPY

    def testAtividadeAcorda(self, animator: EyeAnimator) -> None:
        animator.sleep()
        animator.setActivity(Expression.THINKING)
        assert not animator.isSleeping

    def testAtividadeInvalidaERejeitada(self, animator: EyeAnimator) -> None:
        with pytest.raises(ValueError, match="atividade"):
            animator.setActivity(Expression.HAPPY)


class TestHumores:
    def testRisoViraAlegria(self, animator: EyeAnimator) -> None:
        animator.setMood(Expression.LAUGH)
        avancar(animator, 2.5)
        assert animator.currentExpression is Expression.HAPPY

    def testTonturaVoltaAoNeutro(self, animator: EyeAnimator) -> None:
        animator.setMood(Expression.DIZZY)
        avancar(animator, 3.2)
        assert animator.currentExpression is Expression.NEUTRAL

    def testRisoSacodeNaVertical(self, animator: EyeAnimator) -> None:
        animator.setMood(Expression.LAUGH)
        alturas = [f.left.offsetY for f in coletar(animator, 1.0)]
        assert max(alturas) - min(alturas) > 20

    def testTonturaSacodeOsOlhosForaDeFase(self, animator: EyeAnimator) -> None:
        animator.setMood(Expression.DIZZY)
        quadros = coletar(animator, 1.0)
        assert any(abs(f.left.offsetX - f.right.offsetX) > 8 for f in quadros)

    def testExpressoesDeAtividadeNaoViramHumor(self, animator: EyeAnimator) -> None:
        animator.setMood(Expression.THINKING)
        assert animator.currentExpression is Expression.NEUTRAL

    def testTrocaDeHumorEGradual(self, animator: EyeAnimator) -> None:
        """O defeito antigo: expressão mudava de um quadro para o outro."""
        avancar(animator, 0.5)
        animator.setMood(Expression.ANGRY)
        quadros = coletar(animator, 0.6)

        saltos = [abs(b.left.topLid - a.left.topLid) for a, b in pairwise(quadros)]
        assert max(saltos) < 0.05, "a pálpebra deveria descer aos poucos"
        assert quadros[-1].left.topLid > 0.2, "e chegar ao destino"


class TestVida:
    def testOOlharNuncaFicaCompletamenteParado(self, animator: EyeAnimator) -> None:
        """Microssacadas: olho de verdade treme mesmo fixando um ponto."""
        posicoes = {round(f.left.offsetX, 3) for f in coletar(animator, 6.0)}
        assert len(posicoes) > 12

    def testAAlturaNuncaFicaTravada(self, animator: EyeAnimator) -> None:
        """Respiração: a altura oscila de leve o tempo todo, mesmo em repouso."""
        alturas = [f.left.openness for f in coletar(animator, 6.0)]
        assert len({round(h, 4) for h in alturas}) > 50

    def testAAlturaEmRepousoFicaPertoDoNatural(self, animator: EyeAnimator) -> None:
        """Respiração e curiosidade somadas não podem inchar o olho."""
        emRepouso = [h for h in (f.left.openness for f in coletar(animator, 8.0)) if h > 0.85]
        assert max(emRepouso) < 1.25

    def testOOlhoDireitoAtrasaEmRelacaoAoEsquerdo(self, animator: EyeAnimator) -> None:
        quadros = coletar(animator, 8.0)
        assert any(abs(f.left.offsetX - f.right.offsetX) > 5 for f in quadros)

    def testPiscaSozinhaDeTemposEmTempos(self, animator: EyeAnimator) -> None:
        alturas = [f.left.openness for f in coletar(animator, 20.0)]
        assert min(alturas) < 0.2

    def testTrocaDeHumorSozinhaQuandoOciosa(self) -> None:
        animator = EyeAnimator(idleAnimations=True, rng=random.Random(1))
        vistos = {animator.update(PASSO).expression for _ in range(60 * 90)}
        assert len(vistos) > 1

    def testNaoTrocaDeHumorComAsAnimacoesDesligadas(self, animator: EyeAnimator) -> None:
        vistos = {animator.update(PASSO).expression for _ in range(60 * 60)}
        assert vistos == {Expression.NEUTRAL}


class TestEstabilidade:
    def testDtGrandeNaoTeleporta(self, animator: EyeAnimator) -> None:
        frame = animator.update(5.0)
        assert 0.0 <= frame.left.height <= 2.0

    def testParametrosFicamEmFaixasSensatas(self, animator: EyeAnimator) -> None:
        animator.setActivity(Expression.SPEAKING)
        for frame in coletar(animator, 10.0):
            for shape in (frame.left, frame.right):
                assert 0.0 <= shape.height <= 1.6
                assert 0.5 <= shape.width <= 1.6
                assert 0.0 <= shape.topLid <= 1.0
                assert 0.0 <= shape.bottomLid <= 1.0
                assert abs(shape.offsetX) < 600
                assert abs(shape.offsetY) < 300

    def testSequenciaLongaDeComandosNaoQuebra(self, animator: EyeAnimator) -> None:
        rng = random.Random(99)
        acoes = [
            lambda: animator.setMood(rng.choice([e for e in Expression if e.isMood])),
            lambda: animator.setActivity(
                rng.choice([Expression.THINKING, Expression.SPEAKING, None])
            ),
            animator.blinkNow,
            animator.toggleSleep,
        ]
        for _ in range(300):
            rng.choice(acoes)()
            for _ in range(6):
                animator.update(PASSO)


class TestLayout:
    def testEscalaProporcional(self) -> None:
        layout = EyeLayout.forScreen(2560, 1440)
        assert layout.scale == pytest.approx(1.0)
        assert layout.eyeWidth == 640

    def testTelaPequenaEncolheTudo(self) -> None:
        layout = EyeLayout.forScreen(800, 480)
        assert layout.eyeWidth < 640

    def testOlhosFicamDentroDaTela(self) -> None:
        layout = EyeLayout.forScreen(1280, 720)
        assert 0 < layout.leftEyeX < layout.rightEyeX < 1280
        assert 0 < layout.eyeCenterY < 720
