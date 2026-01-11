from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from typing import Optional
import threading
import asyncio
import faulthandler
import traceback


def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _get_date_log_path(log_dir: str, component: str) -> str:
    """Get log file path with today's date: component-YYYY-MM-DD.log"""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(log_dir, f"{component}-{date_str}.log")


class _DateFileHandler(logging.FileHandler):
    """
    File handler that automatically switches to a new file each day (UTC).
    Filename format: component-YYYY-MM-DD.log
    """

    def __init__(self, log_dir: str, component: str, encoding: str = "utf-8"):
        self.log_dir = log_dir
        self.component = component
        self._current_date = self._get_utc_date()
        log_path = _get_date_log_path(log_dir, component)
        super().__init__(log_path, mode="a", encoding=encoding)

    def _get_utc_date(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def emit(self, record: logging.LogRecord) -> None:
        # Check if we need to roll over to a new day
        current_date = self._get_utc_date()
        if current_date != self._current_date:
            self._current_date = current_date
            # Close old file, open new one
            self.close()
            self.baseFilename = _get_date_log_path(self.log_dir, self.component)
            self.stream = self._open()
        super().emit(record)


def _project_root() -> str:
    # This file is under shared/, project root is one level up
    here = os.path.abspath(os.path.dirname(__file__))
    return os.path.abspath(os.path.join(here, ".."))


def log_dir_for_component(component: str) -> str:
    """
    Get log directory for a component.

    New structure: ~/.mirage/logs/<component>/
    Components: node, indexer, backend, postgres, hermes, caddy, referrals, deploy
    """
    # ~/.mirage/logs/<component>/
    base_dir = os.path.expanduser("~/.mirage/logs")
    return os.path.join(base_dir, component)


def log_dir_for_node(node_id: int) -> str:
    """Legacy function - redirects to log_dir_for_component for backwards compatibility."""
    # For backwards compatibility, map node_id to component
    # In production, node_id is typically 1 and logs go to ~/.mirage/logs/node/
    return log_dir_for_component("node")


class _StreamToLogger:
    def __init__(self, level: int) -> None:
        self._level = level
        self._logger = logging.getLogger()

    def write(self, buf: str) -> int:
        buf = str(buf)
        if buf.rstrip():
            for line in buf.rstrip().splitlines():
                self._logger.log(self._level, line.rstrip())
        return len(buf)

    def flush(self) -> None:
        pass


def configure_logging(
    component: str,
    node_id: Optional[int] = None,
    level: int = logging.INFO,
    redirect_std: bool = True,
) -> str:
    """
    Configure Python logging to write to date-based files under ~/.mirage/logs/<component>/.
    Each day gets a new file: component-YYYY-MM-DD.log (UTC).
    Optionally redirects stdout/stderr to logging.

    Args:
        component: Name of the component (indexer, backend, referrals, deploy, etc.)
        node_id: Deprecated, ignored. Kept for backwards compatibility.
        level: Logging level (default: INFO)
        redirect_std: Whether to redirect stdout/stderr to logging

    Returns the absolute log file path.
    """
    try:
        log_dir = log_dir_for_component(component)
        _ensure_dir(log_dir)
        log_path = _get_date_log_path(log_dir, component)

        # Date-based file handler - auto-switches at midnight UTC
        file_handler = _DateFileHandler(log_dir, component, encoding="utf-8")
        file_handler.setLevel(level)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
        file_handler.setFormatter(formatter)

        # Console handler preserved for interactive visibility
        console = logging.StreamHandler()
        console.setLevel(level)
        console.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        # Avoid duplicate handlers on repeated calls
        _types = {type(h) for h in root_logger.handlers}
        if _DateFileHandler not in _types:
            root_logger.addHandler(file_handler)
        if logging.StreamHandler not in _types:
            root_logger.addHandler(console)

        # Optional stdout/stderr redirection to logging
        if redirect_std:
            try:
                if not isinstance(sys.stdout, _StreamToLogger):
                    sys.stdout = _StreamToLogger(logging.INFO)  # type: ignore
                if not isinstance(sys.stderr, _StreamToLogger):
                    sys.stderr = _StreamToLogger(logging.ERROR)  # type: ignore
            except Exception:
                pass

        # Capture warnings into logging
        try:
            logging.captureWarnings(True)
        except Exception:
            pass

        # Enable faulthandler to dump tracebacks on fatal signals; goes to stderr (redirected)
        try:
            if not faulthandler.is_enabled():
                faulthandler.enable()
        except Exception:
            pass

        # Global unhandled exception hook
        try:

            def _excepthook(exc_type, exc, tb):
                logging.getLogger().error(
                    "FATAL: Unhandled exception",
                    exc_info=(exc_type, exc, tb),
                )

            sys.excepthook = _excepthook
        except Exception:
            pass

        # Thread exception hook (Python 3.8+)
        try:

            def _thread_excepthook(args: threading.ExceptHookArgs) -> None:  # type: ignore[name-defined]
                logging.getLogger().error(
                    f"FATAL: Unhandled exception in thread {getattr(args.thread, 'name', '')}",
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )

            threading.excepthook = _thread_excepthook  # type: ignore[attr-defined]
        except Exception:
            pass

        # asyncio default exception handler
        try:

            def _asyncio_handler(loop, context):
                exc = context.get("exception")
                msg = context.get("message") or (str(exc) if exc else str(context))
                logging.getLogger().error("ASYNC ERROR: %s", msg, exc_info=exc)

            try:
                loop = asyncio.get_event_loop()
                loop.set_exception_handler(_asyncio_handler)
            except Exception:
                pass
        except Exception:
            pass

        # Unraisable exceptions (Python 3.8+)
        try:

            def _unraisable(unraisable):
                logging.getLogger().error(
                    f"UNRAISABLE: {getattr(unraisable, 'err_msg', '')}",
                    exc_info=(type(unraisable.exc_value), unraisable.exc_value, unraisable.exc_traceback),
                )

            if hasattr(sys, "unraisablehook"):
                sys.unraisablehook = _unraisable  # type: ignore[attr-defined]
        except Exception:
            pass

        return log_path
    except Exception:
        # Fallback to basic config
        logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
        return os.path.join(_project_root(), "logs", f"{component}.log")


__all__ = ["configure_logging", "log_dir_for_component", "log_dir_for_node"]
