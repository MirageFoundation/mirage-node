#!/usr/bin/env python3
"""
Post-deploy verification for v1.36.0.

Per the /upgrade workflow this file is rewritten every release to check ONLY
what THIS release changes:

  python scripts/verify_upgrade.py
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py

What v1.36.0 changes (deploy-visible)
--------------------------------------
Indexer hardening from the 2026-08-14 security review. No chain code changed, so
every check here is about the deployed indexer rather than about state:

  * Governance event attributes were base64-decoded on a guess. Roughly one
    four-digit proposal ID in nine decodes to something unparseable, which aborts
    the block and re-fails at the same height forever. The fuse is the global
    proposal counter reaching 1400; it was at 108 when this was written.
  * Vote weight was looked up from a fixed set of levels {0, 1, 10, 100} while
    the chain treats any level >= 100 as admin. One governance MsgSetLevel to 101
    plus one ordinary message from that account wedged the indexer identically.
  * A deleted post kept granting its author the topic standing that gates
    downvote weight, so post/self-vote/delete could be banked indefinitely.
  * Startup profile reconciliation would soft-delete every profile if the chain
    reported an empty inventory.

Checks:

  1. Frontend version.txt reports v1.36.0.
  2. Chain binary version reports v1.36.0.
  3. Upgrade handler name v1.36.0 is applied (applied_plan query).
  4. Chain is live and has produced blocks past the upgrade height.
  5. The indexer is advancing. Both wedges this release removes present as a
     stuck indexer, and that is invisible in the chain's own health.
  6. The deployed indexer does not base64-decode event attributes, and reads
     them through the single shared helper.
  7. The deployed indexer resolves admin levels by range, not by a fixed set.
  8. The deployed indexer retracts topic standing when a post is deleted.
  9. The standing-repair migration has been recorded as applied.
 10. No live user holds topic standing sourced only from deleted posts, which
     is the exploit's fingerprint and the migration's job to have removed.

Checks 6 through 10 read deployment artifacts (the deployed indexer source, the
indexer database) that are not reachable from every vantage point. When the
artifact is absent they report NOTE and do not affect the exit code, because a
missing artifact means "not verifiable from here", not "verified". Run both
invocations above for the full set — a run that only prints NOTE for a check has
not performed it.

This script is read-only: it never broadcasts and never writes. Properties that
cannot be observed read-only are proven by tests instead:

  * every fix in this release —
    tests/test_backend.py --category indexer_hardening

  That category is offline (no chain, no transactions) and includes the
  database-backed behavioural checks, which build their own throwaway schema.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# The shipped software version, checked against version.txt and the binary. The
# chain upgrade handler carries the same name this release: nothing here is
# consensus-breaking, but mixed binaries compute different topic standing from
# the same blocks and a node left behind keeps both wedge fuses lit.
RELEASE_VERSION = "v1.36.0"
UPGRADE_NAME = "v1.36.0"
COMET_RPC_URL = "http://127.0.0.1:26657"
REST_URL = "http://127.0.0.1:1317"

# Blocks the chain must have produced after the upgrade height before the
# upgrade counts as "live", not just "applied".
MIN_BLOCKS_AFTER_UPGRADE = 5

# The indexer must gain height across this window. timeout_commit is 3s, so this
# spans several blocks even on a slow host.
INDEXER_PROGRESS_WINDOW_SEC = 10

# Key written by indexer/migrations/v1_36_0_repair_deleted_post_standing.py.
STANDING_MIGRATION_KEY = "v1.36.0_repair_deleted_post_standing"

passed = 0
failed = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  FAIL  {msg}")


def note(msg: str) -> None:
    """Informational only — does not affect the exit code."""
    print(f"  NOTE  {msg}")


def http_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # urllib's message is just the status line; the gRPC-gateway puts the
        # actual reason in the body, which is the only useful part here.
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.read().decode()[:300]}") from None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def deployed_source(relative: str) -> Path | None:
    """The deployed copy of an indexer file, preferring the container path.

    Checks read the deployed tree rather than the repo: a host that did not
    receive the new code is exactly what this script exists to make visible.
    """
    for base in (Path("/opt/mirage"), repo_root()):
        p = base / relative
        if p.is_file():
            return p
    return None


def check_version_txt() -> None:
    candidates = [
        Path("/opt/mirage/web/frontend/build/version.txt"),
        Path("/opt/mirage/web/frontend/public/version.txt"),
        repo_root() / "web" / "frontend" / "public" / "version.txt",
    ]
    for p in candidates:
        if p.is_file():
            ver = p.read_text().strip()
            if ver == RELEASE_VERSION:
                ok(f"version.txt={ver} ({p})")
            else:
                fail(f"version.txt={ver!r} want {RELEASE_VERSION} ({p})")
            return
    fail("version.txt not found")


def check_binary_version() -> None:
    bin_candidates = [
        "/usr/local/bin/miraged",
        "/root/go/bin/miraged",
        str(repo_root() / "blockchain" / "bin" / "miraged"),
        str(repo_root() / "blockchain" / "miraged"),
    ]
    for b in bin_candidates:
        if not os.path.isfile(b):
            continue
        try:
            out = subprocess.check_output([b, "version", "--long"], stderr=subprocess.STDOUT, timeout=10).decode()
        except Exception as e:
            fail(f"miraged version failed ({b}): {e}")
            return
        # Parse the version: line rather than searching the whole output. The
        # long form lists every dependency, and a substring match reports the
        # release as shipped when some module happens to carry that version —
        # github.com/rs/zerolog@v1.35.0 passed this check on a v1.34.0 binary.
        reported = ""
        for line in out.splitlines():
            if line.startswith("version:"):
                reported = line.split(":", 1)[1].strip()
                break
        if not reported:
            fail(f"miraged version --long printed no version: line ({b}): {out.strip()[:200]!r}")
        elif reported.lstrip("v") == RELEASE_VERSION.lstrip("v"):
            ok(f"binary version={reported} ({b})")
        else:
            fail(f"binary version={reported!r} want {RELEASE_VERSION} ({b})")
        return
    fail("miraged binary not found")


def applied_upgrade_height() -> int:
    """Height at which the UPGRADE_NAME plan was applied. Raises if not applied."""
    data = http_json(f"{REST_URL}/cosmos/upgrade/v1beta1/applied_plan/{UPGRADE_NAME}")
    height = int(data.get("height") or data.get("Height") or 0)
    if height <= 0:
        raise RuntimeError(f"upgrade {UPGRADE_NAME} not applied: {data}")
    return height


def check_upgrade_applied() -> None:
    try:
        height = applied_upgrade_height()
    except Exception as e:
        fail(f"applied_plan check failed: {e}")
        return
    ok(f"upgrade {UPGRADE_NAME} applied at height={height}")


def comet_head() -> int:
    return int(http_json(f"{COMET_RPC_URL}/status")["result"]["sync_info"]["latest_block_height"])


def check_chain_live_past_upgrade() -> None:
    try:
        head = comet_head()
    except Exception as e:
        fail(f"comet status failed: {e}")
        return
    if head <= 0:
        fail(f"chain height={head}")
        return

    try:
        upgrade_height = applied_upgrade_height()
    except Exception as e:
        fail(f"chain liveness check: {e}")
        return

    produced = head - upgrade_height
    if produced >= MIN_BLOCKS_AFTER_UPGRADE:
        ok(f"chain live at height={head}, {produced} block(s) after the upgrade height {upgrade_height}")
    else:
        fail(
            f"chain at height={head} has produced only {produced} block(s) since the upgrade height "
            f"{upgrade_height}; want at least {MIN_BLOCKS_AFTER_UPGRADE}"
        )


def indexer_db_url() -> str:
    """INDEXER_DB_URL from the environment, or from the deployed env files.

    `docker exec mirage python3 .../verify_upgrade.py` — the invocation in this
    file's docstring — does not source the env files, so reading them directly is
    what makes the check run instead of reporting NOTE for a solvable reason.
    """
    from_env = os.environ.get("INDEXER_DB_URL", "").strip()
    if from_env:
        return from_env
    env_dir = Path("/root/.mirage/env")
    if not env_dir.is_dir():
        return ""
    for env_file in sorted(env_dir.glob("*.env")):
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("INDEXER_DB_URL="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def check_indexer_advancing() -> None:
    """Both wedges this release removes present as a stuck indexer, and the
    chain's own health says nothing about it: blocks keep being produced while
    the indexer retries one block forever. Sampling twice is what distinguishes
    "behind and catching up" from "stuck", so lag alone is reported, not asserted.
    """
    db_url = indexer_db_url()
    if not db_url:
        note("no INDEXER_DB_URL in the environment or /root/.mirage/env: indexer progress not verifiable from here")
        return
    try:
        import psycopg
    except ImportError:
        note("psycopg unavailable: indexer progress not verifiable from here")
        return

    def _last_height() -> int:
        """Read in its own connection: holding a snapshot across the sleep would
        both risk reading stale data and pin the database's vacuum horizon."""
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM meta WHERE key = 'last_height'")
                row = cur.fetchone()
        if row is None:
            raise RuntimeError("meta.last_height is missing from the indexer database")
        return int(row[0])

    try:
        first = _last_height()
        head = comet_head()
        time.sleep(INDEXER_PROGRESS_WINDOW_SEC)
        second = _last_height()
    except Exception as e:
        fail(f"indexer progress check failed: {e}")
        return

    if second > first:
        ok(f"indexer advancing: {first} -> {second} in {INDEXER_PROGRESS_WINDOW_SEC}s (chain head was {head})")
    else:
        fail(
            f"indexer stuck at height {second} for {INDEXER_PROGRESS_WINDOW_SEC}s while the chain is at {head}; "
            f"check the indexer log for a block it cannot project"
        )


