"""Prevent maintenance and SPA shell responses from becoming stale at the edge."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from deploy.migrations._helpers import backup_file


MIGRATION_KEY = "v1.29.5-caddy-maintenance-cache"
DESCRIPTION = "Disable maintenance-page caching and hot-reload Caddy"

CADDYFILE = Path(os.environ.get("CADDYFILE", "/etc/caddy/Caddyfile"))


def _replace_once(content, old, new, label):
    if new in content:
        return content, False
    count = content.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {label} block, found {count}")
    return content.replace(old, new, 1), True


def _patch_content(content):
    replacements = [
        (
            "maintenance cache headers",
            "\thandle @maintenance {\n" "\t\t# API and chain endpoints get JSON 503 during maintenance",
            "\thandle @maintenance {\n"
            '\t\theader Cache-Control "no-store, max-age=0"\n'
            '\t\theader Pragma "no-cache"\n'
            '\t\theader Expires "0"\n'
            "\n"
            "\t\t# API and chain endpoints get JSON 503 during maintenance",
        ),
        (
            "maintenance response status",
            "\t\t# Everything else gets the HTML maintenance page\n"
            "\t\thandle {\n"
            "\t\t\troot * /etc/caddy\n"
            "\t\t\trewrite * /maintenance.html\n"
            '\t\t\theader Content-Type "text/html; charset=utf-8"\n'
            "\t\t\tfile_server\n"
            "\t\t}\n"
            "\t}\n"
            "\n"
            "\t# Uniform media upload endpoint",
            "\t\t# Everything else gets the HTML maintenance page\n"
            "\t\thandle {\n"
            "\t\t\troot * /etc/caddy\n"
            "\t\t\trewrite * /maintenance.html\n"
            '\t\t\theader Content-Type "text/html; charset=utf-8"\n'
            "\t\t\tfile_server {\n"
            "\t\t\t\tstatus 503\n"
            "\t\t\t}\n"
            "\t\t}\n"
            "\t}\n"
            "\n"
            "\t# Uniform media upload endpoint",
        ),
        (
            "SPA route cache header",
            "\t\t@html path /\n" '\t\theader @html Cache-Control "no-cache"\n' "\n" "\t\ttry_files {path} /index.html",
            "\t\t@html path /\n"
            '\t\theader @html Cache-Control "no-cache"\n'
            "\n"
            "\t\t@spa_route not file\n"
            '\t\theader @spa_route Cache-Control "no-cache"\n'
            "\n"
            "\t\ttry_files {path} /index.html",
        ),
        (
            "backend-error cache headers",
            "\t\thandle @maintenance_err {\n" "\t\t\t# API and chain endpoints get JSON error",
            "\t\thandle @maintenance_err {\n"
            '\t\t\theader Cache-Control "no-store, max-age=0"\n'
            '\t\t\theader Pragma "no-cache"\n'
            '\t\t\theader Expires "0"\n'
            "\n"
            "\t\t\t# API and chain endpoints get JSON error",
        ),
        (
            "backend-error response status",
            "\t\t\t# Everything else gets the HTML maintenance page\n"
            "\t\t\thandle {\n"
            "\t\t\t\troot * /etc/caddy\n"
            "\t\t\t\trewrite * /maintenance.html\n"
            '\t\t\t\theader Content-Type "text/html; charset=utf-8"\n'
            "\t\t\t\tfile_server\n"
            "\t\t\t}\n"
            "\t\t}\n"
            "\t}\n"
            "}",
            "\t\t\t# Everything else gets the HTML maintenance page\n"
            "\t\t\thandle {\n"
            "\t\t\t\troot * /etc/caddy\n"
            "\t\t\t\trewrite * /maintenance.html\n"
            '\t\t\t\theader Content-Type "text/html; charset=utf-8"\n'
            "\t\t\t\tfile_server {\n"
            "\t\t\t\t\tstatus 503\n"
            "\t\t\t\t}\n"
            "\t\t\t}\n"
            "\t\t}\n"
            "\t}\n"
            "}",
        ),
    ]

    changed = []
    for label, old, new in replacements:
        content, did_change = _replace_once(content, old, new, label)
        if did_change:
            changed.append(label)
    return content, changed


def _run_caddy(caddy_bin, action, config):
    return subprocess.run(
        [caddy_bin, action, "--config", str(config), "--adapter", "caddyfile"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def run(config_dir, logger):
    if not CADDYFILE.exists():
        logger.info(f"  {CADDYFILE} not present; template default applies")
        return "no Caddyfile (fresh host)"

    original = CADDYFILE.read_text(encoding="utf-8")
    content, changes = _patch_content(original)
    if not changes:
        logger.info("  Caddy maintenance cache policy already up to date")
        return "already up to date"

    caddy_bin = shutil.which("caddy")
    if not caddy_bin:
        raise RuntimeError("caddy binary not found; cannot validate or reload configuration")

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=CADDYFILE.parent,
            prefix=".Caddyfile.",
            delete=False,
        ) as temp:
            temp.write(content)
            temp_path = Path(temp.name)
        _run_caddy(caddy_bin, "validate", temp_path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    backup_file(CADDYFILE)
    CADDYFILE.write_text(content, encoding="utf-8")
    try:
        _run_caddy(caddy_bin, "reload", CADDYFILE)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        CADDYFILE.write_text(original, encoding="utf-8")
        try:
            _run_caddy(caddy_bin, "reload", CADDYFILE)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as rollback_error:
            raise RuntimeError(f"Caddy reload failed and rollback reload also failed: {rollback_error}") from error
        raise RuntimeError(f"Caddy reload failed; restored previous configuration: {error}") from error

    summary = ", ".join(changes)
    logger.info(f"  Patched and reloaded Caddy: {summary}")
    return f"patched and reloaded ({summary})"
