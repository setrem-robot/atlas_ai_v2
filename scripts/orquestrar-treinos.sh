#!/usr/bin/env bash
# Treina a Atlas a noite toda, em rodadas, sem ninguém olhando (WSL, destacado).
#
# Cada rodada (IA, GPU): o professor gera mais dados (aula ‖ papo -> seguida ->
# parafrase -> web) -> julgar -> dataset -> LoRA do zero em ~/atlas-run/rN ->
# instala no Pi como atlas-1b-rN (ou atlas-qwen-rN) -> prova no Pi -> se ganhar do modelo do robô,
# troca no .env e mede a conversa no mudo (volta se ficar lenta) -> GGUF numa
# release do GitHub. Os dados vão para a release dados-professor toda rodada.
# Sem 5% de exemplos novos, gera mais em vez de treinar de novo.
#
# Vosk (CPU): a varredura de pesos roda uma vez, se ~/escuta-treino/resumo.txt
# não existir.
#
# O professor é o Ollama do Windows (127.0.0.1, via networkingMode=mirrored),
# com OLLAMA_NUM_PARALLEL=3. Estado das rodadas em ~/atlas-run/estado.env.
#
# Tudo é retomável: rodar de novo continua de onde parou. Andamento em
# orquestrar-treinos.log, ao lado deste arquivo.
#
# Rodar destacado (fechar o terminal não mata; o wsl.exe oculto segura o WSL):
#   powershell Start-Process -WindowStyle Hidden wsl -ArgumentList '-d','Ubuntu','--','bash','/mnt/d/Projetos/SetremRobot/RobotEye/.claude/worktrees/fix-audio-qualquer-placa/scripts/orquestrar-treinos.sh'
set -uo pipefail

S="$(cd "$(dirname "$0")" && pwd)"
LOG="$S/orquestrar-treinos.log"
PY=~/atlas-treino/bin/python   # tem unsloth, httpx e python-dotenv (dataset.py importa o avaliar.py, que importa o config)
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

GB="/mnt/c/Program Files/Git/bin/bash.exe"   # ssh, ollama e gh são os do Windows
DEST=atlas@atlas.local
SAI=/mnt/d/Projetos/SetremRobot/modelos-treinados
ESTADO=~/atlas-run/estado.env   # RODADA, MELHOR, NOTA, LINHAS: sobrevive a reinício
winp() { sed -E 's#^/mnt/(.)#/\1#' <<< "$1"; }   # /mnt/d/x -> /d/x, para o Git Bash
noPi() { "$GB" -lc "ssh -o ConnectTimeout=15 $DEST '$1'"; }

professor() {
    cd "$S/treino" || return 1
    export PARALELO=3   # o Ollama do Windows atende três ao mesmo tempo (OLLAMA_NUM_PARALLEL)
    export VOLTAS=$(( RODADA > 1 ? RODADA - 1 : 1 ))   # uma geração nova de aula, papo e seguida por rodada
    "$PY" professor.py aula >> dados-aula.log 2>&1 &
    local aula=$!
    for t in comuns papo seguida parafrase web; do "$PY" professor.py $t >> dados-resto.log 2>&1; done
    wait $aula
    log "ia: professor rodou; julgando"
    "$PY" professor.py julgar >> dados-julgar.log 2>&1 || { log "ia: julgar falhou (treino/dados-julgar.log)"; return 1; }
    "$PY" dataset.py > atlas-treino.jsonl 2>> dados-julgar.log || { log "ia: dataset.py falhou"; return 1; }
}

# Treina do zero a rodada $1, numa pasta só dela (treinar.py retoma de
# saida-treino/ se cair no meio).
lora() {
    local D=~/atlas-run/r$1
    mkdir -p "$D" && cd "$D" || return 1
    cp "$S/treino/atlas-treino.jsonl" "$S/treino/treinar.py" .
    ATLAS_BASE=$BASE "$PY" treinar.py atlas-treino.jsonl >> "$S/treino/treino.log" 2>&1 && [[ -f atlas-1b/config.json ]]
}