def check_event_attrs_not_decoded() -> None:
    """The base64 guess must be gone from the deployed indexer.

    All four readers of the same event object share one helper now; a host that
    kept its own copy of the old logic is still holding a lit fuse.
    """
    p = deployed_source("indexer/message_processor.py")
    if p is None:
        note("indexer source not present: event attribute decoding not verifiable from here")
        return
    src = p.read_text(encoding="utf-8")
    if "b64decode" in src:
        fail(f"{p} still base64-decodes event attributes; the proposal-ID wedge is live on this host")
        return
    if "def attr_text" not in src:
        fail(f"{p} has no attr_text helper: this host is not running the v1.36.0 indexer")
        return

    main = deployed_source("indexer/main.py")
    if main is None:
        note("indexer/main.py not present: attribute readers not verifiable from here")
        return
    if "attr_text" not in main.read_text(encoding="utf-8"):
        fail(f"{main} does not use attr_text; a reader was left on the old decoding path")
        return
    ok("event attributes are read as text, through one shared helper")


def check_admin_levels_by_range() -> None:
    """Vote weight must resolve any level >= 100, not a fixed set."""
    p = deployed_source("indexer/params.py")
    if p is None:
        note("indexer/params.py not present: admin level handling not verifiable from here")
        return
    src = p.read_text(encoding="utf-8")
    if "def level_to_tier_index" not in src:
        fail(f"{p} has no level_to_tier_index: any admin level other than 100 still wedges this host")
        return

    # Import rather than trust the text: the mapping is the whole fix, and a
    # present-but-wrong function would satisfy a source match.
    sys.path.insert(0, str(p.parent.parent))
    try:
        from indexer.params import level_to_tier_index
    except Exception as e:
        note(f"indexer.params not importable here ({e}); level mapping checked by source only")
        ok("level_to_tier_index is present")
        return

    agent_tier = level_to_tier_index(100)
    bad = [lvl for lvl in (100, 101, 150, 1000) if level_to_tier_index(lvl) != agent_tier]
    if bad:
        fail(f"level(s) {bad} do not resolve to the admin tier {agent_tier}")
    else:
        ok(f"admin levels 100..1000 all resolve to tier {agent_tier}")


