"""Shared test infrastructure for backend and blockchain suites."""

from __future__ import annotations

import argparse
import base64
import contextvars
import hashlib
import json
import math
import os
import queue
import random
import socket
import string
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional, Tuple

import requests
from cosmpy.crypto.keypairs import PrivateKey
from cosmpy.aerial.wallet import LocalWallet

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.client import (  # noqa: E402
    get_status,
    get_user_status,
    get_username_from_address,
    get_address_from_username,
    sign_canonical,
    compute_pow,
    check_pow_target,
    _difficulty_factor,
    _BASE_DIFFICULTY_FACTOR,
    _request_with_retries,
)
from shared.canon import (  # noqa: E402
    canon_base_award as _canon_base_award_raw,
    canon_base_post as _canon_base_post_raw,
    canon_base_vote as _canon_base_vote_raw,
    canon_base_edit as _canon_base_edit_raw,
    canon_base_delete as _canon_base_delete_raw,
    canon_base_delete_user as _canon_base_delete_user_raw,
    canon_base_set_username as _canon_base_set_username_raw,
    canon_base_follow_user as _canon_base_follow_user_raw,
    canon_base_unfollow_user as _canon_base_unfollow_user_raw,
    canon_base_follow_topic as _canon_base_follow_topic_raw,
    canon_base_unfollow_topic as _canon_base_unfollow_topic_raw,
    canon_base_enable_agent as _canon_base_enable_agent_raw,
    canon_base_disable_agent as _canon_base_disable_agent_raw,
    canon_base_set_agents as _canon_base_set_agents_raw,
    canon_base_block_post as _canon_base_block_post_raw,
    canon_base_unblock_post as _canon_base_unblock_post_raw,
    canon_base_block_user as _canon_base_block_user_raw,
    canon_base_unblock_user as _canon_base_unblock_user_raw,
    canon_base_block_topic as _canon_base_block_topic_raw,
    canon_base_unblock_topic as _canon_base_unblock_topic_raw,
    canon_base_send_tokens as _canon_base_send_tokens_raw,
    canon_base_subscribe as _canon_base_subscribe_raw,
    canon_base_report as _canon_base_report_raw,
    canon_base_set_auto_renewal as _canon_base_set_auto_renewal_raw,
    canon_base_set_biography as _canon_base_set_biography_raw,
    canon_base_annotate as _canon_base_annotate_raw,
    canon_base_join_community as _canon_base_join_community_raw,
    canon_base_leave_community as _canon_base_leave_community_raw,
    canon_base_block_community as _canon_base_block_community_raw,
    canon_base_unblock_community as _canon_base_unblock_community_raw,
    canon_signed_with_pow,
)

DEFAULT_BACKEND = "http://127.0.0.1:80"
INDEX_TIMEOUT_SEC = 45.0

# Backend URL the running suite was invoked with. run_suite() sets this so
# helpers reached from deep inside a message builder (which never receives the
# URL as an argument) can still make backend calls.
SUITE_BACKEND: str = DEFAULT_BACKEND

# Wallet pool. Categories run concurrently, so one set of five wallets cannot be
# shared: two categories following, blocking and then asserting on sub1 at the
# same time would fail on each other's writes. The pool holds N identical sets
# and each running category leases one for its whole run.
WALLET_ROLES = ("free", "sub1", "sub2", "agent1", "agent2")

# Every set is funded identically, so this stays one global and the case files
# that import it need no change.
FAUCET_AMOUNTS: dict[str, int] = {}

# test_upgrade.sh launches the blockchain and backend suites concurrently, so a
# second suite is provisioning from this same faucet while this one checks it.
_FAUCET_RESERVE_SUITES = 2

_WALLET_SETS: list[dict[str, LocalWallet]] = []


@dataclass
class _TestContext:
    """Which category this thread is running, and which wallet set it holds."""

    category: str
    wallet_set: Optional[int]


_TEST_CTX: contextvars.ContextVar[Optional[_TestContext]] = contextvars.ContextVar("mirage_test_ctx", default=None)


class _WalletView:
    """`WALLETS` as seen by a running category: its own leased set.

    Case files bind this object once (`from tests.common import WALLETS`), so
    every `WALLETS["sub1"]` resolves through the lease with no edit at the call
    site.
    """

    def _set(self) -> dict[str, LocalWallet]:
        ctx = _TEST_CTX.get()
        if ctx is None or ctx.wallet_set is None:
            raise RuntimeError(
                "WALLETS accessed with no wallet lease bound. Either the category "
                "is listed in WALLETLESS_CATEGORIES but uses wallets, or a thread "
                "it spawned was not started through tests.common.parallel_map() "
                "and so did not inherit the lease."
            )
        return _WALLET_SETS[ctx.wallet_set]

    def __getitem__(self, role: str) -> LocalWallet:
        return self._set()[role]

    def get(self, role: str, default=None):
        return self._set().get(role, default)

    def items(self):
        return self._set().items()

    def values(self):
        return self._set().values()

    def keys(self):
        return self._set().keys()

    def __iter__(self):
        return iter(self._set())

    def __contains__(self, role: object) -> bool:
        return role in self._set()

    def __len__(self) -> int:
        return len(self._set())

    def __repr__(self) -> str:
        ctx = _TEST_CTX.get()
        return f"<WALLETS set={'unbound' if ctx is None else ctx.wallet_set}>"


WALLETS = _WalletView()


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    name: str
    status: str  # "pass" | "fail" | "skip"
    status_code: Optional[int] = None
    error: Optional[str] = None
    details: dict = field(default_factory=dict)
    category: Optional[str] = None

    @property
    def passed(self) -> bool:
        """A skip is not a pass. Counting it as one hid real gaps (backend L-6)."""
        return self.status == "pass"


RESULTS: list[TestResult] = []
_RESULTS_LOCK = threading.Lock()

def _current_category() -> Optional[str]:
    """Category of the test recording this result.

    Carried on the context rather than keyed by thread id: a thread spawned by a
    test inherits it through parallel_map(). Guessing it from a single running
    category used to work only while one category ran at a time, and an
    unattributed skip escapes the release gate in summarize().
    """
    ctx = _TEST_CTX.get()
    return None if ctx is None else ctx.category


_COLOR_GREEN = "\033[92m"
_COLOR_RED = "\033[91m"
_COLOR_YELLOW = "\033[93m"
_COLOR_RESET = "\033[0m"
_COLOR_BOLD = "\033[1m"


