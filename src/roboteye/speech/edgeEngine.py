"""Motor de TTS online, pelas vozes neurais da Microsoft.

E o unico motor daqui que precisa de internet, e existe por um motivo so: em
portugues do Brasil ele soa audivelmente mais natural que qualquer coisa que
rode offline hoje. O Piper entrega uma voz clara mas plana; o Kokoro entrega
prosodia melhor; estas vozes entregam entonacao de frase — sobem no fim de uma
pergunta, pausam numa virgula.

Nao substitui o motor local, complementa: e por isso que o catalogo continua com
vozes offline e que ha uma queda automatica para elas quando a rede falha (veja
`fallback.py`).

**Formato.** A API devolve MP3 de 24 kHz a 48 kbps, entao o audio passa por uma
compressao com perdas antes de chegar aqui — algo que os motores locais nao
sofrem. Na pratica a naturalidade da voz compensa de sobra, mas vale saber que
o teto de qualidade do sinal e esse.

**Latencia.** Cada frase e sintetizada inteira antes de comecar a tocar: a ida e
volta na rede domina o tempo, e cortar o MP3 em pedacos para ganhar alguns
milissegundos traz risco de estalo nas emendas. Como o texto ja chega ao locutor
frase a frase, a fala continua comecando cedo.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from roboteye.loggingSetup import getLogger
from roboteye.speech.base import AudioFormat, SpeechChunk, SpeechError

if TYPE_CHECKING:
    from roboteye.config import VoiceSettings

logger = getLogger(__name__)

_INSTALL_HINT = 'Vozes online nao instaladas. Rode: pip install -e ".[online]"'

#: Formato fixo devolvido pela API.
SAMPLE_RATE = 24000

DEFAULT_SPEAKER = "pt-BR-ThalitaMultilingualNeural"

#: Tempo limite para abrir a conexao e para receber o audio, em segundos.
#:
#: Sem teto, uma rede que aceita a conexao e depois emudece — bem mais comum que
#: uma que recusa — deixaria o locutor pendurado sem nunca falhar, e a reserva
#: offline nunca entraria em acao. Um limite baixo e o que transforma "o robo
#: travou" em "o robo trocou de voz".
#:
#: Inteiros: a biblioteca recusa ponto flutuante.
CONNECT_TIMEOUT = 8
RECEIVE_TIMEOUT = 25

#: Servidor que a biblioteca procura. So e usado para perguntar se ja da para
#: chegar la (ver `alcancavel`); quem abre a conexao de verdade e o `edge_tts`.
SERVIDOR = "speech.platform.bing.com"


class EdgeEngine:
    """Sintetiza voz pelas vozes neurais da Microsoft."""

    name = "edge"

    def __init__(self, settings: VoiceSettings) -> None:
        self.settings = settings
        self.speaker = settings.speaker or DEFAULT_SPEAKER
        self.ready = False

    # -- ciclo de vida -----------------------------------------------------
    def warmUp(self) -> None:
        """Confere que as dependencias existem. Nao ha modelo para carregar."""
        if self.ready:
            return
        imports()
        self.ready = True

    def close(self) -> None:
        self.ready = False

    def alcancavel(self) -> bool:
        """Se da para chegar ao servidor de sintese agora.

        So resolve o nome — nao abre conexao nem sintetiza — porque a pergunta
        precisa custar milissegundos quando a rede esta de pe, e porque e
        exatamente a resolucao de nome que falha quando o robo acabou de ligar
        (`Temporary failure in name resolution`).

        Existe para o `FallbackEngine` saber esperar em vez de desistir: ver o
        comentario sobre o arranque em `fallback.py`.
        """
        try:
            socket.getaddrinfo(SERVIDOR, 443, proto=socket.IPPROTO_TCP)
        except OSError:
            return False
        return True

    # -- sintese -----------------------------------------------------------
    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        if not text.strip():
            return

        self.warmUp()
        audio = asyncio.run(self.download(text))
        if not audio:
            raise SpeechError("a sintese online nao devolveu audio")

        yield SpeechChunk(
            audio=decodeMp3(audio),
            format=AudioFormat(sampleRate=SAMPLE_RATE, channels=1, sampleWidth=2),
        )

    async def download(self, text: str) -> bytes:
        edge_tts, _ = imports()

        speech = edge_tts.Communicate(
            text,
            self.speaker,
            rate=self.rate(),
            pitch=self.pitch(),
            connect_timeout=CONNECT_TIMEOUT,
            receive_timeout=RECEIVE_TIMEOUT,
        )
        chunks: list[bytes] = []
        try:
            async for chunk in speech.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
        except Exception as exc:
            raise SpeechError(f"falha na sintese online ({self.speaker}): {exc}") from exc

        return b"".join(chunks)

    def rate(self) -> str:
        """Converte `length_scale` no formato de porcentagem que a API espera.

        `length_scale` estica a fala (1,2 = 20% mais lenta), enquanto a API pede
        a variacao de *velocidade*: uma e o inverso da outra.
        """
        scale = max(0.1, self.settings.lengthScale)
        percent = round((1.0 / scale - 1.0) * 100.0)
        return f"{percent:+d}%"

    def pitch(self) -> str:
        """Tom, no formato de Hz por semitom que a API espera.

        Descer o tom e o que mais deixa a voz macia — mais que falar devagar,
        que soa arrastado. A API fala em Hz; um semitom vale cerca de 12 Hz na
        faixa de uma voz feminina, que e a aproximacao que ela mesma usa.
        """
        return f"{round(self.settings.pitch * 12):+d}Hz"


def imports() -> tuple[Any, Any]:
    try:
        import edge_tts
        import miniaudio
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise SpeechError(_INSTALL_HINT) from exc
    return edge_tts, miniaudio


def decodeMp3(data: bytes) -> bytes:
    """Converte o MP3 devolvido pela API em PCM de 16 bits."""
    _, miniaudio = imports()

    try:
        decoded = miniaudio.decode(
            data,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sampleRate=SAMPLE_RATE,
        )
    except Exception as exc:
        raise SpeechError(f"falha ao decodificar o audio online: {exc}") from exc

    return decoded.samples.tobytes()
