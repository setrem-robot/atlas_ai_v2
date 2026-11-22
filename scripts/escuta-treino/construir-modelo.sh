#!/usr/bin/env bash
#
# Constrói o `vosk-pt-atlas`: o modelo acústico do vosk-pt-grande (FalaBrasil),
# com o grafo refeito — léxico com SETREM/Ropke/Goetz e um modelo de linguagem
# que mistura o português geral do FalaBrasil com o que se diz à Atlas.
#
# Roda no PC (Linux/WSL), não no Pi: precisa de Kaldi, OpenFst, OpenGrm e KenLM,
# e de alguns GB de RAM. O Pi só recebe a pasta pronta (instalar-no-pi.sh).
#
# Pré-requisitos (uma vez; versões e origens em TREINO-E-OTIMIZACAO.md, e os
# insumos caros na release vosk-pt-atlas-v1, escuta-treino-insumos.tgz):
#   $W/env        kaldi + openfst (conda-forge)
#   $W/env-ngram  ngram (OpenGrm, conda-forge)
#   $W/downloads/kenlm/build/bin/lmplz
#   $W/downloads/kaldi/egs/wsj/s5/{utils,steps}
#   $W/downloads/fb/3-gram.2e-7.arpa.gz   (LM geral do FalaBrasil, o mesmo do Gr original)
#   $W/modelos/vosk-pt-grande             (vosk-model-pt-fb-v0.1.1-20220516_2113)
#
# Uso:  [HCLG=1] construir-modelo.sh [PESO_DOMINIO] [SAIDA]
#   PESO_DOMINIO  peso linear do texto da Atlas na mistura (padrão 0.3)
#   HCLG=1        compõe HCLr com Gr num HCLG.fst estático: mais disco e RAM,
#                 mas a decodificação não compõe nada em tempo real (mais
#                 barata no Pi). Sem ele, o modelo sai em lookahead.
#   LEGENDAS=0.3  antes da mistura com o domínio, o LM geral vira geral +
#                 legendas (OpenSubtitles, $W/lm-legendas/legendas.arpa, de
#                 legendas.py) com esse peso: puxa a fala aberta para o jeito
#                 como se fala. Sem ele, só o geral do FalaBrasil.
#
# Retomável: cada etapa pula se a saída já existe. Apague a pasta da etapa
# para refazê-la.

set -euo pipefail

AQUI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
W="${ESCUTA_TREINO:-$HOME/escuta-treino}"
PESO="${1:-0.3}"
SAIDA="${2:-$W/construido/vosk-pt-atlas}"
BASE="$W/modelos/vosk-pt-grande"
ENV="$W/env"
NG="$W/env-ngram/bin"
LMPLZ="$W/downloads/kenlm/build/bin/lmplz"
GERAL="$W/downloads/fb/3-gram.2e-7.arpa.gz"
LEG="${LEGENDAS:-}"
TAG="${PESO}${LEG:+-leg$LEG}"   # nome da mistura e do grafo: um por combinação de pesos
T="$W/build"   # intermediários

export PATH="$ENV/bin:$PATH"
# fstconvert --fst_type=olabel_lookahead carrega o tipo como plugin.
export LD_LIBRARY_PATH="$ENV/lib/fst:$ENV/lib:${LD_LIBRARY_PATH:-}"
log() { echo "[$(date +%H:%M:%S)] $*"; }

mkdir -p "$T"
# Os scripts do Kaldi esperam `utils/` e `steps/` no diretório corrente.
ln -sfn "$W/downloads/kaldi/egs/wsj/s5/utils" "$T/utils"
ln -sfn "$W/downloads/kaldi/egs/wsj/s5/steps" "$T/steps"
cd "$T"
# E alguns deles (validate_lang.pl) leem o ambiente de ./path.sh.
echo "export PATH=\"$PATH\" LD_LIBRARY_PATH=\"$LD_LIBRARY_PATH\"" > path.sh