def check_delete_retracts_standing() -> None:
    """Deleting a post must withdraw the standing it granted its author."""
    p = deployed_source("indexer/database.py")
    if p is None:
        note("indexer/database.py not present: standing retraction not verifiable from here")
        return
    src = p.read_text(encoding="utf-8")
    missing = [
        marker
        for marker in ("_recompute_topic_stats", "COALESCE(p.deleted, FALSE) AND LOWER(v.owner) = LOWER(p.owner)")
        if marker not in src
    ]
    if missing:
        fail(f"{p} is missing {missing}; deleted posts still buy topic standing on this host")
    else:
        ok("deleted posts no longer grant their author topic standing")


def check_standing_migration_applied() -> None:
    """The repair migration must have run: the fix stops new banking, the
    migration is what removes what was banked before it."""
    db_url = indexer_db_url()
    if not db_url:
        note("no INDEXER_DB_URL: standing repair migration not verifiable from here")
        return
    try:
        import psycopg
    except ImportError:
        note("psycopg unavailable: standing repair migration not verifiable from here")
        return
    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM meta WHERE key = %s", (f"migration_{STANDING_MIGRATION_KEY}",))
                row = cur.fetchone()
    except Exception as e:
        fail(f"standing repair migration check failed: {e}")
        return
    if row:
        ok(f"standing repair migration recorded ({STANDING_MIGRATION_KEY})")
    else:
        fail(
            f"migration {STANDING_MIGRATION_KEY} is not recorded; standing banked before this release "
            f"is still credited on this host"
        )


