#!/usr/bin/env python3
"""
Post-deploy verification for v1.35.0.

Per the /upgrade workflow this file is rewritten every release to check ONLY
what THIS release changes:

  python scripts/verify_upgrade.py
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py

What v1.35.0 changes (deploy-visible)
-------------------------------------
The availability fix from the 2026-08-13 security review. GetProfile answered an
absent profile with an unclassified error, so no caller could tell "this account
is gone" — a normal state, since a block being projected can predate the
MsgDeleteUser that removed the profile — from "this node is broken". The indexer
took it as the latter, aborted the block, retried the same block forever, and
stopped advancing for every reader on that host. GetProfile now returns the gRPC
NOT_FOUND status and the indexer skips the refresh; every other status still
aborts the block.

Alongside it: the state-sync bootstrap output is parsed instead of eval'd, the
restore path publishes the same host ports as a normal deploy, and the invite
referral payout is confined to registration.

Checks:

  1. Frontend version.txt reports v1.35.0.
  2. Chain binary version reports v1.35.0.
  3. Upgrade handler name v1.35.0 is applied (applied_plan query).
  4. Chain is live and has produced blocks past the upgrade height.
  5. An address with no profile answers 404 (gRPC NOT_FOUND through the
     gateway), not 500. This is the fix, observed on the deployed binary.
  6. An address that does have a profile still answers 200, so check 5 is
     narrow rather than "the query broke".
  7. The indexer is advancing. A wedged indexer is the symptom this release
     exists to remove, and it is invisible in the chain's own health.
  8. The deployed backend confines the invite referral payout to registration.
  9. The running container publishes no Cosmos REST (1317) or gRPC (9090) port.

Checks 7, 8 and 9 read deployment artifacts (the indexer database, the deployed
backend source, the Docker port map) that are not all reachable from every
vantage point: 7 and 8 need the container's filesystem or DB, 9 needs the Docker
CLI on the host. When the artifact is absent they report NOTE and do not affect
the exit code, because a missing artifact means "not verifiable from here", not
"verified". Run both invocations above for the full set — a run that only prints
NOTE for a check has not performed it.

This script is read-only: it never broadcasts. Two properties of this release
cannot be observed read-only and are proven by tests instead:

  * the state-sync bootstrap is parsed and validated, never eval'd —
    tests/test_backend.py --category node_join
  * an unknown message type is logged and skipped instead of halting the
    indexer, and an absent profile skips the refresh without touching the DB —
    tests/test_backend.py --category indexer_profile_absent
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
# chain upgrade handler carries the same name this release: the query change is
# not consensus-breaking, but the plan is what moves the whole fleet across one
# coordinated height so no node is left running the wedging binary.
RELEASE_VERSION = "v1.35.0"
UPGRADE_NAME = "v1.35.0"
COMET_RPC_URL = "http://127.0.0.1:26657"
REST_URL = "http://127.0.0.1:1317"

# Blocks the chain must have produced after the upgrade height before the
# upgrade counts as "live", not just "applied".
MIN_BLOCKS_AFTER_UPGRADE = 5

# An address that is well-formed enough for the query (GetProfile lowercases and
# looks up; it does not parse bech32) and that no account can hold, so the only
# correct answer is NOT_FOUND.
ABSENT_PROFILE_ADDRESS = "mirage1verifyupgradeabsentprofilenobodyholdsthis"

# The indexer must gain height across this window. timeout_commit is 3s, so this
# spans several blocks even on a slow host.
INDEXER_PROGRESS_WINDOW_SEC = 10

# Ports that must never be published to the host: the Cosmos REST and gRPC
# listeners are unauthenticated and belong on loopback behind Caddy.
FORBIDDEN_HOST_PORTS = ("1317", "9090")

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


def http_status(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Return (status, body) without raising for an error status.

    The status code is the subject of check 5, so it has to be observable
    instead of being folded into an exception.
    """
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


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


