#!/usr/bin/env bash
#
# Aponta o sistema para a placa de som certa e deixa os volumes utilizáveis.
#
# Existe porque duas coisas do áudio no Raspberry Pi não têm padrão bom:
#
#   - a saída padrão é o HDMI, que só toca se a tela tiver alto-falante;
#   - placas USB baratas chegam com o volume em ~30% e o ganho do microfone em
#     zero, o que faz o robô parecer mudo e surdo mesmo com tudo instalado.
#
# Uso:
#   sudo ./scripts/configurar-audio.sh              detecta e configura
#   sudo ./scripts/configurar-audio.sh --card 2     força uma placa
#   sudo ./scripts/configurar-audio.sh --hdmi       usa o HDMI mesmo assim
#   ./scripts/configurar-audio.sh --mostrar         só diz o que existe hoje
#
# É idempotente: rodar de novo apenas reescreve com os mesmos valores.

set -uo pipefail

ALSA_CONF=/etc/asound.conf
#: Volume de saída. 85% dá volume de sala sem entrar na parte distorcida do fim
#: do curso destas placas.
VOLUME_SAIDA=85
#: Ganho de captura. Estas placas chegam em 0 (mudas); ~80% é o que põe a fala
#: normal numa faixa que o reconhecimento entende sem estourar.
GANHO_MIC=80

CARD=""
USAR_HDMI=false
SO_MOSTRAR=false

log() { echo "    $*"; }
fail() { echo "[erro] $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --card)    CARD="${2:?--card exige um numero}"; shift 2 ;;
        --hdmi)    USAR_HDMI=true; shift ;;
        --mostrar) SO_MOSTRAR=true; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *)         fail "opção desconhecida: $1 (use --help)" ;;
    esac
done

# --- o que existe -----------------------------------------------------------
mostrar() {
    echo "Placas com saída:"
    aplay -l 2>/dev/null | grep -E "^card" | sed 's/^/    /' || log "(nenhuma)"
    echo "Placas com entrada (microfone):"
    arecord -l 2>/dev/null | grep -E "^card" | sed 's/^/    /' || log "(nenhuma)"
}

if [[ "${SO_MOSTRAR}" == true ]]; then
    mostrar
    echo "Saída do sistema hoje: $(grep -A1 'pcm.!default' "${ALSA_CONF}" 2>/dev/null | grep -o 'hw:[0-9],[0-9]' || echo 'padrão do ALSA')"
    exit 0
fi

[[ $EUID -eq 0 ]] || fail "rode com sudo (este script escreve em ${ALSA_CONF})"

# --- qual placa -------------------------------------------------------------
# Uma placa USB plugada é uma escolha deliberada de quem montou o robô; o HDMI
# está sempre lá, queira-se ou não. Por isso a USB ganha.
if [[ -z "${CARD}" ]] && [[ "${USAR_HDMI}" == false ]]; then
    CARD="$(aplay -l 2>/dev/null | grep -iE "^card .*usb" | head -1 | sed -E 's/^card ([0-9]+).*/\1/')"
fi

if [[ -z "${CARD}" ]]; then
    CARD="$(aplay -l 2>/dev/null | grep -E "^card" | head -1 | sed -E 's/^card ([0-9]+).*/\1/')"
    [[ -z "${CARD}" ]] && fail "nenhuma placa de som encontrada (aplay -l não devolveu nada)"
    log "sem placa USB; usando a placa ${CARD}"
else
    log "usando a placa ${CARD}: $(aplay -l 2>/dev/null | grep -E "^card ${CARD}" | head -1 | sed -E 's/.*\[([^]]+)\].*/\1/')"
fi

# --- escrever o padrão do sistema -------------------------------------------
# Três camadas, e cada uma resolve um problema que já quebrou este robô:
#
#   plug     o Piper sintetiza a 22050 Hz e boa parte das placas não aceita essa
#            taxa; sem a conversão no meio, a primeira frase falha com
#            "Invalid sample rate";
#   dmix     um dongle USB é UMA placa para a caixinha e o microfone, e o ALSA a
#            entrega em modo exclusivo. Com a escuta segurando o microfone, a
#            Atlas ouvia, pensava, respondia — e não conseguia emitir som:
#            "Device unavailable". O dmix deixa a saída ser compartilhada;
#   dsnoop   o mesmo, do lado da entrada: sem ele, o `doctor` e qualquer teste
#            de microfone falham enquanto o robô está escutando.
#
# `asym` é o que junta os dois lados num único dispositivo padrão.
cat > "${ALSA_CONF}" <<EOF
# Escrito por scripts/configurar-audio.sh — rode-o de novo para mudar.
pcm.!default {
    type asym
    playback.pcm "roboteye_saida"
    capture.pcm "roboteye_entrada"
}

pcm.roboteye_saida {
    type plug
    slave.pcm "roboteye_dmix"
}

pcm.roboteye_dmix {
    type dmix
    ipc_key 3021
    ipc_perm 0666
    slave {
        pcm "hw:${CARD},0"
        rate 48000
        channels 2
        period_size 1024
        buffer_size 8192
    }
}

pcm.roboteye_entrada {
    type plug
    slave.pcm "roboteye_dsnoop"
}

pcm.roboteye_dsnoop {
    type dsnoop
    ipc_key 3022
    ipc_perm 0666
    slave {
        pcm "hw:${CARD},0"
        rate 48000
        channels 1
        period_size 1024
        buffer_size 8192
    }
}

ctl.!default {
    type hw
    card ${CARD}
}
EOF
log "${ALSA_CONF}: saída e microfone compartilhados em hw:${CARD},0"

# --- volumes ----------------------------------------------------------------
# Nomes de controle variam entre placas; tentar vários e ignorar o que não
# existir é mais simples (e mais honesto) do que mapear cada modelo.
subir() {
    local controle="$1" valor="$2" tipo="$3"
    amixer -c "${CARD}" sset "${controle}" "${valor}%" ${tipo} >/dev/null 2>&1 && \
        log "${controle}: ${valor}%"
}

for controle in Speaker PCM Master Headphone; do
    subir "${controle}" "${VOLUME_SAIDA}" unmute
done
for controle in Mic Capture; do
    subir "${controle}" "${GANHO_MIC}" cap
done

# O "Auto Gain Control" destas placas bombeia o ruído de fundo entre as frases,
# o que atrapalha justamente o reconhecimento de fala que ele deveria ajudar.
amixer -c "${CARD}" sset "Auto Gain Control" off >/dev/null 2>&1 && \
    log "Auto Gain Control: desligado"

# Guarda os níveis para o próximo arranque; sem isso, tudo volta ao padrão da
# placa no primeiro reboot e o robô parece ter emudecido sozinho.
alsactl store >/dev/null 2>&1 || log "[aviso] não consegui guardar os níveis (alsactl)"

echo
log "pronto. Teste com:  speaker-test -D default -c 2 -t sine -f 660 -l 1"
