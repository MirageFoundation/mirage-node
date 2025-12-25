from __future__ import annotations

import os
import multiprocessing

bind_host = os.environ.get("BACKEND_HOST", "127.0.0.1")
bind_port = os.environ.get("BACKEND_PORT", "5000")
bind = f"{bind_host}:{bind_port}"

workers_env = os.environ.get("GUNICORN_WORKERS")
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
    server.log.info(f"Starting Gunicorn with {workers} workers on {bind}")

def when_ready(server):
    server.log.info(f"Gunicorn ready. Listening on {bind}")

def on_exit(server):
    server.log.info("Gunicorn shutting down")

