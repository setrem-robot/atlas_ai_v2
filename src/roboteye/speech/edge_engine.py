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
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from roboteye.logging_setup import get_logger
from roboteye.speech.base import AudioFormat, SpeechChunk, SpeechError

if TYPE_CHECKING:
    from roboteye.config import VoiceSettings

logger = get_logger(__name__)

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


class EdgeEngine:
    """Sintetiza voz pelas vozes neurais da Microsoft."""

    name = "edge"

    def __init__(self, settings: VoiceSettings) -> None:
        self._settings = settings
        self._speaker = settings.speaker or DEFAULT_SPEAKER
        self._ready = False

    # -- ciclo de vida -----------------------------------------------------
    def warm_up(self) -> None:
        """Confere que as dependencias existem. Nao ha modelo para carregar."""
        if self._ready:
            return
        _imports()
        self._ready = True

    def close(self) -> None:
        self._ready = False

    # -- sintese -----------------------------------------------------------
    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        if not text.strip():
            return

        self.warm_up()
        audio = asyncio.run(self._download(text))
        if not audio:
            raise SpeechError("a sintese online nao devolveu audio")

        yield SpeechChunk(
            audio=_decode_mp3(audio),
            format=AudioFormat(sample_rate=SAMPLE_RATE, channels=1, sample_width=2),
        )

    async def _download(self, text: str) -> bytes:
        edge_tts, _ = _imports()

        speech = edge_tts.Communicate(
            text,
            self._speaker,
            rate=self._rate(),
            pitch=self._pitch(),
            connect_timeout=CONNECT_TIMEOUT,
            receive_timeout=RECEIVE_TIMEOUT,
        )
        chunks: list[bytes] = []
        try:
            async for chunk in speech.stream():
                if chunk["type"] == "audio":
                    chunks.append(chunk["data"])
        except Exception as exc:
            raise SpeechError(f"falha na sintese online ({self._speaker}): {exc}") from exc

        return b"".join(chunks)

    def _rate(self) -> str:
        """Converte `length_scale` no formato de porcentagem que a API espera.

        `length_scale` estica a fala (1,2 = 20% mais lenta), enquanto a API pede
        a variacao de *velocidade*: uma e o inverso da outra.
        """
        scale = max(0.1, self._settings.length_scale)
        percent = round((1.0 / scale - 1.0) * 100.0)
        return f"{percent:+d}%"

    def _pitch(self) -> str:
        """Tom, no formato de Hz por semitom que a API espera.

        Descer o tom e o que mais deixa a voz macia — mais que falar devagar,
        que soa arrastado. A API fala em Hz; um semitom vale cerca de 12 Hz na
        faixa de uma voz feminina, que e a aproximacao que ela mesma usa.
        """
        return f"{round(self._settings.pitch * 12):+d}Hz"


def _imports() -> tuple[Any, Any]:
    try:
        import edge_tts
        import miniaudio
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise SpeechError(_INSTALL_HINT) from exc
    return edge_tts, miniaudio


def _decode_mp3(data: bytes) -> bytes:
    """Converte o MP3 devolvido pela API em PCM de 16 bits."""
    _, miniaudio = _imports()

    try:
        decoded = miniaudio.decode(
            data,
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=1,
            sample_rate=SAMPLE_RATE,
        )
    except Exception as exc:
        raise SpeechError(f"falha ao decodificar o audio online: {exc}") from exc

    return decoded.samples.tobytes()
