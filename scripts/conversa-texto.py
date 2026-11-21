#!/usr/bin/env python3
"""Conversa só em texto: valida escuta, IA e voz da Atlas, sem a face.

Mostra na tela, em texto cru, o que o Vosk está ouvindo enquanto você fala, a
frase que ele fechou, o que a Atlas respondeu e quanto cada etapa levou. Usa a
mesma persona, LLM e voz do robô (`Application.build`); só a face e o filtro do
nome "Atlas" ficam de fora — aqui toda frase é uma pergunta.

Existe porque "ela não me entende" tem causas em camadas diferentes (microfone,
reconhecimento, IA, voz) e a face esconde todas atrás da mesma animação.

Uso, no Pi (a face precisa estar parada, porque ela segura a tela):
    pkill -f "roboteye face"
    SDL_VIDEODRIVER=kmsdrm .venv/bin/python scripts/conversa-texto.py
    sudo systemctl restart roboteye     # volta a face

Sem tela disponível, só imprime no terminal. Sai com Esc, q ou Ctrl+C.
"""

from __future__ import annotations

import json
import queue
import sys
import textwrap
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402

from roboteye.app import Application  # noqa: E402
from roboteye.config import Settings  # noqa: E402
from roboteye.core.events import (  # noqa: E402
    AssistantReply,
    ErrorOccurred,
    SpeechFinished,
    SpeechStarted,
    ThinkingStarted,
)
from roboteye.speech.devices import resolverEntrada  # noqa: E402

TAXA = 16000
#: 0,25 s por bloco: parcial atualiza rápido sem chamar o Vosk 33 vezes por segundo.
BLOCO = 4000
#: O que o Vosk devolve para ruído; sozinho, não é pergunta.
#: Áudio de cada frase reconhecida, para comparar filtros e modelos depois.
FALAS = Path("/tmp/falas")
RUIDO = {"<unk>", "ah", "a", "e", "é", "o", "hum", "hm", "ã", "hã"}

CORES = {
    "voce": (255, 255, 255),
    "parcial": (230, 200, 80),
    "atlas": (90, 210, 255),
    "tempo": (140, 140, 140),
    "ignorado": (90, 90, 90),
    "erro": (255, 90, 90),
}


