"""Assistente de primeira configuracao: `roboteye setup`.

Quem acabou de clonar o repositorio tem tudo instalado e nada configurado, e as
tres perguntas que faltam sao sempre as mesmas: **onde roda a IA**, **qual
modelo** e **qual voz**. Responder a mao significa abrir o `.env`, entender
dezoito chaves e adivinhar o nome exato de um modelo que talvez nem esteja
baixado — e so descobrir o erro quando o robo falha falando.

Entao o assistente pergunta as tres, mas com o que a maquina ja sabe na mao: o
endereco e **testado** antes de ser gravado, a lista de modelos vem do proprio
Ollama que respondeu, e a voz escolhida ja sai com os arquivos no disco.

O `.env` e editado no lugar, com os comentarios preservados (veja
`web.envfile`), porque ele e a documentacao que fica na maquina.

A mesma coisa serve para instalacao automatizada: com `--non-interactive` e as
respostas em flags, nada e perguntado. E o que o script do Raspberry Pi usa.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from roboteye import voiceCatalog
from roboteye.config import PROJECT_ROOT, Settings
from roboteye.llm.probe import ProbeResult, normalizeHost, probeOllama
from roboteye.loggingSetup import getLogger

logger = getLogger(__name__)

#: Sugestoes de quando a maquina da IA nao tem modelo nenhum instalado. Um nome
#: errado aqui vira uma falha so na primeira frase falada, entao vale oferecer
#: nomes que existem em vez de deixar a pessoa digitar de memoria.
MODEL_SUGGESTIONS: tuple[tuple[str, str], ...] = (
    ("llama3.2:1b", "~1,3 GB - o menor que ainda conversa; anda em CPU"),
    ("llama3.2:3b", "~2,0 GB - obedece bem melhor ao tamanho pedido"),
    ("gemma3:4b", "~3,3 GB - bom portugues, meio-termo de peso"),
    ("qwen3:8b", "~5,2 GB - o melhor daqui, se houver GPU"),
)

#: Quanto cada motor custa em disco. O catalogo nao guarda tamanho, e a
#: diferenca entre 60 MB e 350 MB muda a resposta de quem esta numa rede lenta.
_ENGINE_COST = {
    "piper": "60 MB",
    "kokoro": "354 MB",
    "edge": "so internet",
}

#: Descricoes do catalogo cabem numa linha de terminal estreita depois disto.
_MAX_DESCRICAO = 52

_LOCAL_HOST = "http://localhost:11434"


# ---------------------------------------------------------------------------
# Dialogo
# ---------------------------------------------------------------------------
@dataclass
class Prompt:
    """Perguntas e respostas do terminal, isoladas para poderem ser dubladas.

    Em modo nao interativo — ou quando a entrada acaba, o que acontece num
    script — toda pergunta devolve o proprio padrao em vez de estourar.
    """

    read: Callable[[str], str] = input
    write: Callable[[str], None] = print
    interactive: bool = True

    def say(self, text: str = "") -> None:
        self.write(text)

    def text(self, question: str, default: str = "") -> str:
        if not self.interactive:
            return default
        sufixo = f" [{default}]" if default else ""
        try:
            resposta = self.read(f"{question}{sufixo}: ").strip()
        except (EOFError, KeyboardInterrupt):
            self.say()
            return default
        return resposta or default

    def choice(self, question: str, options: Sequence[tuple[str, str]], default: str) -> str:
        """Menu numerado. `options` e uma lista de (valor, descricao)."""
        if not self.interactive:
            return default

        self.say()
        for indice, (valor, descricao) in enumerate(options, start=1):
            marca = "*" if valor == default else " "
            self.say(f"  {marca} {indice}) {valor:<12} {descricao}")
        self.say()

        while True:
            resposta = self.text(question, default)
            if resposta.isdigit() and 1 <= int(resposta) <= len(options):
                return options[int(resposta) - 1][0]
            if any(resposta == valor for valor, _ in options):
                return resposta
            if resposta == default:
                return default
            self.say(f"  nao entendi {resposta!r}; escolha um numero de 1 a {len(options)}")

    def yesNo(self, question: str, default: bool = True) -> bool:
        if not self.interactive:
            return default
        padrao = "S/n" if default else "s/N"
        resposta = self.text(f"{question} ({padrao})", "").lower()
        if not resposta:
            return default
        return resposta[0] in {"s", "y"}


# ---------------------------------------------------------------------------
# Respostas
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Answers:
    """Respostas vindas da linha de comando; o que faltar vira pergunta."""

    ollama: str | None = None
    model: str | None = None
    voice: str | None = None
    persona: str | None = None
    #: Roda sem modelo de linguagem nenhum (backend `echo`).
    noLlm: bool = False
    #: Nao pergunta nada: usa o que veio nas flags e mantem o resto.
    nonInteractive: bool = False
    #: Nao baixa modelo de voz ao final.
    skipDownload: bool = False


@dataclass(frozen=True, slots=True)
class SetupPlan:
    """O que o assistente decidiu gravar e baixar."""

    values: dict[str, str] = field(default_factory=dict)
    downloads: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Assistente
# ---------------------------------------------------------------------------
def runSetup(
    settings: Settings,
    answers: Answers,
    prompt: Prompt,
    *,
    envPath: Path | None = None,
    projectRoot: Path = PROJECT_ROOT,
) -> SetupPlan:
    """Conduz o dialogo, grava o `.env` e devolve o que foi decidido."""
    from roboteye.web import envfile

    envPath = envPath or (projectRoot / ".env")
    ensureEnvFile(envPath, projectRoot / ".env.example", prompt)

    prompt.say()
    prompt.say("=" * 62)
    prompt.say("  RobotEye - configuracao inicial")
    prompt.say("=" * 62)
    prompt.say("Enter aceita o valor entre colchetes. Nada e gravado antes do fim.")

    valores: dict[str, str] = {}
    valores.update(askLlm(settings, answers, prompt))
    voz = askVoice(settings, answers, prompt)
    valores["ROBOTEYE_VOICE"] = voz
    valores["ROBOTEYE_PERSONA"] = askPersona(settings, answers, prompt, projectRoot)

    envfile.update(envPath, valores)
    prompt.say()
    prompt.say(f"gravado em {envPath}:")
    for chave, valor in valores.items():
        prompt.say(f"  {chave}={valor or '(vazio)'}")

    baixadas = () if answers.skipDownload else downloadVoices(voz, settings, prompt)

    prompt.say()
    prompt.say("-" * 62)
    prompt.say("Pronto. Confira com `roboteye doctor` e comece com `roboteye`.")
    prompt.say("Para mudar algo depois: edite o .env, rode `roboteye setup` de novo")
    prompt.say("ou use a pagina do celular (`roboteye web`).")
    return SetupPlan(values=valores, downloads=baixadas)


def ensureEnvFile(envPath: Path, examplePath: Path, prompt: Prompt) -> None:
    """Cria o `.env` a partir do exemplo, para haver comentarios a preservar."""
    if envPath.is_file():
        return
    if examplePath.is_file():
        shutil.copyfile(examplePath, envPath)
        prompt.say(f"criado {envPath.name} a partir de {examplePath.name}")
    else:  # repositorio incompleto; o arquivo nasce das chaves gravadas
        envPath.touch()


# -- IA ---------------------------------------------------------------------
def askLlm(settings: Settings, answers: Answers, prompt: Prompt) -> dict[str, str]:
    """Onde roda a IA, e com qual modelo."""
    if answers.noLlm:
        prompt.say()
        prompt.say("Sem modelo de linguagem: o robo responde no modo `echo`.")
        return {"ROBOTEYE_LLM_BACKEND": "echo"}

    prompt.say()
    prompt.say("[1/3] Onde roda a IA?")
    prompt.say("      O Ollama e um programa a parte (https://ollama.com). Ele pode")
    prompt.say("      estar nesta maquina ou noutra da rede — num Raspberry Pi, noutra.")

    host = answers.ollama or ""
    if not host:
        escolha = prompt.choice(
            "onde",
            [
                ("local", f"nesta maquina ({_LOCAL_HOST})"),
                ("rede", "noutra maquina da rede (informar o endereco)"),
                ("nenhuma", "sem IA por enquanto — modo `echo`, so para testar a voz"),
            ],
            default="local" if settings.llm.host == _LOCAL_HOST else "rede",
        )
        if escolha == "nenhuma":
            return {"ROBOTEYE_LLM_BACKEND": "echo"}
        host = (
            _LOCAL_HOST
            if escolha == "local"
            else prompt.text("endereco (IP:PORTA)", settings.llm.host)
        )

    sonda, host = probeUntilOk(host, prompt)
    modelo = askModel(settings, answers, prompt, sonda)

    valores = {
        "ROBOTEYE_LLM_BACKEND": "ollama",
        "ROBOTEYE_OLLAMA_HOST": normalizeHost(host),
    }
    if modelo:
        valores["ROBOTEYE_LLM_MODEL"] = modelo
    return valores


def probeUntilOk(host: str, prompt: Prompt) -> tuple[ProbeResult, str]:
    """Testa o endereco e, se falhar, deixa corrigir sem sair do assistente.

    Um endereco errado gravado aqui so daria sinal na primeira conversa, longe
    de quem o digitou. Testar custa uma requisicao e resolve o caso comum: VPN
    fora do ar, IP trocado, Ollama escutando so em localhost.
    """
    while True:
        prompt.say(f"      testando {normalizeHost(host)} ...")
        sonda = probeOllama(host)
        if sonda.ok:
            plural = "s" if len(sonda.models) != 1 else ""
            prompt.say(
                f"      ok: respondeu em {sonda.latencyMs} ms, "
                f"{len(sonda.models)} modelo{plural} instalado{plural}"
            )
            return sonda, sonda.host

        prompt.say(f"      falhou: {sonda.error}")
        if "localhost" in sonda.host or "127.0.0.1" in sonda.host:
            prompt.say("      o Ollama esta rodando? tente `ollama serve` noutro terminal.")
        else:
            prompt.say(
                "      na maquina da IA, exponha o Ollama: `OLLAMA_HOST=0.0.0.0 ollama serve`"
            )

        if not prompt.interactive:
            return sonda, host
        outro = prompt.text("outro endereco (vazio grava assim mesmo)", "")
        if not outro:
            return sonda, host
        host = outro


def askModel(settings: Settings, answers: Answers, prompt: Prompt, sonda: ProbeResult) -> str:
    """Qual modelo usar, entre os que a maquina realmente tem."""
    if answers.model:
        return answers.model

    prompt.say()
    prompt.say("[2/3] Qual modelo?")

    if sonda.models:
        atual = settings.llm.model if settings.llm.model in sonda.models else sonda.models[0]
        opcoes = [(nome, "instalado") for nome in sonda.models]
        prompt.say("      Estes ja estao na maquina da IA:")
        return prompt.choice("modelo", opcoes, default=atual)

    prompt.say("      Nenhum modelo instalado nessa maquina. Sugestoes:")
    opcoes = list(MODEL_SUGGESTIONS)
    escolhido = prompt.choice("modelo", opcoes, default=settings.llm.model)

    if canPull(sonda.host) and prompt.yesNo(f"baixar {escolhido} agora com `ollama pull`?"):
        pull(escolhido, prompt)
    else:
        prompt.say(f"      lembre-se de baixa-lo na maquina da IA: ollama pull {escolhido}")
    return escolhido


def canPull(host: str) -> bool:
    """`ollama pull` so serve se o Ollama for desta maquina."""
    local = any(marca in host for marca in ("localhost", "127.0.0.1", "0.0.0.0"))
    return local and shutil.which("ollama") is not None


def pull(modelo: str, prompt: Prompt) -> None:
    prompt.say(f"      baixando {modelo} (pode demorar)...")
    try:
        resultado = subprocess.run(["ollama", "pull", modelo], check=False)
    except OSError as exc:  # pragma: no cover - depende do sistema
        prompt.say(f"      nao consegui chamar o ollama: {exc}")
        return
    if resultado.returncode != 0:
        prompt.say(f"      `ollama pull` falhou (codigo {resultado.returncode}); baixe a mao.")


# -- voz --------------------------------------------------------------------
def askVoice(settings: Settings, answers: Answers, prompt: Prompt) -> str:
    if answers.voice:
        return answers.voice

    prompt.say()
    prompt.say("[3/3] Qual voz?")
    prompt.say("      As `edge` sao as mais naturais em pt-BR mas precisam de internet;")
    prompt.say("      elas caem sozinhas numa voz local quando a rede falta.")

    opcoes = [
        (key, f"[{spec.language}] {encurtar(spec.description)} {custo(spec.engine)}")
        for key, spec in sorted(
            voiceCatalog.CATALOG.items(),
            # Portugues primeiro: e o idioma do robo. Dentro do idioma, as vozes
            # que ja estao no disco aparecem antes das que exigem download.
            key=lambda item: (item[1].language != "pt", voiceCatalog.needsDownload(item[0])),
        )
    ]
    return prompt.choice("voz", opcoes, default=settings.voice.voice)


def downloadVoices(voz: str, settings: Settings, prompt: Prompt) -> tuple[str, ...]:
    """Baixa a voz escolhida e a reserva offline dela.

    A reserva importa mais do que parece: e o arquivo que precisa estar no disco
    *antes* de a internet cair, e nao depois.
    """
    from roboteye.voices import VoiceDownloadError, consoleProgress, downloadVoice

    alvos = [voz]
    reserva = settings.voice.forVoice(voz).fallbackVoice()
    if reserva and reserva not in alvos:
        alvos.append(reserva)

    pendentes = [chave for chave in alvos if voiceCatalog.needsDownload(chave)]
    if not pendentes:
        prompt.say()
        prompt.say("Nada a baixar: esta configuracao fala inteiramente pela nuvem.")
        return ()

    prompt.say()
    prompt.say(f"Baixando o que a voz precisa: {', '.join(pendentes)}")
    baixadas: list[str] = []
    for chave in pendentes:
        try:
            downloadVoice(chave, onProgress=consoleProgress)
        except VoiceDownloadError as exc:
            prompt.say(f"  erro ao baixar {chave}: {exc}")
            prompt.say(f"  tente depois: roboteye voice download {chave}")
            continue
        baixadas.append(chave)
    return tuple(baixadas)


# -- persona ----------------------------------------------------------------
def askPersona(settings: Settings, answers: Answers, prompt: Prompt, projectRoot: Path) -> str:
    if answers.persona:
        return answers.persona

    # Uma persona só — ou nenhuma pergunta a fazer — não vira menu. Anunciar uma
    # escolha que não existe só polui a saída de uma instalação automatizada.
    disponiveis = availablePersonas(projectRoot / "persona")
    if len(disponiveis) <= 1 or not prompt.interactive:
        return settings.llm.persona

    prompt.say()
    prompt.say("Personalidade (o texto vive em persona/<nome>.md, edite a vontade):")
    opcoes = [(nome, descricao) for nome, descricao in disponiveis]
    return prompt.choice("persona", opcoes, default=settings.llm.persona)


def availablePersonas(personaDir: Path) -> list[tuple[str, str]]:
    """Personas do disco, com a primeira linha de titulo de cada uma."""
    encontradas: list[tuple[str, str]] = []
    for caminho in sorted(personaDir.glob("*.md")):
        if caminho.stem.endswith(".memoria"):
            continue
        encontradas.append((caminho.stem, summary(caminho)))
    return encontradas


def summary(caminho: Path) -> str:
    """Primeira frase de verdade do arquivo de persona.

    Nao serve o primeiro titulo: todas as personas comecam com "Quem voce e", e
    uma lista de opcoes identicas nao ajuda ninguem a escolher. O que distingue
    uma da outra e a linha seguinte.
    """
    try:
        linhas = caminho.read_text(encoding="utf-8").splitlines()
    except OSError:  # pragma: no cover - arquivo ilegivel e caso de borda
        return ""

    emComentario = False
    for linha in linhas:
        texto = linha.strip()
        if emComentario:
            emComentario = "-->" not in texto
            continue
        if texto.startswith("<!--"):
            emComentario = "-->" not in texto
            continue
        if not texto or texto.startswith("#"):
            continue
        return encurtar(texto)
    return ""


def custo(engine: str) -> str:
    return _ENGINE_COST.get(engine, "")


def encurtar(texto: str) -> str:
    return texto if len(texto) <= _MAX_DESCRICAO else texto[: _MAX_DESCRICAO - 1].rstrip() + "..."
