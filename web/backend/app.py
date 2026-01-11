#!/usr/bin/env python3
from __future__ import annotations

"""
Backend entrypoint exposing the Flask app factory.

For production deployment, use Gunicorn via entrypoint.sh.
This file's __main__ block is for local development/testing only.
"""

import os

from factory import create_app
from shared.config import get_config
from logging_utils import logger


app = create_app(init_runtime=True)


if __name__ == "__main__":
    port = int(os.environ.get("BACKEND_PORT", 5000))
    # Bind to localhost by default, unless overridden (e.g. 0.0.0.0 for Docker)
    host = os.environ.get("BACKEND_HOST", "127.0.0.1")
    logger().info(f"Starting Mirage backend on port {port}")
    try:
        db_url = get_config().get_indexer_config().get("database_url", "")
    except Exception:
        db_url = ""
    logger().info(f"Database URL: {db_url}")
    logger().info("Note: For production, use Gunicorn via entrypoint.sh")
    app.run(host=host, port=port, debug=False)
