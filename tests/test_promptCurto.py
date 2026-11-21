from datetime import date

from roboteye.llm.memory import hojePorExtenso
from roboteye.llm.persona import PROMPT_CURTO, PersonaStore


def testDataPorExtenso() -> None:
    assert hojePorExtenso(date(2026, 11, 21)) == "Hoje e sabado, 21 de novembro de 2026."
    assert hojePorExtenso(date(2026, 1, 5)) == "Hoje e segunda-feira, 5 de janeiro de 2026."


def testPromptCurtoLevaSoFatos(tmp_path) -> None:
    (tmp_path / "atlas.md").write_text("identidade longa", encoding="utf-8")
    (tmp_path / "atlas.memoria.md").write_text("- o diretor e o Antonio\n", encoding="utf-8")
    prompt = PersonaStore(tmp_path, "atlas", curto=True).load("pt").systemPrompt()
    assert prompt == f"{PROMPT_CURTO}\n\nFatos:\n- o diretor e o Antonio"