# --- 1. dicionário: o léxico exato do grafo original + as palavras novas -----
if [[ ! -s dict/lexicon.txt ]]; then
    log "dicionário"
    mkdir -p dict
    # align_lexicon: "palavra palavra f1_B f2_I ... fn_E" -> "palavra f1 f2 ... fn"
    awk '$1!="<eps>" && $1!="!SIL" && $1!="<UNK>" {
            printf "%s", $1; for (i=3; i<=NF; i++) { p=$i; sub(/_[BIES]$/, "", p); printf " %s", p }; print "" }' \
        "$BASE/graph/phones/align_lexicon.txt" > dict/lexicon.tmp
    grep -v '^#' "$AQUI/palavras-novas.txt" | awk 'NF>1' >> dict/lexicon.tmp
    { echo "!SIL sil"; echo "<UNK> spn"; LC_ALL=C sort -u dict/lexicon.tmp; } > dict/lexicon.txt
    rm dict/lexicon.tmp
    cut -d' ' -f1 "$BASE/graph/phones.txt" | sed 's/_[BIES]$//' | grep -v -E '^(#|<eps>|sil|spn)' \
        | sort -u > dict/nonsilence_phones.txt
    printf 'sil\nspn\n' > dict/silence_phones.txt
    echo sil > dict/optional_silence.txt
    : > dict/extra_questions.txt
fi

# --- 2. lang: L_disambig.fst com a MESMA tabela de fones do modelo acústico ----
if [[ ! -s lang/L_disambig.fst ]]; then
    log "prepare_lang"
    utils/prepare_lang.sh --phone-symbol-table "$BASE/graph/phones.txt" \
        dict "<UNK>" lang_tmp lang > prepare_lang.log 2>&1 || { tail prepare_lang.log; exit 1; }
fi

# --- 3. LM de domínio: o texto da Atlas, só com palavras do vocabulário --------
if [[ ! -s lm/dominio.arpa ]]; then
    log "LM de domínio"
    mkdir -p lm
    "$ENV/bin/python" "$AQUI/corpus.py" > lm/dominio-bruto.txt
    cut -d' ' -f1 lang/words.txt > lm/vocab.txt
    # Frase com palavra fora do léxico sairia como <unk>; melhor não ensinar.
    awk 'NR==FNR { v[$1]=1; next } { for (i=1; i<=NF; i++) if (!($i in v)) next; print }' \
        lm/vocab.txt lm/dominio-bruto.txt > lm/dominio.txt
    log "  $(wc -l < lm/dominio.txt) frases de domínio"
    # Texto pequeno e repetitivo: o Kneser-Ney do KenLM precisa do fallback.
    "$LMPLZ" -o 3 --discount_fallback -S 20% < lm/dominio.txt > lm/dominio.arpa 2> lm/lmplz.log
fi

