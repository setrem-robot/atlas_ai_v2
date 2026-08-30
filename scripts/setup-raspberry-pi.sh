#!/usr/bin/env bash
#
# Prepara um Raspberry Pi (ou qualquer Debian/Ubuntu) para rodar o RobotEye.
#
# Uso:
#   ./scripts/setup-raspberry-pi.sh                     instalação padrão (pergunta o que falta)
#   ./scripts/setup-raspberry-pi.sh --bluetooth         também configura áudio Bluetooth
#   ./scripts/setup-raspberry-pi.sh --service           também instala o serviço systemd
#   ./scripts/setup-raspberry-pi.sh --branch NOME      branch que o robô segue (padrão: producao)
#   ./scripts/setup-raspberry-pi.sh --escuta           também instala o microfone (STT)
#   ./scripts/setup-raspberry-pi.sh --bluetooth-app    ponte para o app controlar os motores
#   ./scripts/setup-raspberry-pi.sh --voice dora        usa outra voz
#   ./scripts/setup-raspberry-pi.sh --ollama IP:PORTA   endereço da máquina com a IA
#   ./scripts/setup-raspberry-pi.sh --model qwen3:8b    modelo de linguagem
#   ./scripts/setup-raspberry-pi.sh --no-llm            instala sem IA (modo echo)
#   ./scripts/setup-raspberry-pi.sh --yes               não pergunta nada (para automação)
#
# O script é idempotente: rodar de novo apenas atualiza o que faltar.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${REPO_DIR}/.venv"

VOICE=""
MODEL=""
OLLAMA_HOST=""
NO_LLM=false
ASSUME_YES=false
WITH_BLUETOOTH=false
WITH_SERVICE=false
WITH_HEARING=false
WITH_BLE=false
BLE_NOME="Atlas"
#: Branch que o robô segue. Deliberadamente NÃO é o `main`: é o que separa
#: "estou mexendo" de "está no robô".
UPDATE_BRANCH="producao"

# --- aparência --------------------------------------------------------------
BOLD=$(tput bold 2>/dev/null || true)
RESET=$(tput sgr0 2>/dev/null || true)

step()  { echo; echo "${BOLD}==> $*${RESET}"; }
info()  { echo "    $*"; }
warn()  { echo "    [aviso] $*" >&2; }
fail()  { echo "    [erro] $*" >&2; exit 1; }

# --- argumentos -------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --bluetooth) WITH_BLUETOOTH=true; shift ;;
        --service)   WITH_SERVICE=true; shift ;;
        --escuta)    WITH_HEARING=true; shift ;;
        --bluetooth-app) WITH_BLE=true; shift ;;
        --branch)    UPDATE_BRANCH="${2:?--branch exige um nome}"; shift 2 ;;
        --voice)     VOICE="${2:?--voice exige um nome}"; shift 2 ;;
        --model)     MODEL="${2:?--model exige um nome}"; shift 2 ;;
        --ollama)    OLLAMA_HOST="${2:?--ollama exige um endereço}"; shift 2 ;;
        --no-llm)    NO_LLM=true; shift ;;
        -y|--yes)    ASSUME_YES=true; shift ;;
        -h|--help)   sed -n '2,18p' "$0"; exit 0 ;;
        *)           fail "opção desconhecida: $1 (use --help)" ;;
    esac
done

[[ $EUID -eq 0 ]] && fail "não rode como root; o script chama sudo quando precisa"

echo "${BOLD}"
echo "======================================"
echo "        ROBOT EYE - SETUP"
echo "======================================"
echo "${RESET}"
info "repositório: ${REPO_DIR}"

# --- 1. dependências de sistema ---------------------------------------------
step "[1/4] Instalando dependências do sistema"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    python3-pygame \
    libportaudio2 \
    libasound2-plugins \
    libsdl2-2.0-0 \
    libsdl2-ttf-2.0-0 \
    libegl1 \
    libgles2 \
    libgl1 \
    libopengl0 \
    libglx-mesa0 \
    libgbm1 \
    libdrm2 \
    alsa-utils \
    git

