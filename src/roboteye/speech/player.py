"""Saida de audio.

Um `AudioSink` recebe PCM cru e o reproduz. O padrao usa `sounddevice`
(PortAudio, funciona em Windows, Linux e macOS); em Linux sem PortAudio ha um
fallback que escreve no `aplay`, o que cobre o Raspberry Pi com instalacao minima.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any, Protocol

from roboteye.logging_setup import get_logger
from roboteye.speech.base import AudioFormat, SpeechError
from roboteye.speech.devices import AUTO, resolver_saida

if TYPE_CHECKING:
    from roboteye.config import VoiceSettings

logger = get_logger(__name__)


class AudioSink(Protocol):
    """Destino de reproducao de PCM."""

    name: str

    def start(self, audio_format: AudioFormat) -> None:
        """Prepara a reproducao para um formato. Reabre se o formato mudou."""
        ...

    def write(self, audio: bytes) -> None:
        """Reproduz um bloco de PCM (bloqueante ate caber no buffer)."""
        ...

    def stop(self) -> None:
        """Interrompe a reproducao atual e descarta o que estiver em buffer."""
        ...

    def close(self) -> None:
        """Libera o dispositivo."""
        ...


# ---------------------------------------------------------------------------
# sounddevice (padrao, multiplataforma)
# ---------------------------------------------------------------------------
class SoundDeviceSink:
    """Reproducao via PortAudio."""

    name = "sounddevice"

    def __init__(self, device: str | int | None = None) -> None:
        self._device = device
        self._stream: Any | None = None
        self._format: AudioFormat | None = None

    def start(self, audio_format: AudioFormat) -> None:
        if self._stream is not None and self._format == audio_format:
            return

        self.close()

        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:  # pragma: no cover - depende do ambiente
            raise SpeechError(f"sounddevice indisponivel: {exc}") from exc

        if audio_format.sample_width != 2:
            raise SpeechError(
                f"apenas PCM de 16 bits e suportado (recebi {audio_format.sample_width * 8} bits)"
            )

        try:
            self._stream = sd.RawOutputStream(
                samplerate=audio_format.sample_rate,
                channels=audio_format.channels,
                dtype="int16",
                device=self._device,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise SpeechError(f"nao foi possivel abrir o dispositivo de audio: {exc}") from exc

        self._format = audio_format

    def write(self, audio: bytes) -> None:
        if self._stream is None:
            raise SpeechError("write() chamado antes de start()")
        try:
            self._stream.write(audio)
        except Exception as exc:
            # Fechar aqui é o que faz a voz voltar sozinha.
            #
            # A placa USB deste robô se desconecta e reaparece com outro número
            # de dispositivo; do lado do ALSA isso vira
            # `write failed (unrecoverable): No such device`. Sem este `close`,
            # o stream morto continua guardado, `start()` vê o formato igual e
            # volta na hora sem reabrir nada — e **toda** fala seguinte falha do
            # mesmo jeito, para sempre. O robô ficava mudo até alguém reiniciar
            # o serviço, sem nada além de um erro por frase no log.
            self.close()
            raise SpeechError(f"a saida de audio falhou: {exc}") from exc

    def stop(self) -> None:
        if self._stream is None:
            return

        # abort() descarta o buffer; stop() esperaria o audio pendente terminar.
        # Alguns drivers (notadamente o MME do Windows) recusam abort/start
        # enquanto ainda ha dados na placa. Nesse caso descartamos o stream: o
        # proximo start() o reabre limpo, que e exatamente o efeito desejado.
        try:
            self._stream.abort()
            self._stream.start()
        except Exception:
            logger.debug("driver recusou abortar o stream; reabrindo", exc_info=True)
            self.close()

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                logger.debug("erro ao fechar o stream de audio", exc_info=True)
            self._stream = None
        self._format = None


# ---------------------------------------------------------------------------
# aplay (fallback para Linux/Raspberry Pi)
# ---------------------------------------------------------------------------
class AplaySink:
    """Reproducao encaminhando PCM para o `aplay` do ALSA."""

    name = "aplay"

    def __init__(self, device: str | None = None) -> None:
        self._device = device
        self._process: subprocess.Popen[bytes] | None = None
        self._format: AudioFormat | None = None

    def start(self, audio_format: AudioFormat) -> None:
        if self._process is not None and self._format == audio_format:
            return

        self.close()

        command = [
            "aplay",
            "-q",
            "-t",
            "raw",
            "-f",
            f"S{audio_format.sample_width * 8}_LE",
            "-r",
            str(audio_format.sample_rate),
            "-c",
            str(audio_format.channels),
        ]
        if self._device:
            command += ["-D", self._device]

        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE)
        except OSError as exc:
            raise SpeechError(f"nao foi possivel iniciar o aplay: {exc}") from exc

        self._format = audio_format

    def write(self, audio: bytes) -> None:
        if self._process is None or self._process.stdin is None:
            raise SpeechError("write() chamado antes de start()")
        try:
            self._process.stdin.write(audio)
            self._process.stdin.flush()
        except OSError as exc:
            # Mesma razão do `SoundDeviceSink.write`: sem soltar o processo
            # morto, `start()` acha que ainda há um `aplay` de pé e a voz não
            # volta nunca mais.
            self.close()
            raise SpeechError(f"aplay encerrou durante a reproducao: {exc}") from exc

    def stop(self) -> None:
        # aplay nao permite descartar o buffer: reiniciamos o processo.
        audio_format = self._format
        self.close()
        if audio_format is not None:
            self.start(audio_format)

    def close(self) -> None:
        if self._process is not None:
            try:
                if self._process.stdin is not None:
                    self._process.stdin.close()
                self._process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self._process.kill()
            self._process = None
        self._format = None


# ---------------------------------------------------------------------------
# Silencioso
# ---------------------------------------------------------------------------
class NullSink:
    """Descarta o audio. Usado em testes e em ambientes sem som."""

    name = "null"

    def start(self, audio_format: AudioFormat) -> None:
        return None

    def write(self, audio: bytes) -> None:
        return None

    def stop(self) -> None:
        return None

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Selecao
# ---------------------------------------------------------------------------
def create_audio_sink(settings: VoiceSettings) -> AudioSink:
    """Escolhe a melhor saida disponivel no sistema."""
    if settings.engine == "null":
        return NullSink()

    device = resolver_saida(settings.audio_device)

    try:
        import sounddevice  # noqa: F401
    except (ImportError, OSError) as exc:
        logger.debug("sounddevice indisponivel (%s)", exc)
    else:
        return SoundDeviceSink(device)

    if sys.platform.startswith("linux") and shutil.which("aplay"):
        logger.info("usando aplay como saida de audio")
        # O `aplay` fala em nome de dispositivo ALSA (`plughw:2,0`), nao no
        # indice que o sounddevice usa; um numero aqui nao significaria nada
        # para ele, entao so o que veio escrito na configuracao serve.
        pedido = settings.audio_device
        return AplaySink(None if pedido == AUTO else pedido)

    logger.warning("nenhuma saida de audio disponivel; a voz sera silenciosa")
    return NullSink()
