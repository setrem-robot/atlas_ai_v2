"""Escuta com Whisper, pelo `faster-whisper`.

Escolhido por medida, no Pi 5 de producao, contra o Vosk — que era a alternativa
obvia por ser leve. A mesma frase, gravada no mesmo microfone:

    Vosk (modelo pequeno, 52 MB)   "quanto os alunos pena"
    Whisper tiny                   "Atlas, quantos alunos tem o curso de
                                    engenharia de computacao?"
    Whisper base                   igual, com a pontuacao certa

O custo dessa diferenca cabe no robo: `tiny` transcreve a 0,35x do tempo real e
`base` a 0,59x — ou seja, a resposta comeca antes de a pessoa terminar de
esperar. E a diferenca importa mais do que parece, porque **quem vai falar com
este robo sao criancas**: voz aguda, diccao variavel, frases quebradas. E
exatamente onde um modelo pequeno de reconhecimento erra mais, e onde errar
significa a Atlas responder outra coisa.

`cpu_threads` deixa um nucleo de fora de proposito: a face desenha o tempo todo,
e uma transcricao que toma a maquina inteira faz a animacao engasgar bem no
momento em que a pessoa esta esperando resposta.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

from roboteye.hearing.base import HearingError, Transcricao
from roboteye.hearing.microfone import Microfone
from roboteye.loggingSetup import getLogger

logger = getLogger(__name__)


class WhisperEars:
    """Ouve o microfone e devolve o que foi dito, em portugues."""

    name = "whisper"

    def __init__(
        self,
        modelo: str = "base",
        *,
        device: str | int | None = None,
        idioma: str = "pt",
        cpuThreads: int = 3,
        modelDir: str | None = None,
        limiar: float | None = None,
    ) -> None:
        self.nomeModelo = modelo
        self.idioma = idioma
        self.cpuThreads = cpuThreads
        self.modelDir = modelDir
        self.modelo = None
        self.microfone = Microfone(device=device, limiar=limiar)

    def aoFecharFrase(self, callback: Callable[[], None] | None) -> None:
        """Repassa ao microfone quem avisar quando uma frase fecha."""
        self.microfone.aoFecharFrase(callback)

    # -- ciclo de vida -----------------------------------------------------
    def warmUp(self) -> None:
        """Carrega o modelo — segundos num cartao SD, pagos uma vez."""
        if self.modelo is not None:
            return
        try:
            from fasterWhisper import WhisperModel

            self.modelo = WhisperModel(
                self.nomeModelo,
                device="cpu",
                # `int8` e o que torna isto viavel num Pi: sem a quantizacao, o
                # mesmo modelo passa do tempo real e ocupa varias vezes a memoria.
                compute_type="int8",
                cpu_threads=self.cpuThreads,
                download_root=self.modelDir,
            )
        except Exception as exc:
            # Amplo de proposito: um modelo que nao carrega deixa o robo sem
            # ouvidos, nao sem robo. `escutar` avisa depois, com o motivo.
            logger.warning("nao consegui carregar o modelo de escuta: %s", exc)

    def close(self) -> None:
        self.microfone.fechar()

    def pausar(self) -> None:
        self.microfone.pausar()

    def retomar(self) -> None:
        self.microfone.retomar()

    # -- escuta ------------------------------------------------------------
    def escutar(self) -> Iterator[Transcricao]:
        self.warmUp()
        if self.modelo is None:
            raise HearingError(
                f"modelo de escuta {self.nomeModelo!r} indisponivel "
                '(instale com: pip install -e ".[stt]")'
            )

        for trecho in self.microfone.frases():
            transcricao = self.transcrever(trecho)
            if transcricao.texto:
                yield transcricao

    def transcrever(self, audio) -> Transcricao:
        modelo = self.modelo
        if modelo is None:  # pragma: no cover - `escutar` ja garantiu
            return Transcricao("")
        # A transcricao acontece de verdade ao percorrer os segmentos (o
        # `faster-whisper` e preguicoso), entao o cronometro cerca o laco.
        inicio = time.perf_counter()
        try:
            segmentos, _ = modelo.transcribe(
                audio,
                language=self.idioma,
                # `beam_size=1` e busca gulosa: num Pi, o beam maior custa tempo
                # de resposta e devolve quase sempre a mesma frase.
                beam_size=1,
                # O corte por silencio ja foi feito no microfone; este filtro
                # limpa o que sobrou dentro do trecho.
                vad_filter=True,
                condition_on_previous_text=False,
            )
            partes: list[str] = []
            logprobs: list[float] = []
            silencios: list[float] = []
            for s in segmentos:
                partes.append(s.text)
                logprobs.append(s.avg_logprob)
                silencios.append(s.no_speech_prob)
        except Exception as exc:
            # Uma transcricao que falha nao pode derrubar a escuta: a proxima
            # frase tem todo o direito de funcionar.
            logger.warning("nao consegui transcrever o trecho: %s", exc)
            return Transcricao("")

        ms = (time.perf_counter() - inicio) * 1000.0
        return Transcricao(
            # Cada segmento do Whisper vem com um espaco a frente; juntar com
            # `" ".join` cru deixaria espacos duplos no meio da frase que a
            # pessoa nao disse. Um `.strip()` por segmento remove esse artefato.
            texto=" ".join(p.strip() for p in partes if p.strip()),
            ms=ms,
            confianca=sum(logprobs) / len(logprobs) if logprobs else None,
            semFala=max(silencios) if silencios else None,
        )
