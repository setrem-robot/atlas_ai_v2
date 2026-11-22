#!/usr/bin/env bash
# Orquestra os dois treinos no WSL, do começo ao fim, sem ninguém olhando.
#
#   IA   (GPU): professor (aula ‖ papo -> seguida -> parafrase) -> julgar ->
#               dataset -> descarrega o professor -> LoRA (treino/treinar.py)
#   Vosk (CPU): LM geral + legendas, e para cada combinação de pesos constrói
#               e avalia o modelo (escuta-treino/); o resumo vai para
#               ~/escuta-treino/resumo.txt
#
# Os dois correm juntos, mas o LoRA espera o Vosk acabar: o WSL tem 7 GB de RAM,
# e o treino somado à mistura do LM de legendas estoura a memória.
# O professor é o Ollama do Windows (127.0.0.1, via networkingMode=mirrored).
#
# Tudo é retomável: rodar de novo continua de onde parou. Andamento em
# orquestrar-treinos.log, ao lado deste arquivo.
#
# Rodar destacado (fechar o terminal não mata; o wsl.exe oculto segura o WSL):
#   powershell Start-Process -WindowStyle Hidden wsl -ArgumentList '-d','Ubuntu','--','bash','/mnt/d/Projetos/SetremRobot/RobotEye/.claude/worktrees/fix-audio-qualquer-placa/scripts/orquestrar-treinos.sh'
set -uo pipefail

S="$(cd "$(dirname "$0")" && pwd)"
LOG="$S/orquestrar-treinos.log"
PY=~/atlas-treino/bin/python   # tem unsloth e httpx (dataset.py importa o roboteye)
W=~/escuta-treino
export PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1

exec 9> /tmp/orquestrar-treinos.lock
flock -n 9 || { echo "já tem um orquestrador rodando"; exit 1; }
log() { echo "[$(date '+%d/%m %H:%M')] $*" >> "$LOG"; }

