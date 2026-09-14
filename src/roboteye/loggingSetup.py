"""Configuracao de logging da aplicacao."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False

_LEVEL_COLORS = {
    logging.DEBUG: "\033[36m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_RESET = "\033[0m"


class ConsoleFormatter(logging.Formatter):
    """Formato compacto, com cor apenas quando a saida e um terminal."""

    def __init__(self, *, colorize: bool) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
            datefmt="%H:%M:%S",
        )
        self.colorize = colorize

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if not self.colorize:
            return message
        color = _LEVEL_COLORS.get(record.levelno)
        return f"{color}{message}{_RESET}" if color else message


def configureLogging(level: str = "INFO") -> None:
    """Instala o handler de console. Chamadas repetidas apenas ajustam o nivel."""
    global _CONFIGURED

    root = logging.getLogger()
    resolved = getattr(logging, level.upper(), logging.INFO)

    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(ConsoleFormatter(colorize=sys.stderr.isatty()))
        root.addHandler(handler)
        # Bibliotecas HTTP sao verbosas demais em DEBUG.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        _CONFIGURED = True

    root.setLevel(resolved)


def getLogger(name: str) -> logging.Logger:
    """Logger nomeado dentro do namespace da aplicacao."""
    return logging.getLogger(name)
