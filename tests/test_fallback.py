"""Testes da queda de uma voz online para a reserva offline."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from roboteye.speech.base import AudioFormat, SpeechChunk, SpeechError
from roboteye.speech.fallback import FallbackEngine

FORMATO = AudioFormat(sampleRate=22050)


class VozFalsa:
    """Motor de mentira que grava o que lhe pediram."""

    def __init__(self, name: str, *, falhaEm: int | None = None, blocos: int = 2) -> None:
        self.name = name
        self.falas: list[str] = []
        self.aquecido = False
        self.falhaAoAquecer = False
        #: Em qual bloco levantar erro (0 = já no primeiro), ou None para nunca.
        self.falhaEm = falhaEm
        self.blocos = blocos

    def warmUp(self) -> None:
        if self.falhaAoAquecer:
            raise SpeechError(f"{self.name} indisponivel")
        self.aquecido = True

    def close(self) -> None:
        self.aquecido = False

    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        self.falas.append(text)
        for indice in range(self.blocos):
            if indice == self.falhaEm:
                raise SpeechError(f"{self.name} caiu no bloco {indice}")
            yield SpeechChunk(audio=self.name.encode(), format=FORMATO)


def consumir(engine: FallbackEngine, texto: str = "ola") -> list[str]:
    return [c.audio.decode() for c in engine.synthesize(texto)]


class TestCaminhoFeliz:
    def testUsaAVozPreferidaQuandoElaFunciona(self) -> None:
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem", "nuvem"]
        assert local.falas == []

    def testONomeMostraAsDuasVozes(self) -> None:
        assert FallbackEngine(VozFalsa("nuvem"), VozFalsa("local")).name == "nuvem+local"


class TestQueda:
    def testFalhaNoPrimeiroBlocoTrocaDeVoz(self) -> None:
        nuvem, local = VozFalsa("nuvem", falhaEm=0), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["local", "local"]

    def testATrocaAconteceAntesDeQualquerSom(self) -> None:
        """Trocar de voz no meio de uma frase deixaria metade dela em cada timbre.

        Por isso o primeiro bloco é pedido antes de a fala ser dada como certa:
        se ele não vier, ninguém ouviu nada e a queda passa despercebida.
        """
        nuvem, local = VozFalsa("nuvem", falhaEm=0), VozFalsa("local")
        blocos = consumir(FallbackEngine(nuvem, local))
        assert "nuvem" not in blocos

    def testQuedaNoMeioDaFraseNaoRepeteOQueJaFoiDito(self) -> None:
        """Depois que o som começou não dá para voltar atrás: a frase sai cortada."""
        nuvem, local = VozFalsa("nuvem", falhaEm=1, blocos=3), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem"]
        assert local.falas == []


class TestQuarentena:
    def testDepoisDeFalharNaoTentaDeNovoNaFraseSeguinte(self) -> None:
        """Sem quarentena, cada frase pagaria o tempo limite da rede.

        Uma conversa inteira offline ficaria lenta a ponto de ser inutilizável.
        """
        nuvem, local = VozFalsa("nuvem", falhaEm=0), VozFalsa("local")
        engine = FallbackEngine(nuvem, local, cooldown=60.0)

        consumir(engine, "primeira")
        consumir(engine, "segunda")

        assert nuvem.falas == ["primeira"], "a voz online foi tentada de novo cedo demais"
        assert local.falas == ["primeira", "segunda"]

    def testAQuarentenaExpira(self) -> None:
        nuvem, local = VozFalsa("nuvem", falhaEm=0), VozFalsa("local")
        engine = FallbackEngine(nuvem, local, cooldown=0.0)

        consumir(engine, "primeira")
        consumir(engine, "segunda")

        assert nuvem.falas == ["primeira", "segunda"]


class TestAquecimento:
    def testAReservaEPreparadaMesmoComAPreferidaDisponivel(self) -> None:
        """A reserva precisa estar pronta *antes* de ser necessária.

        Ela entra em cena no instante em que a rede falha, e carregar um modelo
        local leva segundos que não cabem no meio de uma frase.
        """
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        FallbackEngine(nuvem, local).warmUp()
        assert local.aquecido and nuvem.aquecido

    def testPreferidaIndisponivelNoArranqueNaoDerrubaNada(self) -> None:
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        nuvem.falhaAoAquecer = True

        engine = FallbackEngine(nuvem, local)
        engine.warmUp()

        assert local.aquecido
        assert consumir(engine) == ["local", "local"]

    def testFecharLiberaOsDois(self) -> None:
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        engine = FallbackEngine(nuvem, local)
        engine.warmUp()
        engine.close()
        assert not local.aquecido and not nuvem.aquecido


class TestSemAudio:
    def testVozPreferidaMudaNaoCaiParaAReserva(self) -> None:
        """Texto vazio produz zero blocos sem que nada tenha dado errado."""
        nuvem, local = VozFalsa("nuvem", blocos=0), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == []
        assert local.falas == []


class TestAviso:
    """A troca de voz não pode passar despercebida.

    Uma reserva do mesmo idioma e gênero soa como "a voz configurada, só que
    errada" — e quem ouve vai procurar o problema na configuração, que é o único
    lugar onde ele não está. Foi exatamente o que aconteceu quando a queda era
    silenciosa.
    """

    def testAvisaAoCairParaAReserva(self) -> None:
        avisos: list[str] = []
        engine = FallbackEngine(
            VozFalsa("nuvem", falhaEm=0), VozFalsa("local"), onSwitch=avisos.append
        )
        consumir(engine)

        assert len(avisos) == 1
        assert "reserva" in avisos[0] and "local" in avisos[0]

    def testNaoRepeteOAvisoACadaFrase(self) -> None:
        """Avisar uma vez informa; avisar sempre vira ruído e some no meio da conversa."""
        avisos: list[str] = []
        engine = FallbackEngine(
            VozFalsa("nuvem", falhaEm=0),
            VozFalsa("local"),
            cooldown=60.0,
            onSwitch=avisos.append,
        )
        for _ in range(5):
            consumir(engine)

        assert len(avisos) == 1

    def testAvisaQuandoAVozPreferidaVolta(self) -> None:
        nuvem = VozFalsa("nuvem", falhaEm=0)
        avisos: list[str] = []
        engine = FallbackEngine(nuvem, VozFalsa("local"), cooldown=0.0, onSwitch=avisos.append)

        consumir(engine)  # cai
        nuvem.falhaEm = None  # a rede voltou
        consumir(engine)

        assert len(avisos) == 2
        assert "de volta" in avisos[1]

    def testAvisaQuandoAPreferidaFalhaNoArranque(self) -> None:
        avisos: list[str] = []
        nuvem = VozFalsa("nuvem")
        nuvem.falhaAoAquecer = True

        FallbackEngine(nuvem, VozFalsa("local"), onSwitch=avisos.append).warmUp()
        assert len(avisos) == 1

    def testSemFalhaNaoHaAviso(self) -> None:
        avisos: list[str] = []
        engine = FallbackEngine(VozFalsa("nuvem"), VozFalsa("local"), onSwitch=avisos.append)
        engine.warmUp()
        consumir(engine)
        assert avisos == []

    def testFuncionaSemNinguemEscutando(self) -> None:
        engine = FallbackEngine(VozFalsa("nuvem", falhaEm=0), VozFalsa("local"))
        assert consumir(engine) == ["local", "local"]


@pytest.mark.parametrize("cooldown", [-5.0, 0.0, 10.0])
def testCooldownNegativoNaoQuebra(cooldown: float) -> None:
    engine = FallbackEngine(VozFalsa("a"), VozFalsa("b"), cooldown=cooldown)
    assert consumir(engine) == ["a", "a"]


class VozDeRede(VozFalsa):
    """Voz online que sabe dizer se a rede já chegou.

    Existe porque o motor de rede real ganhou essa pergunta (`alcancavel`) para
    que a saudação de arranque não fosse pela voz errada — ver a docstring de
    `fallback.py`.
    """

    def __init__(self, name: str = "nuvem", *, chegaNaTentativa: int | None = 0) -> None:
        super().__init__(name)
        #: Em qual consulta a rede aparece. None = nunca chega.
        self.chega = chegaNaTentativa
        self.consultas = 0

    def alcancavel(self) -> bool:
        atual = self.consultas
        self.consultas += 1
        return self.chega is not None and atual >= self.chega


class TestEsperaDeArranque:
    """A primeira frase espera a rede subir; as seguintes, não.

    O robô fala a saudação segundos antes de a rede existir. Desistir ali não
    trocava uma frase de voz — trocava a voz do robô pelo resto da sessão,
    porque nada mais fala depois da saudação.
    """

    def testNaoEsperaQuandoARedeJaEstaDePe(self) -> None:
        nuvem, local = VozDeRede(chegaNaTentativa=0), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem", "nuvem"]
        assert nuvem.consultas == 1, "uma consulta basta quando a rede responde"

    def testEsperaARedeChegarEUsaAVozBoa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dormidas: list[float] = []
        monkeypatch.setattr("roboteye.speech.fallback.time.sleep", dormidas.append)

        nuvem, local = VozDeRede(chegaNaTentativa=2), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem", "nuvem"]
        assert local.falas == [], "a reserva não devia ter falado"
        assert dormidas, "esperou sem dormir — isso viraria laço quente"

    def testDesisteEFalaPelaReservaSeARedeNaoVier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem internet nenhuma, o robô ainda tem que dar bom dia."""
        agora = [0.0]
        monkeypatch.setattr("roboteye.speech.fallback.time.monotonic", lambda: agora[0])
        monkeypatch.setattr(
            "roboteye.speech.fallback.time.sleep",
            lambda s: agora.__setitem__(0, agora[0] + s),
        )

        nuvem, local = VozDeRede(chegaNaTentativa=None), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["local", "local"]
        assert agora[0] <= FallbackEngine(nuvem, local).esperaDeArranque + 1

    def testEsperaUmaVezSo(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Depois da primeira frase, quem conversa prefere a reserva agora."""
        monkeypatch.setattr("roboteye.speech.fallback.time.sleep", lambda _: None)

        nuvem, local = VozDeRede(chegaNaTentativa=1), VozFalsa("local")
        motor = FallbackEngine(nuvem, local)
        consumir(motor)
        consultasAposAPrimeira = nuvem.consultas
        consumir(motor, "outra frase")
        assert nuvem.consultas == consultasAposAPrimeira

    def testVozLocalNaoEPerguntada(self) -> None:
        """Uma voz de disco nunca esteve fora do ar; não há o que esperar."""
        localPreferida, reserva = VozFalsa("local"), VozFalsa("outra")
        assert consumir(FallbackEngine(localPreferida, reserva)) == ["local", "local"]

    def testEsperaDesligadaNaoConsultaARede(self) -> None:
        nuvem, local = VozDeRede(chegaNaTentativa=None), VozFalsa("local")
        consumir(FallbackEngine(nuvem, local, esperaDeArranque=0))
        assert nuvem.consultas == 0