def _pass(name: str, **details) -> TestResult:
    r = TestResult(name=name, status="pass", details=details, category=_current_category())
    with _RESULTS_LOCK:
        RESULTS.append(r)
    print(f"  {_COLOR_GREEN}PASS{_COLOR_RESET}  {name}")
    return r


def _fail(name: str, error: str = "", **details) -> TestResult:
    r = TestResult(name=name, status="fail", error=error, details=details, category=_current_category())
    with _RESULTS_LOCK:
        RESULTS.append(r)
    err = f" — {error}" if error else ""
    print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {name}{err}")
    return r


def _skip(name: str, reason: str = "", **details) -> TestResult:
    r = TestResult(
        name=name,
        status="skip",
        error=reason,
        details={"skipped": True, **details},
        category=_current_category(),
    )
    with _RESULTS_LOCK:
        RESULTS.append(r)
    err = f" — {reason}" if reason else ""
    print(f"  {_COLOR_YELLOW}SKIP{_COLOR_RESET}  {name}{err}")
    return r


def _debug(msg: str) -> None:
    print(f"  {_COLOR_YELLOW}debug{_COLOR_RESET} {msg}")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fresh_nonce() -> int:
    return int(time.time_ns()) ^ random.getrandbits(32)


def _lb_bytes(lb_hex: str) -> bytes:
    try:
        return bytes.fromhex(lb_hex.strip())
    except Exception:
        return lb_hex.encode()


def _get(url: str, params: dict | None = None) -> Tuple[int, dict]:
    max_retries = 7
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params or {}, timeout=10)
        except requests.RequestException as e:
            if attempt >= max_retries:
                raise
            delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry GET {url} err={type(e).__name__} attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue

        if r.status_code in (429, 502, 503, 504) and attempt < max_retries:
            retry_after = r.headers.get("Retry-After")
            try:
                delay = min(5.0, float(retry_after)) if retry_after else min(5.0, 0.25 * (2 ** (attempt - 1)))
            except Exception:
                delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry GET {url} status={r.status_code} attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue

        if r.status_code == 500 and attempt < max_retries:
            try:
                body = r.json()
            except Exception:
                body = None
            if body and ("error" in body or "raw_log" in body or "message" in body):
                return r.status_code, body
            delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry GET {url} status=500 attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue

        try:
            body = r.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            body.setdefault("_http_status", r.status_code)
        return r.status_code, body

    return 599, {}


def _post(url: str, payload: dict) -> Tuple[int, dict]:
    max_retries = 7
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=20)
        except requests.RequestException as e:
            if attempt >= max_retries:
                raise
            delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry POST {url} err={type(e).__name__} attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue

        if r.status_code in (429, 502, 503, 504) and attempt < max_retries:
            retry_after = r.headers.get("Retry-After")
            try:
                delay = min(5.0, float(retry_after)) if retry_after else min(5.0, 0.25 * (2 ** (attempt - 1)))
            except Exception:
                delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry POST {url} status={r.status_code} attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue

        if r.status_code == 500 and attempt < max_retries:
            try:
                body = r.json()
            except Exception:
                body = None
            if body and ("error" in body or "raw_log" in body or "message" in body):
                return r.status_code, body
            delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry POST {url} status=500 attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue

        try:
            body = r.json()
        except Exception:
            body = {}
        if isinstance(body, dict):
            body.setdefault("_http_status", r.status_code)
        return r.status_code, body

    return 599, {}


def _post_multipart(url: str, data: dict, files: Optional[dict] = None):
    """POST multipart/form-data, retrying edge throttling the way _post does.

    Uploads cannot use _post (it sends JSON), and the Caddy edge rate limiter
    answers a burst of uploads with 429 before the request reaches the backend.
    Returns the raw Response so callers can read status and body.
    """
    max_retries = 7
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(url, data=data, files=files, timeout=30)
        except requests.RequestException as e:
            # Transport faults are retried on the same budget as the throttling
            # above, matching shared/client.py. Without this a momentary resolver
            # or socket failure raised straight out of the caller and took every
            # remaining assertion in the test function with it, reported as one
            # UNEXPECTED_ERROR — which reads like a broken endpoint rather than a
            # blip. `files` here holds bytes, not handles, so a retry re-sends the
            # same body. Exhausting the budget still raises.
            if attempt >= max_retries:
                raise
            delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry upload {url} error={type(e).__name__} attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue
        if r.status_code in (429, 502, 503, 504) and attempt < max_retries:
            retry_after = r.headers.get("Retry-After")
            try:
                delay = min(5.0, float(retry_after)) if retry_after else min(5.0, 0.25 * (2 ** (attempt - 1)))
            except Exception:
                delay = min(5.0, 0.25 * (2 ** (attempt - 1)))
            _debug(f"retry upload {url} status={r.status_code} attempt={attempt}/{max_retries} sleep={delay:.2f}s")
            time.sleep(delay)
            continue
        return r

    return r


def _expect_http_error(label: str, resp: dict, status: int, contains: str | None = None) -> None:
    http_status = int(resp.get("_http_status", 0) or 0)
    err = str(resp.get("error", "")).lower()
    if http_status != status:
        _fail(label, f"expected http={status}, got http={http_status} error={err!r} resp={resp}")
        return
    if contains and contains.lower() not in err:
        _fail(label, f"expected error~={contains!r}, got error={err!r} resp={resp}")
        return
    _pass(label)


# ---------------------------------------------------------------------------
# Local Docker testnet helpers
# ---------------------------------------------------------------------------

# Test code must execute inside the local testnet container. Host-side
# docker-exec fallback made it too easy to bypass the required environment and
# accidentally run a transaction-heavy suite from the wrong execution surface.
_INSIDE_CONTAINER = os.path.isfile("/.dockerenv")


def _docker_exec(cmd: str, timeout: int = 30) -> Tuple[int, str]:
    """Run a command inside the local testnet container."""
    if not _INSIDE_CONTAINER:
        raise RuntimeError(
            "test helpers cannot run outside the local Docker container; "
            "use docker exec mirage bash -lc 'cd /opt/mirage && ...'"
        )
    argv = ["bash", "-lc", cmd]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    out = result.stdout.strip()
    if result.returncode != 0 and not out:
        out = result.stderr.strip()
    return result.returncode, out


