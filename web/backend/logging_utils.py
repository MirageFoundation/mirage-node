from __future__ import annotations

"""Logging utilities and structured event helpers.

Functions:
- configure_logging(): Configure global logging.
- logger(): Get module logger.
- next_request_id(): Incrementing request id.
- log_event(rid, event, **fields): Structured log line.
"""

import itertools
import logging
import time
from typing import Any


_REQ_COUNTER = itertools.count(1)


def configure_logging() -> None:
    try:
        from shared.logging_setup import configure_logging as _cfg

        _path = _cfg(component="backend", level=logging.INFO)
        logging.getLogger("mirage-backend").info(f"backend logging initialized -> {_path}")
    except Exception:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def logger() -> logging.Logger:
    return logging.getLogger("mirage-backend")


def next_request_id() -> int:
    try:
        return next(_REQ_COUNTER)
    except Exception:
        return int(time.time() * 1000) % 1000000


def log_event(rid: int, event: str, **fields: Any) -> None:
    try:
        parts = [f"{k}={fields[k]}" for k in sorted(fields.keys())]
        msg = f"{event} rid={rid} " + " ".join(parts)
    except Exception:
        msg = f"{event} rid={rid} fields={fields}"
    logger().info(msg)


__all__ = ["configure_logging", "logger", "next_request_id", "log_event"]