# Instala a rodada $1 no Ollama do Pi como $MOD (o .env não muda) e devolve a
# nota da prova (certas) em $NOTA_R.
provar() {
    local m=$MOD
    "$GB" -lc "ollama pull $TPL" >> "$S/treino/treino.log" 2>&1   # o template do Modelfile vem dele
    rm -rf "$SAI/r$1" && mkdir -p "$SAI/r$1" && cp -r ~/atlas-run/r$1/atlas-1b "$SAI/r$1/" || return 1
    "$GB" -lc "cd '$(winp "$SAI/r$1")' && TEMPLATE_DE=$TPL bash '$(winp "$S")/treino/instalar-no-pi.sh' $DEST $m" \
        >> "$S/treino/treino.log" 2>&1 || { log "pi: instalar $m falhou (treino/treino.log)"; return 1; }
    "$GB" -lc "ssh $DEST 'mkdir -p ~/bench/scripts/treino ~/avaliacoes && ln -sfn ~/atlas_ai_v2/src ~/bench/src' \
        && scp -q '$(winp "$S")/treino/avaliar.py' $DEST:bench/scripts/treino/" >> "$LOG" 2>&1
    local P="cd ~/atlas_ai_v2 && .venv/bin/python ~/bench/scripts/treino/avaliar.py"
    noPi "$P --modelo $m --curto --mostrar > ~/avaliacoes/$m.txt 2>&1; tail -n2 ~/avaliacoes/$m.txt" >> "$LOG" 2>&1
    NOTA_R=$(noPi "cat ~/avaliacoes/$m.txt" 2>/dev/null | grep -oE "^$m: [0-9]+" | grep -oE '[0-9]+$')
    [[ -n "$NOTA_R" ]] || { log "pi: a prova de $m não deu nota (~/avaliacoes/$m.txt)"; return 1; }
    log "pi: $m acertou $NOTA_R"
}

# A régua: o que o robô usa hoje, medido com a mesma prova.
notaDoAtual() {
    noPi "cd ~/atlas_ai_v2 && .venv/bin/python ~/bench/scripts/treino/avaliar.py --modelo $MELHOR \
        $([[ $MELHOR == atlas-* ]] && echo --curto) > ~/avaliacoes/regua-$MELHOR.txt 2>&1" >> "$LOG" 2>&1
    NOTA=$(noPi "cat ~/avaliacoes/regua-$MELHOR.txt" 2>/dev/null | grep -oE "^$MELHOR: [0-9]+" | grep -oE '[0-9]+$')
}

# Põe o modelo $1 no robô e só deixa se a conversa real ficar rápida (mudo).
trocar() {
    local m=$1 conversa mediana
    noPi "cd ~/atlas_ai_v2 && cp .env ~/avaliacoes/env-pre-$m.bak \
        && sed -i -e \"/^ROBOTEYE_LLM_MODEL=/d\" -e \"/^ROBOTEYE_LLM_PROMPT_CURTO=/d\" .env \
        && printf \"ROBOTEYE_LLM_MODEL=$m\nROBOTEYE_LLM_PROMPT_CURTO=true\n\" >> .env \
        && kill -KILL \$(systemctl show -p MainPID --value roboteye); sleep 60; systemctl is-active roboteye" >> "$LOG" 2>&1
    conversa=$("$GB" -lc "ssh $DEST 'bash -s $m | tee ~/avaliacoes/conversa-$m.txt' < '$(winp "$S")/medir-conversa.sh'" 2>&1)
    mediana=$(grep -oE 'mediana [0-9.]+' <<< "$conversa" | grep -oE '[0-9.]+$')
    if [[ -n "$mediana" ]] && awk -v x="$mediana" 'BEGIN { exit !(x <= 2.5) }'; then
        log "troca: $m no ar; conversa com mediana ${mediana} s"
        return 0
    fi
    log "troca: $m lento (mediana ${mediana:-?} s); voltando o .env de antes"
    noPi "cp ~/avaliacoes/env-pre-$m.bak ~/atlas_ai_v2/.env \
        && kill -KILL \$(systemctl show -p MainPID --value roboteye); sleep 45; systemctl is-active roboteye" >> "$LOG" 2>&1
    return 1
}

