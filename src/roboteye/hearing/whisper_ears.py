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

from collections.abc import Iterator

from roboteye.hearing.base import HearingError
from roboteye.hearing.microfone import Microfone
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)


class WhisperEars:
    """Ouve o microfone e devolve o que foi dito, em portugues."""

    name = "whisper"

    def __init__(
        self,
        modelo: str = "base",
        *,
        device: str | int | None = None,
        idioma: str = "pt",
        cpu_threads: int = 3,
        model_dir: str | None = None,
    ) -> None:
        self._nome_modelo = modelo
        self._idioma = idioma
        self._cpu_threads = cpu_threads
        self._model_dir = model_dir
        self._modelo = None
        self._microfone = Microfone(device=device)

    # -- ciclo de vida -----------------------------------------------------
    def warm_up(self) -> None:
        """Carrega o modelo — segundos num cartao SD, pagos uma vez."""
        if self._modelo is not None:
            return
        try:
            from faster_whisper import WhisperModel

            self._modelo = WhisperModel(
                self._nome_modelo,
                device="cpu",
                # `int8` e o que torna isto viavel num Pi: sem a quantizacao, o
                # mesmo modelo passa do tempo real e ocupa varias vezes a memoria.
                compute_type="int8",
                cpu_threads=self._cpu_threads,
                download_root=self._model_dir,
            )
        except Exception as exc:
            # Amplo de proposito: um modelo que nao carrega deixa o robo sem
            # ouvidos, nao sem robo. `escutar` avisa depois, com o motivo.
            logger.warning("nao consegui carregar o modelo de escuta: %s", exc)

    def close(self) -> None:
        self._microfone.fechar()

    def pausar(self) -> None:
        self._microfone.pausar()

    def retomar(self) -> None:
        self._microfone.retomar()

    # -- escuta ------------------------------------------------------------
    def escutar(self) -> Iterator[str]:
        self.warm_up()
        if self._modelo is None:
            raise HearingError(
                f"modelo de escuta {self._nome_modelo!r} indisponivel "
                '(instale com: pip install -e ".[stt]")'
            )

        for trecho in self._microfone.frases():
            texto = self._transcrever(trecho)
            if texto:
                yield texto

    def _transcrever(self, audio) -> str:
        modelo = self._modelo
        if modelo is None:  # pragma: no cover - `escutar` ja garantiu
            return ""
        try:
            segmentos, _ = modelo.transcribe(
                audio,
                language=self._idioma,
                # `beam_size=1` e busca gulosa: num Pi, o beam maior custa tempo
                # de resposta e devolve quase sempre a mesma frase.
                beam_size=1,
                # O corte por silencio ja foi feito no microfone; este filtro
                # limpa o que sobrou dentro do trecho.
                vad_filter=True,
                condition_on_previous_text=False,
            )
            return " ".join(s.text for s in segmentos).strip()
        except Exception as exc:
            # Uma transcricao que falha nao pode derrubar a escuta: a proxima
            # frase tem todo o direito de funcionar.
            logger.warning("nao consegui transcrever o trecho: %s", exc)
            return ""
