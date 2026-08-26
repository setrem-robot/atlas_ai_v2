"""Voz online com rede de seguranca offline.

A melhor voz em portugues do Brasil hoje esta na nuvem; a voz que sempre
funciona esta no disco. Nao ha razao para escolher uma das duas de antemao: este
motor tenta a primeira e, se ela falhar, fala pela segunda.

O que se ganha e que ficar sem internet deixa de ser uma falha e vira apenas uma
troca de timbre. O robo continua respondendo.

**A falha custa uma vez, nao sempre.** Depois de um erro, o motor online fica de
molho por um tempo antes de ser tentado de novo. Sem isso, cada frase pagaria o
tempo limite da rede antes de cair para a voz local — e uma conversa inteira
offline ficaria insuportavelmente lenta.

**A primeira frase merece paciencia.** No arranque a rede ainda esta subindo, e
desistir nesse instante nao troca uma frase de voz: troca a voz do robo pelo
tempo todo, porque nada mais fala depois da saudacao. Medido neste robo: o
servico sobe as 00:19:22, a face abre as :28 e a rede so fica utilizavel as :31
— a saudacao tentava a voz de rede tres segundos cedo demais. Antes da primeira
sintese, entao, o motor preferido ganha um tempo para ficar alcancavel. Custa
alguns segundos de silencio uma vez, com a face ja no ar; nao custa nada quando
a rede ja esta de pe.

**A troca acontece antes de qualquer som sair.** Um motor produz audio aos
blocos, e trocar no meio de uma frase deixaria metade dela em cada voz. Por
isso o primeiro bloco e sempre pedido antes de comprometer a fala: se ele nao
vier, ninguem ouviu nada ainda e a queda passa despercebida.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

from roboteye.logging_setup import get_logger
from roboteye.speech.base import SpeechChunk, SpeechError, TTSEngine

logger = get_logger(__name__)

#: Quanto tempo o motor preferido fica em quarentena depois de falhar.
DEFAULT_COOLDOWN = 60.0

#: Quanto esperar, antes da primeira frase, o motor preferido ficar alcancavel.
#: Neste robo a rede chega 3 s depois de a face abrir; o resto e folga para um
#: Wi-Fi lento. Passado isso, a primeira frase sai pela reserva e a vida segue.
ESPERA_DE_ARRANQUE = 20.0

#: De quanto em quanto tempo perguntar se a rede ja chegou.
INTERVALO_DA_ESPERA = 2.0


class FallbackEngine:
    """Fala pelo motor preferido; cai para o reserva quando ele falha."""

    def __init__(
        self,
        primary: TTSEngine,
        backup: TTSEngine,
        *,
        cooldown: float = DEFAULT_COOLDOWN,
        espera_de_arranque: float = ESPERA_DE_ARRANQUE,
        on_switch: Callable[[str], None] | None = None,
    ) -> None:
        self._primary = primary
        self._backup = backup
        self._cooldown = max(0.0, cooldown)
        self._blocked_until = 0.0
        self._espera_de_arranque = max(0.0, espera_de_arranque)
        #: A espera acontece uma vez so. Depois da primeira frase, uma falha de
        #: rede e uma falha de rede — quem esta conversando prefere a voz
        #: reserva agora a voz certa daqui a vinte segundos.
        self._primeira_frase = True
        #: Chamado quando a voz muda, para que a troca nao passe despercebida.
        #: Uma reserva do mesmo idioma e genero passa facilmente por "a voz
        #: configurada, so que errada" — e quem esta ouvindo vai procurar o erro
        #: na configuracao, que e o lugar onde ele nao esta.
        self._on_switch = on_switch
        self._announced = False
        #: Atributo, e nao propriedade: o protocolo `TTSEngine` declara `name`
        #: como variavel, e uma propriedade so de leitura nao o satisfaz.
        self.name = f"{primary.name}+{backup.name}"

    # -- ciclo de vida -----------------------------------------------------
    def warm_up(self) -> None:
        """Prepara o reserva sempre; o preferido, so se der.

        A ordem importa: o reserva e quem precisa estar pronto no instante em
        que o preferido falhar, e carregar um modelo local leva segundos que
        nao cabem no meio de uma frase.
        """
        self._backup.warm_up()
        try:
            self._primary.warm_up()
        except SpeechError as exc:
            logger.warning("voz preferida indisponivel (%s); usando a reserva", exc)
            self._block()

    def close(self) -> None:
        self._primary.close()
        self._backup.close()

    # -- sintese -----------------------------------------------------------
    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        if self._primeira_frase:
            self._primeira_frase = False
            self._esperar_o_preferido()

        if self._available():
            chunks = self._try_primary(text)
            if chunks is not None:
                yield from chunks
                return

        yield from self._backup.synthesize(text)

    def _try_primary(self, text: str) -> Iterator[SpeechChunk] | None:
        """Devolve o audio do motor preferido, ou None se ele falhou.

        O primeiro bloco e forcado aqui dentro: e o que garante que a decisao
        entre uma voz e outra seja tomada antes de qualquer som ser tocado.
        """
        stream = self._primary.synthesize(text)
        try:
            first = next(stream)
        except StopIteration:
            return iter(())
        except Exception as exc:
            logger.warning("voz preferida falhou (%s); caindo para a reserva", exc)
            self._block()
            return None

        return _resume(first, stream, self._block)

    # -- arranque -----------------------------------------------------------
    def _esperar_o_preferido(self) -> None:
        """Da ao motor preferido um tempo para ficar de pe, uma unica vez.

        Pergunta ao proprio motor se ele ja e alcancavel, quando ele souber
        responder — um motor local nao sabe, e nem precisa: ele nunca esteve
        fora do ar. Isto roda na thread que ia sintetizar de qualquer jeito, e
        nunca na que desenha a face.
        """
        alcancavel = getattr(self._primary, "alcancavel", None)
        if alcancavel is None or self._espera_de_arranque <= 0:
            return
        if alcancavel():
            return

        logger.info(
            "a rede ainda nao subiu; esperando ate %.0fs para falar com a voz %s",
            self._espera_de_arranque,
            self._primary.name,
        )
        limite = time.monotonic() + self._espera_de_arranque
        while time.monotonic() < limite:
            time.sleep(INTERVALO_DA_ESPERA)
            if alcancavel():
                logger.info("a rede chegou; a primeira frase vai na voz %s", self._primary.name)
                return
        # Nao adianta tentar assim mesmo: a espera acabou de provar que o
        # servidor esta inalcancavel, e a tentativa so somaria o tempo limite da
        # conexao ao silencio — quase trinta segundos antes de o robo dar bom
        # dia. A quarentena normal cuida de tentar de novo mais tarde.
        logger.warning(
            "a rede nao chegou em %.0fs; a primeira frase vai pela voz %s",
            self._espera_de_arranque,
            self._backup.name,
        )
        self._block()

    # -- quarentena ---------------------------------------------------------
    def _available(self) -> bool:
        disponivel = time.monotonic() >= self._blocked_until
        if disponivel and self._announced:
            # Voltou a funcionar: o proximo tropeco merece ser anunciado de novo.
            self._announced = False
            self._notify(f"voz {self._primary.name} de volta")
        return disponivel

    def _block(self) -> None:
        self._blocked_until = time.monotonic() + self._cooldown
        if not self._announced:
            self._announced = True
            self._notify(
                f"falando pela voz reserva ({self._backup.name}): {self._primary.name} indisponivel"
            )

    def _notify(self, message: str) -> None:
        if self._on_switch is not None:
            self._on_switch(message)


def _resume(
    first: SpeechChunk,
    stream: Iterator[SpeechChunk],
    on_failure: Callable[[], None],
) -> Iterator[SpeechChunk]:
    """Entrega o primeiro bloco e segue com o resto do fluxo.

    Se a conexao cair depois que a fala ja comecou, nao da mais para trocar de
    voz sem repetir o que ja foi dito: o audio restante e descartado e a frase
    termina cortada, que e o mal menor.
    """
    yield first
    try:
        yield from stream
    except Exception as exc:
        logger.warning("a voz preferida caiu no meio da frase (%s)", exc)
        on_failure()