# Nada mora só neste PC: os dados vão toda rodada para a release
# dados-professor; o GGUF, quando vira o modelo do robô.
salvarDados() {
    tar czf "$SAI/dados-professor.tgz" -C "$S/treino" dados
    "$GB" -lc "cd '$(winp "$SAI")' && (gh release view dados-professor --repo setrem-robot/atlas_ai_v2 >/dev/null 2>&1 \
        || gh release create dados-professor --repo setrem-robot/atlas_ai_v2 --target producao --prerelease \
            --title 'Treino: dados do professor' --notes 'scripts/treino/dados/ (professor.py), atualizado a cada rodada do orquestrar-treinos.sh.') \
        && gh release upload dados-professor dados-professor.tgz --clobber --repo setrem-robot/atlas_ai_v2" \
        >> "$S/treino/treino.log" 2>&1 && log "github: dados salvos ($(du -h "$SAI/dados-professor.tgz" | cut -f1))" \
        || log "github: aviso, não consegui salvar os dados (treino/treino.log)"
}

salvarModelo() {
    local m=$1
    "$GB" -lc "cd '$(winp "$SAI/r$RODADA")' \
        && B=\$(cygpath -u \"\$(ollama show $m --modelfile | awk '/^FROM / { print \$2; exit }')\") \
        && cp \"\$B\" $m-q4_K_M.gguf \
        && gh release create $m $m-q4_K_M.gguf --repo setrem-robot/atlas_ai_v2 --target producao --latest \
            --title 'IA: $m' --notes 'LoRA sobre o $TPL, q4_K_M, rodada $RODADA do orquestrar-treinos.sh. Prova no Pi: $NOTA_R/72 (antes: $NOTA/72 do $MELHOR_ANTES). Instalar com scripts/treino/instalar-no-pi.sh.'" \
        >> "$S/treino/treino.log" 2>&1 && log "github: release $m publicada" || log "github: aviso, a release $m falhou"
}

main() {
    log "início (rodadas a noite toda)"
    mkdir -p ~/atlas-run "$SAI"
    [[ -f $ESTADO ]] || printf 'RODADA=2\nMELHOR=gemma3:1b\nNOTA=\nLINHAS=0\n' > "$ESTADO"
    [[ -s $W/resumo.txt ]] || vosk
    while true; do
        source "$ESTADO"
        BASE=${BASE:-gemma}
        case $BASE in
            qwen) TPL=qwen2.5:1.5b; MOD=atlas-qwen-r$RODADA ;;
            *)    TPL=gemma3:1b;    MOD=atlas-1b-r$RODADA ;;
        esac
        log "rodada $RODADA: gerando dados"
        professor || { sleep 600; continue; }
        local linhas; linhas=$(wc -l < "$S/treino/atlas-treino.jsonl")
        salvarDados
        # Treinar de novo só vale com pelo menos 5% de exemplos novos.
        if (( linhas < LINHAS * 105 / 100 )); then
            log "rodada $RODADA: só $linhas exemplos (treinado com $LINHAS); gerando mais antes de treinar"
            sleep 900; continue
        fi
        log "rodada $RODADA: $linhas exemplos; treinando"
        "$PY" "$S/treino/professor.py" descarregar || true
        lora $RODADA || { log "rodada $RODADA: LoRA falhou (treino/treino.log)"; sleep 600; continue; }
        provar $RODADA || { sleep 300; continue; }
        [[ -n $NOTA ]] || notaDoAtual
        log "rodada $RODADA: $MOD $NOTA_R contra $MELHOR ${NOTA:-?}"
        MELHOR_ANTES=$MELHOR
        if [[ -n $NOTA ]] && (( NOTA_R > NOTA )) && trocar $MOD; then
            salvarModelo $MOD
            MELHOR=$MOD; NOTA=$NOTA_R
        else
            noPi "ollama rm $MOD >/dev/null" >> "$LOG" 2>&1   # libera o cartão do Pi
        fi
        printf 'RODADA=%s\nMELHOR=%s\nNOTA=%s\nLINHAS=%s\nBASE=%s\n' $((RODADA + 1)) "$MELHOR" "$NOTA" "$linhas" "$BASE" > "$ESTADO"
    done
}
# Tudo numa linha só: o bash lê o script aos poucos, e editar este arquivo com
# o orquestrador rodando o faria executar lixo. Assim ele já leu tudo.
main "$@"; exit $?
