"""Escuta com Vosk — reconhecimento de fala offline, em portugues.

Escolhido por medida, no Pi 5 de producao: o modelo pequeno de portugues ocupa
52 MB, transcreve mais rapido que o tempo real e nao precisa de internet nem de
chave de API. O Whisper daria transcricao melhor, mas nao ha wheel dele para
aarch64 sem compilar o PyTorch inteiro, e mesmo o modelo `tiny` fica longe do
tempo real numa CPU de Raspberry Pi — o que num robo significa esperar em
silencio depois de cada pergunta.

**O fim da frase quem detecta e o Vosk.** Nao ha detector de silencio escrito
aqui: `AcceptWaveform` devolve `True` quando a pessoa terminou de falar, e e esse
o sinal que fecha a frase. Um detector proprio, por energia, seria pior no ponto
que importa — ele cortaria a fala nas pausas naturais de quem esta pensando.

**O robo nao pode ouvir a si mesmo.** O microfone esta a centimetros da caixinha:
sem pausar a escuta enquanto a Atlas fala, ela transcreve a propria voz e
responde a si mesma, em laco. Quem pausa e retoma e o `Application`, que ja
recebe `SpeechStarted` e `SpeechFinished` pelo barramento de eventos.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
from collections.abc import Iterator
from pathlib import Path

from roboteye.hearing.base import HearingError
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: Taxa que os modelos do Vosk esperam. Nao e escolha nossa.
TAXA = 16000

#: Tamanho do bloco lido do microfone. 4000 quadros sao 250 ms: pequeno o
#: bastante para a frase fechar logo depois de a pessoa parar de falar, grande o
#: bastante para nao acordar a CPU o tempo todo num robo que escuta o dia inteiro.
BLOCO = 4000


class VoskEars:
    """Ouve o microfone e devolve o que foi dito, em portugues."""

    name = "vosk"

    def __init__(
        self,
        model_path: Path,
        *,
        device: str | int | None = None,
        taxa: int = TAXA,
    ) -> None:
        self._model_path = model_path
        self._device = device
        self._taxa = taxa
        self._model = None
        self._blocos: queue.Queue[bytes | None] = queue.Queue(maxsize=64)
        self._pausado = threading.Event()
        self._fechado = threading.Event()

    # -- ciclo de vida -----------------------------------------------------
    def warm_up(self) -> None:
        """Carrega o modelo do disco.

        Custa alguns segundos num cartao SD, e paga-se uma vez no arranque em vez
        de na primeira pergunta de quem chegou perto do robo.
        """
        if self._model is not None:
            return
        try:
            from vosk import Model, SetLogLevel

            # O Vosk fala muito no stderr durante o carregamento, e nada disso
            # interessa a quem esta lendo o log do robo.
            SetLogLevel(-1)
            self._model = Model(str(self._model_path))
        except Exception as exc:
            # Amplo de proposito: um modelo que nao carrega deixa o robo sem
            # ouvidos, nao sem robo. `escutar` avisa depois, com o caminho.
            logger.warning("nao consegui carregar o modelo de escuta: %s", exc)

    def close(self) -> None:
        self._fechado.set()
        # Destrava quem estiver esperando um bloco que nao vira mais.
        with contextlib.suppress(queue.Full):
            self._blocos.put_nowait(None)

    def pausar(self) -> None:
        if not self._pausado.is_set():
            logger.debug("escuta pausada (a Atlas esta falando)")
        self._pausado.set()

    def retomar(self) -> None:
        if self._pausado.is_set():
            logger.debug("escuta retomada")
        self._pausado.clear()

    # -- escuta ------------------------------------------------------------
    def escutar(self) -> Iterator[str]:
        self.warm_up()
        if self._model is None:
            raise HearingError(
                f"modelo de escuta ausente em {self._model_path} "
                "(rode: ./scripts/baixar-modelo-escuta.sh)"
            )

        try:
            import sounddevice as sd
            from vosk import KaldiRecognizer
        except (ImportError, OSError) as exc:
            raise HearingError(f"escuta indisponivel: {exc}") from exc

        reconhecedor = KaldiRecognizer(self._model, self._taxa)

        def alimentar(entrada, _quadros, _tempo, status) -> None:
            if status:
                logger.debug("microfone reclamou: %s", status)
            # Descartar enquanto pausado e o que impede o robo de transcrever a
            # propria voz — e tambem esvazia a fila, para ele nao processar,
            # ao retomar, tudo o que disse enquanto falava.
            if self._pausado.is_set():
                return
            # Fila cheia significa que o reconhecimento ficou para tras; perder
            # um bloco (250 ms) e melhor que travar a captura do microfone, e o
            # Vosk atravessa a falta sem perceber.
            with contextlib.suppress(queue.Full):
                self._blocos.put_nowait(bytes(entrada))

        with sd.RawInputStream(
            samplerate=self._taxa,
            blocksize=BLOCO,
            device=self._device,
            dtype="int16",
            channels=1,
            callback=alimentar,
        ):
            logger.info("escutando pelo microfone")
            while not self._fechado.is_set():
                try:
                    bloco = self._blocos.get(timeout=0.5)
                except queue.Empty:
                    continue
                if bloco is None:
                    break
                if reconhecedor.AcceptWaveform(bloco):
                    texto = json.loads(reconhecedor.Result()).get("text", "").strip()
                    if texto:
                        yield texto
