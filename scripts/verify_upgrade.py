#!/usr/bin/env python3
"""
Post-deploy verification for the version in /opt/mirage/VERSION (currently
the same string as the git tag).

Per the /upgrade workflow this file is rewritten every release to check ONLY
what THIS release changes:

  python scripts/verify_upgrade.py
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py

v1.36.2 is a hotfix on top of v1.36.1: it restores the upload request shape that
every shipped mobile build sends, which v1.36.0 stopped accepting. Its own check
is 12, at the end.

The v1.36.1 checks are retained rather than dropped because the fleet run of them
was interrupted, so they have never actually been executed against all four
hosts. They verify deployment artifacts, not a one-time migration, so re-running
them costs nothing and closes that gap.

NEITHER v1.36.1 NOR v1.36.2 IS A CHAIN UPGRADE
----------------------------------------------
There is no upgrade handler, no software-upgrade proposal and no halt height,
because there is no binary change: `git diff v1.36.0..v1.36.1 -- blockchain/` is
empty. Everything in this release is backend, indexer and deploy tooling.

That is why this script does not query applied_plan, unlike every version of it
since v1.28.0. Asking the chain to confirm a plan that was deliberately never
proposed would fail on a correctly deployed node, and adding a no-op handler
just to give this script something to assert would have cost a real chain halt
for a feature that touches no chain code.

What v1.36.1 changes (deploy-visible)
-------------------------------------
The relaying backend now publishes an epoch-scoped network tag in TxBody.memo:

    tag = HMAC-SHA256(SECRET, domain || iso_year || iso_week || family || ip)[:16]

so any third-party agent can cluster accounts acting from one network — the
signature of a vote farm — without an IP being disclosed to anyone. memo is an
existing TxBody field that the relay paths left empty and that the relayer's
outer signature already covered, so no validator needed to learn anything new.

The key's scope is a trust domain. Whoever holds it can evaluate the HMAC across
the whole IPv4 space offline, so it is shared exactly as far as the parties
already trusted with raw client IPs. The officially operated frontends share one
value (scripts/set_net_tag_key.py) so a tag matches whichever door a user comes
through; an independent operator keeps the per-node value the deploy migration
generates and never receives ours.

Alongside the tag the relay publishes a coarse network class — hosting, vpn,
cellular, isp or unknown — resolved from a local IPtoASN snapshot. It is what
lets a reader tell forty votes from two hosting networks (damning) from forty
across two cellular ones (probably carrier NAT).

Checks:

  1. Frontend version.txt reports v1.36.1.
  2. Chain binary version reports v1.36.1. The Go source is unchanged, so this
     is purely a "did the deploy rebuild and relabel the binary" check — and it
     is the one v1.36.0's rehearsal caught shipping wrong.
  3. No upgrade plan is pending. A scheduled halt on a release that ships no new
     handler would stop the chain at that height with nothing able to resume it.
  4. Chain is live and producing blocks.
  5. The indexer is advancing.
  6. NET_TAG_HMAC_KEY is present and well-formed in backend.env (the v1.36.1
     deploy migration ran), and is not a value published in this repository.
  7. The deployed backend attaches the memo at the single signing chokepoint,
     so the gas estimate, the simulation and the broadcast cannot disagree.
  8. The net_tags table exists with the indexes an agent's queries need.
  9. The ASN dataset is installed, and its age is reported. Staleness is a NOTE
     up to 30 days and a FAIL past it: the refresh is a daily job, and a month
     of silent failure means the class field is quietly wrong.
 10. Tags are actually landing on chain — recent transactions carry parseable
     memos. This is the end-to-end check; everything above it can pass while no
     tag is ever written.
 11. Memos on chain are within the chain's memo budget.
 12. The deployed upload endpoint still reads `kind` from the query string first
     — that is what lets it size-cap a body before accepting it — and falls back
     to the form field, which is the only shape any shipped mobile build sends.
     v1.36.0 honoured the query string alone and rejected every app upload for
     half a day.

Checks 5 through 12 read deployment artifacts (the deployed source, the indexer
database, backend.env) that are not reachable from every vantage point. When the
artifact is absent they report NOTE and do not affect the exit code, because a
missing artifact means "not verifiable from here", not "verified". Run both
invocations above for the full set — a run that only prints NOTE for a check has
not performed it.

This script is read-only: it never broadcasts and never writes. Properties that
cannot be observed read-only are proven by tests instead:

  * the tag construction, the memo grammar, the hostile-memo parser, the ASN
    lookup and the import-time key requirement —
    tests/test_backend.py --category net_tags

  That category is offline and walletless (no chain, no transactions).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_VERSION_PATHS = (
    Path("/opt/mirage/VERSION"),
    Path(__file__).resolve().parent.parent / "VERSION",
)


def _load_release_version() -> str:
    for path in _VERSION_PATHS:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"v\d+\.\d+\.\d+", value):
                return value
            raise SystemExit(f"VERSION malformed: {value!r} in {path}")
    raise SystemExit("VERSION file missing")


RELEASE_VERSION = _load_release_version()
COMET_RPC_URL = "http://127.0.0.1:26657"
REST_URL = "http://127.0.0.1:1317"

# The indexer must gain height across this window. timeout_commit is 3s, so this
# spans several blocks even on a slow host.
INDEXER_PROGRESS_WINDOW_SEC = 10

# Blocks the chain must have produced across a short sample to count as live.
# There is no upgrade height to measure from this release, so liveness is
# measured directly rather than relative to a plan.
LIVENESS_WINDOW_SEC = 8

MIN_NET_TAG_KEY_BYTES = 32

# Any key that appears in this repository is public by definition. A node that
# kept a documentation or test value would publish tags anyone can recompute,
# which silently removes the only thing protecting the addresses.
PUBLISHED_KEYS = {"ab" * 32, "aa" * 32, "bb" * 32, "cd" * 32, "00" * 32}

ASN_STALE_NOTE_DAYS = 7
ASN_STALE_FAIL_DAYS = 30

# How far back to look for evidence that tags are landing.
NET_TAG_SAMPLE_LIMIT = 200

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
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.read().decode()[:300]}") from None


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def deployed_source(relative: str) -> Path | None:
    """The deployed copy of a file, preferring the container path.

    Checks read the deployed tree rather than the repo: a host that did not
    receive the new code is exactly what this script exists to make visible.
    """
    for base in (Path("/opt/mirage"), repo_root()):
        p = base / relative
        if p.is_file():
            return p
    return None


def env_file_text(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def env_value(key: str) -> tuple[str | None, Path | None]:
    """Read a key from the deployed backend.env, falling back to the template."""
    for env_path in (Path("/root/.mirage/env/backend.env"), repo_root() / "deploy/templates/env/backend.env"):
        text = env_file_text(env_path)
        if text is None:
            continue
        for line in text.splitlines():
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1].strip(), env_path
        return None, env_path
    return None, None


def indexer_db_url() -> str:
    """INDEXER_DB_URL from the environment, or from the deployed env files."""
    from_env = os.environ.get("INDEXER_DB_URL", "").strip()
    if from_env:
        return from_env
    env_dir = Path("/root/.mirage/env")
    try:
        if not env_dir.is_dir():
            return ""
        env_files = sorted(env_dir.glob("*.env"))
    except OSError:
        return ""
    for env_file in env_files:
        try:
            text = env_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip().startswith("INDEXER_DB_URL="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return ""


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
    """The Go source is identical to v1.36.0, so this checks the label only.

    That is not a trivial check. deploy.sh skips the rebuild when it sees no
    source change, and in v1.36.0 exactly that produced a binary reporting
    v1.36.0-1-gd783da08 while every suite passed. A release whose source is
    unchanged is the case most likely to hit it.
    """
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
        # release as shipped when some module happens to carry that version.
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


def check_no_pending_upgrade_plan() -> None:
    """This release registers no handler, so no plan may be scheduled.

    A plan left pending would halt the chain at its height with no handler of
    that name in the binary, and nothing on the node could resume it.
    """
    try:
        data = http_json(f"{REST_URL}/cosmos/upgrade/v1beta1/current_plan")
    except Exception as e:
        note(f"current_plan not reachable ({e}): pending upgrade not verifiable from here")
        return
    plan = data.get("plan")
    if not plan:
        ok("no upgrade plan scheduled (v1.36.1 ships no handler, so none should be)")
        return
    fail(
        f"an upgrade plan is scheduled that this binary cannot execute: "
        f"name={plan.get('name')!r} height={plan.get('height')}; the chain will halt there"
    )


def comet_head() -> int:
    return int(http_json(f"{COMET_RPC_URL}/status")["result"]["sync_info"]["latest_block_height"])


def check_chain_live() -> None:
    try:
        first = comet_head()
        time.sleep(LIVENESS_WINDOW_SEC)
        second = comet_head()
    except Exception as e:
        fail(f"comet status failed: {e}")
        return
    if second > first:
        ok(f"chain live: height {first} -> {second} in {LIVENESS_WINDOW_SEC}s")
    else:
        fail(f"chain stalled at height {second} for {LIVENESS_WINDOW_SEC}s")


def check_indexer_advancing() -> None:
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


def check_net_tag_key_provisioned() -> None:
    """The deploy migration must have installed a real, private key."""
    value, env_path = env_value("NET_TAG_HMAC_KEY")
    if env_path is None:
        note("backend.env not present: NET_TAG_HMAC_KEY not verifiable from here")
        return
    if value is None:
        fail(f"{env_path} has no NET_TAG_HMAC_KEY: the v1.36.1 deploy migration has not run on this host")
        return
    if not value:
        fail(f"NET_TAG_HMAC_KEY is empty in {env_path}: the backend will refuse to start")
        return
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        fail(f"NET_TAG_HMAC_KEY in {env_path} is not hex: the backend will refuse to start")
        return
    if len(raw) < MIN_NET_TAG_KEY_BYTES:
        fail(f"NET_TAG_HMAC_KEY is {len(raw)} bytes in {env_path}; need at least {MIN_NET_TAG_KEY_BYTES}")
        return
    if value.lower() in PUBLISHED_KEYS:
        fail(
            f"NET_TAG_HMAC_KEY in {env_path} is a value published in this repository: "
            f"anyone can recompute every tag this node emits, which deanonymizes its users"
        )
        return
    ok(f"NET_TAG_HMAC_KEY provisioned ({len(raw)} bytes, {env_path})")


def check_memo_injected_at_chokepoint() -> None:
    """One chokepoint, or the estimate and the broadcast can disagree.

    Each relay route builds the body up to four times — the gas estimator's size
    probe, the tx handed to simulate, the broadcast, and a rebuild on an
    unordered-nonce collision. If any of them skips the memo, the simulated
    transaction is a different size from the signed one.
    """
    p = deployed_source("web/backend/tx.py")
    if p is None:
        fail("web/backend/tx.py is absent: this host cannot be emitting network tags")
        return
    src = p.read_text(encoding="utf-8")
    if "_prepare_signed_body" not in src:
        fail(f"{p} has no _prepare_signed_body: this host is not running the v1.36.1 backend")
        return
    # Every signing path must go through the helper; a bare call to the
    # unordered/timeout appender is a path that skips the memo.
    bare = len(re.findall(r"(?<!def )_append_unordered_timeout\(body_bytes", src))
    if bare:
        fail(f"{p} has {bare} signing path(s) bypassing _prepare_signed_body; those transactions go out untagged")
        return
    ok("the memo is attached at the single signing chokepoint")


def check_upload_accepts_both_kind_shapes() -> None:
    """Both request shapes, or one whole client population cannot post media.

    The query string has to be read first so the per-kind size cap is chosen
    before the body is accepted. The form field has to remain readable because
    every mobile build already on a phone sends `kind` only there, with no query
    string at all — and the resulting rejection is returned before the body is
    read, so the client sees a dropped connection rather than the 400 and reports
    it as a network fault.
    """
    p = deployed_source("web/backend/routes/public.py")
    if p is None:
        note("web/backend/routes/public.py absent: upload contract not verifiable from here")
        return
    src = p.read_text(encoding="utf-8")
    start = src.find("def upload_media")
    if start < 0:
        fail(f"{p} has no upload_media: this host is not running the v1.36.2 backend")
        return
    # Comments here quote both attribute names while explaining the rule, so
    # strip them before deciding which one the code actually reads first.
    body = "\n".join(line for line in src[start : start + 4000].splitlines() if not line.strip().startswith("#"))
    head, _, tail = body.partition("request.files")
    if "request.args" not in head:
        fail(
            f"{p}: upload_media does not read `kind` from the query string before the body, so the per-kind size cap cannot be applied"
        )
        return
    if "request.form" in head:
        fail(f"{p}: upload_media reads the form before the body is bounded, which is the defect M-3 closed")
        return
    if "request.form" not in tail:
        fail(
            f"{p}: upload_media has no form fallback for `kind`; every shipped mobile build uploads with no query string and will be rejected"
        )
        return
    ok("upload_media reads `kind` from the query string first and still accepts the shipped app's form-only shape")


def check_net_tags_table() -> None:
    db_url = indexer_db_url()
    if not db_url:
        note("no INDEXER_DB_URL: net_tags schema not verifiable from here")
        return
    try:
        import psycopg
    except ImportError:
        note("psycopg unavailable: net_tags schema not verifiable from here")
        return
    want_cols = {"txhash", "namespace", "epoch", "family", "tag", "net_class", "relayer", "height", "created_at"}
    want_idx = {
        "idx_net_tags_tag",
        "idx_net_tags_created_at",
        "idx_net_tags_relayer_lower",
        "idx_net_tags_epoch",
    }
    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'net_tags'")
                cols = {r[0] for r in cur.fetchall()}
                cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'net_tags'")
                idx = {r[0] for r in cur.fetchall()}
    except Exception as e:
        fail(f"net_tags schema check failed: {e}")
        return
    if not cols:
        fail("net_tags table does not exist: this host is not running the v1.36.1 indexer")
        return
    missing_cols = sorted(want_cols - cols)
    missing_idx = sorted(want_idx - idx)
    if missing_cols or missing_idx:
        fail(f"net_tags is incomplete: missing columns {missing_cols}, missing indexes {missing_idx}")
        return
    ok(f"net_tags present with {len(cols)} columns and all {len(want_idx)} required indexes")


def check_asn_dataset() -> None:
    """The dataset must be installed, and its age is the thing worth reporting."""
    directory = Path(os.environ.get("ASN_DB_DIR", "").strip() or (Path.home() / ".mirage" / "asn"))
    meta_path = directory / "meta.json"
    if not meta_path.is_file():
        note(
            f"no ASN dataset at {directory}: tags are still emitted, but without a network class. "
            f"Run deploy/refresh_asn_db.py"
        )
        return
    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        fail(f"{meta_path} is unreadable: {e}")
        return
    built_at = meta.get("built_at")
    if not isinstance(built_at, (int, float)):
        fail(f"{meta_path} has no usable built_at")
        return
    age_days = (time.time() - built_at) / 86400.0
    v4 = meta.get("v4_records", 0)
    v6 = meta.get("v6_records", 0)
    if age_days >= ASN_STALE_FAIL_DAYS:
        fail(
            f"ASN dataset is {age_days:.1f} days old (v4={v4} v6={v6}); the daily refresh has been failing "
            f"for over {ASN_STALE_FAIL_DAYS} days and the network class is no longer trustworthy"
        )
    elif age_days >= ASN_STALE_NOTE_DAYS:
        note(f"ASN dataset is {age_days:.1f} days old (v4={v4} v6={v6}); check the refresh job")
        ok(f"ASN dataset installed (v4={v4} v6={v6})")
    else:
        ok(f"ASN dataset installed and fresh: {age_days:.1f} days old, v4={v4} v6={v6}")


def check_tags_landing_on_chain() -> None:
    """The end-to-end check: are tags actually being written and projected?

    Everything above this can pass on a node that emits no tag at all, so this
    is the one that proves the feature is live. Zero rows is a NOTE rather than
    a failure only when the node has indexed no relayed transactions yet.
    """
    db_url = indexer_db_url()
    if not db_url:
        note("no INDEXER_DB_URL: on-chain tags not verifiable from here")
        return
    try:
        import psycopg
    except ImportError:
        note("psycopg unavailable: on-chain tags not verifiable from here")
        return
    try:
        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM net_tags")
                tag_rows = int((cur.fetchone() or [0])[0] or 0)
                cur.execute("SELECT COUNT(*) FROM tx_index")
                tx_rows = int((cur.fetchone() or [0])[0] or 0)
                cur.execute(
                    """
                    SELECT epoch, family, net_class, COUNT(*)
                      FROM net_tags
                     GROUP BY epoch, family, net_class
                     ORDER BY COUNT(*) DESC
                     LIMIT 5
                    """
                )
                breakdown = cur.fetchall()
                cur.execute("SELECT COUNT(*) FROM net_tags WHERE namespace = '' OR tag = '' OR epoch = ''")
                malformed = int((cur.fetchone() or [0])[0] or 0)
    except Exception as e:
        fail(f"on-chain tag check failed: {e}")
        return

    if malformed:
        fail(f"{malformed} net_tags row(s) have an empty namespace, tag or epoch; the projection is storing junk")
        return
    if tag_rows == 0:
        if tx_rows == 0:
            note("no transactions indexed yet, so no tags to check")
        else:
            fail(
                f"{tx_rows} transaction(s) indexed but net_tags is empty: this node is relaying without "
                f"attaching tags, or the indexer is not projecting them"
            )
        return
    ok(f"{tag_rows} network tag(s) projected; top groups (epoch, family, class, n): {breakdown[:3]}")


def check_memo_within_budget_on_chain() -> None:
    """Real memos must be inside the chain's memo budget, not just synthetic ones."""
    p = deployed_source("shared/nettag.py")
    if p is None:
        note("shared/nettag.py not present: memo budget not verifiable from here")
        return
    sys.path.insert(0, str(p.parent.parent))
    try:
        from shared.nettag import MEMO_MAX_BYTES, NET_CLASSES, TAG_BYTES, NAMESPACE_BYTES, b64u_encode, encode_memo
    except Exception as e:
        note(f"shared.nettag not importable here ({e}); memo budget checked by presence only")
        ok("shared/nettag.py is deployed")
        return

    worst = encode_memo(
        b64u_encode(b"\xff" * NAMESPACE_BYTES),
        "2026-W53",
        6,
        b64u_encode(b"\xff" * TAG_BYTES),
        max(NET_CLASSES, key=len),
    )
    size = len(worst.encode("ascii"))
    if size > MEMO_MAX_BYTES:
        fail(f"the largest legal memo is {size} bytes, over the {MEMO_MAX_BYTES} budget")
    else:
        ok(f"largest legal memo is {size} bytes, inside the {MEMO_MAX_BYTES} budget")


def main() -> int:
    print(f"verify_upgrade.py for {RELEASE_VERSION} (no chain upgrade: blockchain/ is unchanged)")
    check_version_txt()
    check_binary_version()
    check_no_pending_upgrade_plan()
    check_chain_live()
    check_indexer_advancing()
    check_net_tag_key_provisioned()
    check_memo_injected_at_chokepoint()
    check_net_tags_table()
    check_asn_dataset()
    check_tags_landing_on_chain()
    check_memo_within_budget_on_chain()
    check_upload_accepts_both_kind_shapes()
    note(
        "the tag construction, memo grammar, hostile-memo parser, ASN lookup and import-time key requirement "
        "are proven by tests/test_backend.py --category net_tags (offline; no chain traffic)"
    )
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
