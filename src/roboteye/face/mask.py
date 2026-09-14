"""O olho como um campo de distancia.

Antes, o olho era desenhado como um retangulo arredondado e as palpebras eram
*recortadas* dele com um poligono e uma elipse. Isso tinha tres defeitos que
apareciam na tela:

* o corte reto amputava os cantos arredondados e deixava **pontas agudas** —
  era o que fazia o olho bravo parecer uma fatia de queijo;
* o arco do sorriso nao alcancava as quinas e sobrava uma **tira solta** embaixo;
* o antialiasing dependia de desenhar grande e reduzir, o que suaviza pouco
  justamente nas diagonais, que e onde mais se ve serrilhado.

Aqui a forma e descrita como uma funcao: para cada ponto, a distancia com sinal
ate a borda do olho (negativa dentro, positiva fora). Uma expressao e a
combinacao de tres campos — a caixa arredondada, a palpebra superior e a
palpebra inferior — e a combinacao usa uma interseccao *suave*, que arredonda
sozinha toda quina que aparecer. E o que faz as pontas agudas sumirem sem
nenhum caso especial.

Da distancia sai o antialiasing de graca: um pixel a meio caminho da borda fica
com meia opacidade. Nao ha superamostragem nenhuma, e a borda sai limpa em
qualquer tamanho.

O sistema de coordenadas usa a **altura base do olho como unidade**, com a
origem no centro e `y` crescendo para baixo (como na tela). Assim o raio dos
cantos e isotropico: um canto arredondado continua sendo um arco de circulo
mesmo quando o olho esta achatado por uma piscada.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from roboteye.face.shapes import EyeShape

#: Raio do arredondamento aplicado a cada quina onde dois campos se encontram,
#: em unidades de altura do olho. E o parametro que separa "palpebra" de
#: "corte de faca": em 0 voltam as pontas agudas do renderizador antigo.
DEFAULT_FILLET = 0.055

#: Meia-largura da elipse que forma o sorriso, em alturas de olho. Bem maior que
#: o olho de proposito: so a barriga da elipse o atravessa, o que mantem a curva
#: continua em vez de terminar em bico nas quinas.
SMILE_SPREAD = 1.15

#: Quanto a palpebra inferior sobe, por unidade de `bottom_lid`.
SMILE_DEPTH = 0.86

#: Quanto a inclinacao da palpebra superior inclina a reta, por unidade de
#: `top_lid_slant`. E a tangente do angulo: 0,34 da cerca de 19 graus no maximo.
#: Passando disso o olho deixa de parecer uma palpebra baixada e vira uma cunha.
SLANT_STRENGTH = 0.34

#: Curvatura da borda da palpebra superior. Positivo baixa os cantos em relacao
#: ao meio, que e como uma palpebra de verdade se apoia sobre o olho.
LID_CURVE = 0.22


@dataclass(frozen=True, slots=True)
class MaskGeometry:
    """Como amostrar o campo.

    A grade pode ser **maior** que o olho, para caber o halo que transborda das
    bordas, e pode ser **menor** que o olho na tela, quando ha um teto de
    resolucao — nesse caso o resultado e ampliado depois. Por isso o tamanho da
    grade e o tamanho do olho sao medidas separadas.

    Tudo aqui e em pixels da grade. A unidade do campo de distancia e a altura
    do olho, entao `eye_height` e o fator que converte uma da outra.

    `subpixel_x`/`subpixel_y` sao a parte fracionaria da posicao na tela: e o
    que permite o olho deslizar continuamente em vez de andar de pixel em pixel.
    """

    gridWidth: int
    gridHeight: int
    eyeWidth: float
    eyeHeight: float
    subpixelX: float = 0.0
    subpixelY: float = 0.0

    @property
    def halfWidth(self) -> float:
        """Meia-largura da caixa do olho, em alturas de olho."""
        return self.eyeWidth / (2.0 * self.eyeHeight) if self.eyeHeight else 0.5

    @property
    def pixel(self) -> float:
        """Tamanho de um pixel da grade, em alturas de olho."""
        return 1.0 / self.eyeHeight if self.eyeHeight else 1.0


# ---------------------------------------------------------------------------
# Primitivas de campo de distancia
# ---------------------------------------------------------------------------
def roundedBox(
    x: np.ndarray, y: np.ndarray, halfWidth: float, halfHeight: float, radius: float
) -> np.ndarray:
    """Distancia com sinal ate um retangulo de cantos arredondados."""
    radius = min(radius, halfWidth, halfHeight)
    qx = np.abs(x) - halfWidth + radius
    qy = np.abs(y) - halfHeight + radius
    outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
    inside = np.minimum(np.maximum(qx, qy), 0.0)
    return outside + inside - radius


def lidEdge(x: np.ndarray, y: np.ndarray, offset: float, slope: float, curve: float) -> np.ndarray:
    """Distancia ate a borda da palpebra, negativa **abaixo** dela.

    A borda e `y = offset + slope*x + curve*x^2`. O termo quadratico e o que
    separa uma palpebra de uma regua: uma palpebra de verdade acompanha a
    curvatura do olho e desce mais nos cantos que no meio. Uma reta perfeita le
    como corte mecanico — foi o que sobrou de mais artificial na piscada depois
    que ela deixou de ser um esmagamento.

    A divisao pela norma converte a diferenca vertical em distancia
    perpendicular de verdade, sem a qual o arredondamento da quina ficaria mais
    forte nas inclinacoes grandes que nas pequenas.
    """
    edge = offset + slope * x + curve * x * x
    localSlope = slope + 2.0 * curve * x
    return (edge - y) / np.hypot(1.0, localSlope)


def ellipse(
    x: np.ndarray, y: np.ndarray, centerY: float, halfWidth: float, halfHeight: float
) -> np.ndarray:
    """Distancia aproximada ate uma elipse centrada em `(0, center_y)`.

    A aproximacao (escalar para o circulo unitario e reescalar pelo menor
    semieixo) subestima a distancia longe da borda, o que nao importa: perto da
    borda — que e onde o antialiasing e o arredondamento agem — ela e fiel.
    """
    dx = x / halfWidth
    dy = (y - centerY) / halfHeight
    return (np.hypot(dx, dy) - 1.0) * min(halfWidth, halfHeight)


def smoothIntersect(a: np.ndarray, b: np.ndarray, fillet: float) -> np.ndarray:
    """Interseccao de dois campos, com a quina arredondada por `fillet`.

    A interseccao dura seria `maximum(a, b)`, e e ela que produz as pontas
    agudas. Esta versao mistura os dois campos numa faixa de largura `fillet`
    ao redor do encontro, o que deixa no lugar da quina um arco de raio
    aproximadamente `fillet`.
    """
    if fillet <= 0.0:
        return np.maximum(a, b)
    blend = np.clip(0.5 - 0.5 * (b - a) / fillet, 0.0, 1.0)
    return a * blend + b * (1.0 - blend) + fillet * blend * (1.0 - blend)


# ---------------------------------------------------------------------------
# O olho
# ---------------------------------------------------------------------------
def eyeField(
    shape: EyeShape,
    geometry: MaskGeometry,
    *,
    innerIsRight: bool,
    fillet: float = DEFAULT_FILLET,
) -> np.ndarray:
    """Campo de distancia do olho, amostrado na grade de `geometry`.

    Devolve um array `(altura, largura)` em que valores negativos estao dentro
    do olho. A unidade e a altura base do olho.
    """
    gridWidth = max(1, geometry.gridWidth)
    gridHeight = max(1, geometry.gridHeight)
    unit = max(geometry.eyeHeight, 1e-6)

    # A grade e centrada no olho. O deslocamento sub-pixel entra deslocando a
    # *amostragem*, nao a forma: e por isso que ele sobrevive intacto a qualquer
    # redimensionamento posterior.
    xs = np.arange(gridWidth, dtype=np.float32) + 0.5 - gridWidth / 2.0
    ys = np.arange(gridHeight, dtype=np.float32) + 0.5 - gridHeight / 2.0
    xs = (xs - geometry.subpixelX) / unit
    ys = (ys - geometry.subpixelY) / unit

    x = xs[None, :]
    y = ys[:, None]

    # `half_width` estica so o eixo x, o que mantem os cantos circulares mesmo
    # quando o olho esta achatado por uma piscada.
    halfWidth = geometry.halfWidth
    halfHeight = 0.5
    radius = shape.radius * min(2.0 * halfWidth, 1.0)

    field = roundedBox(x, y, halfWidth, halfHeight, radius)

    if shape.topLid > 0.001:
        # A inclinacao positiva precisa baixar o canto voltado para o centro da
        # face; qual dos dois lados e esse depende de qual olho estamos desenhando.
        direction = 1.0 if innerIsRight else -1.0
        slope = shape.topLidSlant * SLANT_STRENGTH * direction
        # A borda e ancorada no centro do olho, entao inclinar nao muda quanto a
        # palpebra cobre em media — so como ela reparte essa cobertura.
        offset = -halfHeight + shape.topLid
        field = smoothIntersect(field, lidEdge(x, y, offset, slope, LID_CURVE), fillet)

    if shape.bottomLid > 0.001:
        # A elipse ocupa a parte de baixo; o olho e o que sobra fora dela.
        depth = shape.bottomLid * SMILE_DEPTH
        occluder = ellipse(x, y, halfHeight, SMILE_SPREAD, depth)
        field = smoothIntersect(field, -occluder, fillet)

    return field


def fieldToAlpha(field: np.ndarray, edge: float) -> np.ndarray:
    """Converte distancia em opacidade, com a borda suavizada em `edge`.

    `edge` e a largura da transicao, na mesma unidade do campo. Um pixel cujo
    centro cai exatamente na borda recebe meia opacidade — que e precisamente o
    que o antialiasing deveria fazer.
    """
    return np.clip(0.5 - field / max(edge, 1e-6), 0.0, 1.0)


#: Quantos desvios-padrao do desfoque cabem na margem reservada ao halo. Abaixo
#: de ~3 o brilho ainda nao chegou a zero na borda da grade, e o corte aparece
#: na tela como um retangulo fantasma em volta do olho.
GLOW_SIGMAS = 3.0


def softGlow(alpha: np.ndarray, sigma: float) -> np.ndarray:
    """Halo externo, por desfoque da cobertura.

    A tentacao e tirar o halo direto do campo de distancia, que ja esta
    calculado — mas o campo mente do lado de fora. Uma interseccao feita com
    `max` e exata *dentro* da forma e apenas um limite inferior fora dela: onde
    uma palpebra cortou a borda, o campo continua achando que ha superficie
    perto, e o brilho vaza para uma regiao onde nao ha olho nenhum. Era isso que
    punha uma mancha retangular abaixo do olho sorrindo.

    Desfocar a cobertura nao tem esse problema: o que nao esta desenhado nao
    brilha.
    """
    kernel = gaussianKernel(sigma)
    if kernel.size <= 1:
        return alpha
    return convolve(convolve(alpha, kernel, axis=0), kernel, axis=1)


def gaussianKernel(sigma: float) -> np.ndarray:
    radius = int(max(0.0, sigma) * 3.0 + 0.5)
    if radius < 1:
        return np.ones(1, dtype=np.float32)
    offsets: np.ndarray = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-0.5 * (offsets / max(sigma, 1e-6)) ** 2)
    return (kernel / kernel.sum()).astype(np.float32)


def convolve(data: np.ndarray, kernel: np.ndarray, *, axis: int) -> np.ndarray:
    """Convolucao 1-D ao longo de um eixo, com zeros fora da borda.

    Zeros na borda sao o que queremos: fora da grade nao ha olho, entao nao ha
    brilho a espalhar para dentro.
    """
    radius = kernel.size // 2
    padding = [(0, 0), (0, 0)]
    padding[axis] = (radius, radius)
    padded = np.pad(data, padding)

    out = np.zeros_like(data)
    for index, weight in enumerate(kernel):
        window = [slice(None), slice(None)]
        window[axis] = slice(index, index + data.shape[axis])
        out += weight * padded[tuple(window)]
    return out
