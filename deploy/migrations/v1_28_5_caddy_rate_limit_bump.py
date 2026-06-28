"""Raise Caddy per-IP rate limits across the fleet and hot-reload.

Context: users hit "HTTP 429: Too many requests" during normal browsing. The
limiter is Caddy's mholt/caddy-ratelimit sliding window, keyed per client IP.
The /api/* zone allowed only 10 requests in any 1s window with zero burst
margin — a single SPA page load / feed render fires many uncoordinated /api
calls and trips it. Raise the ceilings: api 10->50/s, chain RPC/REST 10->30/s.

The live /etc/caddy/Caddyfile is rendered by setup_letsencrypt.py and is NOT
re-rendered on already-deployed (HTTPS) nodes — entrypoint keeps the existing
file when the domain's HTTPS config is present. So flipping the template
default does not reach deployed validators. This one-time migration patches the
live Caddyfile on disk. Caddy is started earlier in entrypoint (before
migrations run), so a file patch alone would only apply on the next restart;
we therefore also hot-reload Caddy so the new limits take effect this deploy.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from deploy.migrations._helpers import backup_file

MIGRATION_KEY = "v1.28.5-caddy-rate-limit-bump"
DESCRIPTION = "Raise Caddy per-IP rate limits (api 10->50, chain 10->30) and hot-reload"

CADDYFILE = Path(os.environ.get("CADDYFILE", "/etc/caddy/Caddyfile"))

# rate_limit zone name -> desired `events` count (window stays 1s)
TARGET_EVENTS = {
    "api_limit": 50,
    "chain_rpc_limit": 30,
    "chain_rest_limit": 30,
}


def _set_zone_events(content, zone, events):
    """Set `events N` inside a named rate_limit zone block.

    DOTALL + non-greedy spans the intervening `key {client_ip}` line (whose
    braces would otherwise break a `[^}]*` match) and stops at the first
    `events` after the zone name. Returns (new_content, old_value|None).
    """
    pattern = re.compile(rf"(zone\s+{re.escape(zone)}\b.*?events\s+)(\d+)", re.DOTALL)
    match = pattern.search(content)
    if not match:
        return content, None
    old = int(match.group(2))
    if old == events:
        return content, old
    return pattern.sub(rf"\g<1>{events}", content, count=1), old


def run(config_dir, logger):
    if not CADDYFILE.exists():
        # Fresh host: Caddyfile is rendered from the template, which already
        # carries the raised limits. Nothing to patch.
        logger.info(f"  {CADDYFILE} not present; template default applies")
        return "no Caddyfile (fresh host)"

    original = CADDYFILE.read_text(encoding="utf-8")
    content = original
    changes = []
    missing = []

    for zone, events in TARGET_EVENTS.items():
        content, old = _set_zone_events(content, zone, events)
        if old is None:
            missing.append(zone)
        elif old != events:
            changes.append(f"{zone} {old}->{events}")

    if missing:
        logger.warning(f"  rate_limit zones not found: {', '.join(missing)}")

    if content == original:
        logger.info("  Caddy rate limits already at target values")
        return "already up to date"

    backup_file(CADDYFILE)
    CADDYFILE.write_text(content, encoding="utf-8")
    logger.info(f"  Patched Caddy rate limits: {', '.join(changes)}")

    # Hot-reload the running Caddy. Best-effort: the on-disk change is the
    # source of truth and any later restart re-reads it.
    caddy_bin = shutil.which("caddy")
    if not caddy_bin:
        logger.warning("  caddy binary not on PATH; reload skipped (applies on next restart)")
        return f"patched ({', '.join(changes)}); reload skipped (no caddy bin)"

    try:
        subprocess.run(
            [caddy_bin, "reload", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        logger.info("  Reloaded Caddy with new rate limits")
        return f"patched and reloaded ({', '.join(changes)})"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        stderr = (getattr(e, "stderr", "") or "").strip()
        logger.warning(f"  caddy reload failed ({e}); applies on next restart. stderr: {stderr}")
        return f"patched ({', '.join(changes)}); reload failed"
