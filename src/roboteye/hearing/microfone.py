"""Captura do microfone, cortada em frases.

O Vosk sabia dizer sozinho quando a pessoa parou de falar; o Whisper não — ele
transcreve um trecho pronto e não tem opinião sobre onde o trecho começa. Alguém
precisa decidir isso, e é este módulo.

A regra é a mais simples que funciona: **começa a gravar quando o som sobe, para
quando o silêncio dura o bastante.** Nada de modelo de detecção de voz — um
limiar de energia com um pouco de paciência resolve o caso real (uma pessoa
falando perto de um microfone) sem trazer outra dependência para um robô que já
divide quatro núcleos.

Três detalhes decidem se isso funciona ou irrita:

- **o silêncio precisa ser longo o suficiente para caber uma vírgula.** Cortar em
  400 ms parece rápido e transforma "Atlas, quantos alunos tem?" em duas frases
  pela metade;
- **o começo da fala não pode ser perdido.** Quando o som sobe, a primeira
  sílaba já passou — por isso um pedaço do que veio antes é guardado e vai junto;
- **o ruído da sala não pode virar pergunta.** Trechos curtos demais são
  descartados sem chegar ao reconhecimento.
"""

from __future__ import annotations

import contextlib
import queue
from collections import deque
from collections.abc import Iterator

import numpy as np

from roboteye.hearing.base import HearingError
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: Taxa que os modelos de reconhecimento esperam.
TAXA = 16000

#: Tamanho do bloco lido do microfone: 30 ms. É a resolução com que o silêncio é
#: medido, e o que define quão fino dá para cortar.
BLOCO = 480


class Microfone:
    """Escuta e entrega um trecho de áudio por frase falada."""

    def __init__(
        self,
        *,
        device: str | int | None = None,
        limiar: float = 0.02,
        silencio_s: float = 0.8,
        minimo_s: float = 0.4,
        maximo_s: float = 15.0,
    ) -> None:
        self._device = device
        #: Acima disto conta como fala. 0.02 (de 0 a 1) fica acima do ruído de
        #: uma sala normal e abaixo de uma voz falando a um metro.
        self._limiar = limiar
        #: Silêncio que fecha a frase. Ver o comentário sobre a vírgula.
        self._silencio = int(silencio_s * TAXA / BLOCO)
        #: Curto demais é ruído — uma porta, uma cadeira, uma tosse.
        self._minimo = int(minimo_s * TAXA / BLOCO)
        #: Teto de segurança: sem ele, um ruído contínuo (um ventilador ligando)
        #: gravaria para sempre e nada seria transcrito.
        self._maximo = int(maximo_s * TAXA / BLOCO)
        #: O que veio antes de o som subir. 300 ms bastam para a primeira sílaba.
        self._antes: deque[np.ndarray] = deque(maxlen=10)

        self._blocos: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=200)
        self._pausado = False
        self._fechado = False

    def pausar(self) -> None:
        self._pausado = True

    def retomar(self) -> None:
        self._pausado = False

    def fechar(self) -> None:
        self._fechado = True
        with contextlib.suppress(queue.Full):
            self._blocos.put_nowait(None)

    def frases(self) -> Iterator[np.ndarray]:
        """Produz um trecho de áudio por frase falada, até ser fechado."""
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise HearingError(f"microfone indisponivel: {exc}") from exc

        def receber(entrada, _quadros, _tempo, status) -> None:
            if status:
                logger.debug("microfone reclamou: %s", status)
            # Enquanto a Atlas fala, tudo o que chega é a própria voz dela.
            if self._pausado:
                return
            with contextlib.suppress(queue.Full):
                self._blocos.put_nowait(entrada[:, 0].copy())

        with sd.InputStream(
            samplerate=TAXA,
            blocksize=BLOCO,
            device=self._device,
            dtype="float32",
            channels=1,
            callback=receber,
        ):
            logger.info("escutando pelo microfone")
            yield from self._cortar_em_frases()

    def _cortar_em_frases(self) -> Iterator[np.ndarray]:
        falando: list[np.ndarray] = []
        quieto = 0
        #: Blocos com voz de verdade. E este numero, e nao o tamanho do trecho,
        #: que decide se houve pergunta: o preambulo guardado antes da fala
        #: sozinho ja passaria do minimo, e um estalo de porta viraria pergunta.
        com_voz = 0

        while not self._fechado:
            try:
                bloco = self._blocos.get(timeout=0.5)
            except queue.Empty:
                continue
            if bloco is None:
                break

            tem_voz = float(np.sqrt(np.mean(bloco**2))) > self._limiar

            if not falando:
                self._antes.append(bloco)
                if tem_voz:
                    # A fala já começou antes de passarmos do limiar; o que
                    # ficou guardado é justamente a primeira sílaba.
                    falando = list(self._antes)
                    self._antes.clear()
                    quieto = 0
                    com_voz = 1
                continue

            falando.append(bloco)
            if tem_voz:
                quieto = 0
                com_voz += 1
            else:
                quieto += 1

            if quieto >= self._silencio or len(falando) >= self._maximo:
                trecho, falando = falando, []
                self._antes.clear()
                if com_voz >= self._minimo:
                    yield np.concatenate(trecho)
                else:
                    logger.debug("so %d blocos com voz; era ruido, nao pergunta", com_voz)
                com_voz = 0
