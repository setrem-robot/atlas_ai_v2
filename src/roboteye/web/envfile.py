"""Edicao do `.env` preservando o que a maquina nao escreveu.

Um `.env` gerado a partir do exemplo e mais comentario do que configuracao: ele
explica o que cada chave faz, quais valores aceita e por que o padrao e aquele.
Reescrever o arquivo a partir de um dicionario apagaria tudo isso — e quem
abrisse o arquivo depois encontraria uma lista de chaves sem explicacao nenhuma.

Entao a edicao aqui e cirurgica: acha a linha da chave e troca so o valor dela.
Chave que ainda nao existe vai para o fim, e chave que ninguem conhece continua
onde estava.

O arquivo e escrito por substituicao atomica. Se a energia cair no meio de um
salvamento — coisa banal num robo ligado na tomada de uma sala de aula —, o que
sobra e o arquivo antigo inteiro, e nao meio arquivo novo.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

#: `CHAVE=valor`, tolerando espaco em volta e o `export` que alguns .env usam.
_LINE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=)(.*)$")


def read(path: Path) -> dict[str, str]:
    """Le as chaves de um `.env`. Arquivo inexistente devolve vazio."""
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if match:
            values[match.group(2)] = unquote(match.group(4).strip())
    return values


def update(path: Path, changes: dict[str, str]) -> None:
    """Grava `changes` no arquivo, mantendo comentarios, ordem e o resto."""
    if not changes:
        return

    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    pending = dict(changes)
    seen: set[str] = set()

    for index, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            continue
        key = match.group(2)
        if key not in pending:
            continue

        # Toda ocorrencia e trocada, e nao so a primeira. Um `.env` editado a
        # mao pode repetir uma chave; se a troca parasse na primeira, `read`
        # continuaria devolvendo a ultima — a antiga —, e salvar pela pagina
        # pareceria nao ter efeito nenhum.
        prefix, equals = match.group(1), match.group(3)
        lines[index] = f"{prefix}{key}{equals}{quote(pending[key])}"
        seen.add(key)

    pending = {key: value for key, value in pending.items() if key not in seen}
    if pending:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Ajustado pela interface de configuracao")
        lines += [f"{key}={quote(value)}" for key, value in pending.items()]

    writeAtomic(path, "\n".join(lines) + "\n")


def quote(value: str) -> str:
    """Poe aspas so quando o valor precisa delas."""
    if value == "" or any(c in value for c in " \t\"#'"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def unquote(value: str) -> str:
    # Um comentario no fim da linha nao faz parte do valor, mas so quando o
    # valor nao esta entre aspas — `SENHA="a#b"` tem cerquilha de verdade.
    if value[:1] in {'"', "'"} and value[-1:] == value[:1] and len(value) >= 2:
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value.split(" #", 1)[0].strip()


def writeAtomic(path: Path, content: str) -> None:
    """Escreve num arquivo temporario e o move por cima do original.

    O temporario nasce no mesmo diretorio de proposito: `os.replace` so e
    atomico dentro do mesmo sistema de arquivos.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # `delete=False` porque quem fecha o arquivo aqui e o `with`, mas quem o
    # remove e o `os.replace` — ou o tratamento de erro, se ele nao acontecer.
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - fechado no `with` abaixo
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle as arquivo:
            arquivo.write(content)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise
