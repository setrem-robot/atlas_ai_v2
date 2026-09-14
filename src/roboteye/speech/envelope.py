"""O quanto a voz esta alta, agora.

A face animava a fala com uma soma de tres senoides. Funcionava como sinal de
vida, mas nao tinha como estar certa: o olho pulsava no mesmo ritmo tanto numa
palavra longa quanto numa pausa, porque nunca soube o que estava tocando. E a
diferenca entre uma boca que fala e uma boca que mexe.

Aqui o mesmo PCM que vai para o alto-falante passa antes por um medidor, que o
reduz a um envelope de amplitude — um valor por quadro de 20 ms. A face le esse
valor e se move junto com a voz de verdade.

**Sincronizacao.** O medidor nao ve o alto-falante, so o audio entrando. Como o
audio toca em tempo real e sem buracos, basta ancorar o primeiro bloco num
instante e deixar o relogio andar: o resto se posiciona sozinho na fila. O unico
erro sistematico e o atraso do buffer da placa, que e constante e por isso pode
ser descontado de uma vez (`latency`).

O medidor e escrito pela thread do locutor e lido pela thread da face, entao
tudo que ele guarda vive sob um cadeado.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from roboteye.speech.base import AudioFormat

#: Duracao de cada passo do envelope. 20 ms e a escala da silaba: mais curto
#: capta o tremor de cada periodo da voz, mais longo perde o ataque das palavras.
FRAME_SECONDS = 0.020

#: Atraso tipico entre entregar o PCM e ele sair no alto-falante. Descontado
#: para que o movimento nao chegue adiantado em relacao ao som.
DEFAULT_LATENCY = 0.12

#: Nivel de referencia (RMS) que corresponde a "voz alta". Serve de piso para o
#: rastreador de pico, para que uma frase sussurrada nao seja amplificada ate
#: parecer um grito.
REFERENCE_RMS = 0.09

#: Quanto o pico observado decai por segundo. Lento de proposito: o objetivo e
#: acompanhar a diferenca de volume entre vozes, nao entre silabas.
PEAK_DECAY = 0.35

#: Teto de audio ainda nao tocado que vale a pena guardar, em segundos.
#:
#: Normalmente a fila se regula sozinha, porque escrever no alto-falante bloqueia
#: quando o buffer enche e o locutor nao consegue correr na frente. Um destino
#: que nao bloqueia (o silencioso, por exemplo) nao oferece esse freio, e ai a
#: fila acompanharia a fala inteira. O teto e generoso: serve de rede, nao de
#: politica.
MAX_QUEUE_SECONDS = 60.0


class SpeechEnvelope:
    """Envelope de amplitude do audio em reproducao."""

    def __init__(self, *, latency: float = DEFAULT_LATENCY) -> None:
        self.latency = max(0.0, latency)
        self.lock = threading.Lock()
        self.levels: list[float] = []
        #: Instante (relogio monotonico) em que `_levels[0]` chega ao ouvido.
        self.origin: float | None = None
        self.peak = REFERENCE_RMS
        self.active = False

    # -- escrita (thread do locutor) ---------------------------------------
    def begin(self) -> None:
        """Marca o inicio de uma fala, antes de o primeiro audio existir."""
        with self.lock:
            self.active = True

    def end(self) -> None:
        """Marca o fim de uma fala e devolve o medidor ao repouso."""
        with self.lock:
            self.active = False
            self.levels.clear()
            self.origin = None

    def feed(self, audio: bytes, audioFormat: AudioFormat) -> None:
        """Registra um bloco de PCM que acabou de ser entregue a placa."""
        levels = rmsFrames(audio, audioFormat)
        if not levels.size:
            return

        now = time.monotonic()
        with self.lock:
            self.active = True
            playingUntil = self.playingUntil()

            if playingUntil is None or playingUntil <= now:
                # Nada tocando: este bloco abre uma nova fila. O atraso do buffer
                # entra aqui, uma vez so.
                self.origin = now + self.latency
                self.levels = list(levels)
            else:
                # Ja ha audio na fila; este bloco toca logo depois dele.
                self.levels.extend(levels.tolist())

            self.peak = max(self.peak, float(levels.max()))
            self.discardPlayed(now)

    # -- leitura (thread da face) ------------------------------------------
    def level(self) -> float | None:
        """Amplitude atual, de 0 a 1, ou `None` se nao ha medicao.

        `None` nao e o mesmo que zero: significa que este caminho de audio nao
        informa amplitude nenhuma — um motor silencioso, por exemplo. Quem
        anima precisa distinguir os dois casos, porque em silencio o olho deve
        ficar parado e sem medicao ele deve cair no movimento sintetico.
        """
        now = time.monotonic()
        with self.lock:
            if not self.active:
                return None
            if self.origin is None:
                return 0.0

            # Fora da fila: ou o audio ainda nao soou, ou ja acabou. Nos dois
            # casos a resposta e silencio — o olho fica parado numa pausa, que e
            # exatamente o que deveria acontecer.
            index = int((now - self.origin) / FRAME_SECONDS)
            if not 0 <= index < len(self.levels):
                return 0.0

            return min(1.0, self.levels[index] / max(self.peak, REFERENCE_RMS))

    @property
    def isActive(self) -> bool:
        with self.lock:
            return self.active

    # -- interno ------------------------------------------------------------
    def playingUntil(self) -> float | None:
        if self.origin is None:
            return None
        return self.origin + len(self.levels) * FRAME_SECONDS

    def discardPlayed(self, now: float) -> None:
        """Descarta o passado, para a fila nao crescer durante uma fala longa."""
        if self.origin is None:
            return
        played = int((now - self.origin) / FRAME_SECONDS)
        limit = int(MAX_QUEUE_SECONDS / FRAME_SECONDS)
        drop = max(played, len(self.levels) - limit)
        if drop <= 0:
            return
        del self.levels[:drop]
        self.origin += drop * FRAME_SECONDS
        self.peak = max(REFERENCE_RMS, self.peak * (1.0 - PEAK_DECAY * FRAME_SECONDS * drop))


def rmsFrames(audio: bytes, audioFormat: AudioFormat) -> np.ndarray:
    """Reduz um bloco de PCM a um valor RMS por quadro de `FRAME_SECONDS`."""
    if audioFormat.sampleWidth != 2 or not audio:
        return np.empty(0, dtype=np.float32)

    samples = np.frombuffer(audio, dtype="<i2").astype(np.float32) / 32768.0
    if audioFormat.channels > 1:
        usable = samples.size - (samples.size % audioFormat.channels)
        samples = samples[:usable].reshape(-1, audioFormat.channels).mean(axis=1)

    perFrame = max(1, int(audioFormat.sampleRate * FRAME_SECONDS))
    usable = samples.size - (samples.size % perFrame)
    if usable <= 0:
        return np.array([float(np.sqrt(np.mean(samples**2)))], dtype=np.float32)

    blocks = samples[:usable].reshape(-1, perFrame)
    return np.sqrt((blocks * blocks).mean(axis=1)).astype(np.float32)
