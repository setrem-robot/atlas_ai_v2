#!/usr/bin/env python3
"""Mede o custo de um quadro da face, sem abrir janela.

A face desenha o tempo todo — respiracao, sacadas, piscada — entao o orcamento
por quadro nao e um detalhe de arranque: e CPU gasta 24 horas por dia. Num
Raspberry Pi isso compete com a sintese de voz, e passar do orcamento nao
aparece como erro, aparece como animacao engasgada.

Este script isola o renderizador (driver dummy do SDL: sem tela, sem placa de
som) e mede so o que o desenho custa, para que uma otimizacao possa ser provada
em vez de suposta. Rodado no proprio Pi, o numero e o numero; rodado numa maquina
de mesa, serve de referencia relativa — um Cortex-A76 fica na casa de 3 a 4 vezes
mais devagar neste tipo de trabalho.

Uso:
    python scripts/bench_face.py                      # padrao: as tres resolucoes
    python scripts/bench_face.py --resolucao 800x480 --qualidade low
    python scripts/bench_face.py --fps 30             # muda o orcamento por quadro
    python scripts/bench_face.py --orcamento 40       # falha se passar de 40% do quadro
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Precisa vir antes de importar o pygame: e o que evita procurar um servidor
# grafico que nao existe (e o que torna a medida comparavel entre maquinas).
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

# Roda direto do repositorio, sem exigir `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pygame

from roboteye.face.animator import EyeAnimator
from roboteye.face.layout import EyeLayout
from roboteye.face.renderer import EyeRenderer, qualityFor
from roboteye.face.theme import Theme

#: Legenda de exemplo. Medir sem ela subestima o quadro tipico, que e justamente
#: o quadro em que o robo esta falando.
CAPTION = "Sou a Atlas, e ainda estou aprendendo a falar sem tropecar."

#: Quadros descartados antes de medir. Os primeiros pagam a criacao das
#: superficies em cache e nao representam o regime permanente.
WARMUP_FRAMES = 30


@dataclass(frozen=True, slots=True)
class Resultado:
    largura: int
    altura: int
    qualidade: str
    medianaMs: float
    p95Ms: float

    def fracao(self, orcamentoMs: float) -> float:
        """Quanto do quadro o desenho consome, em porcentagem, no p95."""
        return 100.0 * self.p95Ms / orcamentoMs


def medir(largura: int, altura: int, qualidade: str, quadros: int) -> Resultado:
    screen = pygame.display.set_mode((largura, altura))
    layout = EyeLayout.for_screen(largura, altura)
    renderer = EyeRenderer(screen, layout, Theme(), quality=qualityFor(qualidade))
    animator = EyeAnimator(idle_animations=True)

    passo = 1.0 / 60.0
    for _ in range(WARMUP_FRAMES):
        renderer.draw(animator.update(passo), caption=CAPTION, hint="ESC sair")

    tempos: list[float] = []
    for indice in range(quadros):
        frame = animator.update(passo)
        # Varre o envelope de fala: e o caminho quente de verdade, porque e o
        # unico momento em que a face muda de forma a cada quadro.
        animator.set_speech_level(abs((indice % 30) / 30.0 - 0.5) * 2.0)

        inicio = time.perf_counter()
        renderer.draw(frame, caption=CAPTION, hint="ESC sair")
        tempos.append((time.perf_counter() - inicio) * 1000.0)

    tempos.sort()
    return Resultado(
        largura=largura,
        altura=altura,
        qualidade=qualidade,
        medianaMs=statistics.median(tempos),
        p95Ms=tempos[min(len(tempos) - 1, int(len(tempos) * 0.95))],
    )


def resolucao(texto: str) -> tuple[int, int]:
    try:
        largura, altura = (int(parte) for parte in texto.lower().split("x", 1))
    except ValueError as exc:
        mensagem = f"resolucao invalida: {texto!r} (use LARGURAxALTURA)"
        raise argparse.ArgumentTypeError(mensagem) from exc
    return largura, altura


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--resolucao",
        type=resolucao,
        action="append",
        dest="resolucoes",
        help="LARGURAxALTURA (repetivel; padrao: 800x480, 1280x720, 1920x1080)",
    )
    parser.add_argument(
        "--qualidade",
        action="append",
        dest="qualidades",
        choices=["auto", "low", "medium", "high"],
        help="nivel de esforco (repetivel; padrao: auto e low)",
    )
    parser.add_argument("--quadros", type=int, default=400, help="quadros medidos por combinacao")
    parser.add_argument("--fps", type=int, default=60, help="taxa alvo; define o orcamento")
    parser.add_argument(
        "--orcamento",
        type=float,
        default=None,
        help="teto em %% do quadro; passando disso o script falha (util em CI)",
    )
    args = parser.parse_args(argv)

    resolucoes = args.resolucoes or [(800, 480), (1280, 720), (1920, 1080)]
    qualidades = args.qualidades or ["auto", "low"]
    orcamentoMs = 1000.0 / max(1, args.fps)

    pygame.init()
    print(f"\nquadro de {orcamentoMs:.1f} ms ({args.fps} FPS) · {args.quadros} quadros por medida")
    print("=" * 64)

    resultados = [
        medir(largura, altura, qualidade, args.quadros)
        for largura, altura in resolucoes
        for qualidade in qualidades
    ]
    pygame.quit()

    for r in resultados:
        tela = f"{r.largura}x{r.altura}"
        print(
            f"{tela:>10}  {r.qualidade:<7}"
            f"mediana {r.medianaMs:6.2f} ms   p95 {r.p95Ms:6.2f} ms"
            f"   {r.fracao(orcamentoMs):5.1f}% do quadro"
        )
    print("=" * 64)

    if args.orcamento is None:
        return 0

    estourados = [r for r in resultados if r.fracao(orcamentoMs) > args.orcamento]
    for r in estourados:
        print(
            f"[falha] {r.largura}x{r.altura} {r.qualidade}: "
            f"{r.fracao(orcamentoMs):.1f}% do quadro, teto {args.orcamento:.1f}%"
        )
    return 1 if estourados else 0


if __name__ == "__main__":
    raise SystemExit(main())
