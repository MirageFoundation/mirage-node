from __future__ import annotations

import logging
import os
import multiprocessing


class _SuppressWinchFilter(logging.Filter):
    """Filter out 'Handling signal: winch' log messages from Gunicorn."""

    def filter(self, record):
        return "Handling signal: winch" not in record.getMessage()


bind_host = os.environ.get("BACKEND_HOST", "127.0.0.1")
bind_port = os.environ.get("BACKEND_PORT", "5000")
bind = f"{bind_host}:{bind_port}"

workers_env = os.environ.get("BACKEND_GUNICORN_WORKERS")
if workers_env:
    workers = int(workers_env)
else:
    try:
        cpu_count = multiprocessing.cpu_count()
        workers = (2 * cpu_count) + 1
    except Exception:
        workers = 4

worker_class = "sync"

timeout = 120
graceful_timeout = 30
keepalive = 2

accesslog = "-"
errorlog = "-"
loglevel = "info"


def on_starting(server):
    # Suppress noisy "Handling signal: winch" logs (SIGWINCH from terminal resize)
    winch_filter = _SuppressWinchFilter()
    error_logger = logging.getLogger("gunicorn.error")
    for handler in error_logger.handlers:
        handler.addFilter(winch_filter)
    # Also attach to arbiter's log if it uses a different logger (e.g. gunicorn Logger wrapper)
    arbiter_log = getattr(server.log, "logger", server.log)
    if hasattr(arbiter_log, "handlers"):
        for handler in arbiter_log.handlers:
            if winch_filter not in getattr(handler, "filters", []):
                handler.addFilter(winch_filter)
    server.log.info(f"Starting Gunicorn with {workers} workers on {bind}")


def when_ready(server):
    server.log.info(f"Gunicorn ready. Listening on {bind}")


def on_exit(server):
    server.log.info("Gunicorn shutting down")
