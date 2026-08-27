#!/usr/bin/env bash
#
# Mede o Wi-Fi com e sem o Bluetooth anunciando.
#
# No Raspberry Pi 5, Wi-Fi e Bluetooth dividem a mesma antena e a mesma faixa de
# 2,4 GHz. Como o robô depende do Wi-Fi para a IA da máquina de mesa e para a
# voz online, ligar o rádio Bluetooth não é uma decisão de graça — e é esta
# medida que diz se o ESP32 pode ser aposentado.
#
# Uso:
#   ./scripts/bench-radio.sh                 mede contra o gateway
#   ./scripts/bench-radio.sh 192.168.1.108   mede contra outra máquina
#
# Medido no robô de produção (agosto/2026, Pi 5, wlan0 contra o gateway):
#
#   bluetooth parado       perda 0%   rtt 2,96/4,09/8,57    mdev 1,01 ms
#   bluetooth anunciando   perda 0%   rtt 0,68/4,81/41,47   mdev 6,08 ms
#
# Ou seja: nenhuma perda de pacote, média 18% maior, e picos cinco vezes
# maiores. Irrelevante para este robô, onde a resposta da IA leva ~1000 ms.
set -uo pipefail
ALVO="${1:-192.168.1.1}"

medir() {
    local rotulo="$1"
    local saida
    saida=$(ping -I wlan0 -c 40 -i 0.2 -q "${ALVO}" 2>/dev/null | tail -3)
    local perda rtt
    perda=$(echo "${saida}" | grep -o "[0-9]*% packet loss" | head -1)
    rtt=$(echo "${saida}" | grep -o "min/avg/max/mdev = [0-9./]*" | cut -d= -f2)
    printf "  %-28s perda %-6s rtt(min/avg/max/mdev) %s ms\n" "${rotulo}" "${perda%\% packet loss}%" "${rtt}"
}

echo "=== Wi-Fi (wlan0) contra ${ALVO} ==="
sudo bluetoothctl -- advertise off >/dev/null 2>&1
sleep 2
medir "bluetooth parado"

sudo bluetoothctl <<'CMD' >/dev/null 2>&1
menu advertise
uuids 6e400001-b5a3-f393-e0a9-e50e24dcca9e
name Atlas
back
advertise on
CMD
sleep 2
ativas=$(sudo busctl call org.bluez /org/bluez/hci0 org.freedesktop.DBus.Properties Get ss org.bluez.LEAdvertisingManager1 ActiveInstances 2>/dev/null | awk '{print $NF}')
echo "  (anuncios BLE ativos: ${ativas:-?})"
medir "bluetooth anunciando"

sudo bluetoothctl -- advertise off >/dev/null 2>&1
