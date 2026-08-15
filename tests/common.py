"""Shared test infrastructure for backend and blockchain suites."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
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
    canon_signed_with_pow,
    canon_attribution,
)

DEFAULT_BACKEND = "http://127.0.0.1:80"
INDEX_TIMEOUT_SEC = 45.0

WALLETS: dict[str, LocalWallet] = {}
FAUCET_AMOUNTS: dict[str, int] = {}


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

# Category of the test currently running on each thread. Stateless categories run
# in parallel, so a single global would misattribute skips.
_CATEGORY_BY_THREAD: dict[int, str] = {}


def _current_category() -> Optional[str]:
    with _RESULTS_LOCK:
        own = _CATEGORY_BY_THREAD.get(threading.get_ident())
        if own is not None:
            return own
        # A helper thread spawned by a test inherits the category only when no
        # other category could claim the result.
        if len(_CATEGORY_BY_THREAD) == 1:
            return next(iter(_CATEGORY_BY_THREAD.values()))
    return None


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
            _debug(
                f"retry upload {url} error={type(e).__name__} attempt={attempt}/{max_retries} sleep={delay:.2f}s"
            )
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
# fresh shell that does not inherit the tmux session's environment.
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


def _check_test_pow_limit() -> tuple[bool, str]:
    """Require the local anti-spam limit used by the transaction-heavy suites."""
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
    try:
        value = int(params["pow_message_limit"])
    except (KeyError, TypeError, ValueError):
        return False, f"pow_message_limit missing or invalid: {str(params)[:200]}"
    if value != 9_999_999:
        return False, f"pow_message_limit={value}, expected 9999999"
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
    Retries on sequence mismatch (code 32) and waits for the tx to be
    committed before returning so the next send gets the right sequence.
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

    max_retries = 5
    for attempt in range(max_retries):
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
            "-o",
            "json",
        ]

        code, out = _run_miraged(send_args, timeout=30)
        if code != 0:
            # Sequence mismatch at CLI level — retry
            if "sequence mismatch" in out.lower() and attempt < max_retries - 1:
                wait = 2 * (attempt + 1)
                print(f"    [faucet] sequence mismatch, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
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
            if tx_code == 32 or "account sequence mismatch" in str(raw_log).lower():
                wait = 2 * (attempt + 1)
                print(f"    [faucet] sequence mismatch, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue
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
    print(f"    [faucet] exhausted {max_retries} retries on sequence mismatch")
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


def setup_test_wallets(backend: str) -> bool:
    """Generate random wallets, faucet them, and subscribe (level 1=Subscriber, 10=Agent).

    Returns True on success, False on failure.
    """
    from tests.backend_helpers import (
        _do_set_username_raw,
        _wait_username,
        _wait_tx_deliver,
        _do_set_biography,
    )

    print(f"\n{_COLOR_BOLD}[setup] Generating wallets & funding{_COLOR_RESET}")

    # Generate 5 fresh random wallets
    WALLETS["free"] = _generate_wallet()
    WALLETS["sub1"] = _generate_wallet()
    WALLETS["sub2"] = _generate_wallet()
    WALLETS["agent1"] = _generate_wallet()
    WALLETS["agent2"] = _generate_wallet()

    for name, w in WALLETS.items():
        print(f"  Wallet {name:4s}: {w.address()}")

    # Capture height before sending any txs so _wait_tx_deliver scans from here
    from tests.backend_helpers import _rpc_latest_height

    try:
        _send_start_height = _rpc_latest_height()
    except Exception:
        _send_start_height = 1

    # Set usernames for all wallets (required before any other core transaction)
    username_tx_hashes: list[tuple[str, str]] = []
    for name, w in WALLETS.items():
        uname = f"test{name}{_rand_str(4)}"
        resp = _do_set_username_raw(backend, w, uname, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        if resp and resp.get("error"):
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {name}: {resp.get('error')}")
            return False
        if txh:
            username_tx_hashes.append((name, txh))
            print(f"  Username {name:4s}: {uname} (tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp) if resp else "no response"
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {name}: {err}")
            return False

    # Wait for each set_username tx to be delivered in a block before polling indexer
    for name, txh in username_tx_hashes:
        result = _wait_tx_deliver(txh, from_height=_send_start_height)
        if result is None:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {name}: tx not delivered in block")
            return False
        code, _ = result
        if code != 0:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {name}: tx failed in block (code={code})")
            return False

    # Brief delay so indexer can process the blocks before we poll get_profile
    _debug("waiting for indexer to process set_username blocks...")
    time.sleep(10)

    # Wait until usernames are visible in indexer (get_profile)
    for name, w in WALLETS.items():
        addr = str(w.address())
        resolved = _wait_username(backend, addr)
        if resolved:
            print(f"  Username {name:4s}: resolved {resolved}")
        else:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {name}: not visible on-chain")
            return False

    # Faucet all wallets (sub wallets need tokens for subscription fees)
    # Level 1 (Subscriber) = 100K MIRAGE, Level 10 (Agent) = 500K MIRAGE
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
        required = sum(FAUCET_AMOUNTS.values())
        if spendable < required:
            have_m = spendable / 1_000_000
            need_m = required / 1_000_000
            print(
                f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Faucet source balance too low: "
                f"have {have_m:,.0f} MIRAGE, need {need_m:,.0f} MIRAGE"
            )
            print("  Hint: re-init local docker with a funded mnemonic (deploy/deploy.sh --init).")
            return False
    except Exception as e:
        print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Faucet spendable balance check failed: {e}")
        return False
    for name, w in WALLETS.items():
        addr = str(w.address())
        amount = FAUCET_AMOUNTS[name]
        ok = _faucet(backend, addr, amount)
        if not ok:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Faucet failed for {name} ({addr})")
            return False
        print(f"  Fauceted {name:4s}: {amount / 1_000_000:.0f} MIRAGE")

    # Wait for faucet transactions to be included
    print("  Waiting for faucet transactions...")
    time.sleep(6)

    # Verify balances — use chain query directly (backend/indexer may lag)
    miraged = _miraged_cmd()
    kb = _keyring_backend()
    for name, w in WALLETS.items():
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
                print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {name} balance is 0 after faucet (addr={addr})")
                return False
            print(f"  Balance {name:4s}: {bal / 1_000_000:.1f} MIRAGE")
        except Exception as e:
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Cannot check balance for {name}: {e}")
            return False

    # Subscribe wallets: sub1,sub2 -> level 1, agent1/agent2 -> level 10
    for level, name in [(1, "sub1"), (1, "sub2"), (10, "agent1"), (10, "agent2")]:
        w = WALLETS[name]
        resp = _do_subscribe(backend, w, level)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            print(f"  Subscribed {name} to level {level} (tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp)
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Subscribe {name} to level {level}: {err}")
            return False

    # Wait for subscription levels to be reflected in BOTH chain and indexer DB
    # (is_subscriber() checks the indexer, not the chain — must wait for indexer to catch up)
    for level, name in [(1, "sub1"), (1, "sub2"), (10, "agent1"), (10, "agent2")]:
        w = WALLETS[name]
        addr = str(w.address())
        deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
        verified = False
        while time.perf_counter() < deadline:
            try:
                status = get_user_status(backend, addr)
                actual_level = int(status.get("user_level", 0) or 0)
                if actual_level >= level:
                    print(f"  Verified {name} level={actual_level}")
                    verified = True
                    break
            except Exception:
                pass
            time.sleep(1)
        if not verified:
            print(
                f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {name} level not reflected in indexer after {int(INDEX_TIMEOUT_SEC)}s"
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
    for name, bio in AGENT_BIOS.items():
        w = WALLETS[name]
        resp = _do_set_biography(backend, w, bio, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            print(f"  Biography {name}: set ({len(bio)} chars, tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp)
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Biography {name}: {err}")
            return False

    time.sleep(4)

    print(f"  {_COLOR_GREEN}Setup complete{_COLOR_RESET}")
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
    stateless: set[str],
    pre_run_hook: callable | None = None,
    no_skip_categories: set[str] | frozenset = frozenset(),
    walletless_categories: set[str] | frozenset = frozenset(),
) -> int:
    """Generic test suite runner.

    Handles argparse, container-only guard, connectivity check, wallet setup,
    parallel/serial dispatch, and summary.
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
    args = parser.parse_args()
    backend = args.backend.rstrip("/")
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
        print(f"\n{_COLOR_RED}ABORT: Local test PoW limit is not configured.{_COLOR_RESET}")
        print(f"  {pow_error}")
        print("  From the host, submit this proposal first:")
        print(
            "  python3 scripts/submit_proposal.py local "
            "scripts/proposals/proposal_set_pow_message_limit_9999999.json"
        )
        return 1

    if set(to_run).issubset(walletless_categories):
        _debug("selected categories require no test wallets")
    elif not setup_test_wallets(backend):
        print(f"\n{_COLOR_RED}ABORT: Wallet setup failed.{_COLOR_RESET}")
        return 1

    if pre_run_hook:
        ret = pre_run_hook(backend)
        if ret:
            return ret

    def _run_category(cat_name: str, fn) -> None:
        print(f"\n{_COLOR_BOLD}[{cat_name}]{_COLOR_RESET}")
        with _RESULTS_LOCK:
            _CATEGORY_BY_THREAD[threading.get_ident()] = cat_name
        try:
            fn(backend)
        except Exception as e:
            _fail(f"{cat_name}.UNEXPECTED_ERROR", str(e))
        finally:
            with _RESULTS_LOCK:
                _CATEGORY_BY_THREAD.pop(threading.get_ident(), None)

    parallel_names = [n for n in to_run if n in stateless]
    serial_names = [n for n in to_run if n not in stateless]
    if parallel_names:
        _debug(f"parallel categories: {', '.join(parallel_names)}")
        if len(parallel_names) == 1:
            cat_name = parallel_names[0]
            _run_category(cat_name, to_run[cat_name])
        else:
            with ThreadPoolExecutor(max_workers=len(parallel_names)) as pool:
                futures = {pool.submit(_run_category, n, to_run[n]): n for n in parallel_names}
                for fut in as_completed(futures):
                    fut.result()
    if serial_names:
        _debug(f"sequential categories: {', '.join(serial_names)}")
        for cat_name in serial_names:
            _run_category(cat_name, to_run[cat_name])

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
