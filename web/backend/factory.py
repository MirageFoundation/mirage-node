from __future__ import annotations

"""Flask app factory for the Mirage backend.

Functions:
- create_app(init_runtime=True): Initialize Flask app, register blueprints, init runtime.
"""

import json
import os
import sys
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv


def _ensure_project_root_on_path() -> None:
    here = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.abspath(os.path.join(here, "../.."))
    if project_root not in sys.path:
        sys.path.append(project_root)


_ensure_project_root_on_path()

# Load environment variables for local development from persistent config if available
cfg_env = os.path.expanduser("~/.mirage/env/backend.env")
if os.path.exists(cfg_env):
    load_dotenv(cfg_env, override=False)

from logging_utils import configure_logging, logger  # noqa: E402
from node import initialize_runtime  # noqa: E402
from params import load_params  # noqa: E402
from tx import load_tx_size_cost_per_byte  # noqa: E402
from routes.public import public_bp  # noqa: E402
from routes.core import core_bp  # noqa: E402
from routes.communities import communities_bp  # noqa: E402

_GONE_PATHS = {
    "/api/get_topics",
    "/api/search_topics",
    "/api/get_agents",
    "/api/core/follow_topic",
    "/api/core/unfollow_topic",
    "/api/core/block_topic",
    "/api/core/unblock_topic",
    "/api/core/enable_agent",
    "/api/core/disable_agent",
    "/api/core/set_agents",
    "/api/core/annotate",
    "/api/get_quests",
    "/api/quests",
    "/api/achievements",
    "/api/invite",
    "/api/referrals",
    "/api/get_referral",
    "/api/get_invite_codes",
    "/api/validate_invite_code",
}


def create_app(init_runtime: bool = True) -> Flask:
    configure_logging()
    app = Flask(__name__)

    # Always run in production mode
    app.config["ENV"] = "production"
    app.config["DEBUG"] = False
    app.config["TESTING"] = False
    # Bound request bodies before Werkzeug materializes them. Just above the
    # largest permitted video upload (MEDIA_MAX_VIDEO_MB, default 300) so
    # legitimate uploads clear the global gate and per-kind checks in
    # upload_media still enforce the tighter image cap.
    from media.base import max_video_bytes

    app.config["MAX_CONTENT_LENGTH"] = max_video_bytes() + (16 * 1024 * 1024)

    CORS(app)

    app.register_blueprint(public_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(communities_bp)

    @app.before_request
    def _reject_retired_v139_routes():
        path = request.path.rstrip("/") or "/"
        if path in _GONE_PATHS or path.startswith("/api/quests") or path.startswith("/api/referrals") or path.startswith("/api/rewards") or path.startswith("/api/admin/rewards"):
            from error_utils import api_error_code
            return api_error_code("gone", 410)

    # Global safety net: catch any unhandled exception and return a generic error
    @app.errorhandler(Exception)
    def _handle_unhandled(e):
        from werkzeug.exceptions import HTTPException
        from error_utils import safe_error

        # HTTPExceptions carry a real status (e.g. 404 for an unknown route, often an
        # outdated client hitting a removed endpoint). Surface that status instead of
        # masking it as a 500. error_code is set so the after_request hook skips it.
        if isinstance(e, HTTPException):
            code = e.code or 500
            logger().info(f"[http_error] status={code} method={request.method} path={request.path} name={e.name}")
            return jsonify({"error": e.name.lower(), "error_code": "http_error", "status": code}), code

        return safe_error(e, context="unhandled")

    @app.after_request
    def _inject_error_code(response):
        try:
            ct = response.content_type or ""
            if "application/json" not in ct:
                return response
            data = response.get_json(silent=True)
            if not isinstance(data, dict):
                return response
            if "error" not in data or data.get("error_code"):
                return response
            from error_utils import get_error_code

            data["error_code"] = get_error_code(data.get("error"))
            response.set_data(json.dumps(data, separators=(",", ":")))
        except Exception as err:
            logger().error(f"[error_code] failed to inject error_code: {err}")
            raise
        return response

    @app.before_request
    def _record_request_activity():
        if not request.path.startswith("/api/"):
            return
        # Mirage-owned analytics: record visit/engagement for every client
        # (web + mobile) from the one place every request passes through.
        #
        # Last-seen is not written here. A query `address` is unverified, so
        # anyone could keep another user's account looking active, or make a
        # dormant account look alive. It is written by the after_request hook
        # below, and only for a request that succeeded.
        from stats import record_request_event

        record_request_event(request.path)

    @app.after_request
    def _bind_verified_request_activity(response):
        if response.status_code < 400 and getattr(g, "verified_request_address", None):
            from stats import bind_verified_request_identity

            bind_verified_request_identity(request.path)
        # Deferred until the outcome is known. This used to happen inside
        # derive_address_from_pubkey, which despite its name verifies nothing —
        # the derivation only checks for 33 bytes — so an unauthenticated caller
        # could commit a row per forged pubkey and inflate the published
        # active-user count without bound before the request failed.
        from routes.core import flush_user_last_seen

        flush_user_last_seen(response.status_code)
        return response

    # Middleware: inject new_inbox_items into every JSON response for logged-in users
    @app.after_request
    def _inject_inbox_count(response):
        try:
            addr = request.args.get("address") or ""
            if not addr or addr.lower() == "guest":
                return response
            ct = response.content_type or ""
            if "application/json" not in ct:
                return response
            if response.status_code >= 400:
                return response

            import time as _time
            from routes.public import _inbox_cache, _get_new_inbox_count

            client_seen = 0
            try:
                client_seen = int(request.args.get("inbox_last_viewed_at") or 0)
            except Exception:
                client_seen = 0

            # Check cache first to avoid opening a DB connection on every request
            viewer = addr.lower()
            count = None
            cached = _inbox_cache.get(viewer)
            if cached and cached[1] > _time.time():
                cached_seen = cached[2] if len(cached) > 2 else 0
                if not client_seen or cached_seen >= client_seen:
                    count = cached[0]
                else:
                    _inbox_cache.pop(viewer, None)

            if count is None:
                from db import connect_db

                conn = connect_db(timeout=3.0, busy_timeout_ms=5000)
                cur = conn.cursor()
                count = _get_new_inbox_count(cur, addr)
                conn.close()

            data = response.get_json(silent=True)
            if isinstance(data, dict) and "new_inbox_items" not in data:
                data["new_inbox_items"] = count
                response.set_data(json.dumps(data, separators=(",", ":")))
        except Exception:
            pass
        return response

    if init_runtime:
        initialize_runtime()
        # Initialize backend-owned DB schema (quests, invites, referrals, etc.)
        from db import init_backend_schema

        logger().info("Initializing backend DB schema...")
        init_backend_schema()
        logger().info("Backend DB schema initialized")
        from push_listener import start_push_listener

        start_push_listener()
        # Load chain params from indexer DB, waiting for indexer to populate them
        logger().info("Loading chain params from indexer DB (waiting for indexer if needed)...")
        load_params()
        logger().info("Chain params loaded successfully from indexer DB")
        # Load tx size cost once at startup
        logger().info("Loading tx_size_cost_per_byte from indexer DB...")
        load_tx_size_cost_per_byte()
        logger().info("tx_size_cost_per_byte loaded successfully")

    return app


app = create_app(init_runtime=True)


__all__ = ["create_app", "app"]