# Load the node's own env the way the services see it. `docker exec` starts a
# fresh shell that does not inherit the Supervisor children's environment.
_LOAD_NODE_ENV = "set -a; for f in /root/.mirage/env/*.env; do . $f; done; set +a"


def container_env(key: str) -> str:
    """Value of an env var as the node's services see it, or "" if unset."""
    value = os.environ.get(key, "").strip()
    if value or not _check_local_docker():
        return value
    rc, out = _docker_exec(f"printenv {key}")
    if rc == 0 and out.strip():
        return out.strip()
    rc, out = _docker_exec(f"{_LOAD_NODE_ENV}; printenv {key}")
    return out.strip() if rc == 0 else ""


def resolve_db_name(env_key: str) -> str:
    """Database name behind a `*_DB_URL`, or "" when it cannot be resolved."""
    url = container_env(env_key)
    if not url:
        return ""
    from urllib.parse import urlparse

    return urlparse(url).path.lstrip("/")


def docker_python(code: str, mutation: str = "", timeout: int = 60) -> Tuple[int, str]:
    """Run Python against the deployed backend with the node's env loaded.

    Backend modules read required settings at import, so they are only
    importable where that env exists. ENV_DIR is cleared so a probe can never
    persist a value back into backend.env. Output ends with `rc=<exit code>`.
    """
    steps = f"cd /opt/mirage/web/backend; {_LOAD_NODE_ENV}"
    if mutation:
        steps += f"; {mutation}"
    return _docker_exec(
        f'{steps}; ENV_DIR= PYTHONPATH=/opt/mirage python3 -c "{code}" 2>&1; echo rc=$?',
        timeout=timeout,
    )


def docker_import_probe(module: str, mutation: str = "", timeout: int = 60) -> Tuple[int, str]:
    """Prove a module's import-time settings check fires under `mutation`."""
    return docker_python(f"import {module}", mutation=mutation, timeout=timeout)


def _run_miraged(args: list, timeout: int = 30) -> Tuple[int, str]:
    """Run miraged with an explicit argument vector — no shell involved.

    This avoids all bash login-shell issues (profile scripts polluting
    stdout, environment variables being stripped, argument re-parsing).
    Returns (exit_code, stdout).  Stderr is only appended on failure
    so JSON output on stdout stays clean.
    """
    if not _INSIDE_CONTAINER:
        raise RuntimeError("miraged test commands require the local Docker container")
    miraged = _miraged_cmd()
    argv = [miraged] + list(args)
    # Inherit parent environment; ensure HOME is set for keyring access
    env = os.environ.copy()
    env["HOME"] = "/root"
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    out = result.stdout.strip()
    if result.returncode != 0 and not out:
        out = result.stderr.strip()
    return result.returncode, out


def _miraged_cmd() -> str:
    """Return the miraged binary path inside the container."""
    if not _INSIDE_CONTAINER:
        raise RuntimeError("miraged test commands require the local Docker container")
    preferred = "/opt/mirage/blockchain/miraged"
    fallback = "/opt/mirage/blockchain/bin/miraged"
    if os.path.isfile(preferred) and os.access(preferred, os.X_OK):
        return preferred
    if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
        return fallback
    return preferred


# Detect keyring backend from client.toml (os vs test).
_KEYRING_BACKEND: Optional[str] = None


