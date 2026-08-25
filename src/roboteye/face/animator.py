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
from roboteye.face.shapes import EyeShape, preset_for

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


def close_lids(shape: EyeShape, blink: float) -> EyeShape:
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
    bottom_target = max(CLOSED_BOTTOM_LID, shape.bottom_lid)
    top_target = CLOSED_COVERAGE - bottom_target

    closed = shape.with_lids(
        top=shape.top_lid + (top_target - shape.top_lid) * blink,
        bottom=shape.bottom_lid + (bottom_target - shape.bottom_lid) * blink,
    )
    return replace(closed, top_lid_slant=shape.top_lid_slant * (1.0 - blink))


class EyeAnimator:
    """Produz o movimento dos olhos, quadro a quadro."""

    def __init__(self, *, idle_animations: bool = True, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._idle_animations = idle_animations

        # -- o que ela sente e o que ela faz --------------------------------
        self._mood = Expression.NEUTRAL
        self._activity: Expression | None = None
        self._sleeping = False

        # -- transicao de forma ---------------------------------------------
        self._left_from = preset_for(Expression.NEUTRAL)
        self._right_from = self._left_from
        self._left_to = self._left_from
        self._right_to = self._left_from
        self._morph = Tween(1.0, easing.ease_in_out_cubic)

        # -- olhar -----------------------------------------------------------
        self._gaze_x = Tween(0.0, easing.ease_out_cubic)
        self._gaze_y = Tween(0.0, easing.ease_out_cubic)
        self._micro_x = Tween(0.0, easing.ease_out_quad)
        self._micro_y = Tween(0.0, easing.ease_out_quad)
        self._follow_x = 0.0
        self._follow_y = 0.0

        # -- piscada ----------------------------------------------------------
        self._blink = Tween(0.0, easing.ease_in_quad)
        self._blink_phase = "open"
        self._hold_left = 0.0
        self._queued_blinks = 0

        # -- fala -------------------------------------------------------------
        self._speech_pop = Tween(1.0, easing.ease_out_back)
        #: Ultima amplitude medida do audio, ou None se ninguem esta medindo.
        self._speech_level: float | None = None
        #: A mesma amplitude depois de suavizada, que e a que move o olho.
        self._speech_smoothed = 0.0

        # -- relogios ----------------------------------------------------------
        self._clock = 0.0
        self._mood_clock = 0.0
        self._activity_clock = 0.0
        self._next_blink = self._sample(BLINK_INTERVAL)
        self._blink_clock = 0.0
        self._next_gaze = self._sample(GAZE_HOLD)
        self._gaze_clock = 0.0
        self._next_micro = self._sample(MICRO_INTERVAL)
        self._micro_clock = 0.0
        self._next_mood = self._sample(IDLE_EXPRESSION_INTERVAL)
        self._idle_clock = 0.0

    # -----------------------------------------------------------------------
    # Comandos
    # -----------------------------------------------------------------------
    def set_mood(self, expression: Expression) -> None:
        """Define o humor de repouso. Expressoes de atividade sao ignoradas."""
        if not expression.is_mood or expression == self._mood:
            return
        self._mood = expression
        self._mood_clock = 0.0
        self._retarget(MORPH_DURATION)

    def set_activity(self, activity: Expression | None) -> None:
        """Marca que ela esta pensando, falando, ou nenhum dos dois."""
        if activity is not None and not activity.is_activity:
            raise ValueError(f"{activity} nao e uma atividade valida")
        if activity == self._activity:
            return

        previous = self._activity
        self._activity = activity
        self._activity_clock = 0.0

        if activity is not None:
            self._sleeping = False

        if activity is Expression.THINKING:
            self._begin_thinking()
        elif activity is Expression.SPEAKING:
            self._begin_speaking()
        elif activity is Expression.LISTENING:
            self._begin_listening()
        elif previous is not None:
            # Voltou ao repouso: o olhar desce de volta ao centro.
            self._look_at(0.0, 0.0, duration=0.22)

        self._retarget(MORPH_DURATION_FAST if activity else MORPH_DURATION)

    def set_speech_level(self, level: float | None) -> None:
        """Informa a amplitude do audio que esta tocando, de 0 a 1.

        `None` significa "ninguem esta medindo" — nao "silencio". A diferenca
        importa: em silencio o olho deve ficar parado, mas sem medicao ele deve
        cair no movimento sintetico, senao a face fica imovel enquanto fala num
        motor que nao produz PCM.
        """
        self._speech_level = None if level is None else min(1.0, max(0.0, level))

    def blink_now(self) -> None:
        """Forca uma piscada imediata.

        Dormindo, nao ha o que piscar: os olhos ja estao fechados, e a palpebra
        descer sobre um olho fechado nao le como piscar, le como defeito.
        """
        if self._sleeping:
            return
        if self._blink_phase == "open":
            self._start_blink()

    def sleep(self) -> None:
        if self._sleeping:
            return
        self._sleeping = True
        self._activity = None
        # Uma piscada dobrada sorteada um instante antes de dormir ficaria na
        # fila e dispararia com ela ja dormindo. A fila morre aqui.
        self._queued_blinks = 0
        self._look_at(0.0, 0.0, duration=0.4)
        self._retarget(SLEEP_DURATION)

    def wake(self) -> None:
        if not self._sleeping:
            return
        self._sleeping = False
        self._queued_blinks = WAKE_BLINKS
        self._retarget(MORPH_DURATION)

    def toggle_sleep(self) -> None:
        self.wake() if self._sleeping else self.sleep()

    @property
    def is_sleeping(self) -> bool:
        return self._sleeping

    @property
    def activity(self) -> Expression | None:
        """A atividade imposta agora (pensar, falar, ouvir), ou None."""
        return self._activity

    @property
    def current_expression(self) -> Expression:
        if self._sleeping:
            return Expression.SLEEP
        return self._activity or self._mood

    # -----------------------------------------------------------------------
    # Passo de animacao
    # -----------------------------------------------------------------------
    def update(self, dt: float) -> EyeFrame:
        """Avanca a animacao em `dt` segundos e devolve o quadro resultante."""
        dt = max(0.0, min(dt, 0.1))  # uma travada longa nao teleporta a face
        self._clock += dt
        self._mood_clock += dt
        self._activity_clock += dt

        self._update_mood(dt)
        self._update_gaze(dt)
        self._update_blink(dt)

        self._morph.update(dt)
        self._speech_pop.update(dt)

        left = self._left_from.lerp(self._left_to, self._morph.value)
        right = self._right_from.lerp(self._right_to, self._morph.value)

        left, right = self._apply_life(left, right, dt)

        return EyeFrame(expression=self.current_expression, left=left, right=right)

    # -----------------------------------------------------------------------
    # Camadas de movimento
    # -----------------------------------------------------------------------
    def _apply_life(self, left: EyeShape, right: EyeShape, dt: float) -> tuple[EyeShape, EyeShape]:
        """Sobrepoe a forma de repouso tudo aquilo que se mexe."""
        blink = self._blink.value
        breath = math.sin(2.0 * math.pi * BREATH_FREQUENCY * self._clock)

        height = 1.0
        width = 1.0
        lift = breath * BREATH_DRIFT

        if not self._sleeping:
            height *= 1.0 + breath * BREATH_HEIGHT

        # -- piscar: a palpebra desce, o olho nao encolhe --------------------
        if blink > 0.001:
            left = close_lids(left, blink)
            right = close_lids(right, blink)
            width *= 1.0 + blink * BLINK_BULGE
            lift += blink * BLINK_DIP

        # -- falar: o olho pulsa junto com a voz ------------------------------
        if self._activity is Expression.SPEAKING:
            envelope = self._speech_drive(dt)
            height *= 1.0 + envelope * SPEECH_HEIGHT
            width *= 1.0 - envelope * SPEECH_WIDTH
            lift -= envelope * SPEECH_LIFT

        pop = self._speech_pop.value
        height *= pop
        width *= pop

        left = left.scaled(width=width, height=height)
        right = right.scaled(width=width, height=height)

        # -- olhar, com o direito atrasado em relacao ao esquerdo ------------
        gaze_x = self._gaze_x.value + self._micro_x.value
        gaze_y = self._gaze_y.value + self._micro_y.value
        self._follow_x = easing.approach(self._follow_x, gaze_x, dt, FOLLOW_RATE)
        self._follow_y = easing.approach(self._follow_y, gaze_y, dt, FOLLOW_RATE)

        left = left.moved(gaze_x, gaze_y + lift)
        right = right.moved(self._follow_x, self._follow_y + lift)

        # -- curiosidade: o olho do lado para onde ela olha cresce -----------
        left, right = self._apply_curiosity(left, right, gaze_x)

        # -- sacudidas passageiras -------------------------------------------
        left, right = self._apply_shake(left, right)

        return left, right

    def _apply_curiosity(
        self, left: EyeShape, right: EyeShape, gaze_x: float
    ) -> tuple[EyeShape, EyeShape]:
        """O olho mais proximo da borda para onde ela olha fica maior.

        Truque emprestado do RoboEyes: sugere interesse, e quebra a simetria que
        faria os dois olhos parecerem um so objeto duplicado.
        """
        amount = min(1.0, abs(gaze_x) / LOOK_RANGE)
        if amount < 0.05:
            return left, right

        grow = 1.0 + CURIOUS_GAIN * amount
        shrink = 1.0 - CURIOUS_LOSS * amount

        if gaze_x < 0:
            return left.scaled(height=grow), right.scaled(height=shrink)
        return left.scaled(height=shrink), right.scaled(height=grow)

    def _apply_shake(self, left: EyeShape, right: EyeShape) -> tuple[EyeShape, EyeShape]:
        """Riso sacode na vertical; tontura, na horizontal e fora de fase."""
        if self._activity is not None:
            return left, right

        if self._mood is Expression.LAUGH and self._mood_clock < LAUGH_DURATION:
            decay = 1.0 - self._mood_clock / LAUGH_DURATION
            offset = math.sin(2.0 * math.pi * LAUGH_FREQUENCY * self._mood_clock)
            offset *= LAUGH_AMPLITUDE * decay
            return left.moved(dy=offset), right.moved(dy=offset)

        if self._mood is Expression.DIZZY and self._mood_clock < DIZZY_DURATION:
            decay = 1.0 - self._mood_clock / DIZZY_DURATION
            phase = 2.0 * math.pi * DIZZY_FREQUENCY * self._mood_clock
            amplitude = DIZZY_AMPLITUDE * decay
            return (
                left.moved(dx=math.sin(phase) * amplitude),
                right.moved(dx=math.sin(phase + 2.4) * amplitude),
            )

        return left, right

    def _speech_drive(self, dt: float) -> float:
        """O que move o olho enquanto ela fala, de -1 a 1.

        Prefere a amplitude medida do audio; so cai nas senoides quando nao ha
        medicao nenhuma. Nos dois casos o valor passa por um suavizador com
        subida rapida e descida lenta, que e o que impede o olho de tremer a
        cada quadro e o que da peso ao movimento.
        """
        measured = self._speech_level
        if measured is None:
            return self._synthetic_envelope(self._activity_clock)

        target = measured**SPEECH_CURVE
        rate = SPEECH_ATTACK if target > self._speech_smoothed else SPEECH_RELEASE
        self._speech_smoothed = easing.approach(self._speech_smoothed, target, dt, rate)

        # De 0..1 para -1..1: em silencio o olho descansa um pouco abaixo do
        # repouso, e nos picos sobe acima dele.
        return self._speech_smoothed * 2.0 - 1.0

    def _synthetic_envelope(self, t: float) -> float:
        """Curva de -1 a 1 que imita o ritmo irregular da fala."""
        return sum(
            amplitude * math.sin(2.0 * math.pi * frequency * t + phase)
            for frequency, amplitude, phase in SPEECH_FREQUENCIES
        )

    # -----------------------------------------------------------------------
    # Agendas
    # -----------------------------------------------------------------------
    def _update_mood(self, dt: float) -> None:
        """Encerra humores passageiros e sorteia novos quando ela esta ociosa."""
        if self._mood.is_transient:
            limit = LAUGH_DURATION if self._mood is Expression.LAUGH else DIZZY_DURATION
            if self._mood_clock >= limit:
                seguinte = (
                    Expression.HAPPY if self._mood is Expression.LAUGH else Expression.NEUTRAL
                )
                self.set_mood(seguinte)

        if not self._idle_animations or self._activity is not None or self._sleeping:
            return

        self._idle_clock += dt
        if self._idle_clock >= self._next_mood:
            self._idle_clock = 0.0
            self._next_mood = self._sample(IDLE_EXPRESSION_INTERVAL)
            self.set_mood(self._weighted_mood())

    def _update_gaze(self, dt: float) -> None:
        self._gaze_x.update(dt)
        self._gaze_y.update(dt)
        self._micro_x.update(dt)
        self._micro_y.update(dt)

        if self._sleeping:
            return

        # Sacada: salta para um novo ponto de fixacao e espera la.
        self._gaze_clock += dt
        hold = self._next_gaze
        if self._gaze_clock >= hold:
            self._gaze_clock = 0.0
            self._next_gaze = self._sample(
                GAZE_HOLD_THINKING if self._activity is Expression.THINKING else GAZE_HOLD
            )
            target_x, target_y = self._next_fixation()
            self._look_at(target_x, target_y)

        # Microssacada: o olho nunca fica de fato imovel.
        self._micro_clock += dt
        if self._micro_clock >= self._next_micro:
            self._micro_clock = 0.0
            self._next_micro = self._sample(MICRO_INTERVAL)
            self._micro_x.to(self._rng.uniform(-1, 1) * MICRO_AMPLITUDE, MICRO_DURATION)
            self._micro_y.to(self._rng.uniform(-1, 1) * MICRO_AMPLITUDE * 0.6, MICRO_DURATION)

    def _update_blink(self, dt: float) -> None:
        self._blink.update(dt)

        if self._blink_phase == "closing" and self._blink.done:
            # Uma pausa curta com o olho fechado, antes de reabrir. Sem ela a
            # palpebra inverte o sentido no mesmo quadro, e o olho percebe isso
            # como um repique.
            self._blink_phase = "held"
            self._hold_left = BLINK_HOLD
            return

        if self._blink_phase == "held":
            self._hold_left -= dt
            if self._hold_left <= 0.0:
                self._blink_phase = "opening"
                # A palpebra parte do repouso, entao a curva precisa arrancar do
                # zero: com uma curva de saida ela sairia na velocidade maxima
                # logo apos a pausa, e isso se ve como um repuxao.
                self._blink.to(0.0, BLINK_OPEN_DURATION, easing.ease_in_out_cubic)
            return

        if self._blink_phase == "opening" and self._blink.done:
            self._blink_phase = "open"
            self._blink_clock = 0.0
            if self._queued_blinks > 0 and not self._sleeping:
                self._queued_blinks -= 1
                self._start_blink()
            return

        if self._blink_phase != "open" or self._sleeping:
            return

        self._blink_clock += dt
        if self._blink_clock >= self._next_blink:
            self._start_blink()
            if self._rng.random() < DOUBLE_BLINK_CHANCE:
                self._queued_blinks = 1

    # -----------------------------------------------------------------------
    # Acoes internas
    # -----------------------------------------------------------------------
    def _start_blink(self) -> None:
        self._blink_phase = "closing"
        self._blink_clock = 0.0
        self._next_blink = self._sample(
            BLINK_INTERVAL_THINKING if self._activity is Expression.THINKING else BLINK_INTERVAL
        )
        self._blink.to(1.0, BLINK_CLOSE_DURATION, easing.ease_in_quad)

    def _look_at(self, x: float, y: float, duration: float | None = None) -> None:
        """Move o olhar com o perfil de uma sacada: arranque forte, freada longa."""
        span = duration if duration is not None else self._sample(SACCADE_DURATION)
        self._gaze_x.to(x, span, easing.ease_out_cubic)
        self._gaze_y.to(y, span, easing.ease_out_cubic)

    def _next_fixation(self) -> tuple[float, float]:
        """Escolhe o proximo ponto para onde olhar."""
        if self._activity is Expression.THINKING:
            # Pensando, o olhar vagueia pela parte de cima do campo de visao.
            side = self._rng.choice((-1.0, 1.0)) * self._rng.uniform(0.3, 1.0)
            return LOOK_RANGE * THINKING_SPREAD * side, THINKING_LOOK_UP

        if self._activity is Expression.SPEAKING:
            # Falando, ela encara quem ouve, com desvios curtos.
            return LOOK_RANGE * self._rng.uniform(-0.22, 0.22), self._rng.uniform(-12.0, 12.0)

        options = (-1.0, -0.5, 0.0, 0.0, 0.5, 1.0)
        return LOOK_RANGE * self._rng.choice(options), self._rng.uniform(-20.0, 20.0)

    def _begin_thinking(self) -> None:
        """Antecipacao: o olhar cai um instante antes de subir para pensar."""
        self._look_at(self._gaze_x.value, THINKING_ANTICIPATION, THINKING_ANTICIPATION_DURATION)
        self._gaze_clock = 0.0
        self._next_gaze = THINKING_ANTICIPATION_DURATION

    def _begin_listening(self) -> None:
        """Olha para frente e para de vaguear: o robo esta prestando atencao."""
        self._look_at(0.0, 0.0, 0.16)
        self._gaze_clock = 0.0

    def _begin_speaking(self) -> None:
        """Um pequeno salto de escala no instante em que a voz comeca."""
        self._speech_pop.snap(SPEECH_ONSET_POP)
        self._speech_pop.to(1.0, SPEECH_ONSET_DURATION, easing.ease_out_back)
        self._look_at(0.0, 0.0, 0.18)
        self._gaze_clock = 0.0

    def _retarget(self, duration: float) -> None:
        """Comeca a interpolar da forma atual ate a forma da expressao corrente."""
        progress = self._morph.value
        self._left_from = self._left_from.lerp(self._left_to, progress)
        self._right_from = self._right_from.lerp(self._right_to, progress)
        self._left_to, self._right_to = self._target_shapes()
        self._morph.snap(0.0)
        self._morph.to(1.0, duration, easing.ease_in_out_cubic)

    def _target_shapes(self) -> tuple[EyeShape, EyeShape]:
        """Forma de repouso de cada olho na expressao atual.

        A assimetria entre os dois olhos e deliberada: e ela que transforma uma
        forma geometrica em algo com intencao.
        """
        expression = self.current_expression
        base = preset_for(expression)

        if expression is Expression.THINKING:
            # Um olho mais fechado que o outro: a cara de quem esta matutando.
            # A diferenca e pequena de proposito — exagerar vira caricatura.
            return replace(base, top_lid=0.09), replace(base, top_lid=0.21)

        if expression is Expression.DIZZY:
            return replace(base, top_lid=0.28), replace(base, top_lid=0.14, top_lid_slant=0.2)

        return base, base

    # -----------------------------------------------------------------------
    # Sorteios
    # -----------------------------------------------------------------------
    def _sample(self, interval: tuple[float, float]) -> float:
        return self._rng.uniform(*interval)

    def _weighted_mood(self) -> Expression:
        candidates = [
            expression
            for expression, weight in IDLE_WEIGHTS.items()
            if expression != self._mood
            for _ in range(weight)
        ]
        return self._rng.choice(candidates) if candidates else Expression.NEUTRAL
