"""Structured JSON logging with per-request / per-job correlation IDs."""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

from app.config import settings

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def _inject_correlation_id(_logger, _name, event_dict):
    cid = correlation_id_var.get()
    if cid and "correlation_id" not in event_dict:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    file_handler = logging.FileHandler(settings.log_dir / "app.log", encoding="utf-8")
    handlers.append(file_handler)

    logging.basicConfig(format="%(message)s", level=level, handlers=handlers, force=True)
    for noisy in ("uvicorn.access", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_json
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "app") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def set_correlation_id(cid: str | None) -> None:
    correlation_id_var.set(cid)
