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

**O zumbido precisa sair antes de medir qualquer coisa.** Medido no robô: a
energia entre 20 e 150 Hz chegava a ser 40 vezes maior que a da banda da voz —
zumbido da rede elétrica e do próprio dongle USB, não som da sala. Ele domina o
RMS, e o efeito prático é que fala e silêncio medem exatamente igual (1,00x de
separação): nenhum limiar consegue distinguir os dois, e o robô fica surdo com o
microfone funcionando. Um passa-alta simples resolve, e de quebra limpa o que vai
para o reconhecimento — nada abaixo de 150 Hz é voz.

**A placa manda na taxa.** O reconhecimento pede 16 kHz, e nem toda placa grava
nessa taxa: a C-Media deste robô só faz 44,1 e 48 kHz. Normalmente o `plug` do
ALSA converteria, mas com `dsnoop` no caminho — necessário para a caixinha e o
microfone dividirem a mesma placa — ele deixa de anunciar 16 kHz, e a abertura
morre com `Invalid sample rate`. Em vez de depender da configuração do sistema
acertar isso, o microfone abre na taxa que a placa aceitar e converte no código.

**O limiar não pode ser um número fixo.** Foi, e não funcionou: o ruído de fundo
medido no robô de produção (0,042) era o dobro do limiar escolhido no escritório
(0,02), então o silêncio da sala contava como fala. O robô gravava trechos de 15
segundos sem ninguém falando, transcrevia nada e ocupava a CPU o tempo todo. Cada
sala tem um ruído, cada microfone tem um ganho — então o limiar é medido no
arranque, a partir do próprio ambiente.
"""

from __future__ import annotations

import contextlib
import queue
import time
from collections import deque
from collections.abc import Callable, Iterator

import numpy as np

from roboteye.hearing.base import HearingError
from roboteye.logging_setup import get_logger

logger = get_logger(__name__)

#: Taxa que os modelos de reconhecimento esperam.
TAXA = 16000

#: Tamanho do bloco lido do microfone: 30 ms. É a resolução com que o silêncio é
#: medido, e o que define quão fino dá para cortar.
BLOCO = 480

#: Abaixo disto não há voz — só zumbido de rede, vibração de mesa e ruído do
#: próprio conversor USB. A voz humana começa perto de 85 Hz nos graves, mas o
#: que carrega a inteligibilidade (e o que o reconhecimento usa) mora acima de
#: 300; cortar em 150 tira o zumbido inteiro sem tocar na fala.
CORTE_GRAVES_HZ = 150.0

#: Quantos blocos seguidos acima do limiar contam como "ainda falando".
#:
#: Um bloco solto nao conta, e essa e a diferenca entre uma frase que fecha e
#: uma que nao fecha. Zerar a contagem de silencio a cada bloco isolado parece
#: inofensivo ate a voz de quem fala ficar perto do limiar: as silabas cruzam,
#: as pausas nao, e a contagem de silencio nunca chega ao fim. Visto no robo —
#: uma pergunta curta virou uma captura de 15 segundos, o teto, com o
#: reconhecimento descartando 10 deles como nao-fala:
#:
#:     Processing audio with duration 00:15.000
#:     VAD filter removed 00:10.288 of audio
#:
#: Quinze segundos de espera antes de a transcricao sequer comecar. Dois blocos
#: seguidos (60 ms) e pouco para atrapalhar uma silaba de verdade e o bastante
#: para um estalo, uma respiracao ou um pico do ar-condicionado nao segurarem a
#: gravacao aberta.
VOZ_PARA_CONTINUAR = 2

#: Quanto tempo sem **nenhum** bloco significa que a captura morreu.
#:
#: Sala quieta também produz bloco: silêncio é áudio de energia baixa, não
#: ausência de áudio. A 30 ms por bloco chegam uns 33 por segundo, e três
#: segundos de nada só acontecem quando o dispositivo parou de entregar — foi
#: o que aconteceu no robô quando a placa USB se desconectou e voltou com outro
#: número (`usb 1-1: USB disconnect` no `dmesg`). A partir dali o PortAudio
#: ficava girando no `poll` do ALSA sobre um dispositivo que não existia mais:
#: um núcleo inteiro a 100%, o robô surdo, e **nada** no log dizendo isso.
SEM_AUDIO_S = 3.0

#: Espera antes de tentar reabrir, e o teto dela. Dobra a cada tentativa: um
#: dispositivo que sumiu de vez não deve virar um laço de reabertura a cada
#: segundo pelo resto do dia.
ESPERA_INICIAL_S = 1.0
ESPERA_MAXIMA_S = 15.0


class _CapturaParou(Exception):
    """O dispositivo deixou de entregar áudio. Interna: quem trata é `frases()`."""


class PassaAlta:
    """Filtro de primeira ordem, aplicado bloco a bloco.

    Guarda o estado entre blocos porque o áudio chega em pedaços: reiniciar o
    filtro a cada bloco produziria um degrau de 30 em 30 ms, que é exatamente o
    tipo de coisa que o detector de fala leria como alguém falando.
    """

    def __init__(self, corte_hz: float, taxa: int) -> None:
        rc = 1.0 / (2.0 * np.pi * corte_hz)
        dt = 1.0 / taxa
        self._a = rc / (rc + dt)
        self._x_anterior = 0.0
        self._y_anterior = 0.0

    def aplicar(self, bloco: np.ndarray) -> np.ndarray:
        # y[n] = a * (y[n-1] + x[n] - x[n-1]) — a forma padrão do passa-alta RC
        # discreto. Em Python puro seria lento demais para 16 000 amostras por
        # segundo; o `lfilter` do numpy não existe, então a recorrência vai num
        # laço sobre o bloco, que a 480 amostras é barato.
        a = self._a
        saida = np.empty_like(bloco)
        y = self._y_anterior
        x_ant = self._x_anterior
        for i, x in enumerate(bloco):
            y = a * (y + x - x_ant)
            x_ant = x
            saida[i] = y
        self._y_anterior = float(y)
        self._x_anterior = float(x_ant)
        return saida


class Microfone:
    """Escuta e entrega um trecho de áudio por frase falada."""

    def __init__(
        self,
        *,
        device: str | int | None = None,
        limiar: float | None = None,
        silencio_s: float = 0.8,
        minimo_s: float = 0.4,
        maximo_s: float = 10.0,
    ) -> None:
        self._device = device
        #: Acima disto conta como fala. None faz medir a sala no arranque.
        self._limiar = limiar if limiar is not None else 0.0
        self._calibrar = limiar is None
        #: Silêncio que fecha a frase. Ver o comentário sobre a vírgula.
        self._silencio = int(silencio_s * TAXA / BLOCO)
        #: Curto demais é ruído — uma porta, uma cadeira, uma tosse.
        self._minimo = int(minimo_s * TAXA / BLOCO)
        #: Teto de segurança: sem ele, um ruído contínuo (um ventilador ligando)
        #: gravaria para sempre e nada seria transcrito. Bater nele é sinal de
        #: que algo está errado — ninguém faz uma pergunta de dez segundos a um
        #: robô —, e por isso ele avisa no log quando acontece.
        self._maximo = int(maximo_s * TAXA / BLOCO)
        #: O que veio antes de o som subir. 300 ms bastam para a primeira sílaba.
        self._antes: deque[np.ndarray] = deque(maxlen=10)

        #: Avisado no instante em que uma frase fecha — antes de transcrever.
        #: Ver `AvisaAoFecharFrase` em `hearing/base.py`.
        self._ao_fechar_frase: Callable[[], None] | None = None

        self._filtro = PassaAlta(CORTE_GRAVES_HZ, TAXA)
        self._blocos: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=200)
        self._pausado = False
        self._fechado = False

    def ao_fechar_frase(self, callback: Callable[[], None] | None) -> None:
        """Registra quem avisar quando a captura de uma frase termina."""
        self._ao_fechar_frase = callback

    def pausar(self) -> None:
        self._pausado = True

    def retomar(self) -> None:
        self._pausado = False

    def fechar(self) -> None:
        self._fechado = True
        with contextlib.suppress(queue.Full):
            self._blocos.put_nowait(None)

    def frases(self) -> Iterator[np.ndarray]:
        """Produz um trecho de áudio por frase falada, até ser fechado.

        Reabre o dispositivo sozinha quando ele para de entregar áudio. Isto não
        é zelo defensivo genérico: a placa USB deste robô se desconecta e volta
        com outro número de dispositivo, e sem reabrir o robô ficava surdo até
        alguém reiniciar o serviço — enquanto queimava um núcleo de CPU no laço
        de `poll` do ALSA. Ver `SEM_AUDIO_S`.
        """
        try:
            import sounddevice as sd
        except (ImportError, OSError) as exc:
            raise HearingError(f"microfone indisponivel: {exc}") from exc

        espera = ESPERA_INICIAL_S
        primeira = True
        while not self._fechado:
            try:
                yield from self._uma_captura(sd)
                return  # saiu limpo: alguém chamou `fechar()`
            except _CapturaParou as motivo:
                logger.warning("o microfone parou de entregar audio (%s); reabrindo", motivo)
            except HearingError:
                # Nenhuma taxa serve: reabrir não vai mudar isso. Sobe para
                # quem chamou, que já sabe anunciar "escuta indisponivel".
                if primeira:
                    raise
                logger.warning("o microfone sumiu e nao voltou; tentando de novo")
            except Exception:
                logger.exception("falha inesperada na captura; reabrindo")
            finally:
                primeira = False

            if self._fechado:
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

    def _uma_captura(self, sd) -> Iterator[np.ndarray]:
        """Uma sessão de captura, do `open` até o dispositivo parar."""

        def receber(entrada, _quadros, _tempo, status) -> None:
            if status:
                logger.debug("microfone reclamou: %s", status)
            # Enquanto a Atlas fala, tudo o que chega é a própria voz dela.
            if self._pausado:
                return
            bloco = entrada[:, 0]
            if fator > 1:
                # Média de cada grupo, não descarte de amostras: descartar
                # rebate as frequências altas para dentro da fala e o
                # reconhecimento piora justamente nas vozes agudas — as das
                # crianças, que são quem vai falar com este robô.
                n = (len(bloco) // fator) * fator
                bloco = bloco[:n].reshape(-1, fator).mean(axis=1)
            # O filtro entra aqui, antes de tudo: o mesmo áudio limpo é o que
            # alimenta a medição de energia e o reconhecimento.
            with contextlib.suppress(queue.Full):
                self._blocos.put_nowait(self._filtro.aplicar(bloco))

        taxa, fator = self._negociar_taxa(sd)
        with sd.InputStream(
            samplerate=taxa,
            blocksize=BLOCO * fator,
            device=self._device,
            dtype="float32",
            channels=1,
            callback=receber,
        ):
            if self._calibrar:
                # Uma vez só, e só se der certo. Numa reabertura bem-sucedida,
                # medir de novo esperaria até 20 s a Atlas calar a boca — e a
                # sala é a mesma de dois segundos atrás. Mas uma medição que
                # falhou (dispositivo morto, nenhuma amostra) deixou o limiar no
                # valor de emergência, e esse merece ser refeito.
                self._calibrar = not self._medir_a_sala()
            logger.info("escutando pelo microfone (limiar %.4f)", self._limiar)
            yield from self._cortar_em_frases()

    def _negociar_taxa(self, sd) -> tuple[int, int]:
        """Descobre em que taxa dá para gravar, e de quanto é a conversão.

        Só taxas múltiplas de 16 kHz entram na lista: a conversão vira uma média
        de N amostras, exata e barata. Uma taxa qualquer exigiria reamostragem
        de verdade, e nenhuma placa comum obriga a isso.
        """
        for taxa in (TAXA, 32000, 48000):
            fator = taxa // TAXA
            try:
                with sd.InputStream(
                    samplerate=taxa,
                    blocksize=BLOCO * fator,
                    device=self._device,
                    dtype="float32",
                    channels=1,
                ):
                    pass
            except Exception:
                continue
            if fator > 1:
                logger.info("o microfone grava a %d Hz; convertendo para %d", taxa, TAXA)
            return taxa, fator

        raise HearingError("o microfone nao grava em nenhuma taxa util (16000, 32000 ou 48000 Hz)")

    def _avisar_que_fechou(self) -> None:
        """Diz a quem quiser ouvir que a captura de uma frase acabou de fechar.

        Falha em silêncio de propósito: isto é aviso, e quem escuta pode estar
        tocando um som. Um erro ali não pode fazer a frase recém-capturada se
        perder — ela é o que a pessoa acabou de dizer.
        """
        if self._ao_fechar_frase is None:
            return
        try:
            self._ao_fechar_frase()
        except Exception as exc:
            logger.debug("aviso de fim de frase falhou: %s", exc)

    def _medir_a_sala(self) -> bool:
        """Escolhe o limiar a partir do ruído que esta sala realmente tem.

        Devolve `False` quando não chegou amostra nenhuma — o limiar fica no
        valor de emergência e quem chamou sabe que precisa medir de novo.

        Fica no dobro e meio do ruído medido: alto o bastante para o ar
        condicionado não virar pergunta, baixo o bastante para uma criança
        falando a um metro passar. O piso existe para uma sala anecoica não
        deixar o limiar em zero, onde qualquer estalo acordaria o robô.
        """
        # A saudacao de arranque fala justamente agora, e falar pausa a escuta —
        # entao os primeiros segundos nao tem bloco nenhum para medir. Esperar
        # ela terminar e a diferenca entre calibrar com a sala e cair no valor
        # de emergencia, que e baixo demais e faz o robo gravar o proprio
        # silencio o dia inteiro.
        esperou = 0.0
        while self._pausado and esperou < 20.0 and not self._fechado:
            time.sleep(0.2)
            esperou += 0.2
        if esperou:
            logger.debug("esperei %.1fs a Atlas terminar de falar para medir a sala", esperou)
        # O que entrou na fila enquanto ela falava nao serve de amostra.
        with contextlib.suppress(queue.Empty):
            while True:
                self._blocos.get_nowait()

        amostras: list[float] = []
        while len(amostras) < 30:
            try:
                bloco = self._blocos.get(timeout=2.0)
            except queue.Empty:
                break
            if bloco is None:
                break
            amostras.append(float(np.sqrt(np.mean(bloco**2))))

        if not amostras:
            self._limiar = 0.02
            logger.warning("nao consegui medir o ruido da sala; usando 0.02")
            return False

        ruido = float(np.percentile(amostras, 95))
        self._limiar = max(0.015, ruido * 2.5)
        logger.info("ruido da sala %.4f; falar comeca em %.4f", ruido, self._limiar)
        return True

    def _cortar_em_frases(self) -> Iterator[np.ndarray]:
        falando: list[np.ndarray] = []
        quieto = 0
        #: Blocos acima do limiar em sequência. Ver `VOZ_PARA_CONTINUAR`.
        voz_seguida = 0
        #: Blocos com voz de verdade. E este numero, e nao o tamanho do trecho,
        #: que decide se houve pergunta: o preambulo guardado antes da fala
        #: sozinho ja passaria do minimo, e um estalo de porta viraria pergunta.
        com_voz = 0
        ultimo_bloco = time.monotonic()

        while not self._fechado:
            try:
                bloco = self._blocos.get(timeout=0.5)
            except queue.Empty:
                if self._pausado:
                    # A Atlas está falando, e enquanto ela fala a captura
                    # descarta o que chega — é a própria voz dela. Não há bloco
                    # a esperar, então o relógio do vigia **não pode correr**:
                    # senão toda resposta com mais de três segundos terminava
                    # com uma reabertura do dispositivo que ninguém pediu, e o
                    # robô ficava um segundo surdo justo depois de responder,
                    # que é quando a pessoa costuma emendar a próxima pergunta.
                    ultimo_bloco = time.monotonic()
                    continue
                if time.monotonic() - ultimo_bloco > SEM_AUDIO_S:
                    raise _CapturaParou(f"nada ha {SEM_AUDIO_S:.0f}s") from None
                continue
            ultimo_bloco = time.monotonic()
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
                    voz_seguida = 1
                continue

            falando.append(bloco)
            if tem_voz:
                com_voz += 1
                voz_seguida += 1
                # Só uma sequência conta como "ainda falando". Ver
                # `VOZ_PARA_CONTINUAR`: um bloco solto zerando o silêncio é o
                # que fazia a frase nunca fechar.
                if voz_seguida >= VOZ_PARA_CONTINUAR:
                    quieto = 0
            else:
                voz_seguida = 0
                quieto += 1

            no_teto = len(falando) >= self._maximo
            if quieto >= self._silencio or no_teto:
                trecho, falando = falando, []
                self._antes.clear()
                segundos = len(trecho) * BLOCO / TAXA
                if no_teto:
                    logger.warning(
                        "frase cortada no teto de %.0fs (só %.1fs com voz) — "
                        "o limiar de %.4f pode estar alto para esta sala",
                        segundos,
                        com_voz * BLOCO / TAXA,
                        self._limiar,
                    )
                if com_voz >= self._minimo:
                    self._avisar_que_fechou()
                    logger.info("frase de %.1fs (%.1fs com voz)", segundos, com_voz * BLOCO / TAXA)
                    yield np.concatenate(trecho)
                else:
                    logger.debug("so %d blocos com voz; era ruido, nao pergunta", com_voz)
                com_voz = 0
                voz_seguida = 0
