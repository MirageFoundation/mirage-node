#!/usr/bin/env python3
"""
Post-deploy verification for v1.29.0.

Per the /upgrade workflow this file is rewritten every release to check ONLY
what THIS release changes — generic/prior-upgrade checks are removed so a green
run is a precise statement about the current rollout. It is a manual post-deploy
probe (not run automatically by deploy/deploy.sh):

  python scripts/verify_upgrade.py                       # inside container
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py

What v1.29.0 actually changes (deploy-visible, and therefore checked here)
-------------------------------------------------------------------------
v1.29.0 is the "single edge vendor" release: mirage.vote / mirage.talk move
behind Bunny.net (edge + Bunny Shield upload scanning), media uploads become
fail-closed on any node without a scanning edge, and video limits grow to ~30
minutes. The config the deploy migrations + templates land — and that this
script verifies — is:

  1. MEDIA_UPLOADS_ENABLED — fail-closed upload gate, pinned PER NODE by
     deploy/migrations/v1_29_0_media_uploads_enabled.py: `true` only on the
     domains behind a scanning edge (mirage.vote, mirage.talk), `false`
     everywhere else (e.g. the IP-only nodes). settings.py only treats the
     literal "false" as off, so we evaluate the same way the backend does.
  2. 30-min video caps — MEDIA_VIDEO_MAX_DURATION_SEC 600->1800 and
     MEDIA_MAX_VIDEO_MB 300->1500 (deploy/migrations/v1_29_0_video_caps_30min.py;
     Caddy @upload max_size is raised in the template alongside).
  3. AntiSpamBot default agent — added to AUTO_ENABLED_AGENTS on mirage.talk ONLY
     (deploy/migrations/v1_29_0_mirage_talk_antispam_agent.py).
  4. Edge cache correctness — Caddy stamps `Cache-Control: no-store` on the
     dynamic @api and /chain/* routes so the CDN never caches them.
  5. Edge client-IP trust — deploy/refresh_edge_ips.py is wired into the
     entrypoint (and a daily refresh) to emit /etc/caddy/trusted-proxies.caddy
     so Caddy resolves the real client IP behind Cloudflare/Bunny.
  6. The chain is live after the rolling restart (indexer freshness).
  7. The shipped frontend reports the release version.

Config is read from the process environment (os.environ) because that is exactly
what the backend runs with: deploy.sh starts the container with --env-file for
each ~/.mirage/env/*.env, and `docker exec` inherits that same environment. So a
value here is the value the live backend sees, not just what's on disk.

Not verified here (no point-in-time deploy signature):
  - The origin nftables firewall (deploy/setup_origin_firewall.sh) and Bunny
    dashboard state (pull zones, Shield, DNS) are infrastructure outside the
    container; validate those with the runbook, not this script.
  - The Bunny Stream thumbnail backfill is a one-shot indexer migration whose
    effect is historical rows; it has no steady-state runtime signature.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "web" / "backend"))

try:
    import psycopg
except ImportError:
    print("FATAL: psycopg not installed")
    sys.exit(1)


# ─── Constants tied to THIS release. If any change, this file must change. ─────

RELEASE_VERSION = "v1.29.0"

# Domains that sit behind a scanning edge (Bunny Shield) and therefore accept
# public uploads. Must match UPLOAD_DOMAINS in the media-uploads migration.
UPLOAD_DOMAINS = {"mirage.vote", "mirage.talk"}

# AntiSpamBot — default-enabled agent on mirage.talk only.
ANTISPAM_AGENT = "mirage17jn2j2wwnvqdhtecwfh0wa0vpj9qa5gcalztap"
ANTISPAM_DOMAIN = "mirage.talk"

# 30-min video caps: (env key, old default we replaced, new value).
VIDEO_CAPS = [
    ("MEDIA_VIDEO_MAX_DURATION_SEC", "600", "1800"),
    ("MEDIA_MAX_VIDEO_MB", "300", "1500"),
]

CADDYFILE = Path("/etc/caddy/Caddyfile")
TRUSTED_PROXIES = Path("/etc/caddy/trusted-proxies.caddy")


passed = 0
failed = 0
warnings = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  \u2713 {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  \u2717 {msg}")


def warn(msg: str) -> None:
    global warnings
    warnings += 1
    print(f"  \u26a0 {msg}")


def info(msg: str) -> None:
    print(f"  \u2022 {msg}")


def section(title: str) -> None:
    print(f"\n{'\u2500' * 60}")
    print(f"  {title}")
    print(f"{'\u2500' * 60}")


def require_env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise RuntimeError(f"{key} not set")
    return val


def env_value(key: str) -> str:
    return os.environ.get(key, "").strip()


# ─── v1.29.0 checks ───────────────────────────────────────────────────────────


def check_media_uploads_gate() -> None:
    """Fail-closed upload gate, pinned per node.

    A node only accepts public uploads when it sits behind a scanning edge.
    settings.py disables uploads only when the value is literally "false", so we
    derive the *effective* state the same way and compare it to what this domain
    should be (true behind Bunny, false everywhere else)."""
    domain = env_value("DOMAIN").lower()
    behind_edge = domain in UPLOAD_DOMAINS
    expected = "true" if behind_edge else "false"

    raw = env_value("MEDIA_UPLOADS_ENABLED")
    effective = "false" if raw.lower() == "false" else "true"  # mirrors settings.py

    where = domain or "(no DOMAIN — IP-only node)"
    if effective == expected:
        if behind_edge:
            ok(f"MEDIA_UPLOADS_ENABLED={effective} for {where} (uploads accepted behind Bunny Shield)")
        else:
            ok(f"MEDIA_UPLOADS_ENABLED={effective} for {where} (uploads refused — no scanning edge)")
    else:
        fail(
            f"MEDIA_UPLOADS_ENABLED is effectively {effective} for {where}, expected {expected} "
            f"(raw={raw!r}) — fail-closed gate not applied for this node"
        )


def check_video_caps() -> None:
    """30-minute video caps. The migration only bumps nodes still on the old
    default, so a deliberate operator override is a warning (not a failure); the
    OLD default or a missing value means the cap was not applied (failure)."""
    for key, old_default, new_value in VIDEO_CAPS:
        val = env_value(key)
        if not val:
            fail(f"{key} not set (expected {new_value})")
        elif val == new_value:
            ok(f"{key}={val} (30-min video caps applied)")
        elif val == old_default:
            fail(f"{key}={val} is the old default — v1.29.0 cap not applied (expected {new_value})")
        else:
            warn(f"{key}={val} (operator-customized; not the {new_value} default)")


def check_antispam_agent() -> None:
    """AntiSpamBot is a default agent on mirage.talk ONLY. On every other node
    this is a no-op, so we skip with an informational note."""
    domain = env_value("DOMAIN").lower()
    if domain != ANTISPAM_DOMAIN:
        info(f"AntiSpamBot check skipped (domain={domain or '(none)'}; only applies to {ANTISPAM_DOMAIN})")
        return
    agents = [a.strip() for a in env_value("AUTO_ENABLED_AGENTS").split(",") if a.strip()]
    if ANTISPAM_AGENT in agents:
        ok(f"AntiSpamBot present in AUTO_ENABLED_AGENTS ({len(agents)} agent(s) total)")
    else:
        fail(f"AntiSpamBot missing from AUTO_ENABLED_AGENTS on {ANTISPAM_DOMAIN} (got: {agents or 'none'})")


def check_cache_control_no_store() -> None:
    """The dynamic API and chain routes must send Cache-Control: no-store so the
    CDN never serves stale API/RPC responses. Verified from the rendered
    Caddyfile (the source of truth for the header). Expect three: @api,
    /chain/rpc, /chain/rest."""
    if not CADDYFILE.exists():
        fail(f"Caddyfile not found ({CADDYFILE}); cannot verify no-store headers")
        return
    content = CADDYFILE.read_text(errors="ignore")
    n = len(re.findall(r'Cache-Control\s+"no-store"', content))
    if n >= 3:
        ok(f'Caddyfile stamps Cache-Control "no-store" on API + chain routes ({n} directives)')
    elif n > 0:
        warn(f'Caddyfile has only {n} no-store directive(s); expected >=3 (@api, /chain/rpc, /chain/rest)')
    else:
        fail('Caddyfile has no Cache-Control "no-store" on dynamic routes')


def check_trusted_proxies() -> None:
    """The entrypoint runs deploy/refresh_edge_ips.py to emit trusted-proxies.caddy
    so Caddy can recover the real client IP behind the edge. The file must exist
    and carry a trusted_proxies directive regardless of which edge provider."""
    if not TRUSTED_PROXIES.exists():
        fail(f"trusted-proxies.caddy not found ({TRUSTED_PROXIES}); edge IP refresh did not run")
        return
    content = TRUSTED_PROXIES.read_text(errors="ignore")
    if "trusted_proxies" not in content:
        fail("trusted-proxies.caddy present but has no trusted_proxies directive")
        return
    provider = env_value("EDGE_PROVIDER") or "(default/cloudflare)"
    ok(f"trusted-proxies.caddy present with trusted_proxies (EDGE_PROVIDER={provider})")


def check_indexer_freshness(conn: psycopg.Connection) -> None:
    """Post-restart liveness proof: if the chain is producing fresh blocks after
    the rolling restart, the deploy's consensus-neutral changes are executing
    without a fatal mismatch."""
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(height), MAX(block_time) FROM recent_blocks")
        row = cur.fetchone()
    if not row or row[0] is None:
        fail("recent_blocks table is empty (indexer not running?)")
        return
    max_height, max_block_time = row
    ok(f"latest indexed block height={max_height}")
    if max_block_time is None:
        warn("block_time is NULL on latest block")
        return
    try:
        if hasattr(max_block_time, "timestamp"):
            block_ts = max_block_time.timestamp()
        else:
            block_ts = float(max_block_time)
    except Exception as exc:
        warn(f"could not parse block_time: {exc}")
        return
    age_sec = time.time() - block_ts
    if age_sec < 120:
        ok(f"latest block is {age_sec:.0f}s old — chain is live")
    elif age_sec < 600:
        warn(f"latest block is {age_sec:.0f}s old (slightly stale)")
    else:
        fail(
            f"latest block is {age_sec:.0f}s old — chain may have halted "
            f"(check node logs for CONSENSUS_FATAL or panic)"
        )


def check_binary_version() -> None:
    """Cross-check that the shipped frontend version.txt reports the release
    version — a cheap proxy for 'we shipped the correct build'."""
    candidates = [
        Path("/opt/mirage/web/frontend/build/version.txt"),
        Path("/opt/mirage/web/frontend/public/version.txt"),
        Path.cwd() / "web" / "frontend" / "build" / "version.txt",
        Path.cwd() / "web" / "frontend" / "public" / "version.txt",
        Path(__file__).parent.parent / "web" / "frontend" / "build" / "version.txt",
        Path(__file__).parent.parent / "web" / "frontend" / "public" / "version.txt",
    ]
    for p in candidates:
        if not p.exists():
            continue
        actual = p.read_text().strip()
        if actual == RELEASE_VERSION:
            ok(f"version.txt reports {actual} ({p})")
            return
        fail(f"version.txt at {p} reports {actual!r}, expected {RELEASE_VERSION!r}")
        return
    warn("version.txt not found in any known location; skipping frontend version cross-check")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main() -> None:
    global passed, failed, warnings

    print("=" * 60)
    print(f"  Mirage Post-Deploy Verification ({RELEASE_VERSION})")
    print("=" * 60)

    section("1. Environment Variables")
    try:
        backend_db_url = require_env("BACKEND_DB_URL")
        indexer_ro_url = require_env("INDEXER_DB_RO_URL")
        ok("BACKEND_DB_URL is set")
        ok("INDEXER_DB_RO_URL is set")
    except Exception as exc:
        fail(str(exc))
        print("\nFATAL: Missing required environment variables")
        sys.exit(1)

    section("2. Database Connectivity")
    indexer_conn = None
    backend_conn = None
    try:
        backend_conn = psycopg.connect(backend_db_url, autocommit=True)
        ok("Backend DB reachable")
    except Exception as exc:
        fail(f"Backend DB unreachable: {exc}")
    try:
        indexer_conn = psycopg.connect(indexer_ro_url, autocommit=True)
        ok("Indexer DB (RO) reachable")
    except Exception as exc:
        fail(f"Indexer DB (RO) unreachable: {exc}")
    if not indexer_conn or not backend_conn:
        print("\nFATAL: Cannot proceed without database connections")
        sys.exit(1)

    section("3. Media uploads fail-closed gate (per node)")
    check_media_uploads_gate()

    section("4. 30-minute video caps")
    check_video_caps()

    section("5. Default agents (AntiSpamBot on mirage.talk)")
    check_antispam_agent()

    section("6. Edge cache headers (Cache-Control: no-store)")
    check_cache_control_no_store()

    section("7. Edge client-IP trust (trusted-proxies.caddy)")
    check_trusted_proxies()

    section("8. Chain Liveness")
    check_indexer_freshness(indexer_conn)

    section("9. Binary Version Cross-Check")
    check_binary_version()

    if backend_conn:
        backend_conn.close()
    if indexer_conn:
        indexer_conn.close()

    print(f"\n{'=' * 60}")
    total = passed + failed + warnings
    print(f"  Results: {passed} passed, {failed} failed, {warnings} warnings ({total} total)")
    if failed == 0:
        print("  STATUS: ALL CHECKS PASSED")
    else:
        print(f"  STATUS: {failed} FAILURE(S) \u2014 review above")
    print(f"{'=' * 60}\n")
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