def _keyring_backend() -> str:
    """Return the keyring-backend configured in client.toml."""
    global _KEYRING_BACKEND
    if _KEYRING_BACKEND is None:
        val = ""
        client_toml = "/root/.mirage/node/config/client.toml"
        if _INSIDE_CONTAINER:
            try:
                with open(client_toml, "r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if s.startswith("keyring-backend"):
                            parts = s.split("=", 1)
                            if len(parts) == 2:
                                val = parts[1].strip().strip('"').strip("'")
                                break
            except Exception:
                val = ""
        else:
            code, out = _docker_exec(f"cat {client_toml} 2>/dev/null || true")
            text = out or ""
            for line in text.splitlines():
                s = line.strip()
                if s.startswith("keyring-backend"):
                    parts = s.split("=", 1)
                    if len(parts) == 2:
                        val = parts[1].strip().strip('"').strip("'")
                        break
        _KEYRING_BACKEND = val if val else "test"
    return _KEYRING_BACKEND


def _generate_wallet() -> LocalWallet:
    """Generate a fresh random wallet."""
    return LocalWallet(PrivateKey(), prefix="mirage")


def _check_local_docker() -> bool:
    """Verify this process is inside the local testnet container."""
    return _INSIDE_CONTAINER and socket.gethostname().strip().lower() == "testnet"


# Params the transaction-heavy suites need raised, and the proposal that raises
# each. A suite runs hundreds of transactions from a handful of wallets, so both
# the PoW difficulty ramp and a subscriber's daily relay quota are spent far
# faster than any real user would spend them.
_REQUIRED_TEST_LIMITS = {
    "pow_message_limit": (9_999_999, "scripts/proposals/proposal_set_pow_message_limit_9999999.json"),
    "subscriber_daily_relay_limit": (
        10_000,
        "scripts/proposals/proposal_set_subscriber_daily_relay_limit_10000.json",
    ),
}


def _check_test_pow_limit() -> tuple[bool, str]:
    """Require the local anti-spam limits used by the transaction-heavy suites."""
    code, out = _run_miraged(
        ["q", "core", "params", "--home", "/root/.mirage/node", "--output", "json"],
        timeout=15,
    )
    if code != 0:
        return False, f"params query failed: {out[:200]}"
    try:
        json_start = out.find("{")
        if json_start < 0:
            raise ValueError("no JSON object in output")
        params = json.loads(out[json_start:])
    except Exception as exc:
        return False, f"params query returned invalid JSON: {exc}"
    for name, (want, proposal) in _REQUIRED_TEST_LIMITS.items():
        try:
            value = int(params[name])
        except (KeyError, TypeError, ValueError):
            return False, f"{name} missing or invalid: {str(params)[:200]}"
        if value != want:
            return False, f"{name}={value}, expected {want} (submit {proposal})"
    return True, ""


_VALIDATOR_KEY_ADDR: Optional[str] = None


def _resolve_validator_key_addr() -> str:
    """Resolve the validator key address from the node keyring (cached)."""
    global _VALIDATOR_KEY_ADDR
    if _VALIDATOR_KEY_ADDR:
        return _VALIDATOR_KEY_ADDR
    kb = _keyring_backend()
    code, out = _run_miraged(
        ["keys", "list", "--home", "/root/.mirage/node", "--keyring-backend", kb, "--output", "json"],
        timeout=10,
    )
    if code != 0 or not out:
        raise RuntimeError(f"keys list failed: exit={code} out={out[:200]}")
    # miraged may print log lines before/after the JSON array.
    idx = out.find("[")
    if idx < 0:
        raise RuntimeError(f"keys list: no JSON array in output: {out[:200]}")
    keys = json.loads(out[idx:])
    if not keys:
        raise RuntimeError("keys list returned empty array")
    for key in keys:
        if key.get("name") == "validator":
            addr = str(key.get("address", "")).strip()
            if not addr:
                raise RuntimeError(f"keys list: validator key has no address: {key}")
            _debug(f"validator key address: {addr}")
            _VALIDATOR_KEY_ADDR = addr
            return addr
    names = [str(k.get("name", "")) for k in keys]
    raise RuntimeError(f"keys list: validator key not found (names={names})")


def _get_spendable_balance(address: str) -> int:
    """Return spendable umirage balance for an address via CLI."""
    code, out = _run_miraged(
        [
            "q",
            "bank",
            "spendable-balances",
            address,
            "--home",
            "/root/.mirage/node",
            "--node",
            "tcp://127.0.0.1:26657",
            "-o",
            "json",
        ],
        timeout=10,
    )
    if code != 0 or not out:
        raise RuntimeError(f"spendable-balances failed: exit={code} out={out[:200]}")
    data = json.loads(out[out.index("{") :])
    for b in data.get("balances", []):
        if b.get("denom") == "umirage":
            return int(b.get("amount", 0) or 0)
    return 0


def _faucet(backend: str, address: str, amount: int = 500_000_000) -> bool:
    """Send tokens from the validator to an address via CLI.

    Uses the chain's bank module directly (no relay/PoW needed).
    Default: 500 MIRAGE (500_000_000 umirage).

    The transaction is unordered. scripts/test_upgrade.sh funds the blockchain
    and backend suites from this one validator account at the same time, and an
    ordered transaction has to guess the account sequence: two concurrent
    senders read the same sequence, one of them commits, and the other is
    rejected with "expected N, got N-1" until it gives up and aborts wallet
    setup. Retrying cannot fix that — the sibling suite keeps taking the next
    sequence. An unordered transaction carries no sequence at all.
    """
    kb = _keyring_backend()

    try:
        from_addr = _resolve_validator_key_addr()
    except RuntimeError as e:
        print(f"    [faucet] cannot resolve validator key address: {e}")
        return False

    if not from_addr or not from_addr.startswith("mirage1"):
        print(f"    [faucet] bad validator address: {from_addr!r}")
        return False

    send_args = [
        "tx",
        "bank",
        "send",
        from_addr,
        address,
        f"{amount}umirage",
        "--home",
        "/root/.mirage/node",
        "--keyring-backend",
        kb,
        "--chain-id",
        "mirage-1",
        "--yes",
        "--gas",
        "auto",
        "--gas-adjustment",
        "1.5",
        "--gas-prices",
        "1000umirage",
        "--unordered",
        "--timeout-duration",
        "90s",
        "-o",
        "json",
    ]

    code, out = _run_miraged(send_args, timeout=30)
    if code != 0:
        # Show the FATAL/error line (usually at the end), not the Usage block
        lines = out.strip().splitlines()
        fatal = next(
            (l for l in reversed(lines) if "FATAL" in l or "insufficient" in l.lower() or "error" in l.lower()),
            None,
        )
        if fatal:
            import re

            def _umirage_to_mirage(m: re.Match) -> str:
                return f"{int(m.group(1)) / 1_000_000:,.0f} MIRAGE"

            msg = re.sub(r"(\d+)umirage", _umirage_to_mirage, fatal.strip())
            print(f"    [faucet] {msg}")
        else:
            last = lines[-1].strip() if lines else out[:200]
            print(f"    [faucet] exit code {code}: {last}")
        return False
    # Check the on-chain response code (broadcast succeeds with exit 0 even if tx fails)
    try:
        # miraged may print log/gas-estimate lines before the JSON object
        json_start = out.rfind("{")
        if json_start < 0:
            raise ValueError("no JSON object in output")
        resp = json.loads(out[json_start:])
        tx_code = int(resp.get("code", 1))
        tx_hash = resp.get("txhash", "")
        raw_log = resp.get("raw_log", "") or ""
        if tx_code != 0:
            print(f"    [faucet] tx failed code={tx_code}: {raw_log[:200]}")
            return False
    except Exception as e:
        print(f"    [faucet] failed to parse response: {e}\n    output: {out[:300]}")
        return False
    # Wait for tx to be committed by polling the recipient's balance
    # (tx_index is disabled, so we cannot look up by hash)
    if tx_hash:
        bal_args = [
            "q",
            "bank",
            "balances",
            address,
            "--home",
            "/root/.mirage/node",
            "--node",
            "tcp://127.0.0.1:26657",
            "-o",
            "json",
        ]
        for _ in range(15):
            time.sleep(1)
            qcode, qout = _run_miraged(bal_args, timeout=10)
            if qcode == 0 and qout:
                try:
                    json_str = qout[qout.index("{") :]
                    bal_resp = json.loads(json_str)
                    for coin in bal_resp.get("balances", []):
                        if coin.get("denom") == "umirage" and int(coin.get("amount", 0)) >= amount:
                            return True
                except (json.JSONDecodeError, ValueError):
                    pass
        print(f"    [faucet] tx {tx_hash[:16]} not confirmed after 15s (balance never reached {amount}umirage)")
    return False


def _do_subscribe(backend: str, wallet: LocalWallet, level: int, target: str = "") -> dict:
    """Subscribe a wallet to the given level (1=Subscriber, 10=Agent), optionally gifting to target."""
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = str(st.get("last_block_hash", ""))
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()

    # subscribe: difficulty=0, proof=0 (no PoW)
    base = _canon_base_subscribe_raw(pub, _lb_bytes(lb), 0, ts, level, target=target, nonce=nonce)
    signed = canon_signed_with_pow(base, 0)
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "level": level,
        "period_count": 1,
    }
    if target:
        payload["target"] = target
    code, resp = _post(f"{backend}/api/core/subscribe", payload)
    return resp


