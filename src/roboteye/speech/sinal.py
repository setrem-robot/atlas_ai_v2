"""Os sons curtos que a Atlas usa para dizer o que está fazendo, sem falar.

Chamar o nome dela e ficar no silêncio é a pior parte de conversar com este
robô. Quem falou não sabe se foi ouvido, então repete o nome — e a repetição
chega justamente enquanto a resposta da primeira vez está sendo preparada.

Uma frase resolveria isso, e é o que a `resposta_ao_chamado` faz. Mas falar
custa caro: sintetizar "Oi?" leva de meio a dois segundos, dependendo do motor
de voz, e o robô só diz isso **depois** de esperar alguns segundos pela
pergunta. Um som pronto sai na hora.

**Por que um som e não um arquivo.** Um `.wav` no repositório seria mais um
caminho para dar errado (não baixou, permissão, formato) para resolver duzentos
milissegundos de áudio que cabem em vinte linhas de aritmética. Aqui o som é
gerado uma vez, na primeira vez que alguém pede, e fica guardado.

**Por que sem numpy.** São uns poucos milhares de amostras, uma vez só na vida
do processo. A biblioteca padrão dá conta, e assim este módulo continua
utilizável num robô instalado sem os extras de voz.

**Por que ele é curto.** O microfone continua aberto enquanto o sinal toca — a
Atlas não se pausa para um bipe. Um som de 220 ms fica bem abaixo do mínimo de
400 ms que `microfone.py` exige para considerar um trecho como fala, então ele
não vira pergunta nem entra na transcrição.
"""

from __future__ import annotations

import math
from array import array
from functools import cache

from roboteye.speech.base import AudioFormat, SpeechChunk

#: Taxa do sinal. A mesma do Piper, que é o motor local mais comum — assim, na
#: maioria das vezes, tocar o sinal não obriga a reabrir o dispositivo de áudio
#: num formato diferente.
TAXA = 22050

#: As duas notas dos sinais. Sol5 e Ré6 — uma quinta justa, o intervalo mais
#: estável que existe, e por isso o que menos soa como alarme.
#:
#: A **ordem** é que carrega o significado, e é o par que faz sentido: subindo
#: se lê como "pode falar", descendo como "pronto, ouvi". Um som sozinho não
#: diria qual dos dois momentos é — e saber qual é o pedido inteiro aqui.
NOTA_GRAVE_HZ = 784.0
NOTA_AGUDA_HZ = 1175.0

DURACAO_NOTA_S = 0.09
PAUSA_ENTRE_NOTAS_S = 0.02

#: Amplitude, de 0 a 1. Baixa de propósito: isto é um aviso discreto, e vai
#: tocar a poucos centímetros de quem está falando com o robô.
VOLUME = 0.22

#: Subida e descida de cada nota. Sem elas, o corte seco no início e no fim da
#: senoide vira um estalo — e um estalo num alto-falante pequeno é mais audível
#: que a própria nota.
RAMPA_S = 0.008


def _nota(frequencia: float, duracao_s: float) -> array:
    """Uma senoide com as bordas suavizadas, em PCM de 16 bits."""
    total = int(TAXA * duracao_s)
    rampa = max(1, int(TAXA * RAMPA_S))
    amostras = array("h", bytes(2 * total))

    for i in range(total):
        # Meio cosseno na entrada e na saída: a amplitude sai de zero e volta a
        # zero sem degrau nenhum.
        if i < rampa:
            envelope = 0.5 * (1.0 - math.cos(math.pi * i / rampa))
        elif i >= total - rampa:
            restante = total - 1 - i
            envelope = 0.5 * (1.0 - math.cos(math.pi * restante / rampa))
        else:
            envelope = 1.0
        valor = math.sin(2.0 * math.pi * frequencia * i / TAXA)
        amostras[i] = int(valor * envelope * VOLUME * 32767)

    return amostras


def _silencio(duracao_s: float) -> array:
    return array("h", bytes(2 * int(TAXA * duracao_s)))


@cache
def _par(primeira_hz: float, segunda_hz: float) -> bytes:
    som = _nota(primeira_hz, DURACAO_NOTA_S)
    som.extend(_silencio(PAUSA_ENTRE_NOTAS_S))
    som.extend(_nota(segunda_hz, DURACAO_NOTA_S))
    return som.tobytes()


def _chunk(pcm: bytes) -> tuple[SpeechChunk, ...]:
    """Embrulha o PCM no mesmo formato que um motor de voz devolveria.

    É o que permite tocar o sinal pelo caminho que já existe — um dono só do
    dispositivo de áudio.
    """
    return (
        SpeechChunk(
            audio=pcm,
            format=AudioFormat(sample_rate=TAXA, channels=1, sample_width=2),
        ),
    )


def escutando() -> tuple[SpeechChunk, ...]:
    """Subindo: "estou ouvindo, pode perguntar"."""
    return _chunk(_par(NOTA_GRAVE_HZ, NOTA_AGUDA_HZ))


def ouvi() -> tuple[SpeechChunk, ...]:
    """Descendo: "pronto, terminei de ouvir — agora deixa comigo".

    O espelho exato do outro. Dois sons diferentes diriam duas coisas sem
    relação; o mesmo par invertido é lido de imediato como abre e fecha.
    """
    return _chunk(_par(NOTA_AGUDA_HZ, NOTA_GRAVE_HZ))


def duracao_s() -> float:
    """Quanto tempo um sinal dura. Os dois têm a mesma duração."""
    return len(_par(NOTA_GRAVE_HZ, NOTA_AGUDA_HZ)) / 2 / TAXA
