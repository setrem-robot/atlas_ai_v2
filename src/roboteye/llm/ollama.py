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

    def __init__(self, settings: LLMSettings, *, keep_alive: str | None = None) -> None:
        self._host = settings.host
        self._model = settings.model
        self._num_predict = settings.max_tokens
        self._num_ctx = settings.num_ctx
        self._num_thread = settings.num_thread
        #: Mutavel de proposito — ver `set_keep_alive`.
        self._keep_alive = keep_alive if keep_alive is not None else settings.keep_alive
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
                    # Sem isto o aquecimento nao aqueceria nada: com
                    # `keep_alive` valendo "0", o Ollama carrega o modelo,
                    # responde e o descarrega antes da primeira pergunta de
                    # verdade. Quem manda aquecer quer o modelo *residente*.
                    "keep_alive": self._keep_alive_de_aquecimento(),
                    "options": {"num_predict": 1, "num_ctx": self._num_ctx},
                },
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            logger.debug("aquecimento do LLM falhou (segue o jogo): %s", exc)

    def _keep_alive_de_aquecimento(self) -> str:
        return "5m" if self._keep_alive.strip() in {"0", "0s", ""} else self._keep_alive

    def set_keep_alive(self, valor: str) -> None:
        """Muda quanto tempo o modelo fica residente depois de responder.

        Existe para o reserva local: enquanto a IA de rede responde, ele nao
        deve ocupar nada; no momento em que ela cai, passa a valer a pena
        segura-lo na memoria. Ver `FallbackLLMClient`.
        """
        self._keep_alive = valor

    def unload(self) -> bool:
        """Pede ao Ollama que solte este modelo da memoria agora.

        Um `keep_alive` de "0" numa chamada vazia e como a propria API do Ollama
        descarrega — nao ha rota dedicada para isso. Devolve se o pedido foi
        aceito; falhar aqui nao e erro de ninguem, so memoria que continua presa
        ate o tempo dela expirar.
        """
        try:
            resposta = self._http().post(
                "/api/chat",
                json={"model": self._model, "messages": [], "keep_alive": 0},
                timeout=10.0,
            )
            resposta.raise_for_status()
        except httpx.HTTPError as exc:
            logger.debug("nao consegui descarregar %s: %s", self._model, exc)
            return False
        logger.info("modelo %s descarregado da memoria", self._model)
        return True

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
            "keep_alive": self._keep_alive,
            "options": {
                # Respostas curtas: o robo fala, nao redige.
                "num_predict": self._num_predict,
                # O cache de atencao e reservado pelo tamanho declarado, e nao
                # pelo texto que chega: cada token de contexto a mais e memoria
                # presa no Pi mesmo numa conversa de duas frases.
                "num_ctx": self._num_ctx,
                "temperature": 0.8,
                # Ausente quando vale 0: o Ollama so aceita a chave com um
                # numero util, e o padrao dele (todos os nucleos) e o certo
                # numa maquina de mesa.
                **({"num_thread": self._num_thread} if self._num_thread else {}),
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
