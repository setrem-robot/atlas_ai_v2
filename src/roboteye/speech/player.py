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

from roboteye.loggingSetup import getLogger
from roboteye.speech.base import AudioFormat, SpeechError
from roboteye.speech.devices import AUTO, resolverSaida

if TYPE_CHECKING:
    from roboteye.config import VoiceSettings

logger = getLogger(__name__)


class AudioSink(Protocol):
    """Destino de reproducao de PCM."""

    name: str

    def start(self, audioFormat: AudioFormat) -> None:
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
        self.device = device
        self.stream: Any | None = None
        self.format: AudioFormat | None = None

    def start(self, audioFormat: AudioFormat) -> None:
        if self.stream is not None and self.format == audioFormat:
            return

        self.close()

        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:  # pragma: no cover - depende do ambiente
            raise SpeechError(f"sounddevice indisponivel: {exc}") from exc

        if audioFormat.sampleWidth != 2:
            raise SpeechError(
                f"apenas PCM de 16 bits e suportado (recebi {audioFormat.sampleWidth * 8} bits)"
            )

        try:
            self.stream = sd.RawOutputStream(
                samplerate=audioFormat.sampleRate,
                channels=audioFormat.channels,
                dtype="int16",
                device=self.device,
            )
            self.stream.start()
        except Exception as exc:
            self.stream = None
            raise SpeechError(f"nao foi possivel abrir o dispositivo de audio: {exc}") from exc

        self.format = audioFormat

    def write(self, audio: bytes) -> None:
        if self.stream is None:
            raise SpeechError("write() chamado antes de start()")
        try:
            self.stream.write(audio)
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
        if self.stream is None:
            return

        # abort() descarta o buffer; stop() esperaria o audio pendente terminar.
        # Alguns drivers (notadamente o MME do Windows) recusam abort/start
        # enquanto ainda ha dados na placa. Nesse caso descartamos o stream: o
        # proximo start() o reabre limpo, que e exatamente o efeito desejado.
        try:
            self.stream.abort()
            self.stream.start()
        except Exception:
            logger.debug("driver recusou abortar o stream; reabrindo", exc_info=True)
            self.close()

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                logger.debug("erro ao fechar o stream de audio", exc_info=True)
            self.stream = None
        self.format = None


# ---------------------------------------------------------------------------
# aplay (fallback para Linux/Raspberry Pi)
# ---------------------------------------------------------------------------
class AplaySink:
    """Reproducao encaminhando PCM para o `aplay` do ALSA."""

    name = "aplay"

    def __init__(self, device: str | None = None) -> None:
        self.device = device
        self.process: subprocess.Popen[bytes] | None = None
        self.format: AudioFormat | None = None

    def start(self, audioFormat: AudioFormat) -> None:
        if self.process is not None and self.format == audioFormat:
            return

        self.close()

        command = [
            "aplay",
            "-q",
            "-t",
            "raw",
            "-f",
            f"S{audioFormat.sampleWidth * 8}_LE",
            "-r",
            str(audioFormat.sampleRate),
            "-c",
            str(audioFormat.channels),
        ]
        if self.device:
            command += ["-D", self.device]

        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE)
        except OSError as exc:
            raise SpeechError(f"nao foi possivel iniciar o aplay: {exc}") from exc

        self.format = audioFormat

    def write(self, audio: bytes) -> None:
        if self.process is None or self.process.stdin is None:
            raise SpeechError("write() chamado antes de start()")
        try:
            self.process.stdin.write(audio)
            self.process.stdin.flush()
        except OSError as exc:
            # Mesma razão do `SoundDeviceSink.write`: sem soltar o processo
            # morto, `start()` acha que ainda há um `aplay` de pé e a voz não
            # volta nunca mais.
            self.close()
            raise SpeechError(f"aplay encerrou durante a reproducao: {exc}") from exc

    def stop(self) -> None:
        # aplay nao permite descartar o buffer: reiniciamos o processo.
        audioFormat = self.format
        self.close()
        if audioFormat is not None:
            self.start(audioFormat)

    def close(self) -> None:
        if self.process is not None:
            try:
                if self.process.stdin is not None:
                    self.process.stdin.close()
                self.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.process.kill()
            self.process = None
        self.format = None


# ---------------------------------------------------------------------------
# Silencioso
# ---------------------------------------------------------------------------
class NullSink:
    """Descarta o audio. Usado em testes e em ambientes sem som."""

    name = "null"

    def start(self, audioFormat: AudioFormat) -> None:
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
def createAudioSink(settings: VoiceSettings) -> AudioSink:
    """Escolhe a melhor saida disponivel no sistema."""
    if settings.engine == "null":
        return NullSink()

    device = resolverSaida(settings.audioDevice)

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
        pedido = settings.audioDevice
        return AplaySink(None if pedido == AUTO else pedido)

    logger.warning("nenhuma saida de audio disponivel; a voz sera silenciosa")
    return NullSink()
