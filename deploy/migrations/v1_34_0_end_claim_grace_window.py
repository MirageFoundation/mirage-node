"""
Drop LEGACY_UNSIGNED_UNTIL now that /api/rewards/claim always requires a proof.

The grace window let a claim with a missing or unverifiable identity proof be
served so installed mobile builds could keep claiming. v1.34.0 removes that
branch outright — the handler verifies or returns 401 — so the setting no longer
reads anything. settings.py also stops requiring it, and a stale key left in
backend.env would suggest a window that no longer exists.

Idempotent: removing an absent key is a no-op.
"""

from __future__ import annotations

from pathlib import Path

from deploy.migrations._helpers import backup_file, parse_env_file

MIGRATION_KEY = "v1.34.0-end-claim-grace-window"
DESCRIPTION = "Remove LEGACY_UNSIGNED_UNTIL from backend.env; reward claims now always require a signature"


def run(config_dir, logger):
    env_path = Path(config_dir) / "backend.env"
    if not env_path.exists():
        raise RuntimeError("backend.env missing; cannot remove LEGACY_UNSIGNED_UNTIL")

    current = parse_env_file(env_path).get("LEGACY_UNSIGNED_UNTIL", "").strip()
    if not current:
        return "LEGACY_UNSIGNED_UNTIL already absent"

    backup_file(env_path)

    kept = []
    just_removed = False
    for line in env_path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.strip().startswith("LEGACY_UNSIGNED_UNTIL="):
            # The comment block directly above documents the window and would
            # otherwise outlive it. A blank line or another setting stops the
            # walk, so a block above a blank separator is never touched.
            while kept and kept[-1].lstrip().startswith("#"):
                kept.pop()
            just_removed = True
            continue
        if just_removed:
            just_removed = False
            # Both sides of the removed entry had a blank separator; keep one.
            if not line.strip() and kept and not kept[-1].strip():
                continue
        kept.append(line)
    env_path.write_text("".join(kept), encoding="utf-8")

    logger.info(f"  Removed LEGACY_UNSIGNED_UNTIL={current}")
    return f"removed LEGACY_UNSIGNED_UNTIL (was {current})"