def check_absent_profile_is_not_found() -> None:
    """The fix itself, observed on the deployed binary.

    404 is how the gRPC gateway renders NOT_FOUND. Before this release the same
    query produced a 500, which is what the indexer could not tell apart from a
    node fault.
    """
    status, body = http_status(f"{REST_URL}/mirage/core/v1/profile/{ABSENT_PROFILE_ADDRESS}")
    if status == 404:
        ok(f"absent profile answers 404 NOT_FOUND ({ABSENT_PROFILE_ADDRESS})")
    elif status == 200:
        fail(f"absent profile answered 200; {ABSENT_PROFILE_ADDRESS} should hold no profile: {body}")
    else:
        fail(
            f"absent profile answered HTTP {status}, want 404 NOT_FOUND — this node still cannot tell a "
            f"deleted account apart from a node fault, and its indexer will wedge on the next deletion: {body}"
        )


def check_present_profile_is_served() -> None:
    """Control for the check above: profiles that exist must still be served."""
    try:
        listing = http_json(f"{REST_URL}/mirage/core/v1/profiles?pagination.limit=1")
    except Exception as e:
        fail(f"profiles listing failed: {e}")
        return

    profiles = listing.get("profiles") or []
    if not profiles:
        note("chain has no profiles yet: the positive profile query is not verifiable from here")
        return

    owner = str(profiles[0].get("owner") or "").strip()
    if not owner:
        fail(f"profiles listing returned an entry with no owner: {profiles[0]}")
        return

    status, body = http_status(f"{REST_URL}/mirage/core/v1/profile/{owner}")
    if status == 200:
        ok(f"existing profile still answers 200 ({owner})")
    else:
        fail(f"existing profile {owner} answered HTTP {status}, want 200: {body}")


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
    """A wedged indexer is the failure this release removes, and the chain's own
    health says nothing about it: blocks keep being produced while the indexer
    retries one block forever. Sampling twice is what distinguishes "behind and
    catching up" from "stuck", so lag alone is reported, not asserted.
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


def check_referral_payout_guarded() -> None:
    """The deployed backend, not the repo: this release is also the one that
    stopped the invite referral reward from being re-paid on a later username
    change, and a host that did not receive the new code keeps paying.
    """
    candidates = [
        Path("/opt/mirage/web/backend/routes/core.py"),
        repo_root() / "web" / "backend" / "routes" / "core.py",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        src = p.read_text(encoding="utf-8")
        if "_process_invite_quest_completion" not in src:
            fail(f"{p} no longer calls _process_invite_quest_completion")
            return
        if "if is_new_user and code == 0:" in src:
            ok(f"invite referral payout is confined to registration ({p})")
        else:
            fail(
                f"{p} calls _process_invite_quest_completion without the registration guard; "
                f"a username change re-pays the referral reward"
            )
        return
    note("backend source not present: referral payout guard not verifiable from here")


def check_no_forbidden_host_ports() -> None:
    """The restore path used to publish 1317 and 9090, so a host that had been
    rebuilt from backup served unauthenticated REST and gRPC to the internet.
    Read the live port map rather than the script that wrote it.
    """
    try:
        out = subprocess.check_output(
            ["docker", "port", "mirage"], stderr=subprocess.STDOUT, timeout=15
        ).decode()
    except FileNotFoundError:
        note("docker CLI unavailable (this is the in-container invocation): host port map not verifiable from here")
        return
    except Exception as e:
        fail(f"docker port mirage failed: {e}")
        return

    published = [line.strip() for line in out.splitlines() if line.strip()]
    offending = [line for line in published if any(line.startswith(f"{p}/") for p in FORBIDDEN_HOST_PORTS)]
    if offending:
        fail(f"container publishes {offending}; Cosmos REST and gRPC must stay on loopback behind Caddy")
    else:
        ok(f"container publishes no REST/gRPC port ({len(published)} mapping(s))")


def main() -> int:
    print(f"verify_upgrade.py for {RELEASE_VERSION}")
    check_version_txt()
    check_binary_version()
    check_upgrade_applied()
    check_chain_live_past_upgrade()
    check_absent_profile_is_not_found()
    check_present_profile_is_served()
    check_indexer_advancing()
    check_referral_payout_guarded()
    check_no_forbidden_host_ports()
    note(
        "the state-sync bootstrap parser (never eval, validated values) is proven by "
        "tests/test_backend.py --category node_join; the indexer's skip-and-log behaviour for absent "
        "profiles and unknown message types by tests/test_backend.py --category indexer_profile_absent"
    )
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