class Tela:
    """Linhas de texto na tela do Pi, ou só no terminal se não houver tela."""

    def __init__(self) -> None:
        self.linhas: list[tuple[str, str]] = []
        self.parcial = ""
        self.nivel = 0.0
        self.trava = threading.Lock()
        try:
            import pygame

            pygame.display.init()
            pygame.font.init()
            self.superficie = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            pygame.mouse.set_visible(False)
            self.fonte = pygame.font.SysFont("dejavusansmono", 26) or pygame.font.Font(None, 30)
            self.pygame = pygame
        except Exception as exc:
            print(f"(sem tela: {exc}; só terminal)", flush=True)
            self.pygame = None

    def add(self, tipo: str, texto: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} [{tipo}] {texto}", flush=True)
        with self.trava:
            self.linhas.append((tipo, texto))
            del self.linhas[:-200]

    def desenhar(self) -> bool:
        """Desenha um quadro. Devolve False quando pedirem para sair."""
        if self.pygame is None:
            return True
        pg = self.pygame
        for evento in pg.event.get():
            if evento.type == pg.QUIT or (
                evento.type == pg.KEYDOWN and evento.key in (pg.K_ESCAPE, pg.K_q)
            ):
                return False
        largura, altura = self.superficie.get_size()
        _, alturaLinha = self.fonte.size("M")
        colunas = max(20, (largura - 40) // self.fonte.size("M")[0])
        with self.trava:
            itens = list(self.linhas)
            if self.parcial:
                itens.append(("parcial", f"... {self.parcial}"))
        # Nível do microfone ao vivo: se não sobe quando você fala, a voz não chega.
        barra = "#" * min(40, int(self.nivel * 200))
        itens.append(("tempo", f"microfone {self.nivel:.3f} {barra}"))
        quebradas = [
            (tipo, pedaco)
            for tipo, texto in itens
            for pedaco in (textwrap.wrap(texto, colunas) or [""])
        ]
        cabem = (altura - 40) // alturaLinha
        self.superficie.fill((0, 0, 0))
        for i, (tipo, pedaco) in enumerate(quebradas[-cabem:]):
            imagem = self.fonte.render(pedaco, True, CORES[tipo])
            self.superficie.blit(imagem, (20, 20 + i * alturaLinha))
        pg.display.flip()
        return True


def main() -> int:
    tela = Tela()
    settings = Settings.fromEnv()
    app = Application.build(settings)
    blocos: queue.Queue[bytes] = queue.Queue(maxsize=200)
    estado = {"ocupada": False, "desde": 0.0, "fechou": 0.0, "primeiroSom": False, "perdidos": 0}

    def desde() -> str:
        return f"+{time.monotonic() - estado['fechou']:.1f} s"

    app.bus.subscribe(lambda e: tela.add("tempo", f"pensando {desde()}"), eventType=ThinkingStarted)

    def aoFalar(e) -> None:
        if not estado["primeiroSom"]:
            estado["primeiroSom"] = True
            tela.add("tempo", f"primeiro som {desde()}")

    app.bus.subscribe(aoFalar, eventType=SpeechStarted)
    app.bus.subscribe(lambda e: tela.add("atlas", f"ATLAS: {e.text}"), eventType=AssistantReply)
    app.bus.subscribe(lambda e: tela.add("tempo", f"terminou de falar {desde()}"), eventType=SpeechFinished)
    app.bus.subscribe(lambda e: tela.add("erro", f"erro ({e.source}): {e.message}"), eventType=ErrorOccurred)

    tela.add("tempo", "carregando voz, IA e Vosk...")
    inicio = time.monotonic()
    app.speaker.start()
    app.assistant.start()
    app.speaker.warmUp()
    app.llm.warmUp(app.assistant.memory.buildPrompt())
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    modelo = settings.hearing.modelPath / settings.hearing.voskModel
    reconhecedor = KaldiRecognizer(Model(str(modelo)), TAXA)
    dispositivo = resolverEntrada(settings.hearing.device)
    tela.add("tempo", f"pronto em {time.monotonic() - inicio:.1f} s | vosk: {modelo.name} | microfone: {dispositivo or 'padrao'} | modelo IA: {settings.llm.model}")
    tela.add("tempo", "pode falar.")

    def alimentar(entrada, quadros, tempo, status) -> None:
        if estado["ocupada"]:
            return  # não transcreve a própria Atlas
        try:
            blocos.put_nowait(bytes(entrada))
            tela.nivel = int(np.abs(np.frombuffer(entrada, np.int16).astype(np.int32)).max()) / 32768
        except queue.Full:
            estado["perdidos"] += 1

    def escutar() -> None:
        comecou = 0.0
        audio = bytearray()
        FALAS.mkdir(exist_ok=True)
        while True:
            bloco = blocos.get()
            if estado["ocupada"]:
                continue
            audio += bloco
            t0 = time.perf_counter()
            if not reconhecedor.AcceptWaveform(bloco):
                parcial = json.loads(reconhecedor.PartialResult()).get("partial", "")
                if parcial and not comecou:
                    comecou = time.monotonic()
                tela.parcial = parcial
                continue
            ms = (time.perf_counter() - t0) * 1000
            texto = json.loads(reconhecedor.Result()).get("text", "").strip()
            tela.parcial = ""
            falou = time.monotonic() - comecou if comecou else 0.0
            comecou = 0.0
            frase, audio = bytes(audio), bytearray()
            palavras = [p for p in texto.split() if p.lower() != "<unk>"]
            # Sem parcial nenhum antes, não houve fala: é o Vosk fechando a frase
            # após 5 s de silêncio e lendo o ruído de fundo como palavra.
            if not falou or not palavras or (len(palavras) == 1 and palavras[0].lower() in RUIDO):
                if texto:
                    tela.add("ignorado", f"(ruido: {texto})")
                continue
            pergunta = " ".join(palavras)
            arquivo = FALAS / f"{time.strftime('%H%M%S')}.wav"
            with wave.open(str(arquivo), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(TAXA), w.writeframes(frase)
            arquivo.with_suffix(".txt").write_text(pergunta, encoding="utf-8")
            perdidos, estado["perdidos"] = estado["perdidos"], 0
            aviso = f" | {perdidos} blocos de audio PERDIDOS" if perdidos else ""
            tela.add("voce", f"VOCE: {pergunta}")
            tela.add("tempo", f"fala {falou:.1f} s | vosk fechou em {ms:.0f} ms{aviso}")
            estado.update(ocupada=True, desde=time.monotonic(), fechou=time.monotonic(), primeiroSom=False)
            app.assistant.submit(pergunta)

    threading.Thread(target=escutar, name="escuta", daemon=True).start()
    with sd.RawInputStream(
        samplerate=TAXA, blocksize=BLOCO, device=dispositivo, dtype="int16", channels=1, callback=alimentar
    ):
        try:
            while tela.desenhar():
                # A Atlas acabou (falou, falhou ou não tinha o que dizer): volta a ouvir.
                if (
                    estado["ocupada"]
                    and time.monotonic() - estado["desde"] > 1.0
                    and not app.assistant.isBusy
                    and not app.speaker.isSpeaking
                ):
                    reconhecedor.Reset()
                    with blocos.mutex:
                        blocos.queue.clear()
                    estado["ocupada"] = False
                    tela.add("tempo", "ouvindo.")
                time.sleep(1 / 15)
        except KeyboardInterrupt:
            pass
    app.assistant.close()
    app.speaker.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
