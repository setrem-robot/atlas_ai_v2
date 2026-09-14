"""Testes da persona em arquivo e da memória ensinável."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboteye.llm.persona import Persona, PersonaStore, createDefaultPersona


@pytest.fixture
def store(tmp_path: Path) -> PersonaStore:
    return PersonaStore(tmp_path, "atlas")


class TestCarregamento:
    def testUsaAPersonaEmbutidaSemArquivo(self, store: PersonaStore) -> None:
        assert "Atlas" in store.load().identity

    def testLeOArquivoQuandoExiste(self, store: PersonaStore) -> None:
        store.identityPath.write_text("Você é um farol solitário.", encoding="utf-8")
        assert "farol solitário" in store.load().identity

    def testArquivoVazioCaiNoPadrao(self, store: PersonaStore) -> None:
        store.identityPath.write_text("   \n  ", encoding="utf-8")
        assert "Atlas" in store.load().identity

    def testPersonasDiferentesUsamArquivosDiferentes(self, tmp_path: Path) -> None:
        atlas = PersonaStore(tmp_path, "atlas")
        jarvis = PersonaStore(tmp_path, "jarvis")

        atlas.identityPath.write_text("Sou a Atlas.", encoding="utf-8")
        jarvis.identityPath.write_text("Sou o Jarvis.", encoding="utf-8")

        assert "Atlas" in atlas.load().identity
        assert "Jarvis" in jarvis.load().identity


class TestPromptDeSistema:
    def testJuntaIdentidadeFatosERegras(self, store: PersonaStore) -> None:
        store.identityPath.write_text("Você é um farol.", encoding="utf-8")
        store.remember("o mar está calmo hoje")

        prompt = store.load("pt").systemPrompt()

        assert "farol" in prompt
        assert "o mar está calmo hoje" in prompt
        assert "Brazilian Portuguese" in prompt

    def testSemFatosNaoCriaSecaoVazia(self, store: PersonaStore) -> None:
        assert "ensinado por quem te construiu" not in store.load().systemPrompt()

    def testRegrasDeSaidaEstaoSemprePresentes(self, store: PersonaStore) -> None:
        """São requisito do TTS, não do personagem: não podem sumir."""
        store.identityPath.write_text("Apenas isso.", encoding="utf-8")
        prompt = store.load().systemPrompt().lower()

        assert "markdown" in prompt
        assert "duas frases" in prompt

    def testPersonaMontadaAMaoTambemFunciona(self) -> None:
        persona = Persona(name="teste", identity="Você existe.", facts=("o céu é azul",))
        prompt = persona.systemPrompt()

        assert "Você existe." in prompt
        assert "o céu é azul" in prompt


class TestAprender:
    def testGuardaUmFato(self, store: PersonaStore) -> None:
        assert store.remember("meu nome é Kerlon")
        assert "meu nome é Kerlon" in store.loadFacts()

    def testNaoGuardaDuasVezes(self, store: PersonaStore) -> None:
        assert store.remember("o robô se chama Bifrost")
        assert not store.remember("o robô se chama Bifrost")
        assert len(store.loadFacts()) == 1

    def testIgnoraFatoVazio(self, store: PersonaStore) -> None:
        assert not store.remember("   ")
        assert store.loadFacts() == ()

    def testGuardaVariosNaOrdem(self, store: PersonaStore) -> None:
        for fato in ("primeiro", "segundo", "terceiro"):
            store.remember(fato)
        assert store.loadFacts() == ("primeiro", "segundo", "terceiro")

    def testSobreviveEntreInstancias(self, tmp_path: Path) -> None:
        """O ponto do recurso: o que se ensina hoje continua valendo amanhã."""
        PersonaStore(tmp_path, "atlas").remember("o laboratorio fecha as dez")
        assert "o laboratorio fecha as dez" in PersonaStore(tmp_path, "atlas").loadFacts()

    def testArquivoEEditavelAMao(self, store: PersonaStore) -> None:
        store.memoryPath.write_text(
            "# um comentário\n\n- fato um\n- fato dois\n", encoding="utf-8"
        )
        assert store.loadFacts() == ("fato um", "fato dois")

    def testAceitaLinhasSemTracinho(self, store: PersonaStore) -> None:
        store.memoryPath.write_text("fato solto\n", encoding="utf-8")
        assert store.loadFacts() == ("fato solto",)


class TestEsquecer:
    def testRemovePorTrecho(self, store: PersonaStore) -> None:
        store.remember("meu nome é Kerlon")
        store.remember("o robô é azul")

        assert store.forget("Kerlon") == 1
        assert store.loadFacts() == ("o robô é azul",)

    def testBuscaIgnoraCaixa(self, store: PersonaStore) -> None:
        store.remember("Meu Nome É Kerlon")
        assert store.forget("kerlon") == 1

    def testRemoveTodosOsQueBatem(self, store: PersonaStore) -> None:
        store.remember("gosto de café")
        store.remember("café é melhor de manhã")
        store.remember("chá também serve")

        assert store.forget("café") == 2
        assert store.loadFacts() == ("chá também serve",)

    def testSemMemoriaNaoQuebra(self, store: PersonaStore) -> None:
        assert store.forget("qualquer coisa") == 0

    def testTrechoVazioNaoApagaNada(self, store: PersonaStore) -> None:
        store.remember("um fato")
        assert store.forget("  ") == 0
        assert len(store.loadFacts()) == 1

    def testPreservaOsComentariosDoArquivo(self, store: PersonaStore) -> None:
        store.memoryPath.write_text("# cabeçalho\n- some\n- fica\n", encoding="utf-8")
        store.forget("some")
        assert "# cabeçalho" in store.memoryPath.read_text(encoding="utf-8")


class TestPersonaInicial:
    def testCriaOArquivo(self, tmp_path: Path) -> None:
        caminho = createDefaultPersona(tmp_path, "atlas")
        assert caminho.is_file()
        assert "Atlas" in caminho.read_text(encoding="utf-8")

    def testNaoSobrescreveOQueExiste(self, tmp_path: Path) -> None:
        caminho = tmp_path / "atlas.md"
        caminho.write_text("meu texto", encoding="utf-8")

        createDefaultPersona(tmp_path, "atlas")

        assert caminho.read_text(encoding="utf-8") == "meu texto"


class TestAssistantEnsina:
    """O caminho que o usuário percorre: /lembrar muda a resposta seguinte."""

    def testEnsinarEntraNoPrompt(self, makeAssistant, makeLlm, tmp_path) -> None:
        llm = makeLlm("Uma resposta suficientemente longa para o teste.")
        assistant, memory = makeAssistant(llm, personaDir=tmp_path)

        assert assistant.teach("o robô se chama Bifrost")

        promptSistema = memory.buildPrompt()[0].content
        assert "o robô se chama Bifrost" in promptSistema

    def testEsquecerSaiDoPrompt(self, makeAssistant, makeLlm, tmp_path) -> None:
        assistant, memory = makeAssistant(makeLlm(), personaDir=tmp_path)
        assistant.teach("o robô se chama Bifrost")

        assert assistant.forget("Bifrost") == 1
        assert "Bifrost" not in memory.buildPrompt()[0].content

    def testListaOQueAprendeu(self, makeAssistant, makeLlm, tmp_path) -> None:
        assistant, _ = makeAssistant(makeLlm(), personaDir=tmp_path)
        assistant.teach("primeiro fato")
        assistant.teach("segundo fato")

        assert assistant.facts() == ("primeiro fato", "segundo fato")

    def testSemPersonaEnsinarNaoQuebra(self, makeAssistant, makeLlm) -> None:
        assistant, _ = makeAssistant(makeLlm())
        assert not assistant.teach("qualquer coisa")
        assert assistant.forget("qualquer coisa") == 0
        assert assistant.facts() == ()

    def testRecarregarPegaAEdicaoDoArquivo(self, makeAssistant, makeLlm, tmp_path) -> None:
        assistant, memory = makeAssistant(makeLlm(), personaDir=tmp_path)

        (tmp_path / "atlas.md").write_text("Você agora é um farol.", encoding="utf-8")
        assistant.reloadPersona()

        assert "farol" in memory.buildPrompt()[0].content
