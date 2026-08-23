"""Cliente do Ollama.

Usa a API `/api/chat` em modo streaming: os pedacos chegam conforme o modelo
gera, o que permite iniciar a sintese de voz na primeira frase completa em vez de
esperar a resposta inteira.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any

import httpx

from roboteye.llm.base import ChatMessage, LLMError
from roboteye.logging_setup import get_logger

if TYPE_CHECKING:
    from roboteye.config import LLMSettings

logger = get_logger(__name__)


class OllamaClient:
    """Conversa com um servidor Ollama local ou na rede."""

    name = "ollama"

    def __init__(self, settings: LLMSettings) -> None:
        self._host = settings.host
        self._model = settings.model
        self._num_predict = settings.max_tokens
        self._timeout = httpx.Timeout(
            connect=5.0,
            read=settings.timeout,
            write=10.0,
            pool=5.0,
        )
        self._client: httpx.Client | None = None

    # -- ciclo de vida -----------------------------------------------------
    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self._host, timeout=self._timeout)
        return self._client

    def warm_up(self, messages: Sequence[ChatMessage] = ()) -> None:
        """Abre a conexao e deixa o modelo pronto na memoria.

        A primeira chamada de uma conexao custa cerca de 2 s a mais que as
        seguintes; pagar isso no arranque evita que a primeira frase do usuario
        seja justamente a mais lenta.

        Mandar junto a persona — e nao so um "oi" — e o que faz diferenca num
        modelo rodando em CPU. O servidor guarda o prefixo ja processado, e num
        Raspberry Pi 5 os ~500 tokens da persona custam **10 s** para serem
        lidos: sem este aquecimento, quem chega perto do robo e faz a primeira
        pergunta e exatamente quem espera por eles. Medido, na mesma pergunta:
        12 s na primeira vez, 2 s da segunda em diante.
        """
        corpo = [message.as_dict() for message in messages]
        corpo.append({"role": "user", "content": "oi"})
        try:
            self._http().post(
                "/api/chat",
                json={
                    "model": self._model,
                    "messages": corpo,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": 1},
                },
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            logger.debug("aquecimento do LLM falhou (segue o jogo): %s", exc)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- diagnostico -------------------------------------------------------
    def is_available(self) -> bool:
        try:
            response = self._http().get("/api/tags", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("Ollama indisponivel em %s: %s", self._host, exc)
            return False
        return True

    def list_models(self) -> list[str]:
        """Modelos disponiveis no servidor."""
        try:
            response = self._http().get("/api/tags", timeout=5.0)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise LLMError(f"nao foi possivel listar os modelos: {exc}") from exc
        return [model["name"] for model in payload.get("models", [])]

    # -- inferencia --------------------------------------------------------
    def stream_reply(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [message.as_dict() for message in messages],
            "stream": True,
            # Modelos com modo de raciocinio (Qwen3 e afins) gastariam a cota de
            # tokens pensando em voz alta — e o robo falaria o raciocinio inteiro.
            "think": False,
            "options": {
                # Respostas curtas: o robo fala, nao redige.
                "num_predict": self._num_predict,
                "temperature": 0.8,
            },
        }

        try:
            with self._http().stream("POST", "/api/chat", json=payload) as response:
                if response.status_code == 404:
                    response.read()
                    raise LLMError(
                        f"modelo {self._model!r} nao encontrado em {self._host}. "
                        f"Instale com: ollama pull {self._model}"
                    )
                response.raise_for_status()
                yield from _iter_content(response.iter_lines())
        except httpx.ConnectError as exc:
            raise LLMError(
                f"nao foi possivel conectar ao Ollama em {self._host}. "
                "Verifique se ele esta rodando e acessivel na rede."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError(f"o modelo demorou demais para responder: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"erro na chamada ao Ollama: {exc}") from exc


def _iter_content(lines: Iterator[str]) -> Iterator[str]:
    """Extrai o texto das linhas NDJSON devolvidas pelo Ollama."""
    for line in lines:
        line = line.strip()
        if not line:
            continue

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("linha nao-JSON ignorada: %s", line[:120])
            continue

        if error := event.get("error"):
            raise LLMError(str(error))

        content = event.get("message", {}).get("content", "")
        if content:
            yield content

        if event.get("done"):
            break
