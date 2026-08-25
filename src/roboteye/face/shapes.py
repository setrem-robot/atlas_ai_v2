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
    offset_x: float = 0.0
    offset_y: float = 0.0

    #: Quanto a palpebra superior cobre o olho (0 = nenhuma, 1 = tudo).
    top_lid: float = 0.0

    #: Inclinacao da palpebra superior: +1 baixa o canto interno (bravo),
    #: -1 baixa o canto externo (cansado).
    top_lid_slant: float = 0.0

    #: Quanto a palpebra inferior sobe, em arco (0 = nenhuma, 1 = tudo).
    #: E o que forma o sorriso dos olhos.
    bottom_lid: float = 0.0

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
            offset_x=self.offset_x * inverse + other.offset_x * t,
            offset_y=self.offset_y * inverse + other.offset_y * t,
            top_lid=self.top_lid * inverse + other.top_lid * t,
            top_lid_slant=self.top_lid_slant * inverse + other.top_lid_slant * t,
            bottom_lid=self.bottom_lid * inverse + other.bottom_lid * t,
        )

    def scaled(self, *, width: float = 1.0, height: float = 1.0) -> EyeShape:
        """Copia com a largura e a altura multiplicadas."""
        return replace(self, width=self.width * width, height=self.height * height)

    def moved(self, dx: float = 0.0, dy: float = 0.0) -> EyeShape:
        """Copia deslocada em unidades base."""
        return replace(self, offset_x=self.offset_x + dx, offset_y=self.offset_y + dy)

    def with_radius(self, radius: float) -> EyeShape:
        """Copia com outro raio de canto, limitado ao circulo perfeito."""
        return replace(self, radius=min(0.5, max(0.0, radius)))

    def with_lids(self, top: float | None = None, bottom: float | None = None) -> EyeShape:
        """Copia com outra cobertura de palpebra, limitada a faixa valida."""
        return replace(
            self,
            top_lid=self.top_lid if top is None else min(1.0, max(0.0, top)),
            bottom_lid=self.bottom_lid if bottom is None else min(1.0, max(0.0, bottom)),
        )

    @property
    def is_closed(self) -> bool:
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
        exposed = 1.0 - self.top_lid - self.bottom_lid
        return max(0.0, self.height * exposed)


# ---------------------------------------------------------------------------
# Presets: uma expressao e um ponto no espaco de parametros
# ---------------------------------------------------------------------------
NEUTRAL = EyeShape()

#: Palpebra inferior sobe em arco. O sorriso mora aqui.
HAPPY = EyeShape(bottom_lid=0.44, height=0.98)

#: Palpebra superior baixa pelo canto interno.
ANGRY = EyeShape(top_lid=0.30, top_lid_slant=1.0)

#: Palpebra superior baixa pelo canto externo — o oposto exato de bravo.
TIRED = EyeShape(top_lid=0.32, top_lid_slant=-1.0)

#: Quase fechado, um traco.
SLEEP = EyeShape(height=0.05, radius=0.5)

#: Levemente estreitado e um tico mais estreito: concentracao.
THINKING = EyeShape(top_lid=0.14, width=0.97)

#: Falar parte do neutro; a vida vem da modulacao no animador.
SPEAKING = EyeShape()

#: Ouvindo: olhos bem abertos e atentos. Precisa ser distinguivel do neutro a
#: distancia — e o unico sinal de que o robo entendeu que falaram com ele, e
#: quem esta na frente decide se repete a pergunta olhando para isto.
LISTENING = EyeShape(top_lid=0.0, bottom_lid=0.0, height=1.12, width=1.06)

#: Rir e um sorriso mais forte, sacudido na vertical pelo animador.
LAUGH = EyeShape(bottom_lid=0.62, height=0.94)

#: Tonto: olhos moles, palpebras caidas de forma desigual.
DIZZY = EyeShape(top_lid=0.22, top_lid_slant=-0.4, height=0.94)


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


def preset_for(expression: Expression) -> EyeShape:
    """Forma de repouso de uma expressao."""
    return _PRESETS.get(expression, NEUTRAL)
