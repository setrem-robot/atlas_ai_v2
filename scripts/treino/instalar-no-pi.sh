#!/usr/bin/env bash
#
# Leva o modelo treinado (scripts/treino/treinar.py) para o Ollama do Pi.
#
# A conversão é feita no Ollama do PC, não no Pi: importar os safetensors de
# 2 GB e quantizar estoura a memória do Pi (o `ollama create` lá morreu no
# meio). No PC, o Ollama importa `atlas-1b/` e quantiza em q4_K_M, o formato do
# gemma3:1b de hoje (mesmo tamanho na RAM, mesma velocidade). O GGUF que sai é
# um blob do Ollama do PC; ele vai por scp para o Pi, que só o registra.
#
# Uso (Git Bash ou WSL, na pasta onde está `atlas-1b/`, com `ollama` no PATH):
#   instalar-no-pi.sh                         # atlas@atlas.local, nome atlas-1b
#   instalar-no-pi.sh atlas@atlas.local atlas-1b-teste
#
# O modelo fica também no Ollama do PC, com o mesmo nome, para comparar rápido:
#   python scripts/treino/avaliar.py --modelo atlas-1b --curto
#
# Depois de comparar no Pi, no .env:
#   ROBOTEYE_LLM_MODEL=atlas-1b
#   ROBOTEYE_LLM_PROMPT_CURTO=true

set -euo pipefail

DESTINO="${1:-atlas@atlas.local}"
NOME="${2:-atlas-1b}"
TEMPLATE_DE="${TEMPLATE_DE:-gemma3:1b}"
[[ -f atlas-1b/config.json ]] || { echo "[erro] não achei atlas-1b/; rode treinar.py antes" >&2; exit 1; }

# Template e parâmetros do modelo base (TEMPLATE_DE: gemma3:1b ou qwen2.5:1.5b,
# o ATLAS_BASE do treino), que é o formato em que o treino foi feito
# (`comoOOllamaMonta` em treinar.py). Sem o template, o Ollama não sabe montar
# a conversa; sem o stop, o modelo emenda a próxima pergunta.
modelfile() {
    echo "FROM $1"
    ollama show "${TEMPLATE_DE}" --modelfile | awk '
        /^TEMPLATE/ { dentro = 1 }
        dentro { print; if (/"""$/ && !/^TEMPLATE """$/) dentro = 0; next }
        /^PARAMETER (stop|top_k|top_p)/ { print }
    '
}

echo "importando e quantizando no Ollama do PC..."
modelfile ./atlas-1b > Modelfile.pc
grep -q '^TEMPLATE' Modelfile.pc || { echo "[erro] sem o ${TEMPLATE_DE} no Ollama do PC para copiar o template" >&2; exit 1; }
ollama create "${NOME}" -f Modelfile.pc --quantize q4_K_M

BLOB="$(ollama show "${NOME}" --modelfile | awk '/^FROM / { print $2; exit }')"
command -v cygpath >/dev/null && BLOB="$(cygpath -u "${BLOB}")"
[[ -f "${BLOB}" ]] || { echo "[erro] não achei o GGUF em ${BLOB}" >&2; exit 1; }

echo "copiando $(du -h "${BLOB}" | cut -f1) para ${DESTINO}..."
modelfile "/home/${DESTINO%@*}/${NOME}-q4.gguf" > Modelfile.pi
scp -q "${BLOB}" "${DESTINO}:${NOME}-q4.gguf"
scp -q Modelfile.pi "${DESTINO}:Modelfile.${NOME}"

ssh "${DESTINO}" bash -s -- "${NOME}" <<'EOF'
set -euo pipefail
NOME="$1"
ollama create "${NOME}" -f "Modelfile.${NOME}"
# O Ollama copiou o GGUF para os blobs dele; o original só ocupa o cartão.
rm -f "${NOME}-q4.gguf"
ollama list | grep -E "${NOME}"
EOF
rm -f Modelfile.pc Modelfile.pi
echo "pronto. Compare antes de trocar:"
echo "  ssh ${DESTINO} 'cd atlas_ai_v2 && flock ~/.bench.lock .venv/bin/python scripts/treino/avaliar.py --modelo ${NOME} --curto'"