def _required_sub1_spend_budget_umirage(backend: str) -> int:
    """Compute extra funding needed for sub1 from live chain config.

    Includes explicit spends used by this suite:
    - post award: quality_post
    - comment award: receipts
    - token send happy path: 1000 umirage
    - gift subscription to sub2: one period_fee for level 1
    """
    code, cfg = _get(f"{backend}/api/get_chain_config")
    if code != 200 or not isinstance(cfg, dict):
        raise RuntimeError(f"get_chain_config failed (code={code})")

    award_cfgs = cfg.get("award_configs")
    if not isinstance(award_cfgs, list) or not award_cfgs:
        raise RuntimeError("award_configs missing or empty in chain config")

    costs: dict[str, int] = {}
    for entry in award_cfgs:
        if not isinstance(entry, dict):
            raise RuntimeError("invalid award_configs entry type")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise RuntimeError("award_configs entry missing name")
        try:
            costs[name] = int(entry.get("cost", 0) or 0)
        except Exception as e:
            raise RuntimeError(f"invalid cost for award '{name}': {e}") from e

    required_awards = ("quality_post", "receipts")
    missing = [name for name in required_awards if name not in costs]
    if missing:
        raise RuntimeError(f"required award types missing from chain config: {missing}")

    gift_fee = int(cfg.get("subscription_period_fee", 0) or 0)
    if gift_fee <= 0:
        tiers = cfg.get("tiers") or []
        if isinstance(tiers, list) and len(tiers) > 1:
            gift_fee = int((tiers[1] or {}).get("period_fee", 0) or 0)
    if gift_fee <= 0:
        gift_fee = 100_000_000_000

    token_send_amount = 1000  # test_tokens.happy_path
    indexer_transfer_test = 1  # test_backend_indexer.balance_after_transfer
    # Fee buffer: sub1 sends many txs across backend tests (posts/votes/etc).
    fee_buffer = 25_000_000_000  # 25k MIRAGE in umirage
    return (
        int(costs["quality_post"])
        + int(costs["receipts"])
        + token_send_amount
        + indexer_transfer_test
        + gift_fee
        + fee_buffer
    )


def _wallet_label(set_idx: int, role: str) -> str:
    return f"s{set_idx}/{role}"


def _wallet_entries() -> list[tuple[int, str, LocalWallet]]:
    """Every wallet in the pool as (set index, role, wallet).

    Setup works on this flat list so each phase runs once across the whole pool
    instead of once per set.
    """
    return [(i, role, s[role]) for i, s in enumerate(_WALLET_SETS) for role in WALLET_ROLES]


# Roles that hold a paid subscription. free stays free on purpose.
_PAID_ROLES = ("sub1", "sub2", "agent1", "agent2")


