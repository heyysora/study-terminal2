"""Logging with secret redaction.

No credentials are required by the app today. This filter stays as a safety net:
it replaces any configured secret value with ***REDACTED*** and scrubs common
key/token/secret/password patterns in case a future optional provider key is logged.
"""
from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

REDACTED = "***REDACTED***"
_PATTERNS = [
    re.compile(r"((?:api[_-]?key|token|secret|password)['\"]?\s*[:=]\s*['\"]?)([^'\",\s}&]+)", re.I),
    re.compile(r"(['\"](?:key|secret)['\"]\s*:\s*['\"])([^'\"]+)", re.I),
]


class RedactingFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s and len(s) >= 4]

    def redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, REDACTED)
        for p in _PATTERNS:
            text = p.sub(lambda m: m.group(1) + REDACTED, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = self.redact(msg)
        if clean != msg:
            record.msg = clean
            record.args = None
        return True


def configure_logging(level: str, log_dir: Path, secrets: list[str]) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        if getattr(h, "_study_terminal", False):
            root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    redactor = RedactingFilter(secrets)

    console = logging.StreamHandler()
    file = RotatingFileHandler(log_dir / "study_terminal.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    for h in (console, file):
        h.setFormatter(fmt)
        h.addFilter(redactor)
        h._study_terminal = True  # type: ignore[attr-defined]
        root.addHandler(h)

    # httpx logs full URLs at INFO; keep it quiet. Keys travel in headers, not URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
