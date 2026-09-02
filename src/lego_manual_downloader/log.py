"""Console logging for the CLI.

Levels are rendered for a human reading a terminal, not for a log aggregator: INFO
lines are the ordinary narration of a run and print bare, while everything else
carries a level tag so it stands out. Progress goes to stdout and problems to
stderr, so `2>/dev/null` and `>/dev/null` each keep the half you asked for.
"""

import logging
import os
import sys
from pathlib import Path
from typing import IO

LEVELS = ("debug", "info", "warning", "error")
DEFAULT_LEVEL = "info"

PACKAGE_LOGGER = "lego_manual_downloader"

_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(message)s"

_RESET = "\033[0m"
_COLORS = {
    logging.DEBUG: "\033[90m",  # grey
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[31m",
}


class _Formatter(logging.Formatter):
    """Bare message at INFO, `LEVEL   message` everywhere else."""

    def __init__(self, color: bool) -> None:
        super().__init__("%(message)s")
        self._color = color

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        if record.levelno == logging.INFO:
            return text
        tag = f"{record.levelname:<8}"
        if self._color and record.levelno in _COLORS:
            tag = f"{_COLORS[record.levelno]}{tag}{_RESET}"
        return f"{tag}{text}"


def _use_color(stream: IO[str], override: bool | None) -> bool:
    if override is not None:
        return override
    if os.environ.get("NO_COLOR"):
        return False
    return stream.isatty()


def _stream_handler(stream: IO[str], color: bool | None) -> logging.StreamHandler[IO[str]]:
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_Formatter(_use_color(stream, color)))
    return handler


def configure(
    level: str = DEFAULT_LEVEL, log_file: Path | None = None, color: bool | None = None
) -> None:
    """Point the package logger at the console, replacing any previous setup."""
    logger = logging.getLogger(PACKAGE_LOGGER)
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    logger.setLevel(level.upper())

    out = _stream_handler(sys.stdout, color)
    out.addFilter(lambda record: record.levelno < logging.WARNING)
    logger.addHandler(out)

    err = _stream_handler(sys.stderr, color)
    err.setLevel(logging.WARNING)
    logger.addHandler(err)

    if log_file is not None:
        to_file = logging.FileHandler(log_file.expanduser(), encoding="utf-8")
        to_file.setFormatter(logging.Formatter(_FILE_FORMAT))
        logger.addHandler(to_file)
