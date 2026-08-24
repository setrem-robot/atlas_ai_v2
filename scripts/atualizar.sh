#!/usr/bin/env bash
#
# Traz a versão publicada do robô e a coloca no ar — ou desiste e volta atrás.
#
# Roda de dois lugares, os dois pelo systemd (`roboteye-update.service`):
#   - no arranque da máquina, para o robô acordar já na versão publicada;
#   - quando alguém aperta "Atualizar" na página do celular.
#
# Não há timer periódico de propósito: um robô que se reinicia sozinho no meio de
# uma apresentação é pior que um robô desatualizado.
#
# Uso:
#   ./scripts/atualizar.sh                    verifica e aplica, se houver novidade
#   ./scripts/atualizar.sh --forcar           reinstala mesmo sem novidade
#   ./scripts/atualizar.sh --branch outro     de outro branch (padrão: producao)
#   ./scripts/atualizar.sh --agora            não espera a Atlas ficar ociosa

set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_DIR}/.venv"
SERVICO="roboteye"

BRANCH="${ROBOTEYE_UPDATE_BRANCH:-producao}"
FORCAR=false
ESPERAR_OCIOSO=true

#: Quanto esperar a Atlas terminar o que está dizendo antes de desistir da vez.
#: Uma resposta longa com voz de rede leva uns 20 s; o dobro disso é folga.
ESPERA_OCIOSO_S=45
#: Quanto dar ao robô para voltar de pé antes de considerar a atualização ruim.
ESPERA_SAUDE_S=60

log() { echo "[atualizar] $*"; }
fail() { echo "[atualizar] ERRO: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --forcar)  FORCAR=true; shift ;;
        --agora)   ESPERAR_OCIOSO=false; shift ;;
        --branch)  BRANCH="${2:?--branch exige um nome}"; shift 2 ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *)         fail "opção desconhecida: $1 (use --help)" ;;
    esac
done

cd "${REPO_DIR}" || fail "não achei o repositório em ${REPO_DIR}"

# O systemd chama este script como root, porque reiniciar o serviço exige isso.
# Mas `git` e `pip` precisam rodar como o dono do repositório: como root, o git
# recusa a árvore ("dubious ownership") e os arquivos que ele criar ficariam
# inacessíveis para quem cuida do robô no dia a dia.
DONO="$(stat -c %U "${REPO_DIR}")"
como_dono() {
    if [[ "$(id -un)" == "${DONO}" ]]; then
        "$@"
    else
        sudo -u "${DONO}" "$@"
    fi
}

# --- 1. há novidade? --------------------------------------------------------
log "procurando novidade em origin/${BRANCH}"
if ! como_dono git fetch --quiet origin "${BRANCH}" 2>/dev/null; then
    fail "não consegui falar com o GitHub (sem rede?)"
fi

ATUAL="$(como_dono git rev-parse HEAD)"
PUBLICADO="$(como_dono git rev-parse "origin/${BRANCH}")"

# Dois vazios são iguais, e foi assim que a primeira versão deste script
# anunciou "já estamos na versão publicada" sem ter conseguido ler commit nenhum
# — um robô que nunca atualiza, dizendo que está em dia.
if [[ -z "${ATUAL}" || -z "${PUBLICADO}" ]]; then
    fail "não consegui ler os commits (o git falhou; rode com --help e veja o log acima)"
fi

if [[ "${ATUAL}" == "${PUBLICADO}" ]] && [[ "${FORCAR}" == false ]]; then
    log "já estamos na versão publicada ($(como_dono git log -1 --format=%s | cut -c1-60))"
    exit 0
fi

log "versão publicada: $(como_dono git log -1 --format='%h %s' "origin/${BRANCH}" | cut -c1-70)"