# --- 4. mistura linear (OpenGrm) do geral com o domínio -------------------------
MIX="lm/mistura-${TAG}.arpa"
if [[ ! -s "$MIX" ]]; then
    log "mistura: domínio ${PESO}${LEG:+, legendas $LEG no geral}"
    # Uma tabela de símbolos para os dois: o ngrammerge exige que batam.
    awk '$1!="#0" && $1!="<s>" && $1!="</s>"' lang/words.txt | sed 's/^<eps> /<epsilon> /' > lm/simbolos.txt
    # <unk> vira <UNK> (fone "spn"), como no Gr original: ruído sai "[unk]",
    # que a escuta descarta, em vez de virar uma palavra curta inventada.
    unk() { sed 's/\t<unk>/\t<UNK>/; s/ <unk>/ <UNK>/g'; }
    [[ -s lm/geral.mod ]] || "$NG/ngramread" --ARPA --symbols=lm/simbolos.txt <(zcat "$GERAL" | unk) lm/geral.mod
    GERALMOD=lm/geral.mod
    if [[ -n "$LEG" ]]; then
        # legendas.py já filtrou pelo words.txt: todo símbolo existe na tabela.
        [[ -s lm/legendas.mod ]] || "$NG/ngramread" --ARPA --symbols=lm/simbolos.txt \
            <(unk < "$W/lm-legendas/legendas.arpa") lm/legendas.mod
        GERALMOD="lm/geral-leg${LEG}.mod"
        [[ -s "$GERALMOD" ]] || "$NG/ngrammerge" --method=model_merge --normalize \
            --alpha="$(python3 -c "print(1-${LEG})")" --beta="$LEG" \
            lm/geral.mod lm/legendas.mod "$GERALMOD"
    fi
    "$NG/ngramread" --ARPA --symbols=lm/simbolos.txt <(unk < lm/dominio.arpa) lm/dominio.mod
    "$NG/ngrammerge" --method=model_merge --normalize \
        --alpha="$(python3 -c "print(1-${PESO})")" --beta="$PESO" \
        "$GERALMOD" lm/dominio.mod "lm/mistura-${TAG}.mod"
    "$NG/ngramprint" --ARPA "lm/mistura-${TAG}.mod" > "$MIX"
fi

# --- 5. HCLr (uma vez; não depende do LM) e Gr (por mistura) --------------------
if [[ ! -s hclr/HCLr.fst ]]; then
    log "HCLr (demora)"
    mkdir -p am hclr/lang
    ln -sfn "$BASE/am/final.mdl" am/final.mdl
    ln -sfn "$BASE/am/tree" am/tree
    cp -r lang/* hclr/lang/
    arpa2fst --disambig-symbol='#0' --read-symbol-table=lang/words.txt "$MIX" hclr/lang/G.fst 2> hclr/arpa2fst.log
    # Modelo chain: self-loop-scale 1.0 (o padrão 0.1 do script é para GMM).
    utils/mkgraph_lookahead.sh --self-loop-scale 1.0 hclr/lang am hclr > hclr/mkgraph.log 2>&1 \
        || { tail hclr/mkgraph.log; exit 1; }
fi
G="grafo-${TAG}"
if [[ ! -s "$G/Gr.fst" ]]; then
    log "Gr.fst"
    mkdir -p "$G"
    # O mesmo que o mkgraph_lookahead faz: rótulos de entrada do G trocados
    # pelos que o HCLr espera; os de saída continuam sendo os de words.txt.
    arpa2fst --disambig-symbol='#0' --read-symbol-table=lang/words.txt "$MIX" - 2> "$G/arpa2fst.log" \
        | fstrelabel --relabel_ipairs=hclr/relabel | fstarcsort --sort_type=ilabel \
        | fstconvert --fst_type=const > "$G/Gr.fst"
fi

# --- 6. monta a pasta do modelo, sem HCLG e sem reescore -----------------------
log "montando $SAIDA"
rm -rf "$SAIDA"
mkdir -p "$SAIDA/graph/phones"
cp -r "$BASE/am" "$BASE/conf" "$BASE/ivector" "$SAIDA/"
if [[ "${HCLG:-0}" == 1 ]]; then
    [[ -s "$G/HCLG.fst" ]] || { log "compondo HCLG"
        fstcompose hclr/HCLr.fst "$G/Gr.fst" | fstrmsymbols hclr/disambig_tid.int \
            | fstconvert --fst_type=const > "$G/HCLG.fst"; }
    cp "$G/HCLG.fst" "$SAIDA/graph/"
else
    cp hclr/HCLr.fst hclr/disambig_tid.int "$G/Gr.fst" "$SAIDA/graph/"
fi
cp lang/words.txt lang/phones.txt "$SAIDA/graph/"
cp lang/phones/word_boundary.int "$SAIDA/graph/phones/"
log "pronto: $SAIDA ($(du -sh "$SAIDA" | cut -f1))"
