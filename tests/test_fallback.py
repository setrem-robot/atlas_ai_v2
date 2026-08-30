"""Testes da queda de uma voz online para a reserva offline."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from roboteye.speech.base import AudioFormat, SpeechChunk, SpeechError
from roboteye.speech.fallback import FallbackEngine

FORMATO = AudioFormat(sample_rate=22050)


class VozFalsa:
    """Motor de mentira que grava o que lhe pediram."""

    def __init__(self, name: str, *, falha_em: int | None = None, blocos: int = 2) -> None:
        self.name = name
        self.falas: list[str] = []
        self.aquecido = False
        self.falha_ao_aquecer = False
        #: Em qual bloco levantar erro (0 = já no primeiro), ou None para nunca.
        self._falha_em = falha_em
        self._blocos = blocos

    def warm_up(self) -> None:
        if self.falha_ao_aquecer:
            raise SpeechError(f"{self.name} indisponivel")
        self.aquecido = True

    def close(self) -> None:
        self.aquecido = False

    def synthesize(self, text: str) -> Iterator[SpeechChunk]:
        self.falas.append(text)
        for indice in range(self._blocos):
            if indice == self._falha_em:
                raise SpeechError(f"{self.name} caiu no bloco {indice}")
            yield SpeechChunk(audio=self.name.encode(), format=FORMATO)


def consumir(engine: FallbackEngine, texto: str = "ola") -> list[str]:
    return [c.audio.decode() for c in engine.synthesize(texto)]


class TestCaminhoFeliz:
    def test_usa_a_voz_preferida_quando_ela_funciona(self) -> None:
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem", "nuvem"]
        assert local.falas == []

    def test_o_nome_mostra_as_duas_vozes(self) -> None:
        assert FallbackEngine(VozFalsa("nuvem"), VozFalsa("local")).name == "nuvem+local"


class TestQueda:
    def test_falha_no_primeiro_bloco_troca_de_voz(self) -> None:
        nuvem, local = VozFalsa("nuvem", falha_em=0), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["local", "local"]

    def test_a_troca_acontece_antes_de_qualquer_som(self) -> None:
        """Trocar de voz no meio de uma frase deixaria metade dela em cada timbre.

        Por isso o primeiro bloco é pedido antes de a fala ser dada como certa:
        se ele não vier, ninguém ouviu nada e a queda passa despercebida.
        """
        nuvem, local = VozFalsa("nuvem", falha_em=0), VozFalsa("local")
        blocos = consumir(FallbackEngine(nuvem, local))
        assert "nuvem" not in blocos

    def test_queda_no_meio_da_frase_nao_repete_o_que_ja_foi_dito(self) -> None:
        """Depois que o som começou não dá para voltar atrás: a frase sai cortada."""
        nuvem, local = VozFalsa("nuvem", falha_em=1, blocos=3), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem"]
        assert local.falas == []


class TestQuarentena:
    def test_depois_de_falhar_nao_tenta_de_novo_na_frase_seguinte(self) -> None:
        """Sem quarentena, cada frase pagaria o tempo limite da rede.

        Uma conversa inteira offline ficaria lenta a ponto de ser inutilizável.
        """
        nuvem, local = VozFalsa("nuvem", falha_em=0), VozFalsa("local")
        engine = FallbackEngine(nuvem, local, cooldown=60.0)

        consumir(engine, "primeira")
        consumir(engine, "segunda")

        assert nuvem.falas == ["primeira"], "a voz online foi tentada de novo cedo demais"
        assert local.falas == ["primeira", "segunda"]

    def test_a_quarentena_expira(self) -> None:
        nuvem, local = VozFalsa("nuvem", falha_em=0), VozFalsa("local")
        engine = FallbackEngine(nuvem, local, cooldown=0.0)

        consumir(engine, "primeira")
        consumir(engine, "segunda")

        assert nuvem.falas == ["primeira", "segunda"]


class TestAquecimento:
    def test_a_reserva_e_preparada_mesmo_com_a_preferida_disponivel(self) -> None:
        """A reserva precisa estar pronta *antes* de ser necessária.

        Ela entra em cena no instante em que a rede falha, e carregar um modelo
        local leva segundos que não cabem no meio de uma frase.
        """
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        FallbackEngine(nuvem, local).warm_up()
        assert local.aquecido and nuvem.aquecido

    def test_preferida_indisponivel_no_arranque_nao_derruba_nada(self) -> None:
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        nuvem.falha_ao_aquecer = True

        engine = FallbackEngine(nuvem, local)
        engine.warm_up()

        assert local.aquecido
        assert consumir(engine) == ["local", "local"]

    def test_fechar_libera_os_dois(self) -> None:
        nuvem, local = VozFalsa("nuvem"), VozFalsa("local")
        engine = FallbackEngine(nuvem, local)
        engine.warm_up()
        engine.close()
        assert not local.aquecido and not nuvem.aquecido


class TestSemAudio:
    def test_voz_preferida_muda_nao_cai_para_a_reserva(self) -> None:
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

    def test_avisa_ao_cair_para_a_reserva(self) -> None:
        avisos: list[str] = []
        engine = FallbackEngine(
            VozFalsa("nuvem", falha_em=0), VozFalsa("local"), on_switch=avisos.append
        )
        consumir(engine)

        assert len(avisos) == 1
        assert "reserva" in avisos[0] and "local" in avisos[0]

    def test_nao_repete_o_aviso_a_cada_frase(self) -> None:
        """Avisar uma vez informa; avisar sempre vira ruído e some no meio da conversa."""
        avisos: list[str] = []
        engine = FallbackEngine(
            VozFalsa("nuvem", falha_em=0),
            VozFalsa("local"),
            cooldown=60.0,
            on_switch=avisos.append,
        )
        for _ in range(5):
            consumir(engine)

        assert len(avisos) == 1

    def test_avisa_quando_a_voz_preferida_volta(self) -> None:
        nuvem = VozFalsa("nuvem", falha_em=0)
        avisos: list[str] = []
        engine = FallbackEngine(nuvem, VozFalsa("local"), cooldown=0.0, on_switch=avisos.append)

        consumir(engine)  # cai
        nuvem._falha_em = None  # a rede voltou
        consumir(engine)

        assert len(avisos) == 2
        assert "de volta" in avisos[1]

    def test_avisa_quando_a_preferida_falha_no_arranque(self) -> None:
        avisos: list[str] = []
        nuvem = VozFalsa("nuvem")
        nuvem.falha_ao_aquecer = True

        FallbackEngine(nuvem, VozFalsa("local"), on_switch=avisos.append).warm_up()
        assert len(avisos) == 1

    def test_sem_falha_nao_ha_aviso(self) -> None:
        avisos: list[str] = []
        engine = FallbackEngine(VozFalsa("nuvem"), VozFalsa("local"), on_switch=avisos.append)
        engine.warm_up()
        consumir(engine)
        assert avisos == []

    def test_funciona_sem_ninguem_escutando(self) -> None:
        engine = FallbackEngine(VozFalsa("nuvem", falha_em=0), VozFalsa("local"))
        assert consumir(engine) == ["local", "local"]


@pytest.mark.parametrize("cooldown", [-5.0, 0.0, 10.0])
def test_cooldown_negativo_nao_quebra(cooldown: float) -> None:
    engine = FallbackEngine(VozFalsa("a"), VozFalsa("b"), cooldown=cooldown)
    assert consumir(engine) == ["a", "a"]


class VozDeRede(VozFalsa):
    """Voz online que sabe dizer se a rede já chegou.

    Existe porque o motor de rede real ganhou essa pergunta (`alcancavel`) para
    que a saudação de arranque não fosse pela voz errada — ver a docstring de
    `fallback.py`.
    """

    def __init__(self, name: str = "nuvem", *, chega_na_tentativa: int | None = 0) -> None:
        super().__init__(name)
        #: Em qual consulta a rede aparece. None = nunca chega.
        self._chega = chega_na_tentativa
        self.consultas = 0

    def alcancavel(self) -> bool:
        atual = self.consultas
        self.consultas += 1
        return self._chega is not None and atual >= self._chega


class TestEsperaDeArranque:
    """A primeira frase espera a rede subir; as seguintes, não.

    O robô fala a saudação segundos antes de a rede existir. Desistir ali não
    trocava uma frase de voz — trocava a voz do robô pelo resto da sessão,
    porque nada mais fala depois da saudação.
    """

    def test_nao_espera_quando_a_rede_ja_esta_de_pe(self) -> None:
        nuvem, local = VozDeRede(chega_na_tentativa=0), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem", "nuvem"]
        assert nuvem.consultas == 1, "uma consulta basta quando a rede responde"

    def test_espera_a_rede_chegar_e_usa_a_voz_boa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dormidas: list[float] = []
        monkeypatch.setattr("roboteye.speech.fallback.time.sleep", dormidas.append)

        nuvem, local = VozDeRede(chega_na_tentativa=2), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["nuvem", "nuvem"]
        assert local.falas == [], "a reserva não devia ter falado"
        assert dormidas, "esperou sem dormir — isso viraria laço quente"

    def test_desiste_e_fala_pela_reserva_se_a_rede_nao_vier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sem internet nenhuma, o robô ainda tem que dar bom dia."""
        agora = [0.0]
        monkeypatch.setattr("roboteye.speech.fallback.time.monotonic", lambda: agora[0])
        monkeypatch.setattr(
            "roboteye.speech.fallback.time.sleep",
            lambda s: agora.__setitem__(0, agora[0] + s),
        )

        nuvem, local = VozDeRede(chega_na_tentativa=None), VozFalsa("local")
        assert consumir(FallbackEngine(nuvem, local)) == ["local", "local"]
        assert agora[0] <= FallbackEngine(nuvem, local)._espera_de_arranque + 1

    def test_espera_uma_vez_so(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Depois da primeira frase, quem conversa prefere a reserva agora."""
        monkeypatch.setattr("roboteye.speech.fallback.time.sleep", lambda _: None)

        nuvem, local = VozDeRede(chega_na_tentativa=1), VozFalsa("local")
        motor = FallbackEngine(nuvem, local)
        consumir(motor)
        consultas_apos_a_primeira = nuvem.consultas
        consumir(motor, "outra frase")
        assert nuvem.consultas == consultas_apos_a_primeira

    def test_voz_local_nao_e_perguntada(self) -> None:
        """Uma voz de disco nunca esteve fora do ar; não há o que esperar."""
        local_preferida, reserva = VozFalsa("local"), VozFalsa("outra")
        assert consumir(FallbackEngine(local_preferida, reserva)) == ["local", "local"]

    def test_espera_desligada_nao_consulta_a_rede(self) -> None:
        nuvem, local = VozDeRede(chega_na_tentativa=None), VozFalsa("local")
        consumir(FallbackEngine(nuvem, local, espera_de_arranque=0))
        assert nuvem.consultas == 0
