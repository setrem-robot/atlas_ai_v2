#!/usr/bin/env python3
"""Sintetiza o banco de testes da escuta com várias vozes, em 16 kHz mono.

Cada frase de `frases-teste.tsv` sai uma vez por voz: Piper (offline, quatro
vozes pt_BR) e Edge (vozes neurais da Microsoft, precisam de rede). Voz
sintética não é voz de gente, mas varia timbre, gênero e ritmo o bastante para
comparar modelos entre si — que é tudo o que este banco precisa fazer.

Retomável: arquivo que já existe não é refeito.

Uso:  python gerar_audio.py --vozes DIR_ONNX --saida DIR_BANCO
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import tempfile
import wave
from pathlib import Path

AQUI = Path(__file__).resolve().parent

PIPER = {  # nome curto -> (arquivo .onnx, length_scale): ritmos diferentes de propósito
    "dii": ("pt_BR-dii-high.onnx", 1.0),
    "faber": ("pt_BR-faber-medium.onnx", 0.9),
    "cadu": ("pt_BR-cadu-medium.onnx", 1.1),
    "jeff": ("pt_BR-jeff-medium.onnx", 1.0),
}
EDGE = {
    "francisca": ("pt-BR-FranciscaNeural", "+0%"),
    "antonio": ("pt-BR-AntonioNeural", "+10%"),
    "thalita": ("pt-BR-ThalitaMultilingualNeural", "-5%"),
}


def lerFrases(caminho: Path = AQUI / "frases-teste.tsv") -> list[tuple[str, str]]:
    """(categoria, frase falada), na ordem do arquivo; o índice vira o nome do wav."""
    frases = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip() and not linha.startswith("#"):
            categoria, texto = linha.split("\t", 1)
            frases.append((categoria, texto.strip()))
    return frases


def para16k(origem: Path, destino: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-i", str(origem), "-ac", "1", "-ar", "16000",
         "-sample_fmt", "s16", str(destino)],
        check=True,
    )


def gerarPiper(frases, dirVozes: Path, saida: Path) -> None:
    from piper import PiperVoice, SynthesisConfig

    for nome, (onnx, escala) in PIPER.items():
        pasta = saida / nome
        pasta.mkdir(parents=True, exist_ok=True)
        faltam = [(i, t) for i, (_, t) in enumerate(frases) if not (pasta / f"{i:03d}.wav").exists()]
        if not faltam:
            continue
        voz = PiperVoice.load(str(dirVozes / onnx))
        for i, texto in faltam:
            with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
                with wave.open(tmp.name, "wb") as w:
                    voz.synthesize_wav(texto, w, SynthesisConfig(length_scale=escala))
                para16k(Path(tmp.name), pasta / f"{i:03d}.wav")
        print(f"piper {nome}: {len(faltam)} frases")


async def gerarEdge(frases, saida: Path) -> None:
    import edge_tts

    for nome, (voz, ritmo) in EDGE.items():
        pasta = saida / nome
        pasta.mkdir(parents=True, exist_ok=True)
        n = 0
        for i, (_, texto) in enumerate(frases):
            destino = pasta / f"{i:03d}.wav"
            if destino.exists():
                continue
            with tempfile.NamedTemporaryFile(suffix=".mp3") as tmp:
                await edge_tts.Communicate(texto, voz, rate=ritmo).save(tmp.name)
                para16k(Path(tmp.name), destino)
            n += 1
        print(f"edge {nome}: {n} frases")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--vozes", type=Path, required=True)
    p.add_argument("--saida", type=Path, required=True)
    p.add_argument("--sem-edge", action="store_true")
    a = p.parse_args()
    frases = lerFrases()
    gerarPiper(frases, a.vozes, a.saida)
    if not a.sem_edge:
        asyncio.run(gerarEdge(frases, a.saida))


if __name__ == "__main__":
    main()
