from __future__ import annotations

"""Flask app factory for the Mirage backend.

Functions:
- create_app(init_runtime=True): Initialize Flask app, register blueprints, init runtime.
"""

import os
import sys
from flask import Flask
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
from node import initialize_runtime, require_runtime  # noqa: E402
from params import load_params  # noqa: E402
from routes.public import public_bp  # noqa: E402
from routes.core import core_bp  # noqa: E402


def create_app(init_runtime: bool = True) -> Flask:
    configure_logging()
    app = Flask(__name__)

    # Always run in production mode
    app.config["ENV"] = "production"
    app.config["DEBUG"] = False
    app.config["TESTING"] = False

    CORS(app)

    app.register_blueprint(public_bp)
    app.register_blueprint(core_bp)

    if init_runtime:
        initialize_runtime()
        # Load chain params at startup, waiting for chain to be available
        logger().info("Loading chain params (waiting for chain if needed)...")
        rt = require_runtime()
        load_params()
        logger().info("Chain params loaded successfully")

    return app


app = create_app(init_runtime=True)


__all__ = ["create_app", "app"]
