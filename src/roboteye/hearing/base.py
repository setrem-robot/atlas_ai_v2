"""Contratos da escuta.

A simetria com `speech/` e proposital: ali um `TTSEngine` transforma texto em som,
aqui um `Ouvido` transforma som em texto. Os dois sao protocolos, os dois tem
`warm_up`/`close`, e trocar a implementacao de qualquer um nao toca em mais nada.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class HearingError(RuntimeError):
    """Falha ao escutar."""


@dataclass(frozen=True, slots=True)
class Transcricao:
    """Uma frase reconhecida, com o que se sabe sobre como ela foi reconhecida.

    O texto e o unico campo que o robo usa para responder; o resto existe para
    depurar a escuta — ver por que uma frase saiu errada sem ter de gravar audio.
    Motores que nao medem confianca (o Vosk) deixam esses campos em `None`.
    """

    texto: str
    #: Quanto a transcricao demorou, em milissegundos.
    ms: float = 0.0
    #: Media do log-prob dos trechos: perto de 0 e alta, -1 ja e baixa.
    confianca: float | None = None
    #: Probabilidade de o trecho ser silencio/ruido, e nao fala.
    sem_fala: float | None = None


@runtime_checkable
class Ouvido(Protocol):
    """Escuta o microfone e entrega frases prontas."""

    name: str

    def escutar(self) -> Iterator[Transcricao]:
        """Produz cada frase reconhecida, uma por vez, ate ser fechado.

        Bloqueia esperando alguem falar. Quem chama roda isto numa thread.
        """
        ...

    def pausar(self) -> None:
        """Para de escutar temporariamente. Deve ser idempotente."""
        ...

    def retomar(self) -> None:
        """Volta a escutar. Deve ser idempotente."""
        ...

    def warm_up(self) -> None:
        """Carrega o modelo. Deve ser idempotente e nunca levantar."""
        ...

    def close(self) -> None:
        """Libera o microfone. Deve ser idempotente."""
        ...


@runtime_checkable
class AvisaAoFecharFrase(Protocol):
    """Ouvido que sabe avisar no instante em que a captura de uma frase fecha.

    Nem todo motor tem esse instante bem definido: o Vosk decide sozinho onde a
    frase termina, dentro do próprio reconhecimento, e não há um momento
    separado a anunciar. Por isso isto é um protocolo à parte, e não mais um
    método no `Ouvido` — quem tem, oferece; quem não tem continua sendo um
    ouvido completo.

    O aviso chega **antes** da transcrição, e essa é a razão de ele existir: é
    o instante em que a pessoa pode parar de falar. Esperar o reconhecimento
    para avisar custaria quase dois segundos num Raspberry Pi, e o aviso
    chegaria depois de ela já ter desistido de esperar.
    """

    def ao_fechar_frase(self, callback: Callable[[], None] | None) -> None:
        """Registra quem avisar. `None` desliga."""
        ...