def setup_test_wallets(backend: str, sets: int = 1) -> bool:
    """Generate `sets` identical wallet sets, faucet them, and subscribe to level 1.

    Each set holds one wallet per WALLET_ROLES and is funded identically, so any
    category can lease any set. Returns True on success, False on failure.
    """
    from tests.backend_helpers import (
        _do_set_username_raw,
        _wait_username,
        _wait_tx_deliver,
        _do_set_biography,
        _rpc_latest_height,
    )

    sets = max(1, int(sets))
    if len(_WALLET_SETS) >= sets:
        _debug(f"wallet pool already provisioned: {len(_WALLET_SETS)} sets")
        return True

    print(f"\n{_COLOR_BOLD}[setup] Generating {sets} wallet set(s) & funding{_COLOR_RESET}")

    _WALLET_SETS.clear()
    for _ in range(sets):
        _WALLET_SETS.append({role: _generate_wallet() for role in WALLET_ROLES})

    entries = _wallet_entries()
    for set_idx, role, w in entries:
        print(f"  Wallet {_wallet_label(set_idx, role):11s}: {w.address()}")

    # Capture height before sending any txs so _wait_tx_deliver scans from here
    try:
        _send_start_height = _rpc_latest_height()
    except Exception:
        _send_start_height = 1

    # Set usernames for all wallets (required before any other core transaction).
    # Each free-tier set_username needs PoW, which is CPU-bound Argon2, so the
    # fan-out is capped rather than one thread per wallet in the pool.
    def _username_job(entry: tuple[int, str, LocalWallet]) -> tuple[str, str, dict]:
        set_idx, role, w = entry
        uname = f"test{role}{_rand_str(6)}"
        resp = _do_set_username_raw(backend, w, uname, skip_pow=False)
        return _wallet_label(set_idx, role), uname, resp or {}

    username_tx_hashes: list[tuple[str, str]] = []
    username_results = parallel_map(_username_job, entries, 8)
    for label, uname, resp in username_results:
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        if resp and resp.get("error"):
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {label}: {resp.get('error')}")
            return False
        if txh:
            username_tx_hashes.append((label, txh))
            print(f"  Username {label:11s}: {uname} (tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp) if resp else "no response"
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {label}: {err}")
            return False

    # Wait for each set_username tx to be delivered in a block before polling indexer
    for label, txh in username_tx_hashes:
        result = _wait_tx_deliver(txh, from_height=_send_start_height)
        if result is None:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {label}: tx not delivered in block")
            return False
        code, _ = result
        if code != 0:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {label}: tx failed in block (code={code})")
            return False

    # Wait until usernames are visible in indexer (get_profile)
    for set_idx, role, w in entries:
        label = _wallet_label(set_idx, role)
        resolved = _wait_username(backend, str(w.address()))
        if resolved:
            print(f"  Username {label:11s}: resolved {resolved}")
        else:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {label}: not visible on-chain")
            return False

    # Faucet all wallets (sub wallets need tokens for subscription fees)
    try:
        sub1_spend_budget = _required_sub1_spend_budget_umirage(backend)
        _debug(f"sub1 dynamic spend budget={sub1_spend_budget} umirage")
    except Exception as e:
        print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Cannot compute sub1 spend budget: {e}")
        return False

    FAUCET_AMOUNTS.clear()
    FAUCET_AMOUNTS.update(
        {
            "free": 1_000_000,  #           1 MIRAGE (minimal non-zero for balance checks)
            "sub1": 100_000_000_000 + sub1_spend_budget,  # exact subscription fee + dynamic test spend budget
            "sub2": 100_000_000_000,  #   100,000 MIRAGE  (exact Subscriber fee)
            "agent1": 500_000_000_000,  # 500,000 MIRAGE  (exact Agent fee)
            "agent2": 1_500_000_000_000,  # 1,500,000 MIRAGE (Agent fee + 2 agent gifts)
        }
    )
    try:
        faucet_addr = _resolve_validator_key_addr()
        spendable = _get_spendable_balance(faucet_addr)
        per_set = sum(FAUCET_AMOUNTS.values())
        required = per_set * sets
        if spendable < required:
            have_m = spendable / 1_000_000
            need_m = required / 1_000_000
            print(
                f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Faucet source balance too low: "
                f"have {have_m:,.0f} MIRAGE, need {need_m:,.0f} MIRAGE "
                f"({sets} set(s) x {per_set / 1_000_000:,.0f} MIRAGE)"
            )
            print(f"  Hint: lower --wallet-sets (or MIRAGE_TEST_WALLET_SETS), currently {sets}.")
            print("  Hint: re-init local docker with a funded mnemonic (deploy/deploy.sh --init).")
            return False
        # scripts/test_upgrade.sh launches the blockchain and backend suites
        # concurrently against this one faucet. Requiring headroom for the
        # sibling outright would abort the second suite to start, which sees a
        # balance the first has already drawn down, so this only warns.
        if spendable < required * _FAUCET_RESERVE_SUITES:
            print(
                f"  {_COLOR_YELLOW}WARN{_COLOR_RESET}  faucet has "
                f"{spendable / 1_000_000:,.0f} MIRAGE; a concurrent sibling suite at "
                f"{sets} set(s) needs another {required / 1_000_000:,.0f} and may not fit"
            )
    except Exception as e:
        print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Faucet spendable balance check failed: {e}")
        return False

    for set_idx, role, w in entries:
        label = _wallet_label(set_idx, role)
        amount = FAUCET_AMOUNTS[role]
        if not _faucet(backend, str(w.address()), amount):
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Faucet failed for {label} ({w.address()})")
            return False
        print(f"  Fauceted {label:11s}: {amount / 1_000_000:.0f} MIRAGE")

    # Wait for faucet transactions to be included
    print("  Waiting for faucet transactions...")
    faucet_deadline = time.perf_counter() + 20.0 + 5.0 * sets
    while time.perf_counter() < faucet_deadline:
        try:
            if all(_get_spendable_balance(str(w.address())) > 0 for _, _, w in entries):
                break
        except Exception:
            pass
        time.sleep(0.4)

    # Verify balances — use chain query directly (backend/indexer may lag)
    miraged = _miraged_cmd()
    for set_idx, role, w in entries:
        label = _wallet_label(set_idx, role)
        addr = str(w.address())
        try:
            qcode, qout = _docker_exec(
                f"{miraged} q bank balances {addr} --home /root/.mirage/node "
                f"--node tcp://127.0.0.1:26657 -o json 2>/dev/null"
            )
            bal = 0
            if qcode == 0 and qout:
                bals = json.loads(qout).get("balances", [])
                for b in bals:
                    if b.get("denom") == "umirage":
                        bal = int(b.get("amount", 0))
            if bal <= 0:
                print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {label} balance is 0 after faucet (addr={addr})")
                return False
            print(f"  Balance {label:11s}: {bal / 1_000_000:.1f} MIRAGE")
        except Exception as e:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Cannot check balance for {label}: {e}")
            return False

    # Subscribe the paid roles in every set. Unordered transactions, so all of
    # them go out before anything is awaited.
    paid_entries = [(i, role, w) for i, role, w in entries if role in _PAID_ROLES]
    for set_idx, role, w in paid_entries:
        label = _wallet_label(set_idx, role)
        resp = _do_subscribe(backend, w, 1)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            print(f"  Subscribed {label:11s} to level 1 (tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp)
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Subscribe {label} to level 1: {err}")
            return False

    # Wait for the subscription to be reflected in the indexer DB. Subscriber
    # zero-fee / PoW-exempt paths still key off effective_paid. Admins
    # (level >= 100) use the relay-quota path from their tier without that flag.
    # Waiting only for user_level>=1 can return before the paid flag is set and
    # leave the next request (a skip_pow biography, say) rejected as a free user's.
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    pending = list(paid_entries)
    while pending and time.perf_counter() < deadline:
        still_pending = []
        for set_idx, role, w in pending:
            label = _wallet_label(set_idx, role)
            try:
                status = get_user_status(backend, str(w.address()))
                actual_level = int(status.get("user_level", 0) or 0)
                if actual_level >= 1 and bool(status.get("effective_paid")):
                    print(f"  Verified {label:11s} level={actual_level} effective_paid=true")
                    continue
            except Exception:
                pass
            still_pending.append((set_idx, role, w))
        pending = still_pending
        if pending:
            time.sleep(1)
    if pending:
        unverified = ", ".join(_wallet_label(i, role) for i, role, _ in pending)
        print(
            f"  {_COLOR_RED}FAIL{_COLOR_RESET}  subscription not reflected in indexer "
            f"after {int(INDEX_TIMEOUT_SEC)}s: {unverified}"
        )
        return False

    # Set biographies on the dedicated agent wallets
    AGENT_BIOS = {
        "agent1": (
            "This is a test agent biography.\n"
            "Agents operate at level 10 with expanded capabilities.\n"
            "This biography was set during automated testing."
        ),
        "agent2": (
            "Another test agent biography.\n"
            "This agent was created for integration testing.\n"
            "It verifies that level 10 accounts can hold biographies."
        ),
    }
    bio_tx_hashes: list[tuple[str, str]] = []
    for set_idx, role, w in entries:
        bio = AGENT_BIOS.get(role)
        if bio is None:
            continue
        label = _wallet_label(set_idx, role)
        resp = _do_set_biography(backend, w, bio, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            bio_tx_hashes.append((label, txh))
            print(f"  Biography {label:11s}: set ({len(bio)} chars, tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp)
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Biography {label}: {err}")
            return False

    for label, txh in bio_tx_hashes:
        result = _wait_tx_deliver(txh)
        if result is None:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Biography {label}: tx not delivered")
            return False
        code, _ = result
        if code != 0:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Biography {label}: tx failed in block (code={code})")
            return False

    print(f"  {_COLOR_GREEN}Setup complete: {sets} set(s), {len(entries)} wallets{_COLOR_RESET}")
    return True


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------

# Global PoW factor cache (set during param fetch)
_POW_FACTOR: float = 0.25


def _fetch_params(backend: str, address: str | None = None) -> tuple:
    """Returns (last_block_hash, pow_difficulty, pow_base_bits, pow_factor, balance)."""
    global _POW_FACTOR
    st = get_status(backend, address=address)
    lb = str(st.get("last_block_hash", ""))
    diff = int(st.get("pow_difficulty", 0) or 0)
    base_bits = int(st.get("pow_base_bits", 0) or 0)
    pow_factor = float(st.get("pow_factor", 0.25))
    bal = int(st["balance"]) if st.get("balance") is not None else 0
    _POW_FACTOR = pow_factor
    return lb, diff, base_bits, pow_factor, bal


def return_test_wallet_funds(backend: str) -> None:
    """Send unspent wallet-set funds back to the faucet.

    Provisioning parks about 2.3M MIRAGE per set in throwaway wallets and the
    validator never gets it back on its own, so every run used to shrink the
    faucet permanently. A pool of N sets multiplies that drain by N, which ends
    in "faucet source balance too low" after a couple of runs. Only the paid
    roles are swept: they are PoW-exempt and the validator is the gas payer, so
    the sweep is one signed message each and costs the wallet nothing. `free`
    holds 1 MIRAGE, which is not worth a transaction.
    """
    if not _WALLET_SETS:
        return
    from tests.backend_helpers import _do_send_tokens

    try:
        faucet_addr = _resolve_validator_key_addr()
    except Exception as e:
        print(f"  {_COLOR_YELLOW}WARN{_COLOR_RESET}  cannot resolve faucet address, funds not returned: {e}")
        return

    print(f"\n{_COLOR_BOLD}[teardown] Returning unspent funds to the faucet{_COLOR_RESET}")
    returned = 0
    for set_idx, role, w in _wallet_entries():
        if role not in _PAID_ROLES:
            continue
        label = _wallet_label(set_idx, role)
        try:
            balance = _get_spendable_balance(str(w.address()))
            if balance <= 0:
                continue
            resp = _do_send_tokens(backend, w, faucet_addr, balance, skip_pow=True)
            if str(resp.get("tx_hash", "")):
                returned += balance
            else:
                print(f"  {_COLOR_YELLOW}WARN{_COLOR_RESET}  {label} not returned: {resp.get('error', resp)}")
        except Exception as e:
            print(f"  {_COLOR_YELLOW}WARN{_COLOR_RESET}  {label} not returned: {e}")
    print(f"  Returned {returned / 1_000_000:,.0f} MIRAGE from {len(_WALLET_SETS)} set(s)")


def parallel_map(fn, items, workers: int) -> list:
    """Order-preserving concurrent map that carries the test context into workers.

    ThreadPoolExecutor does not copy contextvars. A worker started without this
    helper has no category (its results escape the release gate) and no wallet
    lease (WALLETS raises). Each job gets its own Context copy because one
    Context object cannot be entered from two threads at once.
    """
    items = list(items)
    if not items:
        return []
    if workers <= 1 or len(items) == 1:
        return [fn(item) for item in items]
    ctx = contextvars.copy_context()
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(lambda item: ctx.copy().run(fn, item), items))


def summarize(results: list[TestResult], no_skip_categories: set[str] | frozenset = frozenset()) -> dict:
    """Count outcomes and flag skips that a release-gate category may not have.

    Pure so the runner's own accounting can be tested without a live backend.
    """
    passed = sum(1 for r in results if r.status == "pass")
    failed = sum(1 for r in results if r.status == "fail")
    skipped = sum(1 for r in results if r.status == "skip")
    gate_skips = [r for r in results if r.status == "skip" and r.category in no_skip_categories]
    return {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "gate_skips": gate_skips,
        "ok": failed == 0 and not gate_skips,
    }


def run_suite(
    name: str,
    categories: dict[str, callable],
    exclusive: set[str] | frozenset = frozenset(),
    pre_run_hook: callable | None = None,
    no_skip_categories: set[str] | frozenset = frozenset(),
    walletless_categories: set[str] | frozenset = frozenset(),
) -> int:
    """Generic test suite runner.

    Handles argparse, container-only guard, connectivity check, wallet setup,
    parallel/exclusive dispatch, and summary.

    Categories run concurrently by default. One in `walletless_categories` needs
    no wallet and runs unthrottled; any other leases one of the pool's wallet
    sets for its duration. One in `exclusive` runs alone after the rest finish,
    because it contends on something a private wallet set cannot isolate.
    """
    if not _INSIDE_CONTAINER:
        print(
            f"\n{_COLOR_RED}ABORT: This suite can only run from inside "
            f"the local Docker testnet container.{_COLOR_RESET}"
        )
        print("  Host execution is disabled. Run:")
        print(
            "  docker exec mirage bash -lc 'cd /opt/mirage && "
            'set -a; for f in /root/.mirage/env/*.env; do . "$f"; done; '
            "set +a; PYTHONPATH=/opt/mirage python3 tests/test_backend.py'"
        )
        return 1

    parser = argparse.ArgumentParser(description=name)
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help=f"Backend URL (default: {DEFAULT_BACKEND})")
    parser.add_argument("--category", "-c", default=None, help=f"Run single category: {', '.join(categories.keys())}")
    parser.add_argument(
        "--wallet-sets",
        type=int,
        default=int(os.environ.get("MIRAGE_TEST_WALLET_SETS", "4")),
        help="Wallet sets to provision, one per concurrent wallet-bound category (default 4)",
    )
    parser.add_argument(
        "--serial",
        action="store_true",
        help="Run every category alone, on one wallet set, to reproduce a parallel failure",
    )
    args = parser.parse_args()
    backend = args.backend.rstrip("/")
    global SUITE_BACKEND
    SUITE_BACKEND = backend
    if args.category:
        cats = [c.strip() for c in args.category.split(",")]
        for category in cats:
            if category not in categories:
                print(f"{_COLOR_RED}Unknown category: {category}{_COLOR_RESET}")
                print(f"Available: {', '.join(categories.keys())}")
                return 1
        to_run = {category: categories[category] for category in cats}
    else:
        to_run = categories

    print("=" * 60)
    print(name)
    print(f"Backend: {backend}")
    print("=" * 60)

    from urllib.parse import urlparse

    parsed = urlparse(backend)
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        print(
            f"\n{_COLOR_RED}ABORT: This test suite is designed to run ONLY on the local Docker testnet.{_COLOR_RESET}"
        )
        print(f"  Backend host '{hostname}' is not localhost.")
        print(f"  Run scripts/reset_local_testnet.py first, then use --backend http://127.0.0.1:80")
        return 1

    if not _check_local_docker():
        print(f"\n{_COLOR_RED}ABORT: This is not the local Docker testnet container.{_COLOR_RESET}")
        print("  Expected container hostname: testnet")
        return 1

    # Hostname gate BEFORE any HTTP. This prevents a copied test tree inside a
    # prod/UAT container from mutating that node.
    try:
        ch = socket.gethostname().strip().lower()
        print(f"  Running inside container (hostname={ch}).")
        if ch != "testnet":
            print(f"\n{_COLOR_RED}ABORT: Container hostname is '{ch}', expected 'testnet'.{_COLOR_RESET}")
            print(f"  This suite must NEVER run against prod/UAT (e.g. mirage-talk, mirage.vote).")
            print(f"  Only the local Docker testnet (hostname=testnet) is allowed.")
            return 1
    except Exception as e:
        print(f"\n{_COLOR_RED}ABORT: Cannot verify container hostname: {e}{_COLOR_RESET}")
        return 1

    try:
        code, _ = _get(f"{backend}/api/get_parameters")
        if code != 200:
            print(f"\n{_COLOR_RED}Cannot reach backend at {backend} (code={code}){_COLOR_RESET}")
            return 1
    except Exception as e:
        print(f"\n{_COLOR_RED}Cannot reach backend at {backend}: {e}{_COLOR_RESET}")
        return 1

    pow_ready, pow_error = _check_test_pow_limit()
    if not pow_ready:
        print(f"\n{_COLOR_RED}ABORT: Local test limits are not configured.{_COLOR_RESET}")
        print(f"  {pow_error}")
        print("  From the host, submit these proposals first:")
        for _, proposal in _REQUIRED_TEST_LIMITS.values():
            print(f"  python3 scripts/submit_proposal.py local {proposal}")
        return 1

    wallet_bound = [n for n in to_run if n not in walletless_categories]
    if not wallet_bound:
        _debug("selected categories require no test wallets")
    else:
        sets_needed = 1 if args.serial else max(1, min(args.wallet_sets, len(wallet_bound)))
        if not setup_test_wallets(backend, sets_needed):
            print(f"\n{_COLOR_RED}ABORT: Wallet setup failed.{_COLOR_RESET}")
            return 1

    # One lease per wallet set. A wallet-bound category blocks here until a set
    # is free, which is what bounds concurrency; walletless ones never queue.
    leases: queue.SimpleQueue = queue.SimpleQueue()
    for i in range(len(_WALLET_SETS)):
        leases.put(i)

    if pre_run_hook:
        ret = pre_run_hook(backend)
        if ret:
            return ret

    def _needs_wallet(cat_name: str) -> bool:
        return cat_name not in walletless_categories

    def _run_category(cat_name: str, fn, needs_wallet: bool) -> None:
        lease = leases.get() if needs_wallet else None
        _TEST_CTX.set(_TestContext(category=cat_name, wallet_set=lease))
        suffix = "" if lease is None else f" (wallets=set{lease})"
        print(f"\n{_COLOR_BOLD}[{cat_name}]{_COLOR_RESET}{suffix}")
        t0 = time.time()
        try:
            fn(backend)
        except Exception as e:
            _fail(f"{cat_name}.UNEXPECTED_ERROR", str(e))
        finally:
            elapsed = time.time() - t0
            print(f"  [{cat_name}] elapsed={elapsed:.1f}s")
            _debug(f"category {cat_name} elapsed={elapsed:.1f}s lease={lease}")
            _TEST_CTX.set(None)
            if lease is not None:
                leases.put(lease)

    exclusive_names = [n for n in to_run if n in exclusive]
    parallel_names = [n for n in to_run if n not in exclusive]
    if args.serial:
        parallel_names, exclusive_names = [], list(to_run)

    print(
        f"  dispatch: {len(parallel_names)} parallel, {len(exclusive_names)} exclusive, "
        f"{len(_WALLET_SETS)} wallet set(s)"
    )

    if parallel_names:
        _debug(f"parallel categories ({len(parallel_names)}): {', '.join(parallel_names)}")
        if len(parallel_names) == 1:
            cat_name = parallel_names[0]
            _run_category(cat_name, to_run[cat_name], _needs_wallet(cat_name))
        else:
            ctx = contextvars.copy_context()
            with ThreadPoolExecutor(max_workers=len(parallel_names)) as pool:
                futures = {
                    pool.submit(ctx.copy().run, _run_category, n, to_run[n], _needs_wallet(n)): n
                    for n in parallel_names
                }
                for fut in as_completed(futures):
                    fut.result()
    if exclusive_names:
        _debug(f"exclusive categories ({len(exclusive_names)}): {', '.join(exclusive_names)}")
        for cat_name in exclusive_names:
            _run_category(cat_name, to_run[cat_name], _needs_wallet(cat_name))

    return_test_wallet_funds(backend)

    s = summarize(RESULTS, no_skip_categories)
    tally = f"{s['passed']} passed, {s['skipped']} skipped, {s['failed']} failed (of {s['total']})"

    print(f"\n{'=' * 60}")
    if s["failed"]:
        print(f"{_COLOR_RED}{_COLOR_BOLD}RESULT: {tally}{_COLOR_RESET}")
        print("\nFailed tests:")
        for r in RESULTS:
            if r.status == "fail":
                err = f" — {r.error}" if r.error else ""
                print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {r.name}{err}")
    elif s["gate_skips"]:
        print(f"{_COLOR_RED}{_COLOR_BOLD}RESULT: {tally} — release-gate category skipped{_COLOR_RESET}")
    else:
        print(f"{_COLOR_GREEN}{_COLOR_BOLD}RESULT: {tally}{_COLOR_RESET}")

    if s["skipped"]:
        print("\nSkipped tests:")
        for r in RESULTS:
            if r.status == "skip":
                reason = f" — {r.error}" if r.error else ""
                cat = f"[{r.category}] " if r.category else ""
                print(f"  {_COLOR_YELLOW}SKIP{_COLOR_RESET}  {cat}{r.name}{reason}")

    if s["gate_skips"]:
        print(f"\n{_COLOR_RED}Release-gate categories must not skip:{_COLOR_RESET}")
        for r in s["gate_skips"]:
            print(f"  {_COLOR_RED}GATE SKIP{_COLOR_RESET}  [{r.category}] {r.name} — {r.error or 'no reason given'}")

    return 0 if s["ok"] else 1
