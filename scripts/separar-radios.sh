#!/usr/bin/env bash
#
# Tira o Wi-Fi de cima do Bluetooth.
#
# No Raspberry Pi 5 os dois rádios saem do mesmo chip e da mesma antena. O
# Bluetooth só existe em 2,4 GHz; o Wi-Fi também fala 5 GHz. Enquanto os dois
# estiverem em 2,4 GHz eles revezam o meio — e é isso que faz o controle pelo
# app engasgar justamente quando a IA da rede está respondendo.
#
# Medido neste robô com `scripts/bench-radio.sh`, em 2,4 GHz e com o anúncio BLE
# no ar: nenhuma perda de pacote, média 18% maior, picos cinco vezes maiores.
# Este script move o Wi-Fi para 5 GHz, onde não há com quem disputar.
#
# Uso:
#   sudo ./scripts/separar-radios.sh              aplica na conexão ativa
#   sudo ./scripts/separar-radios.sh --mostrar    só diz como está
#   sudo ./scripts/separar-radios.sh --desfazer   volta a deixar as duas bandas
#
# Por que não faz parte do `setup-raspberry-pi.sh`: a rede em que o robô vai
# viver muda de lugar para lugar (a Setrem, a casa, a feira), e travar a banda
# na instalação deixaria o robô sem rede em qualquer lugar que só tenha 2,4 GHz.
# Isto se roda depois, na rede onde ele vai ficar.
set -euo pipefail

MOSTRAR=false
DESFAZER=false
case "${1:-}" in
    --mostrar)  MOSTRAR=true ;;
    --desfazer) DESFAZER=true ;;
    -h|--help)  sed -n '2,22p' "$0"; exit 0 ;;
    "")         ;;
    *)          echo "opção desconhecida: $1 (use --help)" >&2; exit 1 ;;
esac

info() { echo "    $*"; }
warn() { echo "    [aviso] $*" >&2; }

command -v nmcli >/dev/null || { echo "nmcli não encontrado; este script é para o NetworkManager" >&2; exit 1; }

# A conexão ativa, e não a interface: é a conexão que guarda a preferência de
# banda, e é ela que o `nmcli connection modify` altera.
CONEXAO="$(nmcli -t -f NAME,TYPE connection show --active | awk -F: '$2=="802-11-wireless"{print $1; exit}')"
IFACE="$(nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1; exit}')"

if [[ -z "${CONEXAO}" ]]; then
    warn "nenhuma conexão Wi-Fi ativa; conecte o robô à rede antes"
    exit 1
fi

echo "==> Rádios do robô"
info "conexão ativa: ${CONEXAO} (${IFACE:-?})"
if [[ -n "${IFACE}" ]] && command -v iw >/dev/null; then
    FREQ="$(iw dev "${IFACE}" link | awk '/freq:/{print $2; exit}')"
    if [[ -n "${FREQ}" ]]; then
        # 4000 MHz não existe como canal: serve só de divisor entre as bandas.
        BANDA=$([[ "${FREQ%%.*}" -ge 4000 ]] && echo "5 GHz" || echo "2,4 GHz")
        info "banda atual: ${BANDA} (${FREQ} MHz)"
    fi
    info "economia de energia: $(iw dev "${IFACE}" get power_save | awk '{print $NF}')"
fi
info "banda configurada: $(nmcli -g 802-11-wireless.band connection show "${CONEXAO}" || echo '(qualquer)')"

if [[ "${MOSTRAR}" == true ]]; then
    exit 0
fi

if [[ "${DESFAZER}" == true ]]; then
    echo "==> Liberando as duas bandas de novo"
    nmcli connection modify "${CONEXAO}" 802-11-wireless.band ""
    nmcli connection up "${CONEXAO}" >/dev/null
    info "pronto: o robô volta a aceitar 2,4 GHz"
    exit 0
fi

# Sem um ponto de acesso em 5 GHz com este SSID, travar a banda deixaria o robô
# offline — e offline ele perde a IA boa e a voz da nuvem de uma vez. Por isso a
# varredura vem antes da mudança, e não depois dela.
echo "==> Procurando a rede em 5 GHz"
SSID="$(nmcli -g 802-11-wireless.ssid connection show "${CONEXAO}")"
nmcli device wifi rescan >/dev/null 2>&1 || true
sleep 3
if ! nmcli -t -f SSID,FREQ device wifi list | awk -F: -v s="${SSID}" '$1==s && $2+0>=4000{achou=1} END{exit !achou}'; then
    warn "não achei '${SSID}' em 5 GHz por aqui."
    warn "Esta rede pode ser só de 2,4 GHz, ou o robô estar longe do roteador"
    warn "(5 GHz alcança menos). Sem 5 GHz, o que resta é reduzir a disputa:"
    warn "  - mantenha o anúncio BLE só enquanto o app precisa dele"
    warn "  - deixe o robô perto do roteador, para o Wi-Fi falar menos vezes"
    exit 1
fi
info "encontrada"

echo "==> Fixando o Wi-Fi em 5 GHz"
nmcli connection modify "${CONEXAO}" 802-11-wireless.band a
# 2 = desligada. O rádio dorme entre pacotes para poupar bateria; num robô na
# tomada isso não compra nada e ainda encurta as frestas que o Bluetooth usaria.
nmcli connection modify "${CONEXAO}" 802-11-wireless-powersave 2
nmcli connection up "${CONEXAO}" >/dev/null
info "aplicado"

echo
echo "Confira com:  roboteye radio"
echo "Meça a diferença com:  ./scripts/bench-radio.sh"
echo "Se a rede sumir, desfaça com:  sudo $0 --desfazer"