# Três dessas linhas existem por causa da imagem Lite, e cada uma custou uma
# falha para ser descoberta:
#
#   build-essential  o extra `online` puxa o miniaudio, que não publica wheel
#                    para aarch64. Sem compilador, a instalação morre aqui.
#   python3-pygame   a wheel do pygame no PyPI embute um SDL compilado sem
#                    KMSDRM. Ela funciona em qualquer desktop e falha com
#                    "kmsdrm not available" exatamente no Pi sem desktop, que é
#                    o alvo. O pacote do Debian usa o SDL do sistema, que tem.
#   libegl1/libgles2 o KMSDRM desenha por EGL; sem eles o SDL abre a tela e
#                    morre com "EGL not initialized".
#   libgl1/libopengl0  esta foi a mais cara de achar, porque não dá erro
#                    nenhum: sem libGL.so.1 o SDL registra "Could not
#                    initialize OpenGL / GLES library" só no log de depuração,
#                    cria os framebuffers, aceita todo `flip` — e não desenha
#                    nada. O monitor fica preto com o robô rodando e o kernel
#                    jurando que está tudo certo. O sintoma que denuncia é a
#                    taxa de quadros: 2143/s numa tela de 60 Hz é o SDL
#                    "desenhando" para lugar nenhum.
#
# A tela e o teclado do console vêm por estes grupos.
sudo usermod -aG video,render,input,audio "${USER}" || warn "nao foi possivel ajustar os grupos"
info "ok"

# --- 2. ambiente virtual ----------------------------------------------------
step "[2/4] Preparando o ambiente Python"
if [[ ! -d "${VENV_DIR}" ]]; then
    # `--system-site-packages` é o que deixa o venv enxergar o python3-pygame do
    # sistema (ver acima). Sem isso o pip instalaria a wheel do PyPI por cima e
    # a face voltaria a não abrir no Pi.
    python3 -m venv --system-site-packages "${VENV_DIR}"
    info "ambiente virtual criado em ${VENV_DIR}"
else
    info "ambiente virtual já existe"
fi

"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
# `online` traz as vozes da nuvem; `tts` traz a voz local que assume quando a
# rede cai. As duas juntas são o que faz o robô continuar falando de qualquer jeito.
EXTRAS="tts,online"
if [[ "${WITH_HEARING}" == true ]]; then
    EXTRAS="${EXTRAS},stt"
fi
if [[ "${WITH_BLE}" == true ]]; then
    EXTRAS="${EXTRAS},ble"
    # O `bluezero` fala com o BlueZ por D-Bus, e as duas pontas disso vem do
    # sistema: compilar o PyGObject no Pi demora minutos e falha na imagem Lite.
    #
    # O `mosquitto` entra aqui porque é para onde a ponte entrega o que recebe.
    # Sem ele, o app conecta, os comandos chegam ao Pi e morrem sem ninguém do
    # outro lado — sem erro em lugar nenhum. Se o `orquestrador` já estiver
    # instalado nesta máquina, o broker dele é o mesmo e o apt não faz nada.
    sudo apt-get install -y --no-install-recommends python3-dbus python3-gi bluez mosquitto
    sudo systemctl enable --now mosquitto || warn "não consegui subir o broker MQTT"
fi
"${VENV_DIR}/bin/pip" install --quiet -e "${REPO_DIR}[${EXTRAS}]"
info "pacote instalado (extras: ${EXTRAS})"

# --- 3. configuração --------------------------------------------------------
# Quem responde "onde roda a IA, qual modelo, qual voz" é o assistente do
# próprio pacote: ele testa o endereço antes de gravar e lista os modelos que a
# máquina realmente tem. Aqui só repassamos o que veio por flag.
step "[3/4] Configuração"

