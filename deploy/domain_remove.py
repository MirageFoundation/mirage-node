#!/usr/bin/env python3
"""Return the node to IP/HTTP mode by clearing DOMAIN and re-rendering Caddy."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path("/opt/mirage")
CADDYFILE = Path("/etc/caddy/Caddyfile")
NODE_ENV = Path.home() / ".mirage" / "env" / "node.env"


def main() -> int:
    if not NODE_ENV.is_file():
        print("ERROR: node.env is missing", file=sys.stderr)
        return 1
    content = NODE_ENV.read_text(encoding="utf-8")
    updated, count = re.subn(r"^DOMAIN=.*$", "DOMAIN=", content, flags=re.M)
    if count > 1:
        print("ERROR: duplicate DOMAIN entries in node.env", file=sys.stderr)
        return 1
    NODE_ENV.write_text(updated)
    os.environ.pop("DOMAIN", None)
    os.environ["DOMAIN"] = ""
    render = subprocess.run(
        [sys.executable, str(ROOT_DIR / "deploy" / "render_template.py"),
         str(ROOT_DIR / "deploy" / "templates" / "caddy" / "Caddyfile"),
         str(CADDYFILE)],
        check=False,
    )
    if render.returncode != 0:
        print("ERROR: failed to render HTTP Caddyfile", file=sys.stderr)
        return 1
    validate = subprocess.run(
        ["caddy", "validate", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        check=False,
        capture_output=True,
        text=True,
    )
    if validate.returncode != 0:
        print("ERROR: Caddyfile validation failed:", file=sys.stderr)
        print(validate.stderr, file=sys.stderr)
        return 1
    reload = subprocess.run(
        ["caddy", "reload", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        check=False,
        capture_output=True,
        text=True,
    )
    if reload.returncode != 0:
        print("ERROR: Caddy reload failed:", file=sys.stderr)
        print(reload.stderr, file=sys.stderr)
        return 1
    print("Domain removed. Node is serving HTTP on this host's IP.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
