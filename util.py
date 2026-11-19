"""Shared helpers: errors, logging, retry."""

from __future__ import annotations

import logging
import logging.handlers
import time
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


class BiliNoteError(Exception):
    """Expected, user-facing error. Printed without a traceback."""

    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


class AuthError(BiliNoteError):
    pass


class ConfigError(BiliNoteError):
    pass


class ApiError(BiliNoteError):
    def __init__(self, message: str, code: int | None = None, hint: str = ""):
        super().__init__(message, hint)
        self.code = code


def setup_logging(logs_dir: Path, verbose: bool = False) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("bili_note")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")

    fh = logging.handlers.RotatingFileHandler(
        logs_dir / "bili_note.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)
    return logger


def retry_call(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    delay: float = 2.0,
    logger: logging.Logger | None = None,
    label: str = "operation",
) -> T:
    """Run fn, retrying on any exception up to `attempts` total tries."""
    last: Exception | None = None
    for i in range(1, max(1, attempts) + 1):
        try:
            return fn()
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001 - retried then surfaced
            last = exc
            if logger:
                logger.warning("%s 第 %d/%d 次失败: %s", label, i, attempts, exc)
            if i < attempts:
                time.sleep(delay * i)
    assert last is not None
    raise last


def mmss(seconds: float | int) -> str:
    seconds = max(0, int(round(float(seconds))))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