vosk() {
    local E="$S/escuta-treino" dom leg r
    cd "$W" || return 1
    for dom in 0.3 0.5; do
        for leg in 0.3 0.5; do
            r="atlas-$dom-leg$leg"
            log "vosk: construindo $r"
            LEGENDAS=$leg bash "$E/construir-modelo.sh" "$dom" "$W/construido/$r" >> log-construir.txt 2>&1 \
                || { log "vosk: construir $r falhou (ver ~/escuta-treino/log-construir.txt)"; return 1; }
            "$W/env/bin/python" "$E/avaliar.py" --modelo "construido/$r" --rotulo "$r" --banco banco \
                --ruido ruido/ruido-pi-1.wav --threads 10 >> log-varrer.txt 2>&1 \
                || { log "vosk: avaliar $r falhou (ver ~/escuta-treino/log-varrer.txt)"; return 1; }
        done
    done
    "$W/env/bin/python" "$E/avaliar.py" --resumo resultados/*.jsonl > resumo.txt 2>&1
    log "vosk: pronto, comparação em ~/escuta-treino/resumo.txt"
}

professor() {
    cd "$S/treino" || return 1
    "$PY" professor.py aula >> dados-aula.log 2>&1 &
    local aula=$!
    { "$PY" professor.py papo && "$PY" professor.py seguida && "$PY" professor.py parafrase; } >> dados-resto.log 2>&1
    local resto=$?
    wait $aula
    local a=$?
    (( a == 0 && resto == 0 )) || { log "ia: professor falhou (aula $a, resto $resto; ver treino/dados-*.log)"; return 1; }
    log "ia: professor pronto, julgando"
    "$PY" professor.py julgar >> dados-julgar.log 2>&1 || { log "ia: julgar falhou (treino/dados-julgar.log)"; return 1; }
    "$PY" dataset.py > atlas-treino.jsonl 2>> dados-julgar.log || { log "ia: dataset.py falhou"; return 1; }
    log "ia: dataset com $(wc -l < atlas-treino.jsonl) exemplos"
    "$PY" professor.py descarregar || log "ia: aviso, não consegui tirar o professor da GPU"
}

lora() {
    mkdir -p ~/atlas-run && cd ~/atlas-run || return 1
    # A 1ª rodada (outro dataset) não pode ser retomada por engano: vai para -v1.
    if [[ ! -f .rodada2 ]]; then
        for d in saida-treino atlas-1b; do [[ -e $d ]] && mv "$d" "$d-v1"; done
        touch .rodada2
    fi
    cp "$S/treino/atlas-treino.jsonl" "$S/treino/treinar.py" .
    "$PY" treinar.py atlas-treino.jsonl >> "$S/treino/treino.log" 2>&1
}

# Leva o modelo para o Ollama do Pi como atlas-1b-v2 (o .env do robô não muda)
# e roda a prova lá, contra o gemma3:1b de hoje. A troca é decisão de quem lê
# ~/avaliacoes/ no Pi. O ssh e o ollama são os do Windows: as chaves do Pi e o
# servidor do Ollama moram lá.
pi() {
    local DEST=atlas@atlas.local SAI=/mnt/d/Projetos/SetremRobot/modelos-treinados/v2
    local gb="/mnt/c/Program Files/Git/bin/bash.exe"
    winp() { sed -E 's#^/mnt/(.)#/\1#' <<< "$1"; }   # /mnt/d/x -> /d/x, para o Git Bash
    mkdir -p "$SAI" && rm -rf "$SAI/atlas-1b" && cp -r ~/atlas-run/atlas-1b "$SAI/" || return 1
    "$gb" -lc "cd '$(winp "$SAI")' && bash '$(winp "$S")/treino/instalar-no-pi.sh' $DEST atlas-1b-v2" \
        >> "$S/treino/treino.log" 2>&1 || { log "pi: instalar-no-pi.sh falhou (ver treino/treino.log)"; return 1; }
    log "pi: atlas-1b-v2 instalado no Ollama do Pi"
    # Nada disto pode morar só neste PC: o GGUF e os dados do professor (horas
    # de GPU) vão para uma release do GitHub, como pré-lançamento até a prova.
    tar czf "$SAI/dados-professor.tgz" -C "$S/treino" dados
    "$gb" -lc "cd '$(winp "$SAI")' \
        && B=\$(cygpath -u \"\$(ollama show atlas-1b-v2 --modelfile | awk '/^FROM / { print \$2; exit }')\") \
        && cp \"\$B\" atlas-1b-v2-q4_K_M.gguf \
        && gh release create atlas-1b-v2 atlas-1b-v2-q4_K_M.gguf dados-professor.tgz \
            --repo setrem-robot/atlas_ai_v2 --target producao --prerelease \
            --title 'IA: atlas-1b v2 (candidato)' \
            --notes 'LoRA do Gemma 3 1B (scripts/treino/treinar.py), q4_K_M. Instalar: instalar-no-pi.sh. A prova no Pi fica em ~/avaliacoes/atlas-1b-v2.txt; ver TREINO-E-OTIMIZACAO.md.'" \
        >> "$S/treino/treino.log" 2>&1 \
        && log "pi: GGUF e dados salvos na release atlas-1b-v2 do GitHub" \
        || log "pi: aviso, a release no GitHub falhou (ver treino/treino.log); os arquivos estão em $SAI"
    log "pi: rodando a prova"
    "$gb" -lc "ssh $DEST 'mkdir -p ~/bench/scripts/treino ~/avaliacoes && ln -sfn ~/atlas_ai_v2/src ~/bench/src' \
        && scp -q '$(winp "$S")/treino/avaliar.py' $DEST:bench/scripts/treino/ \
        && ssh $DEST 'cd ~/atlas_ai_v2 && P=\".venv/bin/python $HOME/bench/scripts/treino/avaliar.py\" \
            && \$P --modelo atlas-1b-v2 --curto --mostrar > ~/avaliacoes/atlas-1b-v2.txt 2>&1 \
            && \$P --modelo gemma3:1b > ~/avaliacoes/gemma3-1b-banca2.txt 2>&1; \
            tail -qn2 ~/avaliacoes/atlas-1b-v2.txt ~/avaliacoes/gemma3-1b-banca2.txt'" \
        >> "$LOG" 2>&1 || { log "pi: a prova falhou (ver ~/avaliacoes no Pi)"; return 1; }
    log "pi: prova pronta (placar acima; detalhe em ~/avaliacoes/ no Pi)"
    trocar
}

# Põe o atlas-1b-v2 no robô sozinho, mas só se ganhar na prova do gemma3:1b e
# do v1 (52/68), e só fica se a conversa real continuar rápida; senão o .env
# volta como estava. A medida faz a Atlas falar dez respostas em voz alta.
trocar() {
    local DEST=atlas@atlas.local gb="/mnt/c/Program Files/Git/bin/bash.exe" placar v2 g
    placar=$("$gb" -lc "ssh $DEST 'cat ~/avaliacoes/atlas-1b-v2.txt ~/avaliacoes/gemma3-1b-banca2.txt'" 2>/dev/null)
    v2=$(grep -oE '^atlas-1b-v2: [0-9]+' <<< "$placar" | grep -oE '[0-9]+$')
    g=$(grep -oE '^gemma3:1b: [0-9]+' <<< "$placar" | grep -oE '[0-9]+$')
    if [[ -z "$v2" || -z "$g" ]] || (( v2 <= g || v2 < 52 )); then
        log "troca: não (v2 ${v2:-?}/68, gemma3:1b ${g:-?}/68, v1 52/68); o robô segue como está"
        return 0
    fi
    log "troca: v2 ${v2}/68 contra ${g}/68 do gemma3:1b; pondo no robô"
    "$gb" -lc "ssh $DEST 'cd ~/atlas_ai_v2 && cp .env ~/avaliacoes/env-pre-atlas-1b-v2.bak \
        && sed -i -e \"/^ROBOTEYE_LLM_MODEL=/d\" -e \"/^ROBOTEYE_LLM_PROMPT_CURTO=/d\" .env \
        && printf \"ROBOTEYE_LLM_MODEL=atlas-1b-v2\nROBOTEYE_LLM_PROMPT_CURTO=true\n\" >> .env \
        && kill -KILL \$(systemctl show -p MainPID --value roboteye); sleep 60; systemctl is-active roboteye'" >> "$LOG" 2>&1
    local conversa mediana
    conversa=$("$gb" -lc "ssh $DEST 'bash -s atlas-1b-v2 | tee ~/avaliacoes/conversa-atlas-1b-v2.txt' < '$(sed -E 's#^/mnt/(.)#/\1#' <<< "$S")/medir-conversa.sh'" 2>&1)
    mediana=$(grep -oE 'mediana [0-9.]+' <<< "$conversa" | grep -oE '[0-9.]+$')
    if [[ -n "$mediana" ]] && awk -v m="$mediana" 'BEGIN { exit !(m <= 2.5) }'; then
        log "troca: atlas-1b-v2 no ar; conversa com mediana ${mediana} s"
        "$gb" -lc "gh release edit atlas-1b-v2 --repo setrem-robot/atlas_ai_v2 --prerelease=false --title 'IA: atlas-1b v2'" >> "$LOG" 2>&1
    else
        log "troca: conversa lenta (mediana ${mediana:-?} s); voltando o .env de antes"
        "$gb" -lc "ssh $DEST 'cp ~/avaliacoes/env-pre-atlas-1b-v2.bak ~/atlas_ai_v2/.env \
            && kill -KILL \$(systemctl show -p MainPID --value roboteye); sleep 45; systemctl is-active roboteye'" >> "$LOG" 2>&1
    fi
}

main() {
log "início"
vosk & V=$!
professor; IA=$?
if (( IA == 0 )); then
    log "ia: esperando o Vosk liberar a RAM"
fi
wait $V
if (( IA == 0 )); then
    log "ia: treinando o LoRA"
    if lora; then
        log "ia: pronto, modelo em ~/atlas-run/atlas-1b"
        pi
    else
        log "ia: LoRA falhou (ver treino/treino.log)"
    fi
fi
log "fim"
}
# Tudo numa linha só: o bash lê o script aos poucos, e editar este arquivo com
# o orquestrador rodando o faria executar lixo. Assim ele já leu tudo.
main "$@"; exit $?
