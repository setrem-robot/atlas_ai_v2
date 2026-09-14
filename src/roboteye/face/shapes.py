"""O olho descrito como um punhado de numeros.

Esta e a ideia central da face: um olho nao e um desenho escolhido de um catalogo,
e um conjunto de parametros continuos. Uma expressao e apenas um ponto no espaco
desses parametros, e trocar de expressao e caminhar ate outro ponto.

Isso resolve de graca o que antes era o maior defeito da animacao: nao existe
mais "trocar de desenho", existe interpolar. Bravo vira feliz passando por todos
os estados intermediarios, e a piscada e so a altura indo a quase zero e voltando.

A convencao do inclinamento da palpebra vale para os dois olhos:
`top_lid_slant` positivo baixa o canto *interno* (em direcao ao centro da face,
o que le como bravo) e negativo baixa o canto *externo* (o que le como cansado).
O renderizador resolve qual lado e qual.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from roboteye.face.expressions import Expression

#: Raio padrao dos cantos, como fracao do menor lado do olho.
#: 0.5 seria um circulo perfeito; 0.30 da o quadrado de cantos macios.
DEFAULT_RADIUS = 0.30


@dataclass(frozen=True, slots=True)
class EyeShape:
    """Estado geometrico de um olho num instante."""

    #: Multiplicadores do tamanho base do olho.
    width: float = 1.0
    height: float = 1.0

    #: Raio dos cantos, como fracao do menor lado.
    radius: float = DEFAULT_RADIUS

    #: Deslocamento em unidades base (referencial 2560x1440).
    offsetX: float = 0.0
    offsetY: float = 0.0

    #: Quanto a palpebra superior cobre o olho (0 = nenhuma, 1 = tudo).
    topLid: float = 0.0

    #: Inclinacao da palpebra superior: +1 baixa o canto interno (bravo),
    #: -1 baixa o canto externo (cansado).
    topLidSlant: float = 0.0

    #: Quanto a palpebra inferior sobe, em arco (0 = nenhuma, 1 = tudo).
    #: E o que forma o sorriso dos olhos.
    bottomLid: float = 0.0

    def lerp(self, other: EyeShape, t: float) -> EyeShape:
        """Interpola ate `other`. `t` de 0 (este) a 1 (o outro)."""
        if t <= 0.0:
            return self
        if t >= 1.0:
            return other

        inverse = 1.0 - t
        return EyeShape(
            width=self.width * inverse + other.width * t,
            height=self.height * inverse + other.height * t,
            radius=self.radius * inverse + other.radius * t,
            offsetX=self.offsetX * inverse + other.offsetX * t,
            offsetY=self.offsetY * inverse + other.offsetY * t,
            topLid=self.topLid * inverse + other.topLid * t,
            topLidSlant=self.topLidSlant * inverse + other.topLidSlant * t,
            bottomLid=self.bottomLid * inverse + other.bottomLid * t,
        )

    def scaled(self, *, width: float = 1.0, height: float = 1.0) -> EyeShape:
        """Copia com a largura e a altura multiplicadas."""
        return replace(self, width=self.width * width, height=self.height * height)

    def moved(self, dx: float = 0.0, dy: float = 0.0) -> EyeShape:
        """Copia deslocada em unidades base."""
        return replace(self, offsetX=self.offsetX + dx, offsetY=self.offsetY + dy)

    def withRadius(self, radius: float) -> EyeShape:
        """Copia com outro raio de canto, limitado ao circulo perfeito."""
        return replace(self, radius=min(0.5, max(0.0, radius)))

    def withLids(self, top: float | None = None, bottom: float | None = None) -> EyeShape:
        """Copia com outra cobertura de palpebra, limitada a faixa valida."""
        return replace(
            self,
            topLid=self.topLid if top is None else min(1.0, max(0.0, top)),
            bottomLid=self.bottomLid if bottom is None else min(1.0, max(0.0, bottom)),
        )

    @property
    def isClosed(self) -> bool:
        """Se o olho esta fechado o bastante para nao valer a pena desenhar."""
        return self.height <= 0.02 or self.width <= 0.02

    @property
    def openness(self) -> float:
        """Quanto do olho continua a vista, de 0 (fechado) a 1 (aberto).

        Um olho pode fechar de duas maneiras — encolhendo ou sendo coberto pelas
        palpebras — e quem olha nao distingue as duas. Esta propriedade junta as
        duas numa medida so, que e a que interessa a quem pergunta "o olho esta
        aberto?" sem querer saber como ele fecha.
        """
        exposed = 1.0 - self.topLid - self.bottomLid
        return max(0.0, self.height * exposed)


# ---------------------------------------------------------------------------
# Presets: uma expressao e um ponto no espaco de parametros
# ---------------------------------------------------------------------------
NEUTRAL = EyeShape()

#: Palpebra inferior sobe em arco. O sorriso mora aqui.
HAPPY = EyeShape(bottomLid=0.44, height=0.98)

#: Palpebra superior baixa pelo canto interno.
ANGRY = EyeShape(topLid=0.30, topLidSlant=1.0)

#: Palpebra superior baixa pelo canto externo — o oposto exato de bravo.
TIRED = EyeShape(topLid=0.32, topLidSlant=-1.0)

#: Quase fechado, um traco.
SLEEP = EyeShape(height=0.05, radius=0.5)

#: Levemente estreitado e um tico mais estreito: concentracao.
THINKING = EyeShape(topLid=0.14, width=0.97)

#: Falar parte do neutro; a vida vem da modulacao no animador.
SPEAKING = EyeShape()

#: Ouvindo: olhos bem abertos e atentos. Precisa ser distinguivel do neutro a
#: distancia — e o unico sinal de que o robo entendeu que falaram com ele, e
#: quem esta na frente decide se repete a pergunta olhando para isto.
LISTENING = EyeShape(topLid=0.0, bottomLid=0.0, height=1.12, width=1.06)

#: Rir e um sorriso mais forte, sacudido na vertical pelo animador.
LAUGH = EyeShape(bottomLid=0.62, height=0.94)

#: Tonto: olhos moles, palpebras caidas de forma desigual.
DIZZY = EyeShape(topLid=0.22, topLidSlant=-0.4, height=0.94)


_PRESETS: dict[Expression, EyeShape] = {
    Expression.NEUTRAL: NEUTRAL,
    Expression.HAPPY: HAPPY,
    Expression.ANGRY: ANGRY,
    Expression.TIRED: TIRED,
    Expression.SLEEP: SLEEP,
    Expression.THINKING: THINKING,
    Expression.SPEAKING: SPEAKING,
    Expression.LISTENING: LISTENING,
    Expression.LAUGH: LAUGH,
    Expression.DIZZY: DIZZY,
}


def presetFor(expression: Expression) -> EyeShape:
    """Forma de repouso de uma expressao."""
    return _PRESETS.get(expression, NEUTRAL)
