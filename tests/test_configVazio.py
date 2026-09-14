"""Textos onde estar em branco é uma escolha, não a ausência de escolha.

Três campos documentam um comportamento para o valor vazio:

    wake_word            vazio -> responde a tudo o que ouvir
    saudacao             vazio -> sobe calado
    resposta_ao_chamado  vazio -> espera calada quando chamam o nome

Nenhum dos três funcionava. `_raw` colapsa `""` em `None`, e `_get_str` troca
`None` pelo padrão — então `ROBOTEYE_WAKE_WORD=` voltava a valer `"atlas"`.

O defeito era mudo e caro de achar. Visto neste robô: a palavra foi desligada
no `.env` para poder testar sem dizer o nome, o robô continuou exigindo o nome,
e o log dizia `ouvi 'a classe qual seu nome', mas nao era comigo` — apontando
para o reconhecimento, que estava certo. Quem procurou, procurou no lugar errado.
"""

from __future__ import annotations

import pytest

from roboteye.config import HearingSettings, LLMSettings


@pytest.fixture(autouse=True)
def semEnvFile(monkeypatch):
    """As variáveis do teste, e não o `.env` de quem estiver rodando."""
    for chave in ("ROBOTEYE_WAKE_WORD", "ROBOTEYE_SAUDACAO", "ROBOTEYE_WAKE_RESPOSTA"):
        monkeypatch.delenv(chave, raising=False)


class TestVazioQuerDizerVazio:
    def testPalavraDeDespertarVaziaDesligaOFiltro(self, monkeypatch) -> None:
        """O caso que aconteceu no robô."""
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "")
        assert HearingSettings.fromEnv().wakeWord == ""

    def testSaudacaoVaziaSobeCalado(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_SAUDACAO", "")
        assert LLMSettings.fromEnv().saudacao == ""

    def testRespostaAoChamadoVaziaEsperaCalada(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_WAKE_RESPOSTA", "")
        assert HearingSettings.fromEnv().respostaAoChamado == ""

    def testSoEspacosTambemContaComoVazio(self, monkeypatch) -> None:
        """Quem edita um `.env` à mão deixa um espaço sem perceber."""
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "   ")
        assert HearingSettings.fromEnv().wakeWord == ""


class TestAusenteContinuaCaindoNoPadrao:
    """A correção não pode transformar "não configurei" em "desliguei"."""

    def testSemAVariavelONomeContinuaValendo(self) -> None:
        assert HearingSettings.fromEnv().wakeWord == "atlas"

    def testSemAVariavelASaudacaoContinua(self) -> None:
        assert LLMSettings.fromEnv().saudacao == "Oi oi, acordei!"

    def testSemAVariavelARespostaContinua(self) -> None:
        assert HearingSettings.fromEnv().respostaAoChamado == "Oi?"

    def testUmValorDeVerdadeContinuaPassando(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "iris")
        assert HearingSettings.fromEnv().wakeWord == "iris"

    def testEspacosEmVoltaDeUmValorSaem(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "  iris  ")
        assert HearingSettings.fromEnv().wakeWord == "iris"
