"""Testes da segmentação de texto entre o LLM e a voz."""

from __future__ import annotations

import pytest

from roboteye.core.text import cleanForSpeech, splitSentences, streamSentences, truncate


class TestSplitSentences:
    def testDivideEmFrasesPreservandoPontuacao(self) -> None:
        assert splitSentences("Olá. Tudo bem? Claro!") == ["Olá.", "Tudo bem?", "Claro!"]

    def testTextoSemPontuacaoFinalViraUmaFrase(self) -> None:
        assert splitSentences("sem ponto final") == ["sem ponto final"]

    def testTextoVazioNaoGeraFrases(self) -> None:
        assert splitSentences("   ") == []

    def testReticenciasNoMeioNaoQuebramAFrase(self) -> None:
        # Regressão: "Your response is... predictable." era falado como duas frases.
        assert splitSentences("Sua resposta é... previsível.") == ["Sua resposta é... previsível."]

    def testReticenciasSeguidasDeMaiusculaQuebram(self) -> None:
        assert splitSentences("Pense nisso... Depois volte.") == [
            "Pense nisso...",
            "Depois volte.",
        ]


class TestStreamSentences:
    def testReagrupaTokensEmFrases(self) -> None:
        tokens = ["A ciência ", "não ", "espera ninguém. ", "Continue ", "o teste agora."]
        assert list(streamSentences(tokens)) == [
            "A ciência não espera ninguém.",
            "Continue o teste agora.",
        ]

    def testFrasesCurtasSaoAgrupadasComASeguinte(self) -> None:
        # "Ok." sozinho soaria picotado no TTS.
        resultado = list(streamSentences(["Ok. ", "Agora preste muita atenção nisto aqui."]))
        assert resultado == ["Ok. Agora preste muita atenção nisto aqui."]

    def testRestoSemPontuacaoEEmitidoNoFinal(self) -> None:
        assert list(streamSentences(["Uma frase completa aqui. ", "E um resto"])) == [
            "Uma frase completa aqui.",
            "E um resto",
        ]

    def testMinusculaAposOPontoNaoQuebra(self) -> None:
        # Sinal de continuação (reticências, abreviação): melhor falar junto.
        assert list(streamSentences(["Uma frase completa aqui. ", "e um resto"])) == [
            "Uma frase completa aqui. e um resto",
        ]

    def testFluxoVazioNaoEmiteNada(self) -> None:
        assert list(streamSentences([])) == []


class TestCleanForSpeech:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("**muito** importante", "muito importante"),
            ("use `código` aqui", "use código aqui"),
            ("## Título", "Título"),
            ("olá 🤖 robô", "olá robô"),
            ("espaços     demais", "espaços demais"),
        ],
    )
    def testRemoveRuido(self, entrada: str, esperado: str) -> None:
        assert cleanForSpeech(entrada) == esperado


class TestTruncate:
    def testEncurtaTextosLongos(self) -> None:
        assert truncate("a" * 100, limit=10) == "a" * 9 + "…"

    def testMantemTextosCurtos(self) -> None:
        assert truncate("curto", limit=10) == "curto"
