"""
Central logging configuration.

Importing this module configures the root logger once, honoring LOG_LEVEL and
LOG_JSON from settings. In production (LOG_JSON=true) logs are emitted as
single-line JSON for ingestion by log aggregators; in development they are
human-readable. A `request_id` contextvar is provided for request tracing.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

from src.config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

_CONFIGURED = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, val in getattr(record, "extra_fields", {}).items():
            payload[key] = val
        return json.dumps(payload, ensure_ascii=False)


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        base = f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} [{record.levelname}] {record.name}"
        if rid and rid != "-":
            base += f" rid={rid}"
        return f"{base}: {record.getMessage()}"


def configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter() if settings.log_json else _TextFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    _CONFIGURED = True


def set_request_id(rid: str) -> None:
    request_id_var.set(rid)


# Configure on import.
configure()
