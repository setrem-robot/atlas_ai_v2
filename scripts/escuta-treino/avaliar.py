#!/usr/bin/env python3
"""Mede um modelo Vosk no banco de testes: WER e acerto de frase, por SNR e tipo.

O áudio passa pelo mesmo caminho do robô (`voskEars.py`): 0,5 s de silêncio de
partida, o passa-alta de 150 Hz do `microfone.py` e blocos de 30 ms. O ruído é
o gravado no microfone do Pi, somado com a relação sinal-ruído medida *depois*
do passa-alta — abaixo de 150 Hz o ruído do dongle é quase todo zumbido que o
robô já joga fora, e contá-lo daria SNRs otimistas de mentira.

Cada linha do resultado guarda a hipótese, para analisar os erros depois.
Retomável: um resultado já gravado para o mesmo rótulo não é refeito.

Uso:
  python avaliar.py --modelo DIR --rotulo base --banco DIR --ruido WAV [--snr limpo 15 10 5]
  python avaliar.py --resumo resultados/*.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import resource
import sys
import time
import unicodedata
import wave
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parents[1] / "src"))
sys.path.insert(0, str(AQUI))

from gerar_audio import lerFrases  # noqa: E402
from roboteye.hearing.microfone import BLOCO, CORTE_GRAVES_HZ, TAXA, PassaAlta  # noqa: E402
from roboteye.hearing.voskEars import SILENCIO_DE_PARTIDA_S, limparTexto  # noqa: E402

ANTES_S = 0.6  # ruído antes da fala: no robô o microfone nunca começa mudo
DEPOIS_S = 1.0  # e depois, para o Vosk fechar a frase pelo silêncio, como lá


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFC", texto.lower())
    return " ".join(re.sub(r"[^\w\s]", " ", texto).split())


def distancia(ref: list[str], hip: list[str]) -> int:
    """Levenshtein por palavra."""
    linha = list(range(len(hip) + 1))
    for i, r in enumerate(ref, 1):
        nova = [i]
        for j, h in enumerate(hip, 1):
            nova.append(min(linha[j] + 1, nova[j - 1] + 1, linha[j - 1] + (r != h)))
        linha = nova
    return linha[-1]


def lerWav(caminho: Path) -> np.ndarray:
    with wave.open(str(caminho)) as w:
        assert w.getframerate() == TAXA and w.getnchannels() == 1, caminho
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16) / 32768.0


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x**2)) + 1e-12)


def filtrar(x: np.ndarray) -> np.ndarray:
    return PassaAlta(CORTE_GRAVES_HZ, TAXA).aplicar(x.astype(np.float32))


def montar(fala: np.ndarray, ruido: np.ndarray, snr: str, semente: int) -> np.ndarray:
    """Fala + ruído do Pi, já filtrada como o robô filtra."""
    antes, depois = int(ANTES_S * TAXA), int(DEPOIS_S * TAXA)
    total = antes + len(fala) + depois
    sinal = np.concatenate([np.zeros(antes), fala, np.zeros(depois)])
    if snr != "limpo":
        inicio = np.random.default_rng(semente).integers(0, len(ruido) - total)
        trecho = ruido[inicio : inicio + total]
        # A SNR vale na banda que chega ao Vosk, depois do passa-alta.
        ganho = rms(filtrar(fala)) / rms(filtrar(trecho)) / 10 ** (float(snr) / 20)
        sinal = sinal + trecho * ganho
    return filtrar(sinal)


def decodificar(modelo, audio: np.ndarray) -> str:
    from vosk import KaldiRecognizer

    rec = KaldiRecognizer(modelo, TAXA)
    partida = np.zeros(int(SILENCIO_DE_PARTIDA_S * TAXA))
    pcm = (np.clip(np.concatenate([partida, audio]), -1, 1) * 32767).astype(np.int16).tobytes()
    textos = []
    for i in range(0, len(pcm), BLOCO * 2):
        if rec.AcceptWaveform(pcm[i : i + BLOCO * 2]):
            textos.append(json.loads(rec.Result()).get("text", ""))
    textos.append(json.loads(rec.FinalResult()).get("text", ""))
    return limparTexto(" ".join(textos))


def avaliar(a) -> None:
    from vosk import Model, SetLogLevel

    saida = Path(a.resultados) / f"{a.rotulo}.jsonl"
    feitos = set()
    if saida.exists():
        for linha in saida.read_text(encoding="utf-8").splitlines():
            d = json.loads(linha)
            feitos.add((d["voz"], d["i"], d["snr"]))
    frases = lerFrases()
    ruido = lerWav(Path(a.ruido))
    vozes = sorted(p.name for p in Path(a.banco).iterdir() if p.is_dir())
    if a.vozes:
        vozes = [v for v in vozes if v in a.vozes]
    tarefas = [
        (v, i, s) for s in a.snr for v in vozes for i in range(len(frases)) if (v, i, s) not in feitos
    ]
    if not tarefas:
        print(f"{a.rotulo}: nada a fazer")
        return
    SetLogLevel(-1)
    t0 = time.time()
    modelo = Model(a.modelo)
    print(f"{a.rotulo}: modelo carregado em {time.time() - t0:.1f} s; {len(tarefas)} decodificações")

    def uma(tarefa):
        voz, i, snr = tarefa
        fala = lerWav(Path(a.banco) / voz / f"{i:03d}.wav")
        # crc32 e não hash(): o trecho de ruído tem de ser o mesmo entre modelos.
        audio = montar(fala, ruido, snr, semente=zlib.crc32(f"{voz}{i}".encode()))
        t = time.perf_counter()
        hip = decodificar(modelo, audio)
        seg = time.perf_counter() - t
        categoria, texto = frases[i]
        ref = normalizar(texto)
        hipN = normalizar(hip)
        return {
            "voz": voz, "i": i, "snr": snr, "cat": categoria, "ref": ref, "hip": hipN,
            "erros": distancia(ref.split(), hipN.split()), "palavras": len(ref.split()),
            "rtf": seg / (len(audio) / TAXA),
        }

    with saida.open("a", encoding="utf-8") as f, ThreadPoolExecutor(a.threads) as pool:
        for n, r in enumerate(pool.map(uma, tarefas), 1):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            if n % 100 == 0:
                f.flush()
                print(f"  {n}/{len(tarefas)}", flush=True)
    # Pico de RAM do processo inteiro: modelo + reconhecedores. No Pi é o número
    # que decide se o modelo cabe ao lado da LLM e da face.
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"{a.rotulo}: pico de RAM {pico:.0f} MiB, {time.time() - t0:.0f} s no total")


def resumo(arquivos: list[str]) -> None:
    """Tabela WER% / acerto de frase% por rótulo x categoria x SNR."""
    print(f"{'rótulo':28} {'snr':>6} " + " ".join(f"{c:>17}" for c in ("dominio", "nomes", "geral", "todas")))
    for arq in arquivos:
        linhas = [json.loads(x) for x in Path(arq).read_text(encoding="utf-8").splitlines()]
        snrs = sorted({d["snr"] for d in linhas}, key=lambda s: -1e9 if s == "limpo" else -float(s))
        for snr in snrs:
            celulas = []
            for cat in ("dominio", "nomes", "geral", None):
                sel = [d for d in linhas if d["snr"] == snr and (cat is None or d["cat"] == cat)]
                if not sel:
                    celulas.append(f"{'-':>17}")
                    continue
                wer = 100 * sum(d["erros"] for d in sel) / sum(d["palavras"] for d in sel)
                ok = 100 * sum(d["erros"] == 0 for d in sel) / len(sel)
                celulas.append(f"{wer:6.1f}% / {ok:5.1f}%  ")
            print(f"{Path(arq).stem:28} {snr:>6} " + " ".join(celulas))
        rtf = np.mean([d["rtf"] for d in linhas])
        print(f"{'':28} {'rtf':>6} {rtf:.3f} (PC, {len(linhas)} decodificações)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--modelo")
    p.add_argument("--rotulo")
    p.add_argument("--banco")
    p.add_argument("--ruido")
    p.add_argument("--snr", nargs="+", default=["limpo", "15", "10", "5"])
    p.add_argument("--vozes", nargs="*")
    p.add_argument("--threads", type=int, default=os.cpu_count() - 2)
    p.add_argument("--resultados", default="resultados")
    p.add_argument("--resumo", nargs="*")
    a = p.parse_args()
    if a.resumo:
        resumo(a.resumo)
    else:
        Path(a.resultados).mkdir(parents=True, exist_ok=True)
        avaliar(a)


if __name__ == "__main__":
    main()