# `x && y` como comando solto encerraria o script sob `set -e` sempre que a
# condição fosse falsa — daí os `if`.
SETUP_ARGS=()
if [[ -n "${VOICE}" ]];       then SETUP_ARGS+=(--voice "${VOICE}"); fi
if [[ -n "${MODEL}" ]];       then SETUP_ARGS+=(--model "${MODEL}"); fi
if [[ -n "${OLLAMA_HOST}" ]]; then SETUP_ARGS+=(--ollama "${OLLAMA_HOST}"); fi
if [[ "${NO_LLM}" == true ]]; then SETUP_ARGS+=(--no-llm); fi
# Sem terminal — instalação automatizada, `curl | bash`, Ansible — perguntar
# seria esperar por uma resposta que nunca vem.
if [[ "${ASSUME_YES}" == true ]] || [[ ! -t 0 ]]; then
    SETUP_ARGS+=(--non-interactive)
fi

# A expansão longa mantém o array vazio inofensivo sob `set -u`.
"${VENV_DIR}/bin/roboteye" setup ${SETUP_ARGS[@]+"${SETUP_ARGS[@]}"}

# PIN fixo da página de configuração. Sem um gravado aqui, o robô sorteia um a
# cada arranque — e num robô que liga sozinho isso significaria caçar o PIN no
# log toda vez que alguém quisesse mexer nele pelo celular.
if ! grep -q "^ROBOTEYE_WEB_PIN=..*" "${REPO_DIR}/.env"; then
    PIN="$(shuf -i 100000-999999 -n 1)"
    if grep -q "^ROBOTEYE_WEB_PIN=" "${REPO_DIR}/.env"; then
        sed -i "s|^ROBOTEYE_WEB_PIN=.*|ROBOTEYE_WEB_PIN=${PIN}|" "${REPO_DIR}/.env"
    else
        printf 'ROBOTEYE_WEB_PIN=%s\n' "${PIN}" >> "${REPO_DIR}/.env"
    fi
    info "PIN da página de configuração: ${PIN}"
fi

# --- 3.5 audio --------------------------------------------------------------
# O padrão do Raspberry Pi é o HDMI, que só toca se a tela tiver alto-falante; e
# placas USB baratas chegam com o volume em ~30% e o microfone mudo. Sem este
# passo, o robô parece instalado e não fala.
step "Configurando a saída de som"
if sudo "${REPO_DIR}/scripts/configurar-audio.sh"; then
    info "ok"
else
    warn "não consegui configurar o áudio; rode ./scripts/configurar-audio.sh --mostrar"
fi

# --- 3.6 escuta -------------------------------------------------------------
if [[ "${WITH_HEARING}" == true ]]; then
    step "Baixando o modelo de reconhecimento de fala"
    "${REPO_DIR}/scripts/baixar-modelo-escuta.sh" || warn "modelo de escuta não baixado"
    if grep -q "^ROBOTEYE_HEARING_ENABLED=" "${REPO_DIR}/.env"; then
        sed -i "s|^ROBOTEYE_HEARING_ENABLED=.*|ROBOTEYE_HEARING_ENABLED=true|" "${REPO_DIR}/.env"
    else
        printf 'ROBOTEYE_HEARING_ENABLED=true\n' >> "${REPO_DIR}/.env"
    fi
    info "escuta ligada; o robô acorda com a palavra \"atlas\""
fi

# --- 4. extras opcionais ----------------------------------------------------
step "[4/4] Extras"

if [[ "${WITH_BLUETOOTH}" == true ]]; then
    info "configurando áudio Bluetooth..."
    sudo apt-get install -y pulseaudio pulseaudio-module-bluetooth bluez
    sudo systemctl enable bluetooth
    sudo systemctl start bluetooth
    sudo rfkill unblock bluetooth || warn "rfkill falhou (pode não haver rádio Bluetooth)"
    info "Bluetooth pronto. Pareie o alto-falante com: bluetoothctl"
else
    info "Bluetooth não configurado (use --bluetooth se precisar)"
fi

