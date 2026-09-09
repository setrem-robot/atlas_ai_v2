"""Escuta com Vosk — reconhecimento offline, em português, **enquanto a pessoa fala**.

A diferença para o Whisper não é o tamanho do modelo: é *quando* o
reconhecimento acontece.

O Whisper é encoder-decoder e precisa da frase inteira antes de começar. Medido
neste robô, o modelo `base` transcreve a 0,59x do tempo real — numa pergunta de
três segundos são **quase dois segundos de silêncio** depois de a pessoa parar
de falar, antes de o modelo de linguagem sequer receber o texto.

O Vosk é Kaldi e decodifica bloco a bloco, conforme o áudio chega. Quando a
pessoa para de falar, a transcrição **já está pronta**: `AcceptWaveform` devolve
`True` e o texto sai junto. O que sobra é o custo de fechar o último bloco.

O preço está registrado no `whisper_ears.py`, e é real — a mesma frase, no mesmo
microfone:

    Vosk (modelo pequeno, 52 MB)   "quanto os alunos pena"
    Whisper base                   "Atlas, quantos alunos tem o curso de
                                    engenharia de computacao?"

Por isso os dois continuam no repositório e a troca é uma variável de ambiente
(`ROBOTEYE_HEARING_BACKEND`). Este arquivo escolhe resposta rápida; o outro
escolhe entender direito. Qual dos dois serve depende de quem está falando com o
robô e de quanto silêncio quem pergunta aguenta.

**O fim da frase quem detecta é o Vosk.** Não há detector de silêncio aqui:
`AcceptWaveform` devolve `True` quando a pessoa terminou, e é esse o sinal que
fecha a frase. Um detector próprio, por energia, seria pior justamente no ponto
que importa — cortaria a fala nas pausas de quem está pensando.

**O robô não pode ouvir a si mesmo.** O microfone está a centímetros da
caixinha: sem pausar a escuta enquanto a Atlas fala, ela transcreve a própria voz
e responde a si mesma, em laço. Quem pausa e retoma é o `Application`, que já
recebe `SpeechStarted` e `SpeechFinished` pelo barramento.

**Duas coisas aqui não são zelo defensivo — são defeitos que já aconteceram**, e
por isso a captura reusa o que o `microfone.py` aprendeu:

- *a placa manda na taxa.* Este módulo abria direto em 16 kHz. A placa deste robô
  (C-Media, USB) só grava a 44,1 e 48 kHz, e com `dsnoop` no caminho nem anuncia
  16 kHz — a abertura morria com `Invalid sample rate` e o robô subia sem
  ouvidos. Agora a taxa é negociada e a conversão é feita aqui;
- *o dispositivo some e volta com outro número.* Sem reabrir, o PortAudio fica
  girando no `poll` do ALSA sobre um dispositivo que não existe mais: um núcleo
  a 100%, o robô surdo, e nada no log. Ver `SEM_AUDIO_S`.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np

from roboteye.hearing.base import HearingError, Transcricao
from roboteye.hearing.microfone import (
    BLOCO,
    CORTE_GRAVES_HZ,
    ESPERA_INICIAL_S,
    ESPERA_MAXIMA_S,
    SEM_AUDIO_S,
    TAXA,
    CapturaParou,
    PassaAlta,
    negociar_taxa,
    reduzir,
)
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: Quanto o `float32` do PortAudio vale em `int16`, que é o que o Vosk lê.
ESCALA_INT16 = 32767.0

#: Silêncio empurrado ao reconhecedor antes de a fala poder começar.
#:
#: **O Vosk não reconhece a primeira palavra se o áudio começa nela.** Medido
#: aqui, a mesma frase sintetizada, com e sem meio segundo de silêncio na
#: frente:
#:
#:     "Atlas"                            ""    →  "atlas"
#:     "Atlas, quanto e dois mais dois?"  "quanto e dois mais dois"
#:                                        →  "atlas quanto e dois mais dois"
#:
#: O decodificador precisa de alguns quadros para fixar o contexto acústico e a
#: adaptação de ivector; sem eles, come o começo. Numa sala isso não aparece,
#: porque silêncio é o que mais chega ao microfone — **mas aparece ao retomar
#: depois de a Atlas falar**, que é justo quando a pessoa vai perguntar. E a
#: palavra comida seria o nome dela: o robô ouviria a pergunta inteira e
#: concluiria que não era com ele.
SILENCIO_DE_PARTIDA_S = 0.5


class VoskEars:
    """Ouve o microfone e devolve o que foi dito, em português."""

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
        self._ao_fechar_frase: Callable[[], None] | None = None

    # -- ciclo de vida -----------------------------------------------------
    def warm_up(self) -> None:
        """Carrega o modelo do disco.

        Custa alguns segundos num cartão SD, e paga-se uma vez no arranque em vez
        de na primeira pergunta de quem chegou perto do robô.
        """
        if self._model is not None:
            return
        try:
            from vosk import Model, SetLogLevel

            # O Vosk fala muito no stderr durante o carregamento, e nada disso
            # interessa a quem está lendo o log do robô.
            SetLogLevel(-1)
            self._model = Model(str(self._model_path))
        except Exception as exc:
            # Amplo de propósito: um modelo que não carrega deixa o robô sem
            # ouvidos, não sem robô. `escutar` avisa depois, com o caminho.
            logger.warning("nao consegui carregar o modelo de escuta: %s", exc)

    def close(self) -> None:
        self._fechado.set()
        # Destrava quem estiver esperando um bloco que não virá mais.
        with contextlib.suppress(queue.Full):
            self._blocos.put_nowait(None)

    def pausar(self) -> None:
        if not self._pausado.is_set():
            logger.debug("escuta pausada (a Atlas esta falando)")
        self._pausado.set()

    def retomar(self) -> None:
        if self._pausado.is_set():
            logger.debug("escuta retomada")
            # Enquanto pausado nada foi entregue ao reconhecedor, então para ele
            # a fala que vem agora começa no primeiro quadro do universo — e ele
            # comeria o "Atlas". Ver `SILENCIO_DE_PARTIDA_S`.
            self._preparar_o_ouvido()
        self._pausado.clear()

    def _preparar_o_ouvido(self) -> None:
        """Enfileira o silêncio que dá contexto ao reconhecedor.

        Barato de propósito: alimentar o Vosk enquanto a Atlas fala manteria o
        contexto sozinho, mas gastaria um núcleo decodificando silêncio durante
        toda a resposta — e devolver núcleos enquanto ela pensa foi justamente o
        que tirou o primeiro token de 3300 ms para 200 ms.
        """
        mudo = self._para_int16(np.zeros(BLOCO, dtype=np.float32))
        for _ in range(int(SILENCIO_DE_PARTIDA_S * TAXA / BLOCO)):
            with contextlib.suppress(queue.Full):
                self._blocos.put_nowait(mudo)

    def ao_fechar_frase(self, callback: Callable[[], None] | None) -> None:
        """Registra quem avisar quando uma frase fecha. `None` desliga.

        Aqui o instante é o mesmo em que a transcrição fica pronta — não há a
        espera de quase dois segundos que existe no caminho do Whisper. O aviso
        continua saindo antes do texto ser entregue porque tocar o som primeiro
        é o que faz quem perguntou saber que pode parar de falar.
        """
        self._ao_fechar_frase = callback

    # -- escuta ------------------------------------------------------------
    def escutar(self) -> Iterator[Transcricao]:
        """Produz cada frase reconhecida, até ser fechado.

        Reabre o dispositivo sozinha quando ele para de entregar áudio, com
        espera que dobra a cada tentativa. Mesma razão do `Microfone.frases()`:
        a placa USB deste robô se desconecta e volta com outro número.
        """
        self.warm_up()
        if self._model is None:
            raise HearingError(
                f"modelo de escuta ausente em {self._model_path} "
                "(rode: ./scripts/baixar-modelo-escuta.sh --vosk)"
            )

        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise HearingError(f"escuta indisponivel: {exc}") from exc

        espera = ESPERA_INICIAL_S
        primeira = True
        while not self._fechado.is_set():
            try:
                yield from self._uma_captura(sd)
                return  # saiu limpo: alguém chamou `close()`
            except CapturaParou as motivo:
                logger.warning("o microfone parou de entregar audio (%s); reabrindo", motivo)
            except HearingError:
                # Nenhuma taxa serve: reabrir não muda isso. Sobe para quem
                # chamou, que já sabe anunciar "escuta indisponivel".
                if primeira:
                    raise
                logger.warning("o microfone sumiu e nao voltou; tentando de novo")
            except Exception:
                logger.exception("falha inesperada na captura; reabrindo")
            finally:
                primeira = False

            if self._fechado.is_set():
                return
            # O que ficou na fila é de antes da queda: entregá-lo agora colaria
            # um pedaço de frase velha no começo da próxima.
            self._descartar_pendentes()
            time.sleep(espera)
            espera = min(espera * 2.0, ESPERA_MAXIMA_S)

    def _descartar_pendentes(self) -> None:
        with contextlib.suppress(queue.Empty):
            while True:
                self._blocos.get_nowait()

    def _uma_captura(self, sd) -> Iterator[Transcricao]:
        """Uma sessão de captura, do `open` até o dispositivo parar."""
        from vosk import KaldiRecognizer

        filtro = PassaAlta(CORTE_GRAVES_HZ, self._taxa)

        def alimentar(entrada, _quadros, _tempo, status) -> None:
            if status:
                logger.debug("microfone reclamou: %s", status)
            # Descartar enquanto pausado é o que impede o robô de transcrever a
            # própria voz — e também esvazia a fila, para ele não processar, ao
            # retomar, tudo o que disse enquanto falava.
            if self._pausado.is_set():
                return
            bloco = filtro.aplicar(reduzir(entrada[:, 0], fator))
            # Fila cheia significa que o reconhecimento ficou para trás; perder
            # um bloco (30 ms) é melhor que travar a captura do microfone, e o
            # Vosk atravessa a falta sem perceber.
            with contextlib.suppress(queue.Full):
                self._blocos.put_nowait(self._para_int16(bloco))

        taxa, fator = negociar_taxa(sd, self._device)
        reconhecedor = KaldiRecognizer(self._model, self._taxa)
        with sd.InputStream(
            samplerate=taxa,
            blocksize=BLOCO * fator,
            device=self._device,
            dtype="float32",
            channels=1,
            callback=alimentar,
        ):
            # Também na abertura: quem fala assim que o robô sobe não teria
            # silêncio nenhum antes da primeira palavra.
            self._preparar_o_ouvido()
            logger.info("escutando pelo microfone (vosk, decodificando enquanto voce fala)")
            yield from self._reconhecer(reconhecedor)

    @staticmethod
    def _para_int16(bloco: np.ndarray) -> bytes:
        """`float32` de -1..1 para os bytes `int16` que o Vosk lê.

        O corte antes da conversão não é decorativo: um pico acima de 1,0 vira,
        sem ele, um número negativo ao transbordar o `int16` — um estalo no meio
        da fala, bem onde o reconhecimento mais precisa de sinal limpo.
        """
        limitado = np.clip(bloco, -1.0, 1.0)
        return (limitado * ESCALA_INT16).astype(np.int16).tobytes()

    def _reconhecer(self, reconhecedor) -> Iterator[Transcricao]:
        """Alimenta o Vosk e entrega cada frase que ele fecha."""
        ultimo_bloco = time.monotonic()
        while not self._fechado.is_set():
            try:
                bloco = self._blocos.get(timeout=0.5)
            except queue.Empty:
                # Enquanto pausado não chega bloco nenhum de propósito — contar
                # esse tempo como dispositivo morto reabriria o microfone toda
                # vez que a Atlas falasse por mais de três segundos.
                if self._pausado.is_set():
                    ultimo_bloco = time.monotonic()
                    continue
                if time.monotonic() - ultimo_bloco > SEM_AUDIO_S:
                    raise CapturaParou(f"nada ha {SEM_AUDIO_S:.0f}s") from None
                continue
            if bloco is None:
                return
            ultimo_bloco = time.monotonic()

            inicio = time.perf_counter()
            if not reconhecedor.AcceptWaveform(bloco):
                continue
            texto = json.loads(reconhecedor.Result()).get("text", "").strip()
            if not texto:
                continue
            # O som de "terminei de ouvir" sai antes de a frase ser entregue: é
            # o instante em que quem perguntou pode parar de falar.
            self._avisar_que_fechou()
            # O Vosk não expõe confiança por aqui; só o tempo do último bloco
            # entra na medida, que é o custo real de fechar a frase — e é a
            # diferença toda para o Whisper, que mede a frase inteira.
            ms = (time.perf_counter() - inicio) * 1000.0
            logger.info("frase fechada pelo vosk em %.0f ms", ms)
            yield Transcricao(texto=texto, ms=ms)

    def _avisar_que_fechou(self) -> None:
        """Toca quem quis ser avisado, sem deixar o aviso derrubar a escuta."""
        if self._ao_fechar_frase is None:
            return
        try:
            self._ao_fechar_frase()
        except Exception as exc:
            # Um aviso que falha não pode custar a frase que acabou de ser
            # reconhecida: ela é o motivo de tudo isto existir.
            logger.debug("aviso de fim de frase falhou: %s", exc)