# --- 2. a Atlas pode ser interrompida? --------------------------------------
# Quem sabe se ela está no meio de uma frase é o próprio robô, e ele responde
# isso na mesma página que serve ao celular. Perguntar a ele é mais honesto do
# que adivinhar por uso de CPU.
esta_ocupada() {
    local pin porta resposta
    pin="$(grep -sE '^ROBOTEYE_WEB_PIN=' "${REPO_DIR}/.env" | cut -d= -f2- | tr -d '[:space:]')"
    porta="$(grep -sE '^ROBOTEYE_WEB_PORT=' "${REPO_DIR}/.env" | cut -d= -f2- | tr -d '[:space:]')"
    [[ -z "${pin}" ]] && return 1        # sem PIN não dá para perguntar; segue o jogo
    resposta="$(curl -s --max-time 3 -H "X-Pin: ${pin}" \
        "http://127.0.0.1:${porta:-8080}/api/state" 2>/dev/null)" || return 1
    [[ "${resposta}" == *'"ocupado": true'* ]]
}

if [[ "${ESPERAR_OCIOSO}" == true ]]; then
    esperou=0
    while esta_ocupada && (( esperou < ESPERA_OCIOSO_S )); do
        log "a Atlas está no meio de uma resposta; esperando..."
        sleep 3
        esperou=$(( esperou + 3 ))
    done
    if esta_ocupada; then
        log "ela continua ocupada depois de ${ESPERA_OCIOSO_S}s; fica para a próxima vez"
        exit 0
    fi
fi

# --- 3. aplicar -------------------------------------------------------------
# `reset --hard` porque este repositório é um espelho do publicado, não um lugar
# de trabalho: qualquer diferença local aqui é resto de depuração, e mantê-la
# faria a próxima atualização falhar num conflito que ninguém vai ver.
# `.env`, `models/` e `.venv` não são versionados, então nada disso os toca.
aplicar() {
    local alvo="$1"
    como_dono git reset --hard --quiet "${alvo}" || return 1

    # Só reinstala quando as dependências mudaram: `pip install -e` num Pi custa
    # minutos, e a maior parte das atualizações não mexe no pyproject.
    if ! como_dono git diff --quiet "${ATUAL}" "${alvo}" -- pyproject.toml 2>/dev/null; then
        log "as dependências mudaram; reinstalando (isso demora)"
        como_dono "${VENV_DIR}/bin/pip" install --quiet -e "${REPO_DIR}[tts,online]" || return 1
    fi

    systemctl restart "${SERVICO}" || return 1
}

# --- 4. o robô voltou de pé? ------------------------------------------------
# Não basta o systemd dizer "active": o processo sobe, a face pode morrer no
# `set_mode` e o serviço passa a reiniciar em laço. A página respondendo prova
# que o processo passou do arranque e está atendendo.
saudavel() {
    local porta esperou=0
    porta="$(grep -sE '^ROBOTEYE_WEB_PORT=' "${REPO_DIR}/.env" | cut -d= -f2- | tr -d '[:space:]')"
    while (( esperou < ESPERA_SAUDE_S )); do
        sleep 3
        esperou=$(( esperou + 3 ))
        systemctl is-active --quiet "${SERVICO}" || continue
        if curl -s --max-time 3 -o /dev/null "http://127.0.0.1:${porta:-8080}/"; then
            # Um restart em laço também passa por "active" entre as tentativas;
            # duas provas seguidas, com folga, separam isso de um robô de pé.
            sleep 5
            systemctl is-active --quiet "${SERVICO}" && return 0
        fi
    done
    return 1
}

log "aplicando..."
if aplicar "${PUBLICADO}" && saudavel; then
    log "no ar: $(como_dono git log -1 --format='%h %s' | cut -c1-70)"
    exit 0
fi

# --- 5. deu errado: voltar para o que funcionava ----------------------------
log "a versão nova não subiu; voltando para ${ATUAL:0:8}"
if aplicar "${ATUAL}" && saudavel; then
    log "de volta na versão anterior, e de pé"
else
    log "a versão anterior TAMBÉM não subiu — precisa de gente aqui"
    log "veja: journalctl -u ${SERVICO} -n 50"
fi
exit 1