if [[ "${WITH_SERVICE}" == true ]]; then
    SERVICE_FILE=/etc/systemd/system/roboteye.service
    info "instalando serviço systemd..."
    sed -e "s|@USER@|${USER}|g" -e "s|@REPO_DIR@|${REPO_DIR}|g" \
        "${REPO_DIR}/scripts/roboteye.service" | sudo tee "${SERVICE_FILE}" >/dev/null

    # --- atualizador ---------------------------------------------------------
    # Traz a versão publicada no arranque e quando alguém aperta o botão na
    # página do celular. Ver `scripts/atualizar.sh`.
    UPDATE_FILE=/etc/systemd/system/roboteye-update.service
    sed -e "s|@USER@|${USER}|g" -e "s|@REPO_DIR@|${REPO_DIR}|g" \
        -e "s|@BRANCH@|${UPDATE_BRANCH}|g" \
        "${REPO_DIR}/scripts/roboteye-update.service" | sudo tee "${UPDATE_FILE}" >/dev/null

    # O botão da página roda como o usuário do robô, e disparar uma unidade do
    # systemd exige privilégio. A regra abaixo dá exatamente esse comando, e só
    # ele: nada de NOPASSWD geral, que transformaria o botão numa porta aberta
    # para qualquer coisa. `visudo -c` recusa arquivo malformado — sem essa
    # conferência, um erro de digitação aqui quebraria o `sudo` da máquina
    # inteira, inclusive o de quem foi consertar.
    SUDOERS_TMP="$(mktemp)"
    cat > "${SUDOERS_TMP}" <<SUDO
# Deixa a página de configuração do RobotEye disparar a atualização.
${USER} ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-block roboteye-update.service
${USER} ALL=(root) NOPASSWD: /bin/systemctl start --no-block roboteye-update.service
SUDO
    if sudo visudo -c -f "${SUDOERS_TMP}" >/dev/null 2>&1; then
        sudo install -m 0440 -o root -g root "${SUDOERS_TMP}" /etc/sudoers.d/roboteye-update
        info "botão de atualizar liberado na página"
    else
        warn "regra de sudo recusada; o botão de atualizar vai pedir para rodar à mão"
    fi
    rm -f "${SUDOERS_TMP}"

    if [[ "${WITH_BLE}" == true ]]; then
        sed -e "s|@REPO_DIR@|${REPO_DIR}|g" -e "s|@BLE_NOME@|${BLE_NOME}|g" \
            "${REPO_DIR}/scripts/roboteye-ble.service" \
            | sudo tee /etc/systemd/system/roboteye-ble.service >/dev/null
        sudo systemctl enable roboteye-ble.service
        info "ponte bluetooth instalada; o celular procura por \"${BLE_NOME}\""
    fi

    sudo systemctl daemon-reload
    sudo systemctl enable roboteye.service
    sudo systemctl enable roboteye-update.service
    info "serviço instalado. Inicie com: sudo systemctl start roboteye"
    info "o robô passa a buscar a versão publicada de origin/${UPDATE_BRANCH} no arranque"
else
    info "serviço systemd não instalado (use --service para o robô subir no boot)"
fi

# --- verificação final ------------------------------------------------------
step "Verificando a instalação"
"${VENV_DIR}/bin/roboteye" doctor || warn "há pendências no diagnóstico acima"

cat <<EOF

${BOLD}======================================
    Setup concluído!
======================================${RESET}

Para usar:

    source ${VENV_DIR}/bin/activate
    roboteye                    # face + chat
    roboteye run --fullscreen   # tela cheia
    roboteye chat               # sem janela (útil via SSH)

Num Raspberry Pi com a imagem Lite não há desktop, e não precisa haver: a face
encontra o monitor sozinha e desenha direto na tela do kernel (KMS/DRM).

Para trocar de IA, modelo ou voz depois:

    roboteye setup              # o mesmo assistente, de novo
    roboteye models             # o que a máquina da IA tem instalado

Se o diagnóstico acusou o LLM como inacessível, lembre-se de subir o Ollama
na outra máquina com:

    OLLAMA_HOST=0.0.0.0 ollama serve

EOF
