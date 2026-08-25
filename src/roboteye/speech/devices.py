"""Descoberta da placa de som.

Num robô, o alto-falante quase nunca é o do monitor. O HDMI é o que existe por
padrão no Raspberry Pi — e é a pior saída possível para ele: depende de a tela
ter alto-falante (a telinha de 5" costuma não ter), e o volume fica nas mãos do
monitor, longe de quem monta o robô.

Quem pluga uma caixinha USB no robô quer ouvir por ela. Por isso `auto` procura
uma placa USB antes de aceitar o padrão do sistema: é a única escolha que acerta
sem ninguém configurar nada, que é o ponto de um robô que liga sozinho.

**Mas não a qualquer preço.** Falar com a placa direto (`hw:`) pula o `plug` do
ALSA, que é quem converte a taxa de amostragem — e placas USB baratas costumam
aceitar só 44100 e 48000 Hz, enquanto o Piper sintetiza a 22050 e o Kokoro a
24000. Escolher a placa crua nesse caso troca "toca no monitor errado" por "não
toca em lugar nenhum", com um `Invalid sample rate` que não diz o porquê. Por
isso `auto` só fica com a placa se ela aceitar a taxa que vamos tocar; caso
contrário devolve o padrão do sistema, onde o `plug` faz a conversão.

Quem aponta o padrão do sistema para a placa certa é `scripts/configurar-audio.sh`.
"""

from __future__ import annotations

from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: Valor de `ROBOTEYE_AUDIO_DEVICE` que pede a escolha automática.
AUTO = "auto"

#: Taxa usada para saber se vale falar com a placa direto. É a do Piper, a voz
#: local — a mais baixa que o projeto toca, e a que placas USB baratas mais
#: recusam.
TAXA_DE_PROVA = 22050

#: Nomes que o ALSA dá aos dispositivos que não são placas de verdade, e sim
#: apelidos para outra coisa. Escolher um deles seria devolver a decisao para o
#: `/etc/asound.conf`, que e justamente o que `auto` quer evitar.
_APELIDOS = ("default", "sysdefault", "pulse", "pipewire", "jack", "dmix", "surround")


def resolver_saida(preferencia: str | None, *, taxa: int = TAXA_DE_PROVA) -> str | int | None:
    """Traduz o que veio da configuracao no que o `sounddevice` entende.

    - vazio ou None: o padrao do sistema, sem opinar;
    - um numero: o indice do dispositivo, como o `sounddevice` os numera;
    - `auto`: procura uma placa USB e cai para o padrao se nao houver;
    - qualquer outro texto: passado adiante como nome (o `sounddevice` aceita
      pedaco do nome).
    """
    if preferencia is None or not preferencia.strip():
        return None

    escolha = preferencia.strip()
    if escolha.isdigit():
        return int(escolha)
    if escolha.lower() != AUTO:
        return escolha

    indice = _primeira_placa_usb(taxa)
    if indice is None:
        logger.debug("nenhuma placa USB utilizavel; usando o padrao do sistema")
        return None
    return indice


def _listar() -> list[dict]:
    """Os dispositivos que o sistema oferece. Isolado para poder ser trocado."""
    import sounddevice as sd

    return list(sd.query_devices())


def _primeira_placa_usb(taxa: int) -> int | None:
    """Indice da primeira placa USB que sabe tocar nesta taxa, ou None."""
    try:
        dispositivos = _listar()
    except Exception as exc:
        # Amplo de proposito: sem `sounddevice` utilizavel nao ha o que
        # escolher, e isso nao pode derrubar o arranque do robo — quem chama
        # segue com o padrao do sistema.
        logger.debug("nao consegui listar dispositivos de audio: %s", exc)
        return None

    for indice, dispositivo in enumerate(dispositivos):
        nome = str(dispositivo.get("name", ""))
        if dispositivo.get("max_output_channels", 0) <= 0:
            continue
        if any(apelido in nome.lower() for apelido in _APELIDOS):
            continue
        if "usb" not in nome.lower():
            continue
        if not _aceita(indice, taxa):
            # Nao e erro: o padrao do sistema toca nela do mesmo jeito, com o
            # ALSA convertendo no meio do caminho.
            logger.info(
                "%s nao aceita %d Hz; deixando o ALSA converter pelo padrao do sistema",
                nome,
                taxa,
            )
            continue
        logger.info("saida de audio escolhida: %s", nome)
        return indice
    return None


def _aceita(indice: int, taxa: int, *, entrada: bool = False) -> bool:
    """Se da para abrir esta placa nesta taxa.

    Abre de verdade, em vez de perguntar ao `check_*_settings`: no microfone
    deste robo o `check` aprova 16000 Hz e a abertura falha com
    `Invalid sample rate` — e quem descobre isso e o robo, no arranque, quando
    ninguem esta olhando. Abrir e fechar custa milissegundos e acontece uma vez.
    """
    try:
        import sounddevice as sd

        classe = sd.RawInputStream if entrada else sd.RawOutputStream
        with classe(samplerate=taxa, device=indice, dtype="int16", channels=1):
            pass
    except Exception:
        # Qualquer recusa — taxa, canais, dispositivo sumido — significa a mesma
        # coisa aqui: esta placa nao serve, procure outra.
        return False
    return True


#: Taxa que o reconhecimento de fala pede. Como na saida, placas USB baratas
#: costumam recusa-la — gravam so a 44100/48000.
TAXA_DE_ESCUTA = 16000


def resolver_entrada(preferencia: str | None, *, taxa: int = TAXA_DE_ESCUTA) -> str | int | None:
    """O mesmo que `resolver_saida`, para o microfone.

    A mesma armadilha vale aqui, e custou um `Invalid sample rate` para ser
    lembrada: a C-Media deste robo grava a 44100 e 48000, e o reconhecimento
    pede 16000. Falar com a placa direto significa gravar nada; pelo padrao do
    sistema, o `plug` do ALSA converte e o microfone funciona.
    """
    if preferencia is None or not preferencia.strip():
        return None

    escolha = preferencia.strip()
    if escolha.isdigit():
        return int(escolha)
    if escolha.lower() != AUTO:
        return escolha

    try:
        dispositivos = _listar()
    except Exception as exc:
        logger.debug("nao consegui listar dispositivos de audio: %s", exc)
        return None

    for indice, dispositivo in enumerate(dispositivos):
        nome = str(dispositivo.get("name", ""))
        if dispositivo.get("max_input_channels", 0) <= 0:
            continue
        if any(apelido in nome.lower() for apelido in _APELIDOS):
            continue
        if "usb" not in nome.lower():
            continue
        if not _aceita(indice, taxa, entrada=True):
            logger.info(
                "%s nao grava a %d Hz; deixando o ALSA converter pelo padrao do sistema",
                nome,
                taxa,
            )
            continue
        logger.info("microfone escolhido: %s", nome)
        return indice
    return None
