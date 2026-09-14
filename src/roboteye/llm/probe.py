"""Sonda a maquina onde roda o Ollama, sem falar com o modelo.

Existe porque tanto a pagina de configuracao quanto o assistente de instalacao
precisam responder a mesma pergunta antes de gravar qualquer coisa: *esse
endereco existe, e o que tem nele?* Perguntar isso ao cliente de conversa nao
serve — ele carrega o modelo na memoria e demora segundos para dizer "nao".

A sonda so bate em `/api/tags`, que devolve a lista de modelos instalados. Isso
da as duas respostas de uma vez: se a maquina esta de pe e quais modelos ha
para escolher.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: A sonda e usada em fluxos interativos, onde esperar e o que mais incomoda.
#: Uma maquina da rede local que nao responde em seis segundos esta fora.
DEFAULT_TIMEOUT = 6.0


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """O que a maquina da IA respondeu — ou por que nao respondeu."""

    ok: bool
    host: str
    #: Ida e volta em milissegundos. So faz sentido quando `ok`.
    latencyMs: int = 0
    models: tuple[str, ...] = field(default_factory=tuple)
    error: str = ""


def normalizeHost(raw: str) -> str:
    """Completa o que uma pessoa digita ate virar uma URL.

    Ninguem digita `http://` ao informar o endereco de uma maquina da rede, e
    quase ninguem lembra a porta do Ollama. Faltando qualquer um dos dois, o
    endereco seria recusado por um detalhe que a maquina sabe preencher.
    """
    host = raw.strip().rstrip("/")
    if not host:
        return ""
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    # Porta ausente: `http://192.168.1.50` -> `http://192.168.1.50:11434`.
    resto = host.split("://", 1)[1]
    if ":" not in resto.split("/", 1)[0]:
        host = f"{host}:11434"
    return host


def probeOllama(rawHost: str, *, timeout: float = DEFAULT_TIMEOUT) -> ProbeResult:
    """Pergunta a maquina quais modelos ela tem."""
    import httpx

    host = normalizeHost(rawHost)
    if not host:
        return ProbeResult(ok=False, host="", error="informe o endereco")

    inicio = time.monotonic()
    try:
        resposta = httpx.get(f"{host}/api/tags", timeout=timeout)
        resposta.raise_for_status()
        modelos = [str(m.get("name", "")) for m in resposta.json().get("models", [])]
    except Exception as exc:
        return ProbeResult(ok=False, host=host, error=explain(exc))

    return ProbeResult(
        ok=True,
        host=host,
        latencyMs=round((time.monotonic() - inicio) * 1000),
        models=tuple(sorted(filter(None, modelos))),
    )


def explain(exc: Exception) -> str:
    """Traduz a falha de rede para algo acionavel.

    A mensagem crua de uma biblioteca HTTP diz o que aconteceu na camada dela,
    nao o que a pessoa tem de conferir. Quem esta instalando o robo precisa da
    segunda coisa.
    """
    texto = str(exc) or type(exc).__name__
    nome = type(exc).__name__
    minusculo = texto.lower()
    # A falha de DNS chega embrulhada em tipos diferentes conforme o sistema, e
    # so o texto a identifica dos dois lados. Ela vem antes do teste de conexao
    # porque no Linux chega como um erro de conexao qualquer.
    dns = ("resolve", "name or service not known", "getaddrinfo", "nodename nor servname")
    if "Timeout" in nome:
        return "sem resposta no tempo limite — a VPN esta de pe? o IP esta certo?"
    if "Name" in nome or any(marca in minusculo for marca in dns):
        return "nome nao resolvido — use o IP em vez do nome da maquina"
    if "Connect" in nome:
        return "conexao recusada — a maquina responde, mas nada escuta nessa porta"
    return texto
