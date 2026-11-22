#!/usr/bin/env bash
#
# Leva o modelo treinado (scripts/treino/treinar.py) para o Ollama do Pi.
#
# Copia o GGUF em F16 e quantiza lá em q4_K_M, o formato do gemma3:1b de hoje:
# mesmo tamanho na RAM e mesma velocidade, com a persona dentro dos pesos.
# O template de conversa é copiado do gemma3:1b instalado no Pi, para o modelo
# treinado receber o prompt exatamente como foi treinado.
#
# Uso (no PC, da raiz do repositório):
#   scripts/treino/instalar-no-pi.sh                 atlas@atlas.local
#   scripts/treino/instalar-no-pi.sh outro@host
#
# Depois, no Pi, no .env:
#   ROBOTEYE_LLM_MODEL=atlas-1b
#   ROBOTEYE_LLM_PROMPT_CURTO=true

set -euo pipefail

DESTINO="${1:-atlas@atlas.local}"
GGUF="$(ls atlas-1b-gguf/*.gguf | grep -iv mmproj | head -1)"
[[ -f "${GGUF}" ]] || { echo "[erro] rode scripts/treino/treinar.py antes" >&2; exit 1; }

echo "copiando ${GGUF} para ${DESTINO}..."
scp "${GGUF}" "${DESTINO}:/tmp/atlas-1b-f16.gguf"

ssh "${DESTINO}" bash -s <<'EOF'
set -euo pipefail
cd /tmp
# O TEMPLATE do gemma3 ocupa várias linhas; pegar o bloco inteiro entre aspas triplas.
ollama show gemma3:1b --modelfile | awk '
    /^FROM / { print "FROM /tmp/atlas-1b-f16.gguf"; next }
    /^TEMPLATE/ { dentro = 1 }
    dentro { print; if (/"""$/ && !/^TEMPLATE """$/) dentro = 0; next }
    /^PARAMETER stop/ { print }
' > Modelfile.atlas
ollama create atlas-1b -f Modelfile.atlas --quantize q4_K_M
rm -f /tmp/atlas-1b-f16.gguf
ollama list | grep -E "atlas-1b|gemma3:1b"
EOF
echo "pronto. Compare antes de trocar:"
echo "  ssh ${DESTINO} 'cd atlas_ai_v2 && .venv/bin/python scripts/treino/avaliar.py --modelo atlas-1b --curto'"
