#!/usr/bin/env bash
# Mede a conversa de ponta a ponta no robô rodando: manda perguntas fixas pela
# página do celular (/api/conversar), espera cada resposta terminar e tira do
# journal o tempo entre "usuario:" e o primeiro "falando:" — o silêncio que
# quem perguntou ouve. Passa pelo mesmo caminho de uma pergunta falada, só sem
# o Vosk: memória, prompt, LLM, quebra em frases e voz. A Atlas fala em voz alta.
#
# Uso (no Pi):  bash medir-conversa.sh [rótulo]
#   do PC:      ssh atlas@atlas.local bash -s depois < scripts/medir-conversa.sh
set -euo pipefail
ROTULO="${1:-medida}"
PIN=$(sed -n 's/^ROBOTEYE_WEB_PIN=//p' ~/atlas_ai_v2/.env | tr -d '"')
URL=http://127.0.0.1:$(sed -n 's/^ROBOTEYE_WEB_PORT=//p' ~/atlas_ai_v2/.env)
api() { curl -sf -m 10 -H "X-Pin: $PIN" -H "Content-Type: application/json" ${2:+-d "$2"} "$URL$1"; }
ocupado() { api /api/state | python3 -c "import json,sys; print(json.load(sys.stdin).get('ocupado'))"; }

PERGUNTAS=(
    "qual é o seu nome"
    "quem é o coordenador do curso"
    "o que é um bit"
    "me dá um exemplo"
    "que dia é hoje"
    "o que é a lei de ohm"
    "e para que serve isso"
    "você gosta de música"
    "o que é um protocolo de rede"
    "obrigado atlas"
)

inicio=$(date '+%Y-%m-%d %H:%M:%S')
for p in "${PERGUNTAS[@]}"; do
    desde=$(date '+%Y-%m-%d %H:%M:%S')
    api /api/conversar "{\"texto\": \"$p\"}" > /dev/null
    # "ocupado" só vale enquanto ela fala, não enquanto pensa: primeiro espera a
    # resposta inteira chegar ao journal, depois a voz acabar. Pergunta mandada
    # antes disso o robô descarta.
    for _ in $(seq 240); do
        journalctl -u roboteye --since "$desde" --no-pager | grep -q "assistente:" && break
        sleep 0.5
    done
    for _ in $(seq 120); do [[ $(ocupado) == False ]] && break; sleep 0.5; done
    sleep 2
done

journalctl -u roboteye --since "$inicio" -o short-unix --no-pager | python3 -c '
import re, sys
rotulo, tempos, pergunta, t0 = sys.argv[1], [], None, None
for linha in sys.stdin:
    m = re.match(r"(\d+\.\d+) .*?(usuario|falando): (.*)", linha)
    if not m:
        continue
    t, tipo, texto = float(m[1]), m[2], m[3]
    if tipo == "usuario":
        pergunta, t0 = texto, t
    elif t0 is not None:
        tempos.append(t - t0)
        print(f"  {t - t0:5.1f} s  {pergunta}  ->  {texto[:70]}")
        t0 = None
if not tempos:
    sys.exit("nenhuma resposta no journal")
tempos.sort()
print(f"{rotulo}: até começar a falar, mediana {tempos[len(tempos) // 2]:.1f} s, pior {tempos[-1]:.1f} s ({len(tempos)} respostas)")
' "$ROTULO"
