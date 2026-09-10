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
def _sem_env_file(monkeypatch):
    """As variáveis do teste, e não o `.env` de quem estiver rodando."""
    for chave in ("ROBOTEYE_WAKE_WORD", "ROBOTEYE_SAUDACAO", "ROBOTEYE_WAKE_RESPOSTA"):
        monkeypatch.delenv(chave, raising=False)


class TestVazioQuerDizerVazio:
    def test_palavra_de_despertar_vazia_desliga_o_filtro(self, monkeypatch) -> None:
        """O caso que aconteceu no robô."""
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "")
        assert HearingSettings.from_env().wake_word == ""

    def test_saudacao_vazia_sobe_calado(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_SAUDACAO", "")
        assert LLMSettings.from_env().saudacao == ""

    def test_resposta_ao_chamado_vazia_espera_calada(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_WAKE_RESPOSTA", "")
        assert HearingSettings.from_env().resposta_ao_chamado == ""

    def test_so_espacos_tambem_conta_como_vazio(self, monkeypatch) -> None:
        """Quem edita um `.env` à mão deixa um espaço sem perceber."""
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "   ")
        assert HearingSettings.from_env().wake_word == ""


class TestAusenteContinuaCaindoNoPadrao:
    """A correção não pode transformar "não configurei" em "desliguei"."""

    def test_sem_a_variavel_o_nome_continua_valendo(self) -> None:
        assert HearingSettings.from_env().wake_word == "atlas"

    def test_sem_a_variavel_a_saudacao_continua(self) -> None:
        assert LLMSettings.from_env().saudacao == "Oi oi, acordei!"

    def test_sem_a_variavel_a_resposta_continua(self) -> None:
        assert HearingSettings.from_env().resposta_ao_chamado == "Oi?"

    def test_um_valor_de_verdade_continua_passando(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "iris")
        assert HearingSettings.from_env().wake_word == "iris"

    def test_espacos_em_volta_de_um_valor_saem(self, monkeypatch) -> None:
        monkeypatch.setenv("ROBOTEYE_WAKE_WORD", "  iris  ")
        assert HearingSettings.from_env().wake_word == "iris"
