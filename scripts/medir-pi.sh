#!/usr/bin/env bash
# Mede o que o robô gasta parado, no próprio Pi: CPU por thread do roboteye e
# do Ollama, RAM de cada um e a livre. É a régua do antes/depois de cada
# otimização; rodar com o robô no estado que se quer medir.
#
# Uso (no Pi):  bash medir-pi.sh [SEGUNDOS]      # padrão 30
#   do PC:      ssh atlas@atlas.local bash -s 30 < scripts/medir-pi.sh
set -euo pipefail
SEG="${1:-30}"
HZ=$(getconf CLK_TCK)
# Pelo serviço, e não por nome: a ponte BLE também roda `bin/roboteye`.
ROBO=$(systemctl show -p MainPID --value roboteye)
OLLAMA=$(pgrep -x ollama | head -1 || true)

# Retrato de cada thread: "tid nome ticks" (utime+stime). O nome vem do comm,
# que o Python preenche com o nome da threading.Thread a partir do 3.13.
fotografar() {
    for t in /proc/$1/task/*; do
        awk -v tid="${t##*/}" -v nome="$(cat "$t/comm")" '{ print tid, nome, $14 + $15 }' "$t/stat" 2>/dev/null
    done
}
antes=$(fotografar "$ROBO")
sleep "$SEG"
depois=$(fotografar "$ROBO")

echo "roboteye (pid $ROBO), $SEG s parado; % de UM núcleo (o Pi tem $(nproc)):"
join <(sort <<<"$antes") <(sort <<<"$depois") | awk -v s="$SEG" -v hz="$HZ" '
    { pct = ($5 - $3) / (s * hz) * 100; total += pct; if (pct >= 0.5) printf "  %-22s %5.1f%%\n", $2 "(" $1 ")", pct }
    END { printf "  %-22s %5.1f%%\n", "TOTAL", total }'
rss() { awk '/VmRSS/ { printf "%d MiB", $2 / 1024 }' "/proc/$1/status"; }
echo "RAM: roboteye $(rss "$ROBO")${OLLAMA:+, ollama $(rss "$OLLAMA")}"
for p in $(pgrep -f "ollama.*runner|llama-server" || true); do echo "     modelo carregado (pid $p) $(rss "$p")"; done
free -m | awk '/Mem:/ { printf "     livre de verdade: %d MiB de %d\n", $7, $2 }'
echo "temperatura $(vcgencmd measure_temp 2>/dev/null | cut -d= -f2), throttled $(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)"
