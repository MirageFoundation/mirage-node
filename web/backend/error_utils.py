from __future__ import annotations

"""Centralized error response helpers.

Never return raw exception text to API clients. Use safe_error() in catch blocks
to log the full exception server-side and return a generic message to the caller.
"""

import traceback
import uuid

from flask import jsonify
from logging_utils import logger


def safe_error(e: Exception, context: str = "") -> tuple:
    """Log exception server-side and return a generic JSON error to the client.

    Args:
        e: The caught exception.
        context: Optional label for the endpoint/function (included in logs).

    Returns:
        A (Response, 500) tuple suitable for returning from a Flask route.
    """
    request_id = uuid.uuid4().hex[:8]
    prefix = f"[{context}] " if context else ""
    logger().error(f"{prefix}request_id={request_id} {type(e).__name__}: {e}\n{traceback.format_exc()}")
    return jsonify({"error": "Internal server error", "request_id": request_id}), 500
