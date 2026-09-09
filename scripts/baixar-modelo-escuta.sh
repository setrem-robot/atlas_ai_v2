#!/usr/bin/env bash
#
# Baixa o modelo de reconhecimento de fala em português.
#
# É um download separado porque só serve a quem vai plugar um microfone — não
# faz sentido em toda instalação.
#
# Sem argumento baixa o modelo do motor que o projeto usa por padrão (Vosk).
# Baixar o outro é útil para poder trocar sem rede depois — o `.env` escolhe
# qual roda, e trocar com o modelo já no disco é reiniciar o serviço.
#
# Uso:
#   ./scripts/baixar-modelo-escuta.sh              Vosk pequeno, 52 MB (padrão)
#   ./scripts/baixar-modelo-escuta.sh --grande     Vosk grande (1,6 GB)
#   ./scripts/baixar-modelo-escuta.sh --whisper    Whisper "base"
#   ./scripts/baixar-modelo-escuta.sh --tiny       Whisper "tiny", mais rápido
#   ./scripts/baixar-modelo-escuta.sh --ambos      os dois, para trocar sem rede
#   ./scripts/baixar-modelo-escuta.sh --forcar     baixa de novo por cima

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ESCUTA_DIR="${REPO_DIR}/models/escuta"
DESTINO="${ESCUTA_DIR}/vosk-pt"
#: O padrão acompanha `ROBOTEYE_HEARING_BACKEND`, que é `vosk`. Se um dia eles
#: divergirem, quem instalar do zero sobe com o motor certo e o modelo do outro
#: — e o robô falha com "modelo de escuta ausente" só na primeira pergunta.
USAR_VOSK=true
USAR_WHISPER=false
TAMANHO="base"

# O pequeno transcreve mais rápido que o tempo real num Pi 5 e acerta o
# suficiente para perguntas curtas. O grande é melhor, mas num Pi ele leva o
# reconhecimento para além do tempo real — o robô ficaria em silêncio depois de
# cada pergunta, esperando entender.
URL_PEQUENO="https://alphacephei.com/vosk/models/vosk-model-small-pt-0.3.zip"
URL_GRANDE="https://alphacephei.com/vosk/models/vosk-model-pt-fb-v0.1.1-20220516_2113.zip"

URL="${URL_PEQUENO}"
FORCAR=false

log() { echo "    $*"; }
fail() { echo "[erro] $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --vosk)    USAR_VOSK=true; shift ;;
        --grande)  URL="${URL_GRANDE}"; USAR_VOSK=true; shift ;;
        --whisper) USAR_WHISPER=true; USAR_VOSK=false; shift ;;
        --tiny)    USAR_WHISPER=true; USAR_VOSK=false; TAMANHO="tiny"; shift ;;
        --ambos)   USAR_WHISPER=true; USAR_VOSK=true; shift ;;
        --forcar)  FORCAR=true; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *)         fail "opção desconhecida: $1 (use --help)" ;;
    esac
done

# --- Whisper (padrão) -------------------------------------------------------
# O `faster-whisper` baixa o modelo sozinho na primeira transcrição. Fazer isso
# aqui tira o download do caminho da primeira pergunta de alguém — e, num robô
# que talvez esteja sem rede na hora da apresentação, do caminho crítico.
if [[ "${USAR_VOSK}" == false ]]; then
    log "baixando o modelo Whisper '${TAMANHO}' (isso demora na primeira vez)..."
    mkdir -p "${ESCUTA_DIR}"
    "${REPO_DIR}/.venv/bin/python" - "${TAMANHO}" "${ESCUTA_DIR}" <<'PY' || fail "download falhou"
import sys
from faster_whisper import WhisperModel

WhisperModel(sys.argv[1], device="cpu", compute_type="int8", download_root=sys.argv[2])
print("    modelo pronto")
PY
    log "pronto: ${ESCUTA_DIR} ($(du -sh "${ESCUTA_DIR}" | cut -f1))"
    log "ligue a escuta com ROBOTEYE_HEARING_ENABLED=true no .env"
    exit 0
fi

# `final.mdl` fica na raiz nos modelos pequenos e em `am/` nos grandes.
if [[ -f "${DESTINO}/final.mdl" || -f "${DESTINO}/am/final.mdl" ]] && [[ "${FORCAR}" == false ]]; then
    log "modelo já está em ${DESTINO} (use --forcar para baixar de novo)"
    exit 0
fi

command -v unzip >/dev/null || fail "instale o unzip: sudo apt install unzip"

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

log "baixando $(basename "${URL}")..."
curl -fL --progress-bar -o "${TMP}/modelo.zip" "${URL}" || fail "download falhou"

log "descompactando..."
unzip -q -o "${TMP}/modelo.zip" -d "${TMP}" || fail "arquivo corrompido"

# O zip traz uma pasta com o nome da versão; o projeto procura sempre em
# `models/vosk/pt`, para que trocar de modelo não exija editar configuração.
EXTRAIDO="$(find "${TMP}" -maxdepth 1 -type d -name "vosk-model-*" | head -1)"
[[ -z "${EXTRAIDO}" ]] && fail "não achei o modelo dentro do zip"

mkdir -p "$(dirname "${DESTINO}")"
rm -rf "${DESTINO}"
mv "${EXTRAIDO}" "${DESTINO}"

log "pronto: ${DESTINO} ($(du -sh "${DESTINO}" | cut -f1))"
log "ligue a escuta com ROBOTEYE_HEARING_ENABLED=true no .env"
