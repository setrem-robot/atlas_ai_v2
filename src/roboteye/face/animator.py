"""A vida dos olhos.

Este modulo nao importa pygame: e logica pura sobre o tempo decorrido, o que o
torna testavel e independente da taxa de quadros. Cada passo produz um
`EyeFrame` — duas `EyeShape` — que o renderizador transforma em pixels.

Como a face ganha vida, em camadas, da mais lenta para a mais rapida:

1. **Forma de repouso**  — a expressao atual, alcancada por interpolacao. Nunca
   ha troca seca de desenho: bravo vira feliz atravessando os estados do meio.
2. **Respiracao**        — oscilacao lentissima de altura. Quase invisivel, mas
   e o que separa "parado" de "vivo".
3. **Olhar**             — sacadas: saltos rapidos entre pontos de fixacao, com
   pausas longas. Olho de verdade nao desliza, ele salta e espera.
4. **Microssacadas**     — tremores minusculos durante a fixacao. O olho humano
   nunca fica realmente imovel.
5. **Piscada**           — assimetrica: fecha rapido, abre devagar.
6. **Atividade**         — pensar e falar sobrepoem seus proprios movimentos.

O olho direito persegue o esquerdo com um atraso de alguns quadros. E um exagero
minusculo, mas e o que impede a face de parecer duas formas identicas coladas.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from roboteye.face import easing
from roboteye.face.easing import Tween
from roboteye.face.expressions import IDLE_WEIGHTS, Expression
from roboteye.face.layout import LOOK_RANGE
from roboteye.face.shapes import EyeShape, presetFor

# --- transicao de expressao --------------------------------------------------
MORPH_DURATION = 0.38
MORPH_DURATION_FAST = 0.18

# --- piscada -----------------------------------------------------------------
#: A 60 FPS, fechar em 0,085 s dava so cinco quadros e a piscada saia seca.
#: Estes valores ficam na faixa de uma piscada humana e rendem o dobro de
#: quadros, o que se traduz em movimento visivelmente mais macio.
BLINK_CLOSE_DURATION = 0.11
BLINK_OPEN_DURATION = 0.19
#: Tempo com o olho fechado no fundo da piscada.
BLINK_HOLD = 0.045

#: Onde ficam as palpebras no fundo da piscada.
#:
#: A piscada antiga encolhia a *altura* do olho, o que o comprimia na direcao do
#: proprio centro: o olho sumia por igual de cima e de baixo, como se fosse
#: espremido. Ninguem pisca assim. Aqui quem se move e a palpebra de cima, que
#: desce sobre um olho de altura constante — e a de baixo sobe um pouco ao seu
#: encontro, como a palpebra inferior de verdade faz.
#:
#: A soma deixa de proposito uma fresta: no fundo da piscada sobra um traco
#: fino, entao a face nunca apaga por completo.
CLOSED_TOP_LID = 0.82
CLOSED_BOTTOM_LID = 0.16

#: Cobertura somada no fundo da piscada. E ela, e nao cada palpebra em separado,
#: que define o quanto o olho fecha — o que permite repartir a cobertura de
#: outro jeito quando a expressao ja levantou a palpebra de baixo, sem que a
#: fresta final mude de espessura. Veja `close_lids`.
CLOSED_COVERAGE = CLOSED_TOP_LID + CLOSED_BOTTOM_LID

#: O olho incha de leve enquanto a palpebra o comprime. E o velho
#: "esmaga e estica" da animacao classica: sem isso a palpebra parece atravessar
#: o olho em vez de pressiona-lo.
BLINK_BULGE = 0.035

#: Quanto o olhar cai durante a piscada, em unidades base. Piscar de verdade
#: leva o olho junto.
BLINK_DIP = 7.0

BLINK_INTERVAL = (2.8, 7.0)
BLINK_INTERVAL_THINKING = (1.4, 3.0)
#: Chance de a piscada vir dobrada, como acontece de verdade.
DOUBLE_BLINK_CHANCE = 0.18

# --- olhar -------------------------------------------------------------------
SACCADE_DURATION = (0.07, 0.11)
GAZE_HOLD = (1.3, 3.6)
GAZE_HOLD_THINKING = (0.5, 1.1)
#: Quanto o olho direito atrasa em relacao ao esquerdo.
FOLLOW_RATE = 34.0

# --- microssacadas -----------------------------------------------------------
MICRO_INTERVAL = (0.35, 1.3)
MICRO_AMPLITUDE = 9.0
MICRO_DURATION = 0.05

# --- respiracao --------------------------------------------------------------
BREATH_FREQUENCY = 0.19
BREATH_HEIGHT = 0.014
BREATH_DRIFT = 4.0

# --- curiosidade (o olho externo cresce ao olhar para o lado) ----------------
CURIOUS_GAIN = 0.16
CURIOUS_LOSS = 0.06

# --- humor ocioso ------------------------------------------------------------
IDLE_EXPRESSION_INTERVAL = (9.0, 18.0)

# --- falar -------------------------------------------------------------------
#: Frequencias incomensuraveis, na faixa silabica da fala (~2 a 6 Hz): a soma
#: nunca se repete, entao o pulso soa organico em vez de metronomico.
#:
#: Isto e o plano B. Quando ha audio de verdade para medir, o envelope vem dele
#: e o olho se move junto com a voz; estas senoides so entram quando o caminho
#: de audio nao informa amplitude nenhuma — um motor silencioso, por exemplo.
SPEECH_FREQUENCIES = ((2.7, 0.50, 0.0), (4.3, 0.30, 1.3), (6.1, 0.20, 2.7))

#: Com que rapidez o olho segue a voz. Subir depressa e descer devagar e o que
#: da peso ao movimento: o ataque de uma silaba e abrupto, a queda nao.
SPEECH_ATTACK = 26.0
SPEECH_RELEASE = 9.0

#: O envelope medido vive em 0..1; o sintetico, em -1..1. Esta curva leva um ao
#: outro e, de quebra, levanta os trechos baixos: fala normal fica na parte de
#: baixo da escala, e sem isso o olho quase nao se mexeria.
SPEECH_CURVE = 0.6
#: Amplitudes pequenas de proposito. O olho deve parecer respirar junto com a
#: voz, nao tremer: passando de ~6% a face fica nervosa em vez de viva.
SPEECH_HEIGHT = 0.055
SPEECH_WIDTH = 0.028
SPEECH_LIFT = 6.0
SPEECH_ONSET_POP = 1.075
SPEECH_ONSET_DURATION = 0.3

# --- pensar ------------------------------------------------------------------
THINKING_LOOK_UP = -78.0
THINKING_SPREAD = 0.55
#: Antecipacao: antes de olhar para cima, o olhar da uma caida rapida.
THINKING_ANTICIPATION = 26.0
THINKING_ANTICIPATION_DURATION = 0.13

# --- sacudidas ---------------------------------------------------------------
LAUGH_FREQUENCY = 3.4
LAUGH_AMPLITUDE = 34.0
LAUGH_DURATION = 2.0
DIZZY_FREQUENCY = 2.1
DIZZY_AMPLITUDE = 26.0
DIZZY_DURATION = 2.6

# --- dormir ------------------------------------------------------------------
SLEEP_DURATION = 0.55
WAKE_BLINKS = 2


@dataclass(frozen=True, slots=True)
class EyeFrame:
    """O par de olhos num instante, pronto para desenhar."""

    expression: Expression
    left: EyeShape
    right: EyeShape


def closeLids(shape: EyeShape, blink: float) -> EyeShape:
    """Leva as palpebras de onde estao ate a posicao de olho fechado.

    Interpolar ate o alvo, em vez de somar a cobertura, e o que faz a piscada
    funcionar a partir de qualquer expressao: um olho ja semicerrado de raiva
    fecha o resto do caminho, em vez de estourar o limite.

    O alvo, porem, nao pode ser fixo. Com um alvo fixo, piscar a partir de um
    sorriso *baixava* a palpebra inferior — de 0,44 para 0,16 — e o sorriso se
    desmanchava no meio da piscada para se refazer depois. Era o que fazia a
    piscada parecer errada em toda expressao que usa a palpebra de baixo.

    Aqui a palpebra inferior e um piso: ela nunca recua, e a de cima cobre o que
    faltar. Como a soma das duas e sempre a mesma, o traco que sobra no fundo da
    piscada tem a mesma espessura venha ela de onde vier.

    A inclinacao afrouxa junto, pelo mesmo motivo: um olho fechado nao tem canto
    caido. Mantida ate o fim, ela fechava a raiva em diagonal, como um corte.
    """
    bottomTarget = max(CLOSED_BOTTOM_LID, shape.bottomLid)
    topTarget = CLOSED_COVERAGE - bottomTarget

    closed = shape.withLids(
        top=shape.topLid + (topTarget - shape.topLid) * blink,
        bottom=shape.bottomLid + (bottomTarget - shape.bottomLid) * blink,
    )
    return replace(closed, topLidSlant=shape.topLidSlant * (1.0 - blink))


class EyeAnimator:
    """Produz o movimento dos olhos, quadro a quadro."""

    def __init__(self, *, idleAnimations: bool = True, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self.idleAnimations = idleAnimations

        # -- o que ela sente e o que ela faz --------------------------------
        self.mood = Expression.NEUTRAL
        self.activityAtual: Expression | None = None
        self.sleeping = False

        # -- transicao de forma ---------------------------------------------
        self.leftFrom = presetFor(Expression.NEUTRAL)
        self.rightFrom = self.leftFrom
        self.leftTo = self.leftFrom
        self.rightTo = self.leftFrom
        self.morph = Tween(1.0, easing.easeInOutCubic)

        # -- olhar -----------------------------------------------------------
        self.gazeX = Tween(0.0, easing.easeOutCubic)
        self.gazeY = Tween(0.0, easing.easeOutCubic)
        self.microX = Tween(0.0, easing.easeOutQuad)
        self.microY = Tween(0.0, easing.easeOutQuad)
        self.followX = 0.0
        self.followY = 0.0

        # -- piscada ----------------------------------------------------------
        self.blink = Tween(0.0, easing.easeInQuad)
        self.blinkPhase = "open"
        self.holdLeft = 0.0
        self.queuedBlinks = 0

        # -- fala -------------------------------------------------------------
        self.speechPop = Tween(1.0, easing.easeOutBack)
        #: Ultima amplitude medida do audio, ou None se ninguem esta medindo.
        self.speechLevel: float | None = None
        #: A mesma amplitude depois de suavizada, que e a que move o olho.
        self.speechSmoothed = 0.0

        # -- relogios ----------------------------------------------------------
        self.clock = 0.0
        self.moodClock = 0.0
        self.activityClock = 0.0
        self.nextBlink = self.sample(BLINK_INTERVAL)
        self.blinkClock = 0.0
        self.nextGaze = self.sample(GAZE_HOLD)
        self.gazeClock = 0.0
        self.nextMicro = self.sample(MICRO_INTERVAL)
        self.microClock = 0.0
        self.nextMood = self.sample(IDLE_EXPRESSION_INTERVAL)
        self.idleClock = 0.0

    # -----------------------------------------------------------------------
    # Comandos
    # -----------------------------------------------------------------------
    def setMood(self, expression: Expression) -> None:
        """Define o humor de repouso. Expressoes de atividade sao ignoradas."""
        if not expression.isMood or expression == self.mood:
            return
        self.mood = expression
        self.moodClock = 0.0
        self.retarget(MORPH_DURATION)

    def setActivity(self, activity: Expression | None) -> None:
        """Marca que ela esta pensando, falando, ou nenhum dos dois."""
        if activity is not None and not activity.isActivity:
            raise ValueError(f"{activity} nao e uma atividade valida")
        if activity == self.activityAtual:
            return

        previous = self.activityAtual
        self.activityAtual = activity
        self.activityClock = 0.0

        if activity is not None:
            self.sleeping = False

        if activity is Expression.THINKING:
            self.beginThinking()
        elif activity is Expression.SPEAKING:
            self.beginSpeaking()
        elif activity is Expression.LISTENING:
            self.beginListening()
        elif previous is not None:
            # Voltou ao repouso: o olhar desce de volta ao centro.
            self.lookAt(0.0, 0.0, duration=0.22)

        self.retarget(MORPH_DURATION_FAST if activity else MORPH_DURATION)

    def setSpeechLevel(self, level: float | None) -> None:
        """Informa a amplitude do audio que esta tocando, de 0 a 1.

        `None` significa "ninguem esta medindo" — nao "silencio". A diferenca
        importa: em silencio o olho deve ficar parado, mas sem medicao ele deve
        cair no movimento sintetico, senao a face fica imovel enquanto fala num
        motor que nao produz PCM.
        """
        self.speechLevel = None if level is None else min(1.0, max(0.0, level))

    def blinkNow(self) -> None:
        """Forca uma piscada imediata.

        Dormindo, nao ha o que piscar: os olhos ja estao fechados, e a palpebra
        descer sobre um olho fechado nao le como piscar, le como defeito.
        """
        if self.sleeping:
            return
        if self.blinkPhase == "open":
            self.startBlink()

    def sleep(self) -> None:
        if self.sleeping:
            return
        self.sleeping = True
        self.activityAtual = None
        # Uma piscada dobrada sorteada um instante antes de dormir ficaria na
        # fila e dispararia com ela ja dormindo. A fila morre aqui.
        self.queuedBlinks = 0
        self.lookAt(0.0, 0.0, duration=0.4)
        self.retarget(SLEEP_DURATION)

    def wake(self) -> None:
        if not self.sleeping:
            return
        self.sleeping = False
        self.queuedBlinks = WAKE_BLINKS
        self.retarget(MORPH_DURATION)

    def toggleSleep(self) -> None:
        self.wake() if self.sleeping else self.sleep()

    @property
    def isSleeping(self) -> bool:
        return self.sleeping

    @property
    def activity(self) -> Expression | None:
        """A atividade imposta agora (pensar, falar, ouvir), ou None."""
        return self.activityAtual

    @property
    def currentExpression(self) -> Expression:
        if self.sleeping:
            return Expression.SLEEP
        return self.activityAtual or self.mood

    # -----------------------------------------------------------------------
    # Passo de animacao
    # -----------------------------------------------------------------------
    def update(self, dt: float) -> EyeFrame:
        """Avanca a animacao em `dt` segundos e devolve o quadro resultante."""
        dt = max(0.0, min(dt, 0.1))  # uma travada longa nao teleporta a face
        self.clock += dt
        self.moodClock += dt
        self.activityClock += dt

        self.updateMood(dt)
        self.updateGaze(dt)
        self.updateBlink(dt)

        self.morph.update(dt)
        self.speechPop.update(dt)

        left = self.leftFrom.lerp(self.leftTo, self.morph.value)
        right = self.rightFrom.lerp(self.rightTo, self.morph.value)

        left, right = self.applyLife(left, right, dt)

        return EyeFrame(expression=self.currentExpression, left=left, right=right)

    # -----------------------------------------------------------------------
    # Camadas de movimento
    # -----------------------------------------------------------------------
    def applyLife(self, left: EyeShape, right: EyeShape, dt: float) -> tuple[EyeShape, EyeShape]:
        """Sobrepoe a forma de repouso tudo aquilo que se mexe."""
        blink = self.blink.value
        breath = math.sin(2.0 * math.pi * BREATH_FREQUENCY * self.clock)

        height = 1.0
        width = 1.0
        lift = breath * BREATH_DRIFT

        if not self.sleeping:
            height *= 1.0 + breath * BREATH_HEIGHT

        # -- piscar: a palpebra desce, o olho nao encolhe --------------------
        if blink > 0.001:
            left = closeLids(left, blink)
            right = closeLids(right, blink)
            width *= 1.0 + blink * BLINK_BULGE
            lift += blink * BLINK_DIP

        # -- falar: o olho pulsa junto com a voz ------------------------------
        if self.activityAtual is Expression.SPEAKING:
            envelope = self.speechDrive(dt)
            height *= 1.0 + envelope * SPEECH_HEIGHT
            width *= 1.0 - envelope * SPEECH_WIDTH
            lift -= envelope * SPEECH_LIFT

        pop = self.speechPop.value
        height *= pop
        width *= pop

        left = left.scaled(width=width, height=height)
        right = right.scaled(width=width, height=height)

        # -- olhar, com o direito atrasado em relacao ao esquerdo ------------
        gazeX = self.gazeX.value + self.microX.value
        gazeY = self.gazeY.value + self.microY.value
        self.followX = easing.approach(self.followX, gazeX, dt, FOLLOW_RATE)
        self.followY = easing.approach(self.followY, gazeY, dt, FOLLOW_RATE)

        left = left.moved(gazeX, gazeY + lift)
        right = right.moved(self.followX, self.followY + lift)

        # -- curiosidade: o olho do lado para onde ela olha cresce -----------
        left, right = self.applyCuriosity(left, right, gazeX)

        # -- sacudidas passageiras -------------------------------------------
        left, right = self.applyShake(left, right)

        return left, right

    def applyCuriosity(
        self, left: EyeShape, right: EyeShape, gazeX: float
    ) -> tuple[EyeShape, EyeShape]:
        """O olho mais proximo da borda para onde ela olha fica maior.

        Truque emprestado do RoboEyes: sugere interesse, e quebra a simetria que
        faria os dois olhos parecerem um so objeto duplicado.
        """
        amount = min(1.0, abs(gazeX) / LOOK_RANGE)
        if amount < 0.05:
            return left, right

        grow = 1.0 + CURIOUS_GAIN * amount
        shrink = 1.0 - CURIOUS_LOSS * amount

        if gazeX < 0:
            return left.scaled(height=grow), right.scaled(height=shrink)
        return left.scaled(height=shrink), right.scaled(height=grow)

    def applyShake(self, left: EyeShape, right: EyeShape) -> tuple[EyeShape, EyeShape]:
        """Riso sacode na vertical; tontura, na horizontal e fora de fase."""
        if self.activityAtual is not None:
            return left, right

        if self.mood is Expression.LAUGH and self.moodClock < LAUGH_DURATION:
            decay = 1.0 - self.moodClock / LAUGH_DURATION
            offset = math.sin(2.0 * math.pi * LAUGH_FREQUENCY * self.moodClock)
            offset *= LAUGH_AMPLITUDE * decay
            return left.moved(dy=offset), right.moved(dy=offset)

        if self.mood is Expression.DIZZY and self.moodClock < DIZZY_DURATION:
            decay = 1.0 - self.moodClock / DIZZY_DURATION
            phase = 2.0 * math.pi * DIZZY_FREQUENCY * self.moodClock
            amplitude = DIZZY_AMPLITUDE * decay
            return (
                left.moved(dx=math.sin(phase) * amplitude),
                right.moved(dx=math.sin(phase + 2.4) * amplitude),
            )

        return left, right

    def speechDrive(self, dt: float) -> float:
        """O que move o olho enquanto ela fala, de -1 a 1.

        Prefere a amplitude medida do audio; so cai nas senoides quando nao ha
        medicao nenhuma. Nos dois casos o valor passa por um suavizador com
        subida rapida e descida lenta, que e o que impede o olho de tremer a
        cada quadro e o que da peso ao movimento.
        """
        measured = self.speechLevel
        if measured is None:
            return self.syntheticEnvelope(self.activityClock)

        target = measured**SPEECH_CURVE
        rate = SPEECH_ATTACK if target > self.speechSmoothed else SPEECH_RELEASE
        self.speechSmoothed = easing.approach(self.speechSmoothed, target, dt, rate)

        # De 0..1 para -1..1: em silencio o olho descansa um pouco abaixo do
        # repouso, e nos picos sobe acima dele.
        return self.speechSmoothed * 2.0 - 1.0

    def syntheticEnvelope(self, t: float) -> float:
        """Curva de -1 a 1 que imita o ritmo irregular da fala."""
        return sum(
            amplitude * math.sin(2.0 * math.pi * frequency * t + phase)
            for frequency, amplitude, phase in SPEECH_FREQUENCIES
        )

    # -----------------------------------------------------------------------
    # Agendas
    # -----------------------------------------------------------------------
    def updateMood(self, dt: float) -> None:
        """Encerra humores passageiros e sorteia novos quando ela esta ociosa."""
        if self.mood.isTransient:
            limit = LAUGH_DURATION if self.mood is Expression.LAUGH else DIZZY_DURATION
            if self.moodClock >= limit:
                seguinte = (
                    Expression.HAPPY if self.mood is Expression.LAUGH else Expression.NEUTRAL
                )
                self.setMood(seguinte)

        if not self.idleAnimations or self.activityAtual is not None or self.sleeping:
            return

        self.idleClock += dt
        if self.idleClock >= self.nextMood:
            self.idleClock = 0.0
            self.nextMood = self.sample(IDLE_EXPRESSION_INTERVAL)
            self.setMood(self.weightedMood())

    def updateGaze(self, dt: float) -> None:
        self.gazeX.update(dt)
        self.gazeY.update(dt)
        self.microX.update(dt)
        self.microY.update(dt)

        if self.sleeping:
            return

        # Sacada: salta para um novo ponto de fixacao e espera la.
        self.gazeClock += dt
        hold = self.nextGaze
        if self.gazeClock >= hold:
            self.gazeClock = 0.0
            self.nextGaze = self.sample(
                GAZE_HOLD_THINKING if self.activityAtual is Expression.THINKING else GAZE_HOLD
            )
            targetX, targetY = self.nextFixation()
            self.lookAt(targetX, targetY)

        # Microssacada: o olho nunca fica de fato imovel.
        self.microClock += dt
        if self.microClock >= self.nextMicro:
            self.microClock = 0.0
            self.nextMicro = self.sample(MICRO_INTERVAL)
            self.microX.to(self.rng.uniform(-1, 1) * MICRO_AMPLITUDE, MICRO_DURATION)
            self.microY.to(self.rng.uniform(-1, 1) * MICRO_AMPLITUDE * 0.6, MICRO_DURATION)

    def updateBlink(self, dt: float) -> None:
        self.blink.update(dt)

        if self.blinkPhase == "closing" and self.blink.done:
            # Uma pausa curta com o olho fechado, antes de reabrir. Sem ela a
            # palpebra inverte o sentido no mesmo quadro, e o olho percebe isso
            # como um repique.
            self.blinkPhase = "held"
            self.holdLeft = BLINK_HOLD
            return

        if self.blinkPhase == "held":
            self.holdLeft -= dt
            if self.holdLeft <= 0.0:
                self.blinkPhase = "opening"
                # A palpebra parte do repouso, entao a curva precisa arrancar do
                # zero: com uma curva de saida ela sairia na velocidade maxima
                # logo apos a pausa, e isso se ve como um repuxao.
                self.blink.to(0.0, BLINK_OPEN_DURATION, easing.easeInOutCubic)
            return

        if self.blinkPhase == "opening" and self.blink.done:
            self.blinkPhase = "open"
            self.blinkClock = 0.0
            if self.queuedBlinks > 0 and not self.sleeping:
                self.queuedBlinks -= 1
                self.startBlink()
            return

        if self.blinkPhase != "open" or self.sleeping:
            return

        self.blinkClock += dt
        if self.blinkClock >= self.nextBlink:
            self.startBlink()
            if self.rng.random() < DOUBLE_BLINK_CHANCE:
                self.queuedBlinks = 1

    # -----------------------------------------------------------------------
    # Acoes internas
    # -----------------------------------------------------------------------
    def startBlink(self) -> None:
        self.blinkPhase = "closing"
        self.blinkClock = 0.0
        self.nextBlink = self.sample(
            BLINK_INTERVAL_THINKING if self.activityAtual is Expression.THINKING else BLINK_INTERVAL
        )
        self.blink.to(1.0, BLINK_CLOSE_DURATION, easing.easeInQuad)

    def lookAt(self, x: float, y: float, duration: float | None = None) -> None:
        """Move o olhar com o perfil de uma sacada: arranque forte, freada longa."""
        span = duration if duration is not None else self.sample(SACCADE_DURATION)
        self.gazeX.to(x, span, easing.easeOutCubic)
        self.gazeY.to(y, span, easing.easeOutCubic)

    def nextFixation(self) -> tuple[float, float]:
        """Escolhe o proximo ponto para onde olhar."""
        if self.activityAtual is Expression.THINKING:
            # Pensando, o olhar vagueia pela parte de cima do campo de visao.
            side = self.rng.choice((-1.0, 1.0)) * self.rng.uniform(0.3, 1.0)
            return LOOK_RANGE * THINKING_SPREAD * side, THINKING_LOOK_UP

        if self.activityAtual is Expression.SPEAKING:
            # Falando, ela encara quem ouve, com desvios curtos.
            return LOOK_RANGE * self.rng.uniform(-0.22, 0.22), self.rng.uniform(-12.0, 12.0)

        options = (-1.0, -0.5, 0.0, 0.0, 0.5, 1.0)
        return LOOK_RANGE * self.rng.choice(options), self.rng.uniform(-20.0, 20.0)

    def beginThinking(self) -> None:
        """Antecipacao: o olhar cai um instante antes de subir para pensar."""
        self.lookAt(self.gazeX.value, THINKING_ANTICIPATION, THINKING_ANTICIPATION_DURATION)
        self.gazeClock = 0.0
        self.nextGaze = THINKING_ANTICIPATION_DURATION

    def beginListening(self) -> None:
        """Olha para frente e para de vaguear: o robo esta prestando atencao."""
        self.lookAt(0.0, 0.0, 0.16)
        self.gazeClock = 0.0

    def beginSpeaking(self) -> None:
        """Um pequeno salto de escala no instante em que a voz comeca."""
        self.speechPop.snap(SPEECH_ONSET_POP)
        self.speechPop.to(1.0, SPEECH_ONSET_DURATION, easing.easeOutBack)
        self.lookAt(0.0, 0.0, 0.18)
        self.gazeClock = 0.0

    def retarget(self, duration: float) -> None:
        """Comeca a interpolar da forma atual ate a forma da expressao corrente."""
        progress = self.morph.value
        self.leftFrom = self.leftFrom.lerp(self.leftTo, progress)
        self.rightFrom = self.rightFrom.lerp(self.rightTo, progress)
        self.leftTo, self.rightTo = self.targetShapes()
        self.morph.snap(0.0)
        self.morph.to(1.0, duration, easing.easeInOutCubic)

    def targetShapes(self) -> tuple[EyeShape, EyeShape]:
        """Forma de repouso de cada olho na expressao atual.

        A assimetria entre os dois olhos e deliberada: e ela que transforma uma
        forma geometrica em algo com intencao.
        """
        expression = self.currentExpression
        base = presetFor(expression)

        if expression is Expression.THINKING:
            # Um olho mais fechado que o outro: a cara de quem esta matutando.
            # A diferenca e pequena de proposito — exagerar vira caricatura.
            return replace(base, topLid=0.09), replace(base, topLid=0.21)

        if expression is Expression.DIZZY:
            return replace(base, topLid=0.28), replace(base, topLid=0.14, topLidSlant=0.2)

        return base, base

    # -----------------------------------------------------------------------
    # Sorteios
    # -----------------------------------------------------------------------
    def sample(self, interval: tuple[float, float]) -> float:
        return self.rng.uniform(*interval)

    def weightedMood(self) -> Expression:
        candidates = [
            expression
            for expression, weight in IDLE_WEIGHTS.items()
            if expression != self.mood
            for _ in range(weight)
        ]
        return self.rng.choice(candidates) if candidates else Expression.NEUTRAL
