#!/usr/bin/env bash
#
# Diz, em dez segundos, se o microfone está captando a sua voz.
#
# Existe porque "o robô não me ouve" tem duas causas muito diferentes — o
# microfone não capta, ou capta e o reconhecimento não entende — e olhar o log
# do robô não separa as duas. Este script separa: ele mostra a energia segundo a
# segundo enquanto você fala.
#
# Uso:
#   ./scripts/testar-microfone.sh            10 segundos
#   ./scripts/testar-microfone.sh 20         outra duração

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEGUNDOS="${1:-10}"

exec "${REPO_DIR}/.venv/bin/python" - "${SEGUNDOS}" "${REPO_DIR}" <<'PY'
import sys

import numpy as np
import sounddevice as sd

segundos = int(sys.argv[1])
sys.path.insert(0, f"{sys.argv[2]}/src")
from roboteye.hearing.microfone import CORTE_GRAVES_HZ, TAXA, PassaAlta

print()
print(f"  >>> FALE SEM PARAR PELOS PROXIMOS {segundos} SEGUNDOS <<<")
print()
gravado = sd.rec(segundos * TAXA, samplerate=TAXA, channels=1, dtype="float32")
sd.wait()

# O mesmo filtro que o robô usa: sem ele, o zumbido da rede domina a medida e
# tudo parece igual, com ou sem voz.
sinal = gravado[:, 0]
filtro = PassaAlta(CORTE_GRAVES_HZ, TAXA)
limpo = np.concatenate(
    [filtro.aplicar(sinal[i : i + 480]) for i in range(0, (len(sinal) // 480) * 480, 480)]
)
por_segundo = np.sqrt((limpo[: (len(limpo) // TAXA) * TAXA].reshape(-1, TAXA) ** 2).mean(axis=1))

print("  segundo  energia")
for i, valor in enumerate(por_segundo):
    print(f"  {i:5d}s   {valor:.4f}  {'#' * int(valor * 400)}")

pico = float(por_segundo.max())
fundo = float(np.median(por_segundo))
variacao = pico / max(fundo, 1e-9)
print()
print(f"  fundo {fundo:.4f} | pico {pico:.4f} | variacao {variacao:.1f}x")
print()

# A variação é o que importa, não o nível: um microfone mudo com muito ruído dá
# nível alto e variação nenhuma, que é o caso difícil de reconhecer no olho.
if variacao >= 4:
    print("  MICROFONE OK — sua voz se destaca bem do fundo.")
elif variacao >= 2:
    print("  FRACO — capta, mas de longe. Aproxime o microfone ou fale mais alto.")
else:
    print("  NAO ESTA CAPTANDO. Sua voz nao muda nada no que chega. Confira:")
    print("    1. o plugue esta na entrada ROSA do adaptador (a verde e a caixinha)")
    print("    2. o plugue esta encaixado ate o fim (meio encaixado da exatamente isto)")
    print("    3. o microfone nao tem chave de mudo no cabo ou no corpo")
    print("    4. teste o microfone noutro aparelho, para descartar defeito")
PY