def check_no_standing_from_deleted_posts() -> None:
    """The exploit's fingerprint, read from data rather than from code.

    An author whose only posts in a topic are deleted must hold no standing there.
    This is what the migration was for, so a row here means the repair did not
    take effect on this host.
    """
    db_url = indexer_db_url()
    if not db_url:
        note("no INDEXER_DB_URL: residual standing not verifiable from here")
        return
    try:
        import psycopg
    except ImportError:
        note("psycopg unavailable: residual standing not verifiable from here")
        return
    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.owner, s.topic, s.net_votes, s.vote_count
                      FROM user_topic_stats s
                     WHERE (s.net_votes <> 0 OR s.vote_count <> 0 OR s.unique_root_posts <> 0)
                       AND NOT EXISTS (
                           SELECT 1 FROM posts p
                            WHERE LOWER(p.owner) = LOWER(s.owner)
                              AND LOWER(COALESCE(p.root_topic, p.topic)) = LOWER(s.topic)
                              AND NOT COALESCE(p.deleted, FALSE)
                       )
                       AND EXISTS (
                           SELECT 1 FROM posts p
                            WHERE LOWER(p.owner) = LOWER(s.owner)
                              AND LOWER(COALESCE(p.root_topic, p.topic)) = LOWER(s.topic)
                              AND COALESCE(p.deleted, FALSE)
                       )
                     LIMIT 5
                    """
                )
                rows = cur.fetchall()
    except Exception as e:
        fail(f"residual standing check failed: {e}")
        return
    if rows:
        fail(f"{len(rows)} owner/topic pair(s) hold standing sourced only from deleted posts, e.g. {rows[0]}")
    else:
        ok("no owner holds topic standing sourced only from deleted posts")


def main() -> int:
    print(f"verify_upgrade.py for {RELEASE_VERSION}")
    check_version_txt()
    check_binary_version()
    check_upgrade_applied()
    check_chain_live_past_upgrade()
    check_indexer_advancing()
    check_event_attrs_not_decoded()
    check_admin_levels_by_range()
    check_delete_retracts_standing()
    check_standing_migration_applied()
    check_no_standing_from_deleted_posts()
    note(
        "the full behaviour of every fix in this release, including the database-level ones, is proven by "
        "tests/test_backend.py --category indexer_hardening (offline; no chain traffic)"
    )
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
