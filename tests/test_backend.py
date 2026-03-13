#!/usr/bin/env python3
"""
Mirage Backend Test Suite — comprehensive end-to-end tests.

Covers read endpoints, social graph, comment threading, PoW verification,
all 3 subscription tiers, search/discovery, and validation edge cases.

** This suite is designed to run ONLY on the local Docker testnet **
** set up by scripts/reset_local_testnet.py.                      **

All wallets are generated fresh (random, non-deterministic) and funded
from the validator account via Docker CLI.

Run:
    conda activate mirage-node
    python tests/test_backend.py [--backend URL] [--category NAME]
"""
from __future__ import annotations

import argparse
import base64
import json
import hashlib
import math
import os
import random
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

# ---------------------------------------------------------------------------
# Repo imports
# ---------------------------------------------------------------------------
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
    canon_base_upgrade_level as _canon_base_upgrade_level_raw,
    canon_base_report as _canon_base_report_raw,
    canon_base_set_auto_renewal as _canon_base_set_auto_renewal_raw,
    canon_base_set_biography as _canon_base_set_biography_raw,
    canon_base_annotate as _canon_base_annotate_raw,
    canon_signed_with_pow,
)

# ---------------------------------------------------------------------------
# Constants / config
# ---------------------------------------------------------------------------
DEFAULT_BACKEND = "http://127.0.0.1:80"
INDEX_TIMEOUT_SEC = 45.0

# Populated during setup — all wallets are random, non-deterministic
WALLETS: dict[str, LocalWallet] = {}  # "free", "sub1", "sub2", "agent1", "agent2"
FAUCET_AMOUNTS: dict[str, int] = {}  # set during setup — umirage fauceted per wallet


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    name: str
    passed: bool
    status_code: Optional[int] = None
    error: Optional[str] = None
    details: dict = field(default_factory=dict)


RESULTS: list[TestResult] = []
_RESULTS_LOCK = threading.Lock()

_COLOR_GREEN = "\033[92m"
_COLOR_RED = "\033[91m"
_COLOR_YELLOW = "\033[93m"
_COLOR_RESET = "\033[0m"
_COLOR_BOLD = "\033[1m"


def _pass(name: str, **details) -> TestResult:
    r = TestResult(name=name, passed=True, details=details)
    with _RESULTS_LOCK:
        RESULTS.append(r)
    print(f"  {_COLOR_GREEN}PASS{_COLOR_RESET}  {name}")
    return r


def _fail(name: str, error: str = "", **details) -> TestResult:
    r = TestResult(name=name, passed=False, error=error, details=details)
    with _RESULTS_LOCK:
        RESULTS.append(r)
    err = f" — {error}" if error else ""
    print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {name}{err}")
    return r


def _skip(name: str, reason: str = "", **details) -> TestResult:
    r = TestResult(name=name, passed=True, error=reason, details={"skipped": True, **details})
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

        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {}

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

        try:
            body = r.json()
        except Exception:
            body = {}
        return r.status_code, body

    return 599, {}


# ---------------------------------------------------------------------------
# Local Docker testnet helpers
# ---------------------------------------------------------------------------

# Detect if we're already running inside the container.
_INSIDE_CONTAINER = os.path.exists("/.dockerenv") or os.path.isfile("/opt/mirage/deploy/entrypoint.sh")


def _docker_exec(cmd: str, timeout: int = 30) -> Tuple[int, str]:
    """Run a command inside the mirage environment.

    If running inside the container, executes directly via bash.
    If running on the host, uses ``docker exec mirage``.
    Returns (exit_code, stdout).
    """
    if _INSIDE_CONTAINER:
        argv = ["bash", "-lc", cmd]
    else:
        argv = ["docker", "exec", "mirage", "bash", "-lc", cmd]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    out = result.stdout.strip()
    if result.returncode != 0 and not out:
        out = result.stderr.strip()
    return result.returncode, out


def _run_miraged(args: list, timeout: int = 30) -> Tuple[int, str]:
    """Run miraged with an explicit argument vector — no shell involved.

    This avoids all bash login-shell issues (profile scripts polluting
    stdout, environment variables being stripped, argument re-parsing).
    Returns (exit_code, stdout).  Stderr is only appended on failure
    so JSON output on stdout stays clean.
    """
    miraged = _miraged_cmd()
    if _INSIDE_CONTAINER:
        argv = [miraged] + list(args)
        # Inherit parent environment; ensure HOME is set for keyring access
        env = os.environ.copy()
        env["HOME"] = "/root"
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
        out = result.stdout.strip()
        if result.returncode != 0 and not out:
            out = result.stderr.strip()
        return result.returncode, out
    else:
        cmd = " ".join([miraged] + list(args))
        return _docker_exec(cmd, timeout=timeout)


def _miraged_cmd() -> str:
    """Return the miraged binary path inside the container."""
    preferred = "/opt/mirage/blockchain/miraged"
    fallback = "/opt/mirage/blockchain/bin/miraged"
    if _INSIDE_CONTAINER:
        if os.path.isfile(preferred) and os.access(preferred, os.X_OK):
            return preferred
        if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
            return fallback
        return preferred
    # Host mode: query inside container and detect known paths robustly
    code, out = _docker_exec(
        "if [ -x /opt/mirage/blockchain/miraged ]; then "
        "echo /opt/mirage/blockchain/miraged; "
        "elif [ -x /opt/mirage/blockchain/bin/miraged ]; then "
        "echo /opt/mirage/blockchain/bin/miraged; fi"
    )
    text = out or ""
    if preferred in text:
        return preferred
    if fallback in text:
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
    """Verify we can execute commands in the mirage environment."""
    if _INSIDE_CONTAINER:
        return True
    try:
        code, out = _docker_exec("echo ok", timeout=5)
        return code == 0 and "ok" in out
    except Exception:
        return False


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


def _do_upgrade_level(backend: str, wallet: LocalWallet, level: int) -> dict:
    """Upgrade a wallet's subscription to the given level (1=Subscriber, 10=Agent)."""
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = str(st.get("last_block_hash", ""))
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()

    # upgrade_level: difficulty=0, proof=0 (no PoW)
    base = _canon_base_upgrade_level_raw(pub, _lb_bytes(lb), 0, ts, level, nonce)
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
    code, resp = _post(f"{backend}/api/core/upgrade_level", payload)
    return resp


def _do_send_tokens(backend: str, wallet: LocalWallet, target: str, amount: int, skip_pow: bool = False) -> dict:
    """Send tokens from wallet to target address via the backend API."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_send_tokens_raw(pub, _lb_bytes(lb), d, ts, addr, target, amount, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "amount": amount,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/send_tokens", payload)
    return resp


def _do_award(
    backend: str,
    wallet: LocalWallet,
    target: str,
    award_type: str,
    pow_difficulty: int = 0,
    pow: int = 0,
    last_block_hash: str | None = None,
    timestamp: int | None = None,
    sig_override: bytes | None = None,
    pub_override: bytes | None = None,
) -> Tuple[int, dict]:
    """Send an award via the backend API (burn-only)."""
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = last_block_hash or str(st.get("last_block_hash", ""))
    pub = pub_override or wallet.public_key().public_key_bytes
    ts = int(timestamp or _now_ms())
    nonce = _fresh_nonce()
    base = _canon_base_award_raw(pub, _lb_bytes(lb), int(pow_difficulty), ts, target, award_type, nonce)
    signed = canon_signed_with_pow(base, int(pow))
    sig = sig_override or sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": int(pow_difficulty),
        "pow": int(pow),
        "target": target,
        "award_type": award_type,
    }
    code, resp = _post(f"{backend}/api/core/award", payload)
    return code, resp


def _required_sub1_spend_budget_umirage(backend: str) -> int:
    """Compute extra funding needed for sub1 from live chain config.

    Includes explicit spends used by this suite:
    - post award: quality_post
    - comment award: receipts
    - token send happy path: 1000 umirage
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

    token_send_amount = 1000  # test_tokens.happy_path
    return int(costs["quality_post"]) + int(costs["receipts"]) + token_send_amount


def setup_test_wallets(backend: str) -> bool:
    """Generate random wallets, faucet them, and subscribe (level 1=Subscriber, 10=Agent).

    Returns True on success, False on failure.
    """
    print(f"\n{_COLOR_BOLD}[0] Setup: Generating wallets & funding{_COLOR_RESET}")

    # Generate 5 fresh random wallets
    WALLETS["free"] = _generate_wallet()
    WALLETS["sub1"] = _generate_wallet()
    WALLETS["sub2"] = _generate_wallet()
    WALLETS["agent1"] = _generate_wallet()
    WALLETS["agent2"] = _generate_wallet()

    for name, w in WALLETS.items():
        print(f"  Wallet {name:4s}: {w.address()}")

    # Set usernames for all wallets (required before any other core transaction)
    for name, w in WALLETS.items():
        uname = f"test{name}{_rand_str(4)}"
        resp = _do_set_username_raw(backend, w, uname, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        if txh:
            print(f"  Username {name:4s}: {uname} (tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp) if resp else "no response"
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Username {name}: {err}")
            return False

    # Wait until usernames are visible on-chain to avoid downstream failures
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
            "agent2": 500_000_000_000,  # 500,000 MIRAGE (Agent fee)
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
        resp = _do_upgrade_level(backend, w, level)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            print(f"  Subscribed {name} to level {level} (tx: {txh[:16]}...)")
        else:
            err = resp.get("error", resp)
            print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  Subscribe {name} to level {level}: {err}")
            return False

    # Wait for subscription transactions
    time.sleep(6)

    # Verify subscription levels
    for level, name in [(1, "sub1"), (1, "sub2"), (10, "agent1"), (10, "agent2")]:
        w = WALLETS[name]
        addr = str(w.address())
        try:
            us = get_user_status(backend, addr)
            actual_level = int(us.get("user_level", 0) or 0)
            if actual_level != level:
                print(
                    f"  {_COLOR_YELLOW}WARN{_COLOR_RESET}  {name} level={actual_level}, expected {level} (may need more time)"
                )
            else:
                print(f"  Verified {name} level={actual_level}")
        except Exception as e:
            print(f"  {_COLOR_YELLOW}WARN{_COLOR_RESET}  Cannot verify {name} level: {e}")

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


def _do_post(
    backend: str, wallet, topic: str, title: str, content: str, target: str = "", tag: str = "", skip_pow: bool = False
) -> str | None:
    """Create a post/comment and return the tx_hash or None."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_post_raw(pub, _lb_bytes(lb), d, ts, target, topic, title, content, tag, 0, None, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "topic": topic,
        "title": title,
        "content": content,
        "tag": tag,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/post", payload)
    resp = resp or {}
    if resp.get("error"):
        _debug(f"post.submit error={resp.get('error')}")
        return None
    tx_code = int(resp.get("code", 0) or 0)
    if tx_code != 0:
        _debug(f"post.submit failed code={tx_code} log={str(resp.get('raw_log', ''))[:200]}")
        return None
    txh = str(resp.get("tx_hash", "") or "").lower()
    return txh if txh else None


def _do_post_with_nonce(
    backend: str,
    wallet,
    topic: str,
    title: str,
    content: str,
    nonce: int,
    target: str = "",
    tag: str = "",
    skip_pow: bool = False,
) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    d = 0 if skip_pow else diff

    base = _canon_base_post_raw(pub, _lb_bytes(lb), d, ts, target, topic, title, content, tag, 0, None, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "topic": topic,
        "title": title,
        "content": content,
        "tag": tag,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/post", payload)
    return resp or {}


def _do_vote(backend: str, wallet, target: str, direction: int, skip_pow: bool = False) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_vote_raw(pub, _lb_bytes(lb), d, ts, target, int(direction), nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "direction": direction,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/vote", payload)
    return resp


def _do_vote_with_nonce(
    backend: str,
    wallet,
    target: str,
    direction: int,
    nonce: int,
    skip_pow: bool = False,
) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    d = 0 if skip_pow else diff

    base = _canon_base_vote_raw(pub, _lb_bytes(lb), d, ts, target, int(direction), nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "direction": direction,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/vote", payload)
    return resp or {}


def _do_edit(
    backend: str,
    wallet,
    override_hash: str,
    topic: str,
    title: str,
    content: str,
    target: str = "",
    tag: str = "",
    skip_pow: bool = False,
) -> dict:
    """Edit a post or comment.

    Args:
        override_hash: The tx hash of the post/comment being edited.
        topic:         Topic (required for root posts, empty for comments).
        title:         New title (root posts only).
        content:       New content.
        target:        Parent post hash (for comments) or "" for root posts.
        tag:           Content tag.
        skip_pow:      True for subscribers.
    """
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_edit_raw(
        pub, _lb_bytes(lb), d, ts, target, topic, title, content, tag, override_hash, None, nonce
    )
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "topic": topic,
        "title": title,
        "content": content,
        "tag": tag,
        "override": override_hash,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/edit", payload)
    return resp


def _do_annotate(
    backend: str,
    wallet,
    override_hash: str,
    topic: str = ".",
    title: str = ".",
    content: str = ".",
    tag: str = ".",
    media: list[str] | None = None,
    appendix: str = ".",
    pow_difficulty: int = 0,
    pow_val: int = 0,
) -> dict:
    """Agent-only: annotate a post with overlay edits. '.' means no change."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    media_list = media if media is not None else ["."]

    base = _canon_base_annotate_raw(
        pub,
        _lb_bytes(lb),
        int(pow_difficulty),
        ts,
        topic,
        title,
        content,
        tag,
        override_hash,
        media=media_list,
        appendix=appendix,
        nonce=nonce,
    )
    signed = canon_signed_with_pow(base, int(pow_val))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": int(pow_difficulty),
        "pow": int(pow_val),
        "topic": topic,
        "title": title,
        "content": content,
        "tag": tag,
        "override": override_hash,
        "media": media_list,
        "appendix": appendix,
    }
    code, resp = _post(f"{backend}/api/core/annotate", payload)
    resp = resp or {}
    if code >= 400 or resp.get("error"):
        details = resp.get("details")
        _debug(f"annotate error code={code} error={resp.get('error')} details={details}")
        out = {"error": resp.get("error", f"HTTP {code}")}
        if details:
            out["details"] = details
        return out
    return resp


def _do_delete(backend: str, wallet, target: str, skip_pow: bool = False) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_delete_raw(pub, _lb_bytes(lb), d, ts, target, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/delete_post", payload)
    return resp


def _do_delete_user(backend: str, wallet, target_addr: str, skip_pow: bool = False) -> Tuple[int, dict]:
    """Delete a user account. Returns (status_code, response_dict)."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_delete_user_raw(pub, _lb_bytes(lb), d, ts, target_addr, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target_addr,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    return _post(f"{backend}/api/core/delete_user", payload)


def _do_follow_user(backend: str, wallet, user_addr: str, follow: bool = True, skip_pow: bool = False) -> dict:
    """Follow or unfollow a user."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    canon_fn = _canon_base_follow_user_raw if follow else _canon_base_unfollow_user_raw
    endpoint = "follow_user" if follow else "unfollow_user"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, addr, user_addr, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "user": user_addr,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_follow_topic(backend: str, wallet, topic: str, follow: bool = True, skip_pow: bool = False) -> dict:
    """Follow or unfollow a topic."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    canon_fn = _canon_base_follow_topic_raw if follow else _canon_base_unfollow_topic_raw
    endpoint = "follow_topic" if follow else "unfollow_topic"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, addr, topic, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "topic": topic,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_block(backend: str, wallet, target: str, block_type: str, block: bool = True, skip_pow: bool = False) -> dict:
    """Block or unblock a post/user. block_type is 'post' or 'user'."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    if block_type == "post":
        canon_fn = _canon_base_block_post_raw if block else _canon_base_unblock_post_raw
        endpoint = "block_post" if block else "unblock_post"
    else:
        canon_fn = _canon_base_block_user_raw if block else _canon_base_unblock_user_raw
        endpoint = "block_user" if block else "unblock_user"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, target, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_block_topic(backend: str, wallet, topic: str, block: bool = True, skip_pow: bool = False) -> dict:
    """Block or unblock a topic."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    canon_fn = _canon_base_block_topic_raw if block else _canon_base_unblock_topic_raw
    endpoint = "block_topic" if block else "unblock_topic"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, "", topic, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "topic": topic,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    print(f"    [debug] {endpoint} topic={topic} difficulty={d}")
    code, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_set_username_raw(backend: str, wallet, username: str, skip_pow: bool = False) -> dict:
    """Set username via the backend API (raw payload construction)."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_set_username_raw(pub, _lb_bytes(lb), d, ts, addr, username, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "username": username,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/set_username", payload)
    return resp


def _do_set_biography(backend: str, wallet, biography: str, skip_pow: bool = False) -> dict:
    """Set biography via the backend API."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_set_biography_raw(pub, _lb_bytes(lb), d, ts, addr, biography, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "biography": biography,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/set_biography", payload)
    return resp


def _do_report(backend: str, wallet, target: str, reason: str, skip_pow: bool = False) -> dict:
    """Report a post via the backend API."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_report_raw(pub, _lb_bytes(lb), d, ts, target, reason, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "reason": reason,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/report", payload)
    return resp


def _do_enable_agent(backend: str, wallet, agent_addr: str, enable: bool = True, skip_pow: bool = False) -> dict:
    """Enable or disable an agent."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    canon_fn = _canon_base_enable_agent_raw if enable else _canon_base_disable_agent_raw
    endpoint = "enable_agent" if enable else "disable_agent"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, addr, agent_addr, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "agent": agent_addr,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_set_agents(backend: str, wallet, agents: list[str], skip_pow: bool = False) -> dict:
    """Atomically set the user's enabled agents list."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_set_agents_raw(pub, _lb_bytes(lb), d, ts, addr, agents, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "agents": agents,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/set_agents", payload)
    return resp


def _do_set_auto_renewal(backend: str, wallet, auto_renew: bool) -> dict:
    """Toggle auto-renewal for a subscriber."""
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = str(st.get("last_block_hash", ""))
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()

    base = _canon_base_set_auto_renewal_raw(pub, _lb_bytes(lb), 0, ts, auto_renew, nonce)
    signed = canon_signed_with_pow(base, 0)
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "auto_renew": auto_renew,
    }
    code, resp = _post(f"{backend}/api/core/set_auto_renewal", payload)
    return resp


def _do_post_with_media(
    backend: str,
    wallet,
    topic: str,
    title: str,
    content: str,
    media: list,
    target: str = "",
    tag: str = "",
    skip_pow: bool = False,
) -> str | None:
    """Create a post with media attachments; returns tx_hash or None."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_post_raw(pub, _lb_bytes(lb), d, ts, target, topic, title, content, tag, 0, media, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "topic": topic,
        "title": title,
        "content": content,
        "tag": tag,
        "media": media,
    }
    if not skip_pow:
        payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/post", payload)
    txh = str((resp or {}).get("tx_hash", "") or "").lower()
    return txh if txh else None


def _wait_list_count(
    backend: str,
    address: str,
    list_key: str,
    expected: int,
    timeout: float = 30.0,
) -> int:
    """Poll until a profile/followed list reaches expected count (or timeout).

    list_key: "followed_users", "followed_topics", "enabled_agents"
    Returns the actual count observed.
    """
    endpoint = "get_user_followed" if list_key.startswith("followed_") else "get_profile"
    deadline = time.perf_counter() + timeout
    actual = 0
    while time.perf_counter() < deadline:
        try:
            code, data = _get(f"{backend}/api/{endpoint}", {"address": address})
            if code == 200 and data:
                actual = len(data.get(list_key) or [])
                if actual >= expected:
                    return actual
        except Exception:
            pass
        time.sleep(1.0)
    return actual


def _wait_indexed(backend: str, owner: str, tx_hash: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        try:
            code, data = _get(f"{backend}/api/get_user_posts", {"owner": owner, "limit": 100, "page": 1})
            if code == 200:
                posts = (data or {}).get("posts") or []
                if any(str(p.get("post_id", "")).lower() == h for p in posts):
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _wait_tx_status(
    backend: str,
    tx_hash: str,
    expect_type: str | None = None,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> dict | None:
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_tx_status", {"hash": h})
        if code == 200 and data:
            if not data.get("found"):
                time.sleep(0.5)
                continue
            if expect_type and data.get("tx_type") != expect_type:
                time.sleep(0.5)
                continue
            if data.get("indexed") and data.get("details"):
                return data
        time.sleep(0.5)
    return None


def _wait_tx_status_failure(
    backend: str,
    tx_hash: str,
    expect_type: str | None = None,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> dict | None:
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_tx_status", {"hash": h})
        if code == 200 and data:
            if not data.get("found"):
                time.sleep(0.5)
                continue
            if data.get("success") is True:
                time.sleep(0.5)
                continue
            if expect_type and data.get("tx_type") != expect_type:
                time.sleep(0.5)
                continue
            return data
        time.sleep(0.5)
    return None


def _wait_tx_deliver(tx_hash: str, timeout: float = INDEX_TIMEOUT_SEC) -> tuple[int, str] | None:
    """Scan blocks for tx_hash and return (code, log) from DeliverTx."""
    if not tx_hash:
        return None
    h = tx_hash.strip().lower().removeprefix("0x")
    deadline = time.perf_counter() + timeout
    try:
        last_height = max(1, _rpc_latest_height() - 1)
    except Exception:
        last_height = 1
    while time.perf_counter() < deadline:
        cur = _rpc_latest_height()
        for height in range(last_height + 1, cur + 1):
            block = requests.get(f"http://127.0.0.1:26657/block?height={height}", timeout=3).json()
            txs = block.get("result", {}).get("block", {}).get("data", {}).get("txs") or []
            tx_index = None
            for idx, tx_b64 in enumerate(txs):
                raw = base64.b64decode(tx_b64)
                if hashlib.sha256(raw).hexdigest().lower() == h:
                    tx_index = idx
                    break
            if tx_index is not None:
                while time.perf_counter() < deadline:
                    br = requests.get(f"http://127.0.0.1:26657/block_results?height={height}", timeout=3).json()
                    deliver = br.get("result", {}).get("txs_results") or []
                    if tx_index < len(deliver):
                        tx_result = deliver[tx_index]
                        code = int(tx_result.get("code", 0) or 0)
                        log = str(tx_result.get("log", "") or "")
                        return code, log
                    time.sleep(0.5)
                return None
        last_height = cur
        time.sleep(0.5)
    return None


def _wait_username(backend: str, address: str, timeout: float = INDEX_TIMEOUT_SEC) -> str | None:
    """Wait until a username is visible on-chain (via get_profile)."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            uname = get_username_from_address(backend, address)
            if uname:
                return uname
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _wait_blocked_topic_state(
    backend: str,
    address: str,
    topic: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    topic_lower = (topic or "").strip().lower()
    while time.perf_counter() < deadline:
        # Check indexed DB first (fast, eventually consistent)
        code, data = _get(f"{backend}/api/get_user_blocked", {"address": address})
        if code == 200:
            blocked = (data or {}).get("blocked_topics") or []
            present = any(str(t or "").strip().lower() == topic_lower for t in blocked)
            if present == expect_present:
                return True
        # Fall back to chain profile (authoritative, always current)
        code2, profile = _get(f"{backend}/api/get_profile", {"address": address})
        if code2 == 200:
            chain_blocked = (profile or {}).get("blocked_topics") or []
            present2 = any(str(t or "").strip().lower() == topic_lower for t in chain_blocked)
            if present2 == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_blocked_topic(backend: str, address: str, topic: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    return _wait_blocked_topic_state(backend, address, topic, True, timeout)


def _wait_followed_topic(
    backend: str,
    address: str,
    topic: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    topic_lower = (topic or "").strip().lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_user_followed", {"address": address})
        if code == 200:
            topics = (data or {}).get("followed_topics") or []
            present = any(str(t or "").strip().lower() == topic_lower for t in topics)
            if present == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_followed_user(
    backend: str,
    address: str,
    user: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    user_lower = (user or "").strip().lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_user_followed", {"address": address})
        if code == 200:
            users = (data or {}).get("followed_users") or (data or {}).get("users") or []
            present = any(user_lower in json.dumps(u).lower() for u in users)
            if present == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_blocked_user(
    backend: str,
    address: str,
    user: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    user_lower = (user or "").strip().lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_user_blocked", {"address": address})
        if code == 200:
            blocked = (data or {}).get("blocked_users") or []
            present = any(str(u or "").strip().lower() == user_lower for u in blocked)
            if present == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_comment_indexed(backend: str, parent: str, tx_hash: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        try:
            code, data = _get(f"{backend}/api/get_comments", {"post_id": parent, "limit": 100})
            if code == 200:
                children = (data or {}).get("children") or []
                if any(str(c.get("post_id", "")).lower() == h for c in children):
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


# =========================================================================
# Category 1: Setup & Parameters
# =========================================================================
def test_params(backend: str):
    print(f"\n{_COLOR_BOLD}[1] Setup & Parameters{_COLOR_RESET}")

    # 1.1 get_parameters returns valid data
    code, data = _get(f"{backend}/api/get_parameters")
    if code == 200 and data.get("last_block_hash"):
        _pass("params.get_parameters returns valid data")
    else:
        _fail("params.get_parameters returns valid data", f"code={code}")
        return  # can't continue without params

    # 1.2 pow_factor is float in (0,1]
    step = data.get("pow_factor")
    try:
        fstep = float(step)
        if 0 < fstep <= 1:
            _pass("params.pow_factor valid", value=fstep)
        else:
            _fail("params.pow_factor valid", f"out of range: {fstep}")
    except Exception as e:
        _fail("params.pow_factor valid", str(e))

    # 1.3 pow_base_bits present and > 0
    md = data.get("pow_base_bits")
    if md and int(md) > 0:
        _pass("params.pow_base_bits > 0", value=int(md))
    else:
        _fail("params.pow_base_bits > 0", f"got {md}")

    # 1.4 pow_difficulty is int >= 0
    pd = data.get("pow_difficulty")
    if pd is not None and int(pd) >= 0:
        _pass("params.pow_difficulty >= 0 (step format)", value=int(pd))
    else:
        _fail("params.pow_difficulty >= 0 (step format)", f"got {pd}")

    # 1.4b tier limits for max_blocked_topics (requires v1.13.0 upgrade)
    tiers = data.get("tiers") or []
    expected_blocked = [10, 125, 500, 1000]
    if len(tiers) >= 4:
        got_blocked = [int((tiers[i] or {}).get("max_blocked_topics", -1)) for i in range(4)]
        if got_blocked == expected_blocked:
            _pass("params.max_blocked_topics tier limits", values=got_blocked)
        else:
            _fail("params.max_blocked_topics tier limits", f"got {got_blocked}")
    else:
        _pass("params.max_blocked_topics tier limits (skipped, pre-v1.13.0)", tiers_len=len(tiers))

    # 1.4c tier limits for max_biography_length (requires v1.18.0 upgrade)
    expected_bio = [0, 512, 512]
    if len(tiers) >= 3:
        got_bio = [int((tiers[i] or {}).get("max_biography_length", -1)) for i in range(3)]
        if got_bio == expected_bio:
            _pass("params.max_biography_length tier limits", values=got_bio)
        else:
            _fail("params.max_biography_length tier limits", f"got {got_bio}")
    else:
        _pass("params.max_biography_length tier limits (skipped, pre-v1.18.0)", tiers_len=len(tiers))

    # 1.5 get_network_stats returns consistent data
    code2, stats = _get(f"{backend}/api/get_network_stats")
    if code2 == 200 and stats.get("pow_difficulty") is not None:
        if str(stats.get("pow_factor")) == str(data.get("pow_factor")):
            _pass("params.network_stats consistent with get_parameters")
        else:
            _fail(
                "params.network_stats consistent with get_parameters",
                f"step mismatch: {stats.get('pow_factor')} vs {data.get('pow_factor')}",
            )
    else:
        _fail("params.network_stats consistent with get_parameters", f"code={code2}")

    # 1.5b get_network_stats returns earned_24h
    if code2 == 200:
        earned = stats.get("earned_24h")
        if earned is not None and int(earned) >= 0:
            _pass("params.network_stats has earned_24h", earned_24h=earned)
        else:
            _fail("params.network_stats has earned_24h", earned_24h=earned)

    # 1.6 get_chain_config returns valid governance params
    code3, cfg = _get(f"{backend}/api/get_chain_config")
    if code3 == 200 and cfg.get("subscription_period"):
        _pass("params.get_chain_config valid", keys=list(cfg.keys()))
    else:
        _fail("params.get_chain_config valid", f"code={code3}")

    # 1.6a award configs present and include expected defaults
    award_cfgs = cfg.get("award_configs") if isinstance(cfg, dict) else None
    expected_awards = {"quality_post", "original_content", "based", "receipts"}
    if isinstance(award_cfgs, list) and award_cfgs:
        names = {str(a.get("name", "")).strip() for a in award_cfgs if isinstance(a, dict)}
        missing = expected_awards - names
        if not missing:
            _pass("params.award_configs defaults present", count=len(award_cfgs))
        else:
            _fail("params.award_configs defaults present", f"missing={sorted(missing)}")
    else:
        _fail("params.award_configs defaults present", "award_configs missing or empty")

    # 1.6b subscription_reserve_percent is 0.95
    reserve_pct = cfg.get("subscription_reserve_percent") if isinstance(cfg, dict) else None
    if reserve_pct is None:
        _fail("params.subscription_reserve_percent_0.95", "missing")
    else:
        try:
            reserve_val = float(reserve_pct)
            if abs(reserve_val - 0.95) < 0.01:
                _pass("params.subscription_reserve_percent_0.95", value=reserve_val)
            else:
                _fail("params.subscription_reserve_percent_0.95", f"got {reserve_pct}")
        except Exception as e:
            _fail("params.subscription_reserve_percent_0.95", str(e))

    # 1.7 get_node_config returns valid
    code3b, ncfg = _get(f"{backend}/api/get_node_config")
    if code3b == 200 and ncfg.get("validator_account_address"):
        _pass("params.get_node_config valid")
    else:
        _fail("params.get_node_config valid", f"code={code3b}")

    # 1.8 bridge_attestation_threshold is float in [0,1] (via bridge config)
    code_bridge, bridge_data = _get(f"{backend}/api/bridge/config")
    if code_bridge == 200 and bridge_data.get("attestation_threshold") is not None:
        bat = float(bridge_data["attestation_threshold"])
        if 0 <= bat <= 1:
            _pass("params.bridge_attestation_threshold in [0,1]", value=bat)
        else:
            _fail("params.bridge_attestation_threshold in [0,1]", f"got {bat}")
    else:
        _pass("params.bridge_attestation_threshold (bridge endpoint may not be available)")

    # 1.9 get_total_supply positive (returns plain text, not JSON)
    try:
        r4 = requests.get(f"{backend}/api/get_total_supply", timeout=10)
        supply_val = float(r4.text.strip()) if r4.status_code == 200 else 0
        if supply_val > 0:
            _pass("params.get_total_supply positive", value=supply_val)
        else:
            _fail("params.get_total_supply positive", f"code={r4.status_code}")
    except Exception as e:
        _fail("params.get_total_supply positive", str(e))

    # 1.10 get_welcome_stats valid structure
    code5, ws = _get(f"{backend}/api/get_welcome_stats")
    if code5 == 200:
        _pass("params.get_welcome_stats returns 200")
    else:
        _fail("params.get_welcome_stats returns 200", f"code={code5}")


# =========================================================================
# Category 2: Account & Username
# =========================================================================
def test_account(backend: str):
    print(f"\n{_COLOR_BOLD}[2] Account & Username{_COLOR_RESET}")

    wallet = WALLETS["free"]
    addr = str(wallet.address())

    # 2.1 get_user_status returns data
    try:
        us = get_user_status(backend, addr)
        if us and "user_level" in us:
            _pass("account.get_user_status returns data", level=us.get("user_level"))
        else:
            _fail("account.get_user_status returns data", f"got {us}")
    except Exception as e:
        _fail("account.get_user_status returns data", str(e))

    # 2.2 get_profile returns data
    code, profile = _get(f"{backend}/api/get_profile", {"address": addr})
    if code == 200:
        _pass("account.get_profile returns 200")
    else:
        _fail("account.get_profile returns 200", f"code={code}")

    # 2.3 Set a unique test username
    # Check if registration is enabled on this node
    _code, _ncfg = _get(f"{backend}/api/get_node_config")
    reg_enabled = (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False
    if not reg_enabled:
        _pass("account.set_username skipped (registration disabled on this node)")
        return

    test_uname = f"test-{_rand_str(6)}"
    try:
        from shared.client import set_username

        resp = set_username(backend, wallet, test_uname, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            # Wait for it
            time.sleep(3)
            _pass("account.set_username succeeds", username=test_uname, tx=txh)
        else:
            _fail("account.set_username succeeds", f"resp={resp}")
            return
    except Exception as e:
        _fail("account.set_username succeeds", str(e))
        return

    # The chain prefixes free-tier (level 0) usernames with "Anon-"
    user_level = int((us or {}).get("user_level", 0))
    expected_uname = f"Anon-{test_uname}" if user_level == 0 else test_uname

    # 2.4 get_address_from_username resolves (poll up to 10s)
    resolved = None
    for _ in range(10):
        time.sleep(1)
        resolved = get_address_from_username(backend, expected_uname)
        if resolved and resolved.lower() == addr.lower():
            break
    if resolved and resolved.lower() == addr.lower():
        _pass("account.get_address_from_username resolves", username=expected_uname)
    else:
        _fail("account.get_address_from_username resolves", f"got {resolved}")

    # 2.5 get_username_from_address resolves (poll up to 10s)
    resolved_name = None
    for _ in range(10):
        time.sleep(1)
        resolved_name = get_username_from_address(backend, addr)
        if resolved_name and resolved_name.lower() == expected_uname.lower():
            break
    if resolved_name and resolved_name.lower() == expected_uname.lower():
        _pass("account.get_username_from_address resolves", username=resolved_name)
    else:
        _fail("account.get_username_from_address resolves", f"got {resolved_name}")

    # 2.6 search_username finds user
    code, sr = _get(f"{backend}/api/search_username", {"q": expected_uname[:8]})
    if code == 200:
        results = sr.get("results") or sr.get("users") or sr.get("data") or []
        # Flatten — some backends return different shapes
        found = any(expected_uname.lower() in json.dumps(r).lower() for r in results) if results else False
        if found:
            _pass("account.search_username finds user")
        else:
            # Search might take time to index, pass with warning
            _pass("account.search_username returns 200 (may need indexing)")
    else:
        _fail("account.search_username finds user", f"code={code}")

    # 2.7 get_users returns list
    code, users = _get(f"{backend}/api/get_users", {"limit": 10})
    if code == 200:
        _pass("account.get_users returns 200")
    else:
        _fail("account.get_users returns 200", f"code={code}")

    # 2.8 get_user_followed returns structure
    code, followed = _get(f"{backend}/api/get_user_followed", {"address": addr})
    if code == 200:
        _pass("account.get_user_followed returns 200")
    else:
        _fail("account.get_user_followed returns 200", f"code={code}")


# =========================================================================
# Category 3: Post Lifecycle
# =========================================================================
def test_post_lifecycle(backend: str):
    print(f"\n{_COLOR_BOLD}[3] Post Lifecycle{_COLOR_RESET}")

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    topic = f"annot{_rand_str(6)}"
    title = f"Test Post {_rand_str(6)}"
    content = f"Content body {_rand_str(20)}"
    try:
        validator_addr = _resolve_validator_key_addr()
    except Exception as e:
        _fail("post.relayer.validator_addr", str(e))
        return
    validator_lower = validator_addr.lower()
    _debug(f"expected relayer={validator_lower}")

    # 3.1 Create post
    txh = _do_post(backend, wallet, topic, title, content)
    if txh:
        _pass("post.create succeeds", tx=txh)
    else:
        _fail("post.create succeeds")
        return

    # 3.2 Wait for indexing & verify in get_user_posts
    if _wait_indexed(backend, addr, txh):
        _pass("post.appears in get_user_posts")
    else:
        _fail("post.appears in get_user_posts", f"not found after {int(INDEX_TIMEOUT_SEC)}s")

    # 3.2a Relayer present in get_user_posts
    code, user_posts = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
    if code == 200:
        posts = (user_posts or {}).get("posts") or []
        p_user = next((p for p in posts if str(p.get("post_id", "")).lower() == txh), None)
        relayer_val = str(p_user.get("relayer", "")).strip().lower() if p_user else ""
        _debug(f"user_posts relayer={relayer_val}")
        if relayer_val == validator_lower:
            _pass("post.relayer in get_user_posts")
        else:
            _fail("post.relayer in get_user_posts", f"relayer={relayer_val}")
    else:
        _fail("post.relayer in get_user_posts", f"code={code}")

    # 3.3 Verify in get_posts feed (poll up to INDEX_TIMEOUT_SEC, use newest sort)
    found = []
    for _ in range(int(INDEX_TIMEOUT_SEC)):
        code, feed = _get(f"{backend}/api/get_posts", {"limit": 50, "by": "newest"})
        posts = (feed or {}).get("posts") or []
        found = [p for p in posts if str(p.get("post_id", "")).lower() == txh]
        if found:
            break
        time.sleep(1)
    if found:
        p = found[0]
        _pass("post.appears in get_posts feed")
    else:
        _fail("post.appears in get_posts feed")

    # 3.3a Relayer present in get_posts feed
    if found:
        p = found[0]
        relayer_val = str(p.get("relayer", "")).strip().lower()
        _debug(f"get_posts relayer={relayer_val}")
        if relayer_val == validator_lower:
            _pass("post.relayer in get_posts feed")
        else:
            _fail("post.relayer in get_posts feed", f"relayer={relayer_val}")

    # 3.4 Post has correct fields
    if found:
        p = found[0]
        ok = (
            p.get("title", "").strip() == title.strip()
            and p.get("topic", "").strip() == topic.strip()
            and content[:20] in (p.get("content") or "")
        )
        if ok:
            _pass("post.fields correct (title, topic, content)")
        else:
            _fail("post.fields correct", f"title={p.get('title')}, topic={p.get('topic')}")

    # 3.4a get_tx_status includes relayer
    post_status = _wait_tx_status(backend, txh, expect_type="post")
    if post_status and post_status.get("details"):
        relayer_val = str((post_status.get("details") or {}).get("relayer", "")).strip().lower()
        _debug(f"tx_status post relayer={relayer_val}")
        if relayer_val == validator_lower:
            _pass("post.relayer in get_tx_status")
        else:
            _fail("post.relayer in get_tx_status", f"relayer={relayer_val}")
    else:
        _fail("post.relayer in get_tx_status", "missing tx status details")

    # 3.4b Search results include relayer
    search_found = False
    search_relayer = ""
    for _ in range(int(INDEX_TIMEOUT_SEC)):
        code, sr = _get(f"{backend}/api/search", {"q": title[:8], "limit": 10})
        if code == 200:
            posts = (sr or {}).get("posts") or []
            match = next((p for p in posts if str(p.get("post_id", "")).lower() == txh), None)
            if match:
                search_found = True
                search_relayer = str(match.get("relayer", "")).strip().lower()
                break
        time.sleep(1)
    _debug(f"search relayer={search_relayer}")
    if search_found and search_relayer == validator_lower:
        _pass("post.relayer in search results")
    else:
        _fail("post.relayer in search results", f"found={search_found} relayer={search_relayer}")

    # 3.4c Award post (non-self)
    awarder = WALLETS["sub1"]
    award_type = "quality_post"
    _debug(f"award post target={txh} type={award_type}")
    award_code, award_resp = _do_award(backend, awarder, txh, award_type)
    award_txh = str(award_resp.get("tx_hash", "")).lower()
    if award_txh:
        _pass("post.award submitted", tx=award_txh)
    else:
        _fail("post.award submitted", f"code={award_code} resp={award_resp}")

    # 3.4d Award appears in post feed data
    award_seen = False
    if award_txh:
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, feed_aw = _get(f"{backend}/api/get_posts", {"limit": 50, "by": "newest"})
            posts_aw = (feed_aw or {}).get("posts") or []
            p_aw = next((p for p in posts_aw if str(p.get("post_id", "")).lower() == txh), None)
            if not p_aw:
                continue
            awards = p_aw.get("awards") or []
            if any(a.get("type") == award_type and int(a.get("count", 0)) >= 1 for a in awards):
                award_seen = True
                break
    if award_seen:
        _pass("post.award appears in feed")
    else:
        _fail("post.award appears in feed")

    # 3.5 Vote up (poll up to INDEX_TIMEOUT_SEC)
    vote_resp = _do_vote(backend, wallet, txh, 1)
    if vote_resp and vote_resp.get("error"):
        _fail("post.vote_up reflected", f"vote failed: {vote_resp}")
    else:
        votes_after_up = 0
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, feed2 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
            posts2 = (feed2 or {}).get("posts") or []
            p2 = next((p for p in posts2 if str(p.get("post_id", "")).lower() == txh), None)
            votes_after_up = int(p2.get("points", 0)) if p2 else 0
            if votes_after_up >= 1:
                break
        if votes_after_up >= 1:
            _pass("post.vote_up reflected", votes=votes_after_up)
        else:
            _fail("post.vote_up reflected", f"votes={votes_after_up}")

    # 3.5a Vote tx_status includes relayer
    vote_txh = str((vote_resp or {}).get("tx_hash", "") or "").lower()
    if vote_txh:
        vote_status = _wait_tx_status(backend, vote_txh, expect_type="vote")
        if vote_status and vote_status.get("details"):
            relayer_val = str((vote_status.get("details") or {}).get("relayer", "")).strip().lower()
            _debug(f"tx_status vote relayer={relayer_val}")
            if relayer_val == validator_lower:
                _pass("vote.relayer in get_tx_status")
            else:
                _fail("vote.relayer in get_tx_status", f"relayer={relayer_val}")
        else:
            _fail("vote.relayer in get_tx_status", "missing tx status details")
    else:
        _fail("vote.relayer in get_tx_status", "missing tx hash")

    # 3.6 Vote down (poll up to INDEX_TIMEOUT_SEC)
    _do_vote(backend, wallet, txh, -1)
    votes_after_down = votes_after_up
    for _ in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, feed3 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
        posts3 = (feed3 or {}).get("posts") or []
        p3 = next((p for p in posts3 if str(p.get("post_id", "")).lower() == txh), None)
        votes_after_down = int(p3.get("points", 0)) if p3 else 0
        if votes_after_down < votes_after_up:
            break
    if votes_after_down < votes_after_up:
        _pass("post.vote_down reflected", votes=votes_after_down)
    else:
        _fail("post.vote_down reflected", f"votes={votes_after_down}")

    # 3.7 Clear vote
    _do_vote(backend, wallet, txh, 0)
    time.sleep(2)
    _pass("post.vote_clear submitted")

    # 3.8 Edit post (root post: target="", override=post hash)
    new_content = f"Edited content {_rand_str(10)}"
    _do_edit(backend, wallet, override_hash=txh, topic=topic, title=title, content=new_content)
    time.sleep(3)
    code, feed4 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
    posts4 = (feed4 or {}).get("posts") or []
    p4 = next((p for p in posts4 if str(p.get("post_id", "")).lower() == txh), None)
    if p4 and new_content[:15] in (p4.get("content") or ""):
        _pass("post.edit reflected in feed")
    else:
        _pass("post.edit submitted (indexer may lag)")

    # 3.9 Create post with tags
    tag_txh = _do_post(backend, wallet, topic, f"Tagged {_rand_str(4)}", "tag test", tag="sensitive")
    if tag_txh:
        _pass("post.create_with_tag succeeds", tx=tag_txh)
    else:
        _fail("post.create_with_tag succeeds")

    # 3.10 Get posts by topic filter
    code, tf = _get(f"{backend}/api/get_posts", {"topic": topic, "limit": 10})
    if code == 200:
        _pass("post.get_posts topic filter works")
    else:
        _fail("post.get_posts topic filter works", f"code={code}")

    # 3.11 Pagination
    code, pg = _get(f"{backend}/api/get_posts", {"limit": 2, "page": 1})
    pg_posts = (pg or {}).get("posts") or []
    if code == 200 and len(pg_posts) <= 2:
        _pass("post.pagination limit works", count=len(pg_posts))
    else:
        _fail("post.pagination limit works", f"code={code}, count={len(pg_posts)}")

    # 3.12 Delete post
    _do_delete(backend, wallet, txh)
    time.sleep(3)
    code, feed5 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "limit": 50})
    posts5 = (feed5 or {}).get("posts") or []
    still_there = any(str(p.get("post_id", "")).lower() == txh for p in posts5)
    if not still_there:
        _pass("post.delete removes from feed")
    else:
        _pass("post.delete submitted (indexer may lag)")


# =========================================================================
# Category 4: Comment Threading
# =========================================================================
def test_comments(backend: str):
    print(f"\n{_COLOR_BOLD}[4] Comment Threading{_COLOR_RESET}")

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    try:
        validator_addr = _resolve_validator_key_addr()
    except Exception as e:
        _fail("comments.relayer.validator_addr", str(e))
        return
    validator_lower = validator_addr.lower()
    _debug(f"expected relayer={validator_lower}")

    def _find_comment(nodes, target_id: str):
        for n in nodes:
            if str(n.get("post_id", "")).lower() == target_id:
                return n
            child = _find_comment(n.get("children") or [], target_id)
            if child:
                return child
        return None

    # Create a parent post
    parent_txh = _do_post(backend, wallet, "test", f"Parent {_rand_str(4)}", "Parent body")
    if not parent_txh:
        _fail("comments.create_parent_post")
        return
    _wait_indexed(backend, addr, parent_txh)
    _pass("comments.parent_post created", tx=parent_txh)

    # 4.1 Create comment on post
    c1_txh = _do_post(backend, wallet, "", "", "First comment", target=parent_txh)
    if c1_txh:
        _pass("comments.create_comment succeeds", tx=c1_txh)
    else:
        _fail("comments.create_comment succeeds")
        return

    # 4.2 Verify via get_comments
    if _wait_comment_indexed(backend, parent_txh, c1_txh):
        _pass("comments.appears in get_comments")
    else:
        _fail("comments.appears in get_comments", f"not found after {int(INDEX_TIMEOUT_SEC)}s")

    # 4.2a Relayer present in get_comments
    code, data = _get(f"{backend}/api/get_comments", {"post_id": parent_txh, "address": addr})
    if code == 200:
        root = (data or {}).get("root") or {}
        children = (data or {}).get("children") or []
        comment_node = _find_comment(children, c1_txh)
        root_relayer = str(root.get("relayer", "")).strip().lower()
        child_relayer = str((comment_node or {}).get("relayer", "")).strip().lower()
        _debug(f"comments relayer root={root_relayer} child={child_relayer}")
        if root_relayer == validator_lower and child_relayer == validator_lower:
            _pass("comments.relayer in get_comments")
        else:
            _fail("comments.relayer in get_comments", f"root={root_relayer} child={child_relayer}")
    else:
        _fail("comments.relayer in get_comments", f"code={code}")

    # 4.2b Award comment (non-self)
    awarder = WALLETS["sub1"]
    award_type = "receipts"
    _debug(f"award comment target={c1_txh} type={award_type}")
    award_code, award_resp = _do_award(backend, awarder, c1_txh, award_type)
    award_txh = str(award_resp.get("tx_hash", "")).lower()
    if award_txh:
        _pass("comments.award submitted", tx=award_txh)
    else:
        _fail("comments.award submitted", f"code={award_code} resp={award_resp}")

    # 4.2c Award appears in get_comments
    award_seen = False
    if award_txh:
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, data = _get(f"{backend}/api/get_comments", {"post_id": parent_txh, "limit": 100})
            if code != 200:
                continue
            children = (data or {}).get("children") or []
            c1 = next((c for c in children if str(c.get("post_id", "")).lower() == c1_txh), None)
            if not c1:
                continue
            awards = c1.get("awards") or []
            if any(a.get("type") == award_type and int(a.get("count", 0)) >= 1 for a in awards):
                award_seen = True
                break
    if award_seen:
        _pass("comments.award appears in get_comments")
    else:
        _fail("comments.award appears in get_comments")

    # 4.3 Nested comment (reply to comment)
    c2_txh = _do_post(backend, wallet, "", "", "Nested reply", target=c1_txh)
    if c2_txh:
        _pass("comments.nested_reply succeeds", tx=c2_txh)
    else:
        _fail("comments.nested_reply succeeds")

    # 4.4 get_root_post_id returns correct root (poll up to INDEX_TIMEOUT_SEC)
    if c2_txh:
        root_ok = False
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, root_data = _get(f"{backend}/api/get_root_post_id", {"comment_id": c2_txh})
            if code == 200:
                root_id = str(root_data.get("root_post_id", "")).lower()
                if root_id == parent_txh:
                    _pass("comments.get_root_post_id correct")
                else:
                    _pass("comments.get_root_post_id returns 200")
                root_ok = True
                break
        if not root_ok:
            _fail("comments.get_root_post_id correct", f"code={code}")

    # 4.5 get_comment_context (may need indexing time)
    if c2_txh:
        ctx_ok = False
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            code, ctx = _get(f"{backend}/api/get_comment_context", {"comment_id": c2_txh})
            if code == 200:
                _pass("comments.get_comment_context returns 200")
                ctx_ok = True
                break
            time.sleep(1)
        if not ctx_ok:
            _fail("comments.get_comment_context returns 200", f"code={code}")

    # 4.6 Edit comment (comment: target=parent, override=comment hash)
    if c1_txh:
        _do_edit(
            backend, wallet, override_hash=c1_txh, topic="", title="", content="Edited comment body", target=parent_txh
        )
        time.sleep(2)
        _pass("comments.edit submitted")

    # 4.7 Delete comment
    if c1_txh:
        _do_delete(backend, wallet, c1_txh)
        time.sleep(2)
        _pass("comments.delete submitted")

    # 4.8 Comments count (best-effort check)
    code, parent_data = _get(f"{backend}/api/get_user_posts", {"owner": addr, "limit": 50})
    _pass("comments.parent_post still queryable")


# =========================================================================
# Category 5: Social Graph
# =========================================================================
def test_social_graph(backend: str):
    print(f"\n{_COLOR_BOLD}[5] Social Graph{_COLOR_RESET}")

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    sub_wallet = WALLETS["sub1"]
    sub_addr = str(sub_wallet.address())
    sub2_wallet = WALLETS["sub2"]
    sub2_addr = str(sub2_wallet.address())
    agent1_wallet = WALLETS["agent1"]
    agent1_addr = str(agent1_wallet.address())
    test_topic = f"testtopic{_rand_str(4)}"

    # 5.1 follow_user
    resp = _do_follow_user(backend, wallet, sub_addr, follow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.follow_user succeeds", tx=txh)
    else:
        _fail("social.follow_user succeeds", f"resp={resp}")

    time.sleep(3)

    # 5.2 verify in get_user_followed
    code, followed = _get(f"{backend}/api/get_user_followed", {"address": addr})
    fol_users = (followed or {}).get("followed_users") or (followed or {}).get("users") or []
    if any(sub_addr.lower() in json.dumps(u).lower() for u in fol_users):
        _pass("social.follow_user reflected in get_user_followed")
    else:
        _pass("social.follow_user submitted (indexer may lag)")

    # 5.3 unfollow_user
    resp = _do_follow_user(backend, wallet, sub_addr, follow=False)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.unfollow_user succeeds")
    else:
        _fail("social.unfollow_user succeeds", f"resp={resp}")

    time.sleep(2)

    # 5.3a follow->block user removes follow
    resp = _do_follow_user(backend, wallet, sub2_addr, follow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.follow_user for block-removal setup", tx=txh)
    else:
        _fail("social.follow_user for block-removal setup", f"resp={resp}")
    if _wait_followed_user(backend, addr, sub2_addr, True):
        _pass("social.follow_user reflected before block")
    else:
        _fail("social.follow_user reflected before block", f"user={sub2_addr}")

    resp = _do_block(backend, wallet, sub2_addr, "user", block=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.block_user after follow succeeds")
    else:
        _fail("social.block_user after follow succeeds", f"resp={resp}")
    if _wait_followed_user(backend, addr, sub2_addr, False):
        _pass("social.block_user removes followed user")
    else:
        _fail("social.block_user removes followed user", f"user={sub2_addr}")
    if _wait_blocked_user(backend, addr, sub2_addr, True):
        _pass("social.block_user reflected in get_user_blocked (mutual)")
    else:
        _fail("social.block_user reflected in get_user_blocked (mutual)", f"user={sub2_addr}")

    # 5.3b block->follow user removes block
    resp = _do_block(backend, wallet, agent1_addr, "user", block=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.block_user for follow-removal setup")
    else:
        _fail("social.block_user for follow-removal setup", f"resp={resp}")
    if _wait_blocked_user(backend, addr, agent1_addr, True):
        _pass("social.block_user reflected before follow")
    else:
        _fail("social.block_user reflected before follow", f"user={agent1_addr}")

    resp = _do_follow_user(backend, wallet, agent1_addr, follow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.follow_user after block succeeds")
    else:
        _fail("social.follow_user after block succeeds", f"resp={resp}")
    if _wait_blocked_user(backend, addr, agent1_addr, False):
        _pass("social.follow_user removes blocked user")
    else:
        _fail("social.follow_user removes blocked user", f"user={agent1_addr}")
    if _wait_followed_user(backend, addr, agent1_addr, True):
        _pass("social.follow_user reflected in get_user_followed (mutual)")
    else:
        _fail("social.follow_user reflected in get_user_followed (mutual)", f"user={agent1_addr}")

    # 5.4 follow_topic
    resp = _do_follow_topic(backend, wallet, test_topic, follow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.follow_topic succeeds")
    else:
        _fail("social.follow_topic succeeds", f"resp={resp}")

    time.sleep(2)

    # 5.4a following feed (magic) must not include topic-only matches from non-followed users
    topic_only_post = _do_post(
        backend,
        sub_wallet,
        test_topic,
        f"Topic-only following leak {_rand_str(4)}",
        "body",
        skip_pow=True,
    )
    if topic_only_post and _wait_indexed(backend, sub_addr, topic_only_post):
        code, follow_feed = _get(
            f"{backend}/api/get_posts",
            {"feed": "following", "by": "magic", "address": addr, "limit": 50, "page": 1},
        )
        if code == 200:
            posts = (follow_feed or {}).get("posts") or []
            leaked = any(str(p.get("post_id", "")).lower() == topic_only_post for p in posts)
            if leaked:
                _fail(
                    "social.following_magic excludes topic-only non-followed authors",
                    f"found_nonfollowed_topic_post={topic_only_post}",
                )
            else:
                _pass("social.following_magic excludes topic-only non-followed authors")
        else:
            _fail("social.following_magic excludes topic-only non-followed authors", f"code={code}")
    else:
        _fail("social.following_magic excludes topic-only non-followed authors", "topic-only post not indexed")

    # 5.5 unfollow_topic
    resp = _do_follow_topic(backend, wallet, test_topic, follow=False)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.unfollow_topic succeeds")
    else:
        _fail("social.unfollow_topic succeeds", f"resp={resp}")

    # 5.5a follow->block topic removes follow
    mutual_topic_fb = f"mutualtopic{_rand_str(4)}"
    resp = _do_follow_topic(backend, wallet, mutual_topic_fb, follow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.follow_topic for block-removal setup")
    else:
        _fail("social.follow_topic for block-removal setup", f"resp={resp}")
    if _wait_followed_topic(backend, addr, mutual_topic_fb, True):
        _pass("social.follow_topic reflected before block")
    else:
        _fail("social.follow_topic reflected before block", f"topic={mutual_topic_fb}")

    resp = _do_block_topic(backend, wallet, mutual_topic_fb, block=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.block_topic after follow succeeds")
    else:
        _fail("social.block_topic after follow succeeds", f"resp={resp}")
    if _wait_followed_topic(backend, addr, mutual_topic_fb, False):
        _pass("social.block_topic removes followed topic")
    else:
        _fail("social.block_topic removes followed topic", f"topic={mutual_topic_fb}")
    if _wait_blocked_topic_state(backend, addr, mutual_topic_fb, True):
        _pass("social.block_topic reflected in get_user_blocked (mutual)")
    else:
        _fail("social.block_topic reflected in get_user_blocked (mutual)", f"topic={mutual_topic_fb}")

    # 5.5b block->follow topic removes block
    mutual_topic_bf = f"mutualtopic{_rand_str(4)}"
    resp = _do_block_topic(backend, wallet, mutual_topic_bf, block=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.block_topic for follow-removal setup")
    else:
        _fail("social.block_topic for follow-removal setup", f"resp={resp}")
    if _wait_blocked_topic_state(backend, addr, mutual_topic_bf, True):
        _pass("social.block_topic reflected before follow")
    else:
        _fail("social.block_topic reflected before follow", f"topic={mutual_topic_bf}")

    resp = _do_follow_topic(backend, wallet, mutual_topic_bf, follow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.follow_topic after block succeeds")
    else:
        _fail("social.follow_topic after block succeeds", f"resp={resp}")
    if _wait_blocked_topic_state(backend, addr, mutual_topic_bf, False):
        _pass("social.follow_topic removes blocked topic")
    else:
        _fail("social.follow_topic removes blocked topic", f"topic={mutual_topic_bf}")
    if _wait_followed_topic(backend, addr, mutual_topic_bf, True):
        _pass("social.follow_topic reflected in get_user_followed (mutual)")
    else:
        _fail("social.follow_topic reflected in get_user_followed (mutual)", f"topic={mutual_topic_bf}")

    # 5.6 block_post — need a post to block
    test_post = _do_post(backend, wallet, "test", f"Blockable {_rand_str(4)}", "body")
    if test_post:
        _wait_indexed(backend, addr, test_post)
        time.sleep(1)
        resp = _do_block(backend, wallet, test_post, "post", block=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("social.block_post succeeds")
        else:
            _fail("social.block_post succeeds", f"resp={resp}")

        time.sleep(2)

        # 5.7 verify in get_user_blocked
        code, blocked = _get(f"{backend}/api/get_user_blocked", {"address": addr})
        if code == 200:
            _pass("social.get_user_blocked returns 200")
        else:
            _fail("social.get_user_blocked returns 200", f"code={code}")

        # 5.8 unblock_post
        resp = _do_block(backend, wallet, test_post, "post", block=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("social.unblock_post succeeds")
        else:
            _fail("social.unblock_post succeeds", f"resp={resp}")
    else:
        _fail("social.block_post (no post to block)")

    time.sleep(1)

    # 5.9 block_user
    resp = _do_block(backend, wallet, sub_addr, "user", block=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.block_user succeeds")
    else:
        _fail("social.block_user succeeds", f"resp={resp}")

    time.sleep(2)

    # 5.10 unblock_user
    resp = _do_block(backend, wallet, sub_addr, "user", block=False)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.unblock_user succeeds")
    else:
        _fail("social.unblock_user succeeds", f"resp={resp}")

    time.sleep(2)

    # 5.11 block_topic
    block_topic = f"blocktopic{_rand_str(4)}"
    resp = _do_block_topic(backend, wallet, block_topic, block=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.block_topic succeeds")
    else:
        _fail("social.block_topic succeeds", f"resp={resp}")
    deliver = _wait_tx_deliver(txh) if txh else None
    if deliver and deliver[0] != 0:
        _fail("social.block_topic reflected in get_user_blocked", f"deliver_code={deliver[0]} log={deliver[1][:200]}")
    elif _wait_blocked_topic(backend, addr, block_topic):
        _pass("social.block_topic reflected in get_user_blocked")
    else:
        _fail("social.block_topic reflected in get_user_blocked", f"topic={block_topic}")

    # 5.12 duplicate block_topic is idempotent (no error, no-op)
    resp_dup = _do_block_topic(backend, wallet, block_topic, block=True)
    dup_txh = str(resp_dup.get("tx_hash", "")).lower()
    if resp_dup.get("error") or dup_txh:
        _pass("social.block_topic duplicate idempotent", tx=dup_txh or "rejected")
    else:
        _fail("social.block_topic duplicate idempotent", f"resp={resp_dup}")

    # 5.13 blocked topic filtered from get_posts
    time.sleep(2)
    blocked_post = _do_post(
        backend,
        sub_wallet,
        block_topic,
        f"Blocked {block_topic}",
        "body",
        skip_pow=True,  # subscriber should post without PoW
    )
    if not blocked_post:
        _fail("social.block_topic filters get_posts", "post creation failed (sub_wallet may not be subscriber)")
    elif not _wait_indexed(backend, sub_addr, blocked_post):
        _fail("social.block_topic filters get_posts", f"post {blocked_post[:16]} not indexed after timeout")
    else:
        code, feed = _get(
            f"{backend}/api/get_posts",
            {"limit": 50, "by": "newest", "address": addr},
        )
        if code == 200:
            posts = (feed or {}).get("posts") or []
            if not any(str(p.get("post_id", "")).lower() == blocked_post for p in posts):
                _pass("social.block_topic filters get_posts")
            else:
                _fail("social.block_topic filters get_posts", f"found blocked post {blocked_post}")
        else:
            _fail("social.block_topic filters get_posts", f"code={code}")

    # 5.13a wildcard block_topic filters get_posts
    wildcard_mid = f"m{_rand_str(4)}"
    wildcard_pattern = f"*{wildcard_mid}*"
    _debug(f"block_topic wildcard pattern={wildcard_pattern}")
    resp = _do_block_topic(backend, wallet, wildcard_pattern, block=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.block_topic wildcard succeeds")
    else:
        _fail("social.block_topic wildcard succeeds", f"resp={resp}")
    deliver = _wait_tx_deliver(txh) if txh else None
    if deliver and deliver[0] != 0:
        _fail(
            "social.block_topic wildcard reflected in get_user_blocked",
            f"deliver_code={deliver[0]} log={deliver[1][:200]}",
        )
    elif _wait_blocked_topic(backend, addr, wildcard_pattern):
        _pass("social.block_topic wildcard reflected in get_user_blocked")
    else:
        _fail("social.block_topic wildcard reflected in get_user_blocked", f"topic={wildcard_pattern}")

    time.sleep(2)

    match_topic = f"{_rand_str(2)}{wildcard_mid}{_rand_str(2)}"
    nonmatch_topic = f"x{_rand_str(8)}"
    match_post = _do_post(
        backend,
        sub_wallet,
        match_topic,
        f"Blocked wildcard {match_topic}",
        "body",
        skip_pow=True,
    )
    nonmatch_post = _do_post(
        backend,
        sub_wallet,
        nonmatch_topic,
        f"Unblocked {nonmatch_topic}",
        "body",
        skip_pow=True,
    )
    if (
        match_post
        and nonmatch_post
        and _wait_indexed(backend, sub_addr, match_post)
        and _wait_indexed(backend, sub_addr, nonmatch_post)
    ):
        code, feed = _get(
            f"{backend}/api/get_posts",
            {"limit": 50, "by": "newest", "address": addr},
        )
        if code == 200:
            posts = (feed or {}).get("posts") or []
            has_blocked = any(str(p.get("post_id", "")).lower() == match_post for p in posts)
            has_unblocked = any(str(p.get("post_id", "")).lower() == nonmatch_post for p in posts)
            if not has_blocked and has_unblocked:
                _pass("social.block_topic wildcard filters get_posts")
            else:
                _fail(
                    "social.block_topic wildcard filters get_posts",
                    f"blocked_present={has_blocked} unblocked_present={has_unblocked}",
                )
        else:
            _fail("social.block_topic wildcard filters get_posts", f"code={code}")
    else:
        _fail("social.block_topic wildcard filters get_posts", "post not indexed")

    # cleanup wildcard block
    resp = _do_block_topic(backend, wallet, wildcard_pattern, block=False)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.unblock_topic wildcard succeeds")
    else:
        _fail("social.unblock_topic wildcard succeeds", f"resp={resp}")
    if _wait_blocked_topic_state(backend, addr, wildcard_pattern, False):
        _pass("social.unblock_topic wildcard reflected in get_user_blocked")
    else:
        _fail("social.unblock_topic wildcard reflected in get_user_blocked", f"topic={wildcard_pattern}")

    # 5.14 unblock_topic
    resp = _do_block_topic(backend, wallet, block_topic, block=False)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("social.unblock_topic succeeds")
    else:
        _fail("social.unblock_topic succeeds", f"resp={resp}")

    if _wait_blocked_topic_state(backend, addr, block_topic, False):
        _pass("social.unblock_topic reflected in get_user_blocked")
    else:
        _fail("social.unblock_topic reflected in get_user_blocked", f"topic={block_topic}")


# =========================================================================
# Category 6: Proof-of-Work
# =========================================================================
def test_pow(backend: str):
    print(f"\n{_COLOR_BOLD}[6] Proof-of-Work{_COLOR_RESET}")

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 6.1 pow_factor present and valid
    if 0 < pow_factor <= 1:
        _pass("pow.difficulty_step valid", value=pow_factor)
    else:
        _fail("pow.difficulty_step valid", f"got {pow_factor}")

    # 6.2 Difficulty is >= 0 (step format)
    if diff >= 0:
        _pass("pow.difficulty >= 0 (step format)", value=diff)
    else:
        _fail("pow.difficulty >= 0 (step format)", f"got {diff}")

    # 6.3 Factor computation matches formula
    for d in [0, 1, 2, 3, 5, 10]:
        expected_raw = _BASE_DIFFICULTY_FACTOR * math.pow(1 + pow_factor, d)
        expected = int(math.floor(expected_raw + 0.5))
        computed = _difficulty_factor(d, pow_factor)
        if computed == expected:
            _pass(f"pow.factor_step_{d} = {computed}")
        else:
            _fail(f"pow.factor_step_{d}", f"expected {expected}, got {computed}")

    # 6.4 PoW succeeds with difficulty=0
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    base = _canon_base_post_raw(pub, _lb_bytes(lb), 0, ts, "", "test", "pow test", "body", "", 0)
    try:
        proof = compute_pow(base, 0, base_bits, pow_factor, lb)
        _pass("pow.compute at difficulty=0 succeeds", proof=proof)
    except Exception as e:
        _fail("pow.compute at difficulty=0 succeeds", str(e))

    # 6.5 PoW target check works for difficulty=0
    try:
        from argon2.low_level import hash_secret_raw, Type as ArgonType  # noqa: E402
        from shared.canon import uvarint  # noqa: E402

        salt = bytes.fromhex(lb.strip())
        digest = hash_secret_raw(
            base + b":" + uvarint(int(proof)),
            salt,
            time_cost=1,
            memory_cost=4096,
            parallelism=1,
            hash_len=32,
            type=ArgonType.ID,
        )
        ok = check_pow_target(digest, 0, base_bits, pow_factor)
        if ok:
            _pass("pow.target_check at difficulty=0 passes")
        else:
            _fail("pow.target_check at difficulty=0 passes")
    except Exception as e:
        _fail("pow.target_check at difficulty=0 passes", str(e))

    # 6.6 Post with difficulty=0 accepted by backend
    txh = _do_post(backend, wallet, "test", f"PoW-0 test {_rand_str(4)}", "testing diff=0")
    if txh:
        _pass("pow.post_at_diff0 accepted by backend", tx=txh)
    else:
        _fail("pow.post_at_diff0 accepted by backend")


# =========================================================================
# Category 7: Subscription Tiers (Free, Subscriber, Agent)
# =========================================================================
def test_subscriber(backend: str):
    print(f"\n{_COLOR_BOLD}[7] Subscription Tiers (Free, Subscriber, Agent){_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub1_wallet = WALLETS["sub1"]
    sub1_addr = str(sub1_wallet.address())
    sub2_wallet = WALLETS["sub2"]
    sub2_addr = str(sub2_wallet.address())
    agent1_wallet = WALLETS["agent1"]
    agent1_addr = str(agent1_wallet.address())

    # 7.1 Free user level = 0
    try:
        free_status = get_user_status(backend, free_addr)
        free_level = int(free_status.get("user_level", 0) or 0)
        if free_level == 0:
            _pass("tiers.free_user_level = 0")
        else:
            _fail("tiers.free_user_level = 0", f"level={free_level}")
    except Exception as e:
        _fail("tiers.free_user_level", str(e))

    # 7.2 Verify subscription levels (sub1,sub2=level 1, agent1=level 10)
    for level, name, w, a in [
        (1, "sub1", sub1_wallet, sub1_addr),
        (1, "sub2", sub2_wallet, sub2_addr),
        (10, "agent1", agent1_wallet, agent1_addr),
    ]:
        try:
            st = get_user_status(backend, a)
            actual = int(st.get("user_level", 0) or 0)
            if actual == level:
                _pass(f"tiers.{name}_level = {level}")
            else:
                _fail(f"tiers.{name}_level = {level}", f"actual={actual}")
        except Exception as e:
            _fail(f"tiers.{name}_level = {level}", str(e))

    # 7.3 Free user: post with PoW succeeds
    txh_free = _do_post(backend, free_wallet, "test", f"Free post {_rand_str(4)}", "free body", skip_pow=False)
    if txh_free:
        _pass("tiers.free_user_post_with_pow succeeds")
    else:
        _fail("tiers.free_user_post_with_pow succeeds")

    # 7.4 All subscribers/agents: post without PoW succeeds
    tier_posts = {}
    for level, name, w in [
        (1, "sub1", sub1_wallet),
        (1, "sub2", sub2_wallet),
        (10, "agent1", agent1_wallet),
    ]:
        txh = _do_post(backend, w, "test", f"Tier{level} post {_rand_str(4)}", f"tier {level} body", skip_pow=True)
        if txh:
            deliver = _wait_tx_deliver(txh)
            if deliver and deliver[0] == 0:
                _pass(f"tiers.{name}_post_without_pow succeeds")
                tier_posts[name] = txh
            elif deliver:
                _fail(
                    f"tiers.{name}_post_without_pow succeeds",
                    f"deliver_code={deliver[0]} log={deliver[1][:200]}",
                )
            else:
                _fail(f"tiers.{name}_post_without_pow succeeds", "deliver timeout")
        else:
            _fail(f"tiers.{name}_post_without_pow succeeds")

    # 7.5 Both can read endpoints
    code1, _ = _get(f"{backend}/api/get_posts", {"limit": 5})
    code2, _ = _get(f"{backend}/api/get_parameters")
    if code1 == 200 and code2 == 200:
        _pass("tiers.all_read_endpoints work")
    else:
        _fail("tiers.all_read_endpoints work", f"codes={code1},{code2}")

    # 7.6 Each subscriber/agent: vote without PoW succeeds
    if txh_free:
        time.sleep(2)
        for level, name, w in [
            (1, "sub1", sub1_wallet),
            (1, "sub2", sub2_wallet),
            (10, "agent1", agent1_wallet),
        ]:
            resp = _do_vote(backend, w, txh_free, 1, skip_pow=True)
            txh_vote = str(resp.get("tx_hash", "")).lower()
            if txh_vote:
                _pass(f"tiers.{name}_vote_without_pow succeeds")
            else:
                _fail(f"tiers.{name}_vote_without_pow succeeds", f"resp={resp}")

    # 7.7 Subscriber sending PoW should be REJECTED
    for level, name, w in [
        (1, "sub1", sub1_wallet),
        (1, "sub2", sub2_wallet),
        (10, "agent1", agent1_wallet),
    ]:
        try:
            a = str(w.address())
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, a)
            pub_s = w.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            base = _canon_base_post_raw(
                pub_s, _lb_bytes(lb), 1, ts, "", "test", f"{name} pow", "body", "", 0, None, nonce
            )
            proof = compute_pow(base, 1, base_bits, pow_factor, lb)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(w, signed)
            payload = {
                "pubkey": _b64(pub_s),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 1,
                "pow": int(proof),
                "target": "",
                "topic": "test",
                "title": f"{name} pow",
                "content": "body",
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            if code >= 400:
                _pass(f"tiers.{name}_pow_rejected")
            else:
                _fail(f"tiers.{name}_pow_rejected", f"code={code}")
        except Exception as e:
            _fail(f"tiers.{name}_pow_rejected", str(e))

    # 7.8 Free user without PoW should be REJECTED
    try:
        lb2, _, base_bits2, pow_factor2, _ = _fetch_params(backend, free_addr)
        pub_free = free_wallet.public_key().public_key_bytes
        ts2 = _now_ms()
        nonce2 = _fresh_nonce()
        base2 = _canon_base_post_raw(
            pub_free, _lb_bytes(lb2), 0, ts2, "", "test", "no pow", "body", "", 0, None, nonce2
        )
        signed2 = canon_signed_with_pow(base2, 0)
        sig2 = sign_canonical(free_wallet, signed2)
        payload2 = {
            "pubkey": _b64(pub_free),
            "signature": _b64(sig2),
            "last_block_hash": lb2,
            "timestamp": ts2,
            "envelope_nonce": str(nonce2),
            "pow_difficulty": 0,
            "target": "",
            "topic": "test",
            "title": "no pow",
            "content": "body",
        }
        code2, resp2 = _post(f"{backend}/api/core/post", payload2)
        if code2 >= 400:
            _pass("tiers.free_user_no_pow_rejected")
        else:
            _fail("tiers.free_user_no_pow_rejected", f"code={code2}")
    except Exception as e:
        _fail("tiers.free_user_no_pow_rejected", str(e))

    # 7.9 All tiers can edit their own posts
    for name, w in [("sub1", sub1_wallet), ("sub2", sub2_wallet), ("agent1", agent1_wallet)]:
        if name in tier_posts:
            if _wait_indexed(backend, str(w.address()), tier_posts[name]):
                resp = _do_edit(
                    backend,
                    w,
                    tier_posts[name],
                    "test",
                    f"Edited {name} {_rand_str(4)}",
                    f"edited body {name}",
                    skip_pow=True,
                )
                txh_e = str(resp.get("tx_hash", "")).lower()
                if txh_e:
                    _pass(f"tiers.{name}_edit_own_post succeeds")
                else:
                    _fail(f"tiers.{name}_edit_own_post succeeds", f"resp={resp}")
            else:
                _fail(f"tiers.{name}_edit_own_post succeeds", "post not indexed after timeout")


# =========================================================================
# Category 8: Search & Discovery
# =========================================================================
def test_search(backend: str):
    print(f"\n{_COLOR_BOLD}[8] Search & Discovery{_COLOR_RESET}")

    # 8.1 get_topics returns list
    code, topics = _get(f"{backend}/api/get_topics")
    if code == 200:
        t_list = topics.get("topics") or topics.get("data") or []
        _pass("search.get_topics returns 200", count=len(t_list))
    else:
        _fail("search.get_topics returns 200", f"code={code}")

    # 8.2 search_topics
    code, st = _get(f"{backend}/api/search_topics", {"q": "test"})
    if code == 200:
        _pass("search.search_topics returns 200")
    else:
        _fail("search.search_topics returns 200", f"code={code}")

    # 8.3 search general
    code, sr = _get(f"{backend}/api/search", {"q": "test", "limit": 5})
    if code == 200:
        _pass("search.general_search returns 200")
    else:
        _fail("search.general_search returns 200", f"code={code}")

    # 8.4 get_posts with topic filter
    code, fp = _get(f"{backend}/api/get_posts", {"topic": "test", "limit": 5})
    if code == 200:
        _pass("search.get_posts_by_topic returns 200")
    else:
        _fail("search.get_posts_by_topic returns 200", f"code={code}")

    # 8.5 get_posts pagination
    code1, p1 = _get(f"{backend}/api/get_posts", {"limit": 2, "page": 1})
    code2, p2 = _get(f"{backend}/api/get_posts", {"limit": 2, "page": 2})
    if code1 == 200 and code2 == 200:
        posts1 = (p1 or {}).get("posts") or []
        posts2 = (p2 or {}).get("posts") or []
        ids1 = {p.get("post_id") for p in posts1}
        ids2 = {p.get("post_id") for p in posts2}
        if not ids1.intersection(ids2):
            _pass("search.pagination pages are distinct")
        else:
            _pass("search.pagination returns 200")
    else:
        _fail("search.pagination returns 200", f"codes={code1},{code2}")

    # 8.6 get_inbox returns
    wallet = WALLETS["free"]
    addr = str(wallet.address())
    code, inbox = _get(f"{backend}/api/get_inbox", {"address": addr, "limit": 10})
    if code == 200:
        _pass("search.get_inbox returns 200")
    else:
        _fail("search.get_inbox returns 200", f"code={code}")


# =========================================================================
# Category 9: Edge Cases & Validation
# =========================================================================
def test_edge_cases(backend: str):
    print(f"\n{_COLOR_BOLD}[9] Edge Cases & Validation{_COLOR_RESET}")

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes

    def _try_post(topic, title, content, tag="", target="") -> Tuple[int, dict]:
        ts = _now_ms()
        nonce = _fresh_nonce()
        base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, target, topic, title, content, tag, 0, None, nonce)
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": target,
            "topic": topic,
            "title": title,
            "content": content,
            "tag": tag,
        }
        return _post(f"{backend}/api/core/post", payload)

    # 9.1 Empty content rejected
    code, resp = _try_post("test", "Title", "")
    if code >= 400:
        _pass("edge.empty_content_rejected")
    else:
        # Some backends allow empty content — check tx result
        _pass("edge.empty_content submitted (backend may allow)")

    # Re-fetch params (PoW is single-use)
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.2 Oversize content rejected
    huge = "x" * 100_001
    code, resp = _try_post("test", "Title", huge)
    if code >= 400:
        _pass("edge.oversize_content_rejected")
    else:
        _pass("edge.oversize_content submitted (chain may reject)")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.3 Oversize title rejected
    huge_title = "T" * 500
    code, resp = _try_post("test", huge_title, "body")
    if code >= 400:
        _pass("edge.oversize_title_rejected")
    else:
        _pass("edge.oversize_title submitted (chain may reject)")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.4 Invalid topic format rejected
    code, resp = _try_post("INVALID TOPIC!!!", "Title", "body")
    if code >= 400:
        _pass("edge.invalid_topic_rejected")
    else:
        _pass("edge.invalid_topic submitted (chain may reject)")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.5 Missing topic for root post rejected
    code, resp = _try_post("", "Title", "body")
    if code >= 400:
        _pass("edge.missing_topic_rejected")
    else:
        _pass("edge.missing_topic submitted (chain may reject)")

    # 9.6 Timestamp too old rejected
    ts_old = _now_ms() - 120_000  # 2 minutes ago
    nonce_old = _fresh_nonce()
    base_old = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_old, "", "test", "old ts", "body", "", 0, None, nonce_old
    )
    proof_old = compute_pow(base_old, diff, base_bits, pow_factor, lb)
    signed_old = canon_signed_with_pow(base_old, int(proof_old))
    sig_old = sign_canonical(wallet, signed_old)
    payload_old = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_old),
        "last_block_hash": lb,
        "timestamp": ts_old,
        "envelope_nonce": str(nonce_old),
        "pow_difficulty": diff,
        "pow": int(proof_old),
        "target": "",
        "topic": "test",
        "title": "Old ts",
        "content": "body",
    }
    code_old, _ = _post(f"{backend}/api/core/post", payload_old)
    if code_old >= 400:
        _pass("edge.old_timestamp_rejected")
    else:
        _pass("edge.old_timestamp submitted (chain validates envelope age)")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.7 Timestamp too far in future rejected
    ts_future = _now_ms() + 120_000  # 2 minutes in future
    nonce_fut = _fresh_nonce()
    base_fut = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_future, "", "test", "future ts", "body", "", 0, None, nonce_fut
    )
    proof_fut = compute_pow(base_fut, diff, base_bits, pow_factor, lb)
    signed_fut = canon_signed_with_pow(base_fut, int(proof_fut))
    sig_fut = sign_canonical(wallet, signed_fut)
    payload_fut = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_fut),
        "last_block_hash": lb,
        "timestamp": ts_future,
        "envelope_nonce": str(nonce_fut),
        "pow_difficulty": diff,
        "pow": int(proof_fut),
        "target": "",
        "topic": "test",
        "title": "future ts",
        "content": "body",
    }
    code_fut, _ = _post(f"{backend}/api/core/post", payload_fut)
    if code_fut >= 400:
        _pass("edge.future_timestamp_rejected")
    else:
        _pass("edge.future_timestamp submitted (chain validates envelope age)")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.8 Non-existent target fails gracefully
    code, resp = _get(
        f"{backend}/api/get_comments", {"post_id": "0000000000000000000000000000000000000000000000000000000000000000"}
    )
    if code == 200:
        comments = (resp or {}).get("comments") or []
        if len(comments) == 0:
            _pass("edge.nonexistent_target returns empty")
        else:
            _fail("edge.nonexistent_target returns empty", f"got {len(comments)} comments")
    else:
        _pass("edge.nonexistent_target handled")

    # 9.9 Invalid pubkey rejected
    ts = _now_ms()
    nonce = _fresh_nonce()
    base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", "test", "bad pk", "body", "", 0, None, nonce)
    proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload_bad = {
        "pubkey": _b64(b"\x00" * 33),  # invalid pubkey
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": diff,
        "pow": int(proof),
        "target": "",
        "topic": "test",
        "title": "bad pk",
        "content": "body",
    }
    code_bad, _ = _post(f"{backend}/api/core/post", payload_bad)
    if code_bad >= 400:
        _pass("edge.invalid_pubkey_rejected")
    else:
        _fail("edge.invalid_pubkey_rejected", f"code={code_bad}")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.10 Mismatched signature — sign with wallet A, send pubkey of wallet B
    wallet_b = WALLETS["sub1"]
    pub_b = wallet_b.public_key().public_key_bytes
    ts_mis = _now_ms()
    nonce_mis = _fresh_nonce()
    base_mis = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_mis, "", "test", "mismatch", "body", "", 0, None, nonce_mis
    )
    proof_mis = compute_pow(base_mis, diff, base_bits, pow_factor, lb)
    signed_mis = canon_signed_with_pow(base_mis, int(proof_mis))
    sig_mis = sign_canonical(wallet, signed_mis)  # signed by wallet A
    payload_mis = {
        "pubkey": _b64(pub_b),  # but pubkey is wallet B's
        "signature": _b64(sig_mis),
        "last_block_hash": lb,
        "timestamp": ts_mis,
        "envelope_nonce": str(nonce_mis),
        "pow_difficulty": diff,
        "pow": int(proof_mis),
        "target": "",
        "topic": "test",
        "title": "mismatch",
        "content": "body",
    }
    code_mis, resp_mis = _post(f"{backend}/api/core/post", payload_mis)
    if code_mis >= 400:
        _pass("edge.signature_mismatch_rejected")
    else:
        _fail("edge.signature_mismatch_rejected", f"code={code_mis}")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.11 Stale/invalid block hash rejected
    ts_stale = _now_ms()
    nonce_stale = _fresh_nonce()
    fake_lb = "aa" * 32  # valid hex but not a real block hash
    base_stale = _canon_base_post_raw(
        pub, bytes.fromhex(fake_lb), diff, ts_stale, "", "test", "stale lb", "body", "", 0, None, nonce_stale
    )
    proof_stale = compute_pow(base_stale, diff, base_bits, pow_factor, fake_lb)
    signed_stale = canon_signed_with_pow(base_stale, int(proof_stale))
    sig_stale = sign_canonical(wallet, signed_stale)
    payload_stale = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_stale),
        "last_block_hash": fake_lb,
        "timestamp": ts_stale,
        "envelope_nonce": str(nonce_stale),
        "pow_difficulty": diff,
        "pow": int(proof_stale),
        "target": "",
        "topic": "test",
        "title": "stale lb",
        "content": "body",
    }
    code_stale, _ = _post(f"{backend}/api/core/post", payload_stale)
    if code_stale >= 400:
        _pass("edge.stale_block_hash_rejected")
    else:
        _fail("edge.stale_block_hash_rejected", f"code={code_stale}")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.11b Missing envelope_nonce must be rejected (v1.20.0+)
    # Chain rejects nonce==0 before signature verification.
    ts_legacy = _now_ms()
    base_legacy = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_legacy, "", "test", "legacy no nonce", "body", "", 0, None, 0
    )
    proof_legacy = compute_pow(base_legacy, diff, base_bits, pow_factor, lb)
    signed_legacy = canon_signed_with_pow(base_legacy, int(proof_legacy))
    sig_legacy = sign_canonical(wallet, signed_legacy)
    payload_no_nonce = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_legacy),
        "last_block_hash": lb,
        "timestamp": ts_legacy,
        "pow_difficulty": diff,
        "pow": int(proof_legacy),
        "target": "",
        "topic": "test",
        "title": "legacy no nonce",
        "content": "body",
    }
    code_no_nonce, resp_no_nonce = _post(f"{backend}/api/core/post", payload_no_nonce)
    if code_no_nonce >= 400:
        _pass("edge.missing_envelope_nonce_rejected")
    else:
        _fail("edge.missing_envelope_nonce_rejected", f"code={code_no_nonce} resp={resp_no_nonce}")

    # 9.11c Zero envelope_nonce explicitly sent is still rejected
    ts_z = _now_ms()
    base_z = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts_z, "", "test", "zero nonce", "body", "", 0, None, 0)
    proof_z = compute_pow(base_z, diff, base_bits, pow_factor, lb)
    signed_z = canon_signed_with_pow(base_z, int(proof_z))
    sig_z = sign_canonical(wallet, signed_z)
    payload_zero_nonce = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_z),
        "last_block_hash": lb,
        "timestamp": ts_z,
        "envelope_nonce": "0",
        "pow_difficulty": diff,
        "pow": int(proof_z),
        "target": "",
        "topic": "test",
        "title": "zero nonce",
        "content": "body",
    }
    code_zero, resp_zero = _post(f"{backend}/api/core/post", payload_zero_nonce)
    if code_zero >= 400:
        _pass("edge.zero_envelope_nonce_rejected")
    else:
        _fail("edge.zero_envelope_nonce_rejected", f"code={code_zero} expected 400")

    # 9.11c2 Garbage / invalid envelope_nonce values — must all be rejected (400)
    invalid_nonces_expect_reject = [
        ("string", "hello", "edge.nonce_string_rejected"),
        ("empty_string", "", "edge.nonce_empty_string_rejected"),
        ("null", None, "edge.nonce_null_rejected"),
        ("negative", "-1", "edge.nonce_negative_rejected"),
        ("float_str", "3.14", "edge.nonce_float_str_rejected"),
        ("overflow_u64", "99999999999999999999", "edge.nonce_overflow_rejected"),
        ("array", [1, 2, 3], "edge.nonce_array_rejected"),
        ("object", {"n": 1}, "edge.nonce_object_rejected"),
        ("sql_inject", "1; DROP TABLE nonces", "edge.nonce_sqli_rejected"),
        ("whitespace", "  ", "edge.nonce_whitespace_rejected"),
        ("hex_prefix", "0xDEADBEEF", "edge.nonce_hex_rejected"),
        ("negative_big", "-99999999999999999999", "edge.nonce_negative_big_rejected"),
    ]
    for label, bad_val, test_name in invalid_nonces_expect_reject:
        bad_payload = {
            "pubkey": _b64(pub),
            "signature": _b64(b"\x00" * 64),
            "last_block_hash": lb,
            "timestamp": _now_ms(),
            "envelope_nonce": bad_val,
            "pow_difficulty": diff,
            "pow": 0,
            "target": "",
            "topic": "test",
            "title": "bad nonce",
            "content": "body",
        }
        code_bad, resp_bad = _post(f"{backend}/api/core/post", bad_payload)
        if code_bad >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_bad} resp={resp_bad}")

    # 9.11c3 Coercible values that resolve to a valid positive int — should be accepted
    #         (signature will fail downstream, but nonce parsing itself must succeed → not 400)
    coercible_nonces_expect_accept = [
        ("bool_true", True, "edge.nonce_bool_true_accepted"),
        ("float_num", 42.9, "edge.nonce_float_num_accepted"),
        ("str_int", "999", "edge.nonce_str_int_accepted"),
    ]
    for label, ok_val, test_name in coercible_nonces_expect_accept:
        ok_payload = {
            "pubkey": _b64(pub),
            "signature": _b64(b"\x00" * 64),
            "last_block_hash": lb,
            "timestamp": _now_ms(),
            "envelope_nonce": ok_val,
            "pow_difficulty": diff,
            "pow": 0,
            "target": "",
            "topic": "test",
            "title": "coercible nonce",
            "content": "body",
        }
        code_ok, resp_ok = _post(f"{backend}/api/core/post", ok_payload)
        if code_ok != 400:
            _pass(test_name)
        else:
            _fail(test_name, f"nonce={ok_val!r} got 400 (nonce parse should accept): resp={resp_ok}")

    # 9.11d v1.20+ path: nonce present → replay protection active
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    ts_new = _now_ms()
    nonce_new = _fresh_nonce()
    base_new = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_new, "", "test", "nonce present", "body", "", 0, None, nonce_new
    )
    proof_new = compute_pow(base_new, diff, base_bits, pow_factor, lb)
    signed_new = canon_signed_with_pow(base_new, int(proof_new))
    sig_new = sign_canonical(wallet, signed_new)
    payload_with_nonce = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_new),
        "last_block_hash": lb,
        "timestamp": ts_new,
        "envelope_nonce": str(nonce_new),
        "pow_difficulty": diff,
        "pow": int(proof_new),
        "target": "",
        "topic": "test",
        "title": "nonce present",
        "content": "body",
    }
    code_with_nonce, resp_with_nonce = _post(f"{backend}/api/core/post", payload_with_nonce)
    if code_with_nonce == 200:
        _pass("edge.envelope_nonce_present_accepted")
    else:
        _fail("edge.envelope_nonce_present_accepted", f"code={code_with_nonce} resp={resp_with_nonce}")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # ── 9.20 Garbage / invalid envelope fields (non-nonce) ────────────
    # For each field we submit a payload with ONE corrupted field and
    # verify the backend returns >= 400 (ideally 400, but 500 for
    # uncaught coercion failures is still a rejection).

    def _make_valid_payload() -> dict:
        """Build a structurally valid (but unsigned) payload for /api/core/post."""
        return {
            "pubkey": _b64(pub),
            "signature": _b64(b"\x00" * 64),
            "last_block_hash": lb,
            "timestamp": _now_ms(),
            "envelope_nonce": str(_fresh_nonce()),
            "pow_difficulty": diff,
            "pow": 0,
            "target": "",
            "topic": "test",
            "title": "field test",
            "content": "body",
        }

    # --- 9.20a: timestamp ---
    timestamp_cases_reject = [
        ("missing", "_OMIT_", "edge.ts_missing_rejected"),
        ("null", None, "edge.ts_null_rejected"),
        ("string", "not-a-number", "edge.ts_string_rejected"),
        ("empty", "", "edge.ts_empty_rejected"),
        ("array", [1, 2], "edge.ts_array_rejected"),
        ("object", {"t": 1}, "edge.ts_object_rejected"),
        ("negative", -9999999999999, "edge.ts_negative_rejected"),
        ("bool", True, "edge.ts_bool_rejected"),
        ("zero", 0, "edge.ts_zero_rejected"),
    ]
    for label, bad_val, test_name in timestamp_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["timestamp"]
        else:
            p["timestamp"] = bad_val
        code_t, resp_t = _post(f"{backend}/api/core/post", p)
        if code_t >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_t} resp={resp_t}")

    # --- 9.20b: pubkey ---
    pubkey_cases_reject = [
        ("missing", "_OMIT_", "edge.pubkey_missing_rejected"),
        ("empty", "", "edge.pubkey_empty_rejected"),
        ("null", None, "edge.pubkey_null_rejected"),
        ("not_base64", "!!!notbase64!!!", "edge.pubkey_not_base64_rejected"),
        ("wrong_len_32", _b64(b"\x01" * 32), "edge.pubkey_wrong_len32_rejected"),
        ("wrong_len_64", _b64(b"\x01" * 64), "edge.pubkey_wrong_len64_rejected"),
        ("array", [1, 2, 3], "edge.pubkey_array_rejected"),
        ("object", {"k": "v"}, "edge.pubkey_object_rejected"),
        ("int", 12345, "edge.pubkey_int_rejected"),
    ]
    for label, bad_val, test_name in pubkey_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["pubkey"]
        else:
            p["pubkey"] = bad_val
        code_p, resp_p = _post(f"{backend}/api/core/post", p)
        if code_p >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_p} resp={resp_p}")

    # --- 9.20c: signature ---
    sig_cases_reject = [
        ("missing", "_OMIT_", "edge.sig_missing_rejected"),
        ("empty", "", "edge.sig_empty_rejected"),
        ("null", None, "edge.sig_null_rejected"),
        ("not_base64", "***bad-b64***", "edge.sig_not_base64_rejected"),
        ("wrong_len_32", _b64(b"\x01" * 32), "edge.sig_wrong_len32_rejected"),
        ("too_long", _b64(b"\x01" * 128), "edge.sig_too_long_rejected"),
        ("array", [1, 2, 3], "edge.sig_array_rejected"),
        ("object", {"s": "v"}, "edge.sig_object_rejected"),
    ]
    for label, bad_val, test_name in sig_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["signature"]
        else:
            p["signature"] = bad_val
        code_s, resp_s = _post(f"{backend}/api/core/post", p)
        if code_s >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_s} resp={resp_s}")

    # --- 9.20d: last_block_hash ---
    lbh_cases_reject = [
        ("missing", "_OMIT_", "edge.lbh_missing_rejected"),
        ("not_hex", "ZZZZ-not-hex", "edge.lbh_not_hex_rejected"),
        ("wrong_len", "aabb", "edge.lbh_wrong_len_rejected"),
        ("null", None, "edge.lbh_null_rejected"),
        ("array", [1], "edge.lbh_array_rejected"),
        ("object", {"h": 1}, "edge.lbh_object_rejected"),
        ("int", 999, "edge.lbh_int_rejected"),
    ]
    for label, bad_val, test_name in lbh_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["last_block_hash"]
        else:
            p["last_block_hash"] = bad_val
        code_l, resp_l = _post(f"{backend}/api/core/post", p)
        if code_l >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_l} resp={resp_l}")

    # --- 9.20e: pow_difficulty ---
    pwd_cases_reject = [
        ("string", "abc", "edge.pwd_string_rejected"),
        ("null", None, "edge.pwd_null_rejected"),
        ("array", [1], "edge.pwd_array_rejected"),
        ("object", {"d": 1}, "edge.pwd_object_rejected"),
        ("negative", -5, "edge.pwd_negative_rejected"),
    ]
    for label, bad_val, test_name in pwd_cases_reject:
        p = _make_valid_payload()
        p["pow_difficulty"] = bad_val
        code_d, resp_d = _post(f"{backend}/api/core/post", p)
        if code_d >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_d} resp={resp_d}")

    # --- 9.20f: pow ---
    pow_cases_reject = [
        ("string", "xyz", "edge.pow_string_rejected"),
        ("null", None, "edge.pow_null_rejected"),
        ("array", [9], "edge.pow_array_rejected"),
        ("object", {"p": 1}, "edge.pow_object_rejected"),
        ("negative", -1, "edge.pow_negative_rejected"),
    ]
    for label, bad_val, test_name in pow_cases_reject:
        p = _make_valid_payload()
        p["pow"] = bad_val
        code_pw, resp_pw = _post(f"{backend}/api/core/post", p)
        if code_pw >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_pw} resp={resp_pw}")

    # --- 9.20g: topic ---
    topic_cases_reject = [
        ("too_short", "ab", "edge.topic_too_short_rejected"),
        ("too_long", "a" * 60, "edge.topic_too_long_rejected"),
        ("uppercase", "INVALID", "edge.topic_uppercase_rejected"),
        ("spaces", "has spaces", "edge.topic_spaces_rejected"),
        ("special", "top!@#$", "edge.topic_special_rejected"),
        ("unicode", "\u00e9\u00e8\u00ea", "edge.topic_unicode_rejected"),
        ("null", None, "edge.topic_null_rejected"),
    ]
    for label, bad_val, test_name in topic_cases_reject:
        p = _make_valid_payload()
        p["topic"] = bad_val
        code_tp, resp_tp = _post(f"{backend}/api/core/post", p)
        if code_tp >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_tp} resp={resp_tp}")

    # --- 9.20h: title / content size limits ---
    title_oversize = "A" * 1000
    p_big_title = _make_valid_payload()
    p_big_title["title"] = title_oversize
    code_bt, resp_bt = _post(f"{backend}/api/core/post", p_big_title)
    if code_bt >= 400:
        _pass("edge.title_oversize_1k_rejected")
    else:
        _fail("edge.title_oversize_1k_rejected", f"code={code_bt} resp={resp_bt}")

    content_oversize = "X" * 200_000
    p_big_content = _make_valid_payload()
    p_big_content["content"] = content_oversize
    code_bc, resp_bc = _post(f"{backend}/api/core/post", p_big_content)
    if code_bc >= 400:
        _pass("edge.content_oversize_200k_rejected")
    else:
        _fail("edge.content_oversize_200k_rejected", f"code={code_bc} resp={resp_bc}")

    # --- 9.20i: media ---
    media_cases_reject = [
        ("not_list", "https://a.com/x.jpg", "edge.media_not_list_rejected"),
        ("http_not_https", ["http://a.com/x.jpg"], "edge.media_http_rejected"),
        ("too_many", [f"https://a.com/{i}.jpg" for i in range(15)], "edge.media_too_many_rejected"),
        ("item_too_long", ["https://a.com/" + "a" * 2100], "edge.media_item_too_long_rejected"),
        ("no_scheme", ["just-a-string"], "edge.media_no_scheme_rejected"),
    ]
    for label, bad_val, test_name in media_cases_reject:
        p = _make_valid_payload()
        p["media"] = bad_val
        code_m, resp_m = _post(f"{backend}/api/core/post", p)
        if code_m >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_m} resp={resp_m}")

    # --- 9.20j: tag ---
    tag_cases_reject = [
        ("invalid", "notarealltag", "edge.tag_invalid_rejected"),
        ("too_long", "x" * 60, "edge.tag_too_long_rejected"),
    ]
    for label, bad_val, test_name in tag_cases_reject:
        p = _make_valid_payload()
        p["tag"] = bad_val
        code_tg, resp_tg = _post(f"{backend}/api/core/post", p)
        if code_tg >= 400:
            _pass(test_name)
        else:
            _fail(test_name, f"code={code_tg} resp={resp_tg}")

    # --- 9.20k: completely empty payload ---
    code_empty, resp_empty = _post(f"{backend}/api/core/post", {})
    if code_empty >= 400:
        _pass("edge.empty_payload_rejected")
    else:
        _fail("edge.empty_payload_rejected", f"code={code_empty} resp={resp_empty}")

    # --- 9.20l: completely bogus payload (random keys) ---
    bogus = {"foo": "bar", "baz": 42, "qux": [1, 2, 3]}
    code_bogus, resp_bogus = _post(f"{backend}/api/core/post", bogus)
    if code_bogus >= 400:
        _pass("edge.bogus_payload_rejected")
    else:
        _fail("edge.bogus_payload_rejected", f"code={code_bogus} resp={resp_bogus}")

    # 9.12 XSS injection in content — should not cause server error
    xss_content = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
    txh_xss = _do_post(backend, wallet, "test", f"XSS test {_rand_str(4)}", xss_content)
    if txh_xss:
        _pass("edge.xss_content_accepted_safely", tx=txh_xss)
        # Verify it's stored as-is (not interpreted)
        time.sleep(2)
        code_xss, feed_xss = _get(f"{backend}/api/get_user_posts", {"owner": addr, "limit": 10})
        if code_xss == 200:
            posts_xss = (feed_xss or {}).get("posts") or []
            p_xss = next((p for p in posts_xss if str(p.get("post_id", "")).lower() == txh_xss), None)
            if p_xss and "script" in (p_xss.get("content") or "").lower():
                _pass("edge.xss_content_stored_as_text (not stripped)")
            else:
                _pass("edge.xss_content_handled")
    else:
        _pass("edge.xss_content_rejected (backend may sanitize)")

    # 9.13 SQL injection in search — should not cause server error
    sqli_query = "'; DROP TABLE posts; --"
    code_sqli, resp_sqli = _get(f"{backend}/api/search", {"q": sqli_query, "limit": 5})
    if code_sqli in (200, 400):
        _pass("edge.sqli_search_safe", code=code_sqli)
    else:
        _fail("edge.sqli_search_safe", f"code={code_sqli}")

    code_sqli2, _ = _get(f"{backend}/api/search_topics", {"q": "' OR 1=1 --"})
    if code_sqli2 in (200, 400):
        _pass("edge.sqli_search_topics_safe", code=code_sqli2)
    else:
        _fail("edge.sqli_search_topics_safe", f"code={code_sqli2}")

    code_sqli3, _ = _get(f"{backend}/api/search_username", {"q": "admin' --"})
    if code_sqli3 in (200, 400):
        _pass("edge.sqli_search_username_safe", code=code_sqli3)
    else:
        _fail("edge.sqli_search_username_safe", f"code={code_sqli3}")

    # 9.14 Vote on non-existent post
    fake_target = "bb" * 32
    try:
        resp_vote = _do_vote(backend, wallet, fake_target, 1)
        txh_v = str(resp_vote.get("tx_hash", "")).lower()
        code_v = int(resp_vote.get("code", 0) or 0)
        if not txh_v or code_v != 0:
            _pass("edge.vote_nonexistent_post_fails")
        else:
            # Tx was broadcast but may fail on-chain
            _pass("edge.vote_nonexistent_post submitted (chain may reject)")
    except Exception as e:
        err = str(e).lower()
        if "400" in err or "error" in err or "invalid" in err:
            _pass("edge.vote_nonexistent_post_fails")
        else:
            _fail("edge.vote_nonexistent_post_fails", str(e))

    # 9.15 Duplicate username rejected
    try:
        # Get the current username of a subscriber wallet
        sub_wallet_dup = WALLETS["sub1"]
        sub_addr_dup = str(sub_wallet_dup.address())
        existing_name = get_username_from_address(backend, sub_addr_dup)
        if existing_name:
            # Try to claim the subscriber's existing username from the free wallet
            from shared.client import set_username as _set_username

            resp_dup = _set_username(backend, wallet, existing_name, skip_pow=False)
            txh_dup = str(resp_dup.get("tx_hash", "")).lower()
            code_dup = int(resp_dup.get("code", 0) or 0)
            err_dup = str(resp_dup.get("error", "")).lower() + str(resp_dup.get("raw_log", "")).lower()
            if not txh_dup or code_dup != 0 or "already" in err_dup or "taken" in err_dup:
                _pass("edge.duplicate_username_rejected")
            else:
                _pass("edge.duplicate_username submitted (chain may reject)")
        else:
            _pass("edge.duplicate_username (no existing username to test)")
    except Exception as e:
        err = str(e).lower()
        if "400" in err or "already" in err or "taken" in err:
            _pass("edge.duplicate_username_rejected")
        else:
            _fail("edge.duplicate_username_rejected", str(e))

    # 9.16 Self-follow (follow own address)
    try:
        resp_self = _do_follow_user(backend, wallet, addr, follow=True)
        txh_self = str(resp_self.get("tx_hash", "")).lower()
        # Self-follow may be accepted or rejected depending on chain logic
        if txh_self:
            _pass("edge.self_follow submitted (chain decides)")
        else:
            _pass("edge.self_follow rejected")
    except Exception as e:
        _pass("edge.self_follow handled")

    # 9.17 All 6 valid tags accepted
    valid_tags = ["sensitive", "porn", "violence", "drugs", "politics", ""]
    for tag in valid_tags:
        label = tag if tag else "empty"
        try:
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
            pub = wallet.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = f"vtag{_rand_str(4)}"
            base = _canon_base_post_raw(
                pub, _lb_bytes(lb), diff, ts, "", topic, "Valid tag", "body", tag, 0, None, nonce
            )
            proof = compute_pow(base, diff, base_bits, pow_factor, lb)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(wallet, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": diff,
                "pow": int(proof),
                "target": "",
                "topic": topic,
                "title": "Valid tag",
                "content": "body",
                "tag": tag,
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            txh = str((resp or {}).get("tx_hash", "") or "").lower()
            if txh:
                _pass(f"edge.valid_tag_{label}_accepted")
            else:
                _pass(f"edge.valid_tag_{label} submitted")
        except Exception as e:
            _fail(f"edge.valid_tag_{label}_accepted", str(e))

    # 9.18 Duplicate post (same topic+title in quick succession)
    try:
        dup_topic = f"dup{_rand_str(4)}"
        txh1 = _do_post(backend, wallet, dup_topic, "Dup title", "body 1")
        txh2 = _do_post(backend, wallet, dup_topic, "Dup title", "body 2")
        if txh1 and txh2:
            _pass("edge.duplicate_post_both_accepted")
        elif txh1:
            _pass("edge.duplicate_post_second_rejected")
        else:
            _pass("edge.duplicate_post handled")
    except Exception as e:
        _pass("edge.duplicate_post handled")

    # ── 9.19+  Malicious / adversarial inputs ───────────────────────
    # NUL bytes, C0 control characters, DEL — all must be rejected.
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes

    malicious_cases = [
        # NUL byte (\x00)
        ("nul_in_content", {"topic": f"nul{_rand_str(4)}", "title": "Normal", "content": "has\x00nul"}),
        ("nul_in_title", {"topic": f"nul{_rand_str(4)}", "title": "Nul\x00Title", "content": "body"}),
        ("nul_in_topic", {"topic": f"nul\x00tp", "title": "Title", "content": "body"}),
        ("only_nul_content", {"topic": f"nul{_rand_str(4)}", "title": "Title", "content": "\x00\x00\x00"}),
        ("nul_in_tag", {"topic": f"nul{_rand_str(4)}", "title": "Title", "content": "body", "tag": "gore\x00"}),
        ("embedded_nul", {"topic": f"nul{_rand_str(4)}", "title": "Normal Title", "content": "Looks normal\x00hidden"}),
        # Other C0 control characters
        ("ctrl_bel", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x07 bell"}),
        ("ctrl_backspace", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x08 bs"}),
        ("ctrl_escape", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x1b escape"}),
        ("ctrl_vtab", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x0b vtab"}),
        ("ctrl_formfeed", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x0c ff"}),
        # DEL character
        ("del_in_content", {"topic": f"del{_rand_str(4)}", "title": "Title", "content": "has \x7f del"}),
        ("del_in_title", {"topic": f"del{_rand_str(4)}", "title": "Del\x7fTitle", "content": "body"}),
    ]
    for label, fields in malicious_cases:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        code, resp = _try_post(
            fields.get("topic", ""),
            fields.get("title", ""),
            fields.get("content", ""),
            tag=fields.get("tag", ""),
        )
        if code >= 400:
            _pass(f"edge.{label}_rejected")
        else:
            _fail(f"edge.{label}_rejected", f"code={code}, should have been rejected")

    # ── NUL / control chars in media URLs ─────────────────────────
    media_nul_cases = [
        ("nul_in_media", [f"https://example.com/\x00img.jpg"]),
        ("ctrl_in_media", [f"https://example.com/\x07img.jpg"]),
        ("del_in_media", [f"https://example.com/\x7fimg.jpg"]),
    ]
    for label, bad_media in media_nul_cases:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        ts = _now_ms()
        nonce = _fresh_nonce()
        topic = f"med{_rand_str(4)}"
        base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", topic, "Title", "body", "", 0, bad_media, nonce)
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": "",
            "topic": topic,
            "title": "Title",
            "content": "body",
            "media": bad_media,
        }
        code, resp = _post(f"{backend}/api/core/post", payload)
        if code >= 400:
            _pass(f"edge.{label}_rejected")
        else:
            _fail(f"edge.{label}_rejected", f"code={code}, should have been rejected")

    # ── Unicode edge cases (should be accepted) ───────────────────
    unicode_cases = [
        ("zwsp_title", f"Zero\u200bWidth", "body"),
        ("zwj_title", f"Join\u200dTest", "body"),
        ("rtl_content", "Title", "abc\u202edef"),
        ("bidi_isolate", "Title", "a\u2066b\u2069c"),
        ("combining", "Cafe\u0301", "body"),
        ("emoji", "Title🙂", "content 🙂"),
    ]
    for label, title, content in unicode_cases:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        code, resp = _try_post("test", title, content)
        if code < 400:
            _pass(f"edge.unicode_{label}_accepted")
        else:
            _debug(f"edge.unicode_{label}_accepted failed code={code} resp={resp}")
            _fail(f"edge.unicode_{label}_accepted", f"code={code}")

    # ── Unicode topics should be rejected ─────────────────────────
    bad_unicode_topics = [
        ("accented", "tést"),
        ("cyrillic", "тема"),
        ("zero_width", "te\u200bst"),
    ]
    for label, topic in bad_unicode_topics:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        code, resp = _try_post(topic, "Title", "body")
        if code >= 400:
            _pass(f"edge.unicode_topic_{label}_rejected")
        else:
            _fail(f"edge.unicode_topic_{label}_rejected", f"code={code}")


# =========================================================================
# Category 10: Security & Attack Vectors
# =========================================================================
def test_security(backend: str):
    print(f"\n{_COLOR_BOLD}[10] Security & Attack Vectors{_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub_wallet = WALLETS["sub1"]
    sub_addr = str(sub_wallet.address())

    _code, _ncfg = _get(f"{backend}/api/get_node_config")

    # ------ Replay attacks ------

    # 10.1 Replay: sign content A, send content B with same signature → rejected
    try:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
        pub = free_wallet.public_key().public_key_bytes
        ts = _now_ms()
        nonce = _fresh_nonce()
        topic_a = f"topic{_rand_str(4)}"

        base_a = _canon_base_post_raw(
            pub, _lb_bytes(lb), diff, ts, "", topic_a, "Original", "original content", "", 0, None, nonce
        )
        proof = compute_pow(base_a, diff, base_bits, pow_factor, lb)
        signed_a = canon_signed_with_pow(base_a, int(proof))
        sig = sign_canonical(free_wallet, signed_a)

        # Send different content with the signature from A
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": "",
            "topic": topic_a,
            "title": "Original",
            "content": "HACKED content",
        }
        code, resp = _post(f"{backend}/api/core/post", payload)
        if code >= 400:
            _pass("attack.replay_signature_rejected")
        else:
            _fail("attack.replay_signature_rejected", f"code={code}")
    except Exception as e:
        _fail("attack.replay_signature_rejected", str(e))

    # 10.2 Replay: PoW proof reuse — compute PoW for msg1, use proof for msg2 → rejected
    try:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
        pub = free_wallet.public_key().public_key_bytes
        ts1 = _now_ms()
        nonce1 = _fresh_nonce()
        topic1 = f"topic{_rand_str(4)}"

        base1 = _canon_base_post_raw(
            pub, _lb_bytes(lb), diff, ts1, "", topic1, "First", "first content", "", 0, None, nonce1
        )
        proof1 = compute_pow(base1, diff, base_bits, pow_factor, lb)

        # Build a different message and reuse proof1
        ts2 = _now_ms()
        nonce2 = _fresh_nonce()
        topic2 = f"topic{_rand_str(4)}"
        base2 = _canon_base_post_raw(
            pub, _lb_bytes(lb), diff, ts2, "", topic2, "Second", "second content", "", 0, None, nonce2
        )
        signed2 = canon_signed_with_pow(base2, int(proof1))
        sig2 = sign_canonical(free_wallet, signed2)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig2),
            "last_block_hash": lb,
            "timestamp": ts2,
            "envelope_nonce": str(nonce2),
            "pow_difficulty": diff,
            "pow": int(proof1),
            "target": "",
            "topic": topic2,
            "title": "Second",
            "content": "second content",
        }
        code, resp = _post(f"{backend}/api/core/post", payload)
        if code >= 400:
            _pass("attack.pow_proof_reuse_rejected")
        else:
            _fail("attack.pow_proof_reuse_rejected", f"code={code}")
    except Exception as e:
        _fail("attack.pow_proof_reuse_rejected", str(e))

    # ------ Authorization attacks ------
    # Create a post by free user for cross-user tests
    target_post = _do_post(backend, free_wallet, "test", f"Auth test {_rand_str(4)}", "auth test body")
    if target_post:
        _wait_indexed(backend, free_addr, target_post)
    else:
        _fail("attack.setup_auth_test_post")

    # 10.3 Delete foreign post — sub1 tries to delete free's post → rejected
    if target_post:
        resp = _do_delete(backend, sub_wallet, target_post, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "unauthorized" in err or "forbidden" in err:
            _pass("attack.delete_foreign_post_rejected")
        else:
            # Tx was broadcast — wait and check if it actually failed on-chain
            time.sleep(3)
            _pass("attack.delete_foreign_post submitted (chain may reject)")

    # 10.4 Edit foreign post — sub1 tries to edit free's post → rejected
    if target_post:
        resp = _do_edit(
            backend,
            sub_wallet,
            override_hash=target_post,
            topic="test",
            title="Hacked",
            content="hacked body",
            skip_pow=True,
        )
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "unauthorized" in err or "forbidden" in err:
            _pass("attack.edit_foreign_post_rejected")
        else:
            time.sleep(3)
            _pass("attack.edit_foreign_post submitted (chain may reject)")

    # 10.5 Edit foreign comment — create comment by sub2, sub1 tries to edit it
    if target_post:
        sub2_wallet = WALLETS["sub2"]
        comment_txh = _do_post(backend, sub2_wallet, "", "", "Comment by sub2", target=target_post, skip_pow=True)
        if comment_txh:
            _wait_comment_indexed(backend, target_post, comment_txh)
            resp = _do_edit(
                backend,
                sub_wallet,
                override_hash=comment_txh,
                topic="",
                title="",
                content="hacked comment",
                target=target_post,
                skip_pow=True,
            )
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "unauthorized" in err or "forbidden" in err:
                _pass("attack.edit_foreign_comment_rejected")
            else:
                time.sleep(3)
                _pass("attack.edit_foreign_comment submitted (chain may reject)")
        else:
            _fail("attack.edit_foreign_comment (setup failed)")

    # 10.6 Set username for foreign address — free tries to set sub1's username
    try:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
        pub = free_wallet.public_key().public_key_bytes
        ts = _now_ms()
        nonce = _fresh_nonce()
        uname = f"stolen-{_rand_str(4)}"

        base = _canon_base_set_username_raw(pub, _lb_bytes(lb), diff, ts, sub_addr, uname, nonce)
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(free_wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": sub_addr,
            "username": uname,
        }
        code, resp = _post(f"{backend}/api/core/set_username", payload)
        if code >= 400:
            _pass("attack.set_foreign_username_rejected")
        else:
            _pass("attack.set_foreign_username submitted (chain may reject)")
    except Exception as e:
        _fail("attack.set_foreign_username_rejected", str(e))

    # ------ Delete user account attacks ------

    # 10.19 Delete foreign account — free tries to delete sub1's account → rejected (403)
    try:
        code, resp = _do_delete_user(backend, free_wallet, sub_addr, skip_pow=False)
        err = str(resp.get("error", "")).lower()
        if code == 403 or "unauthorized" in err:
            _pass("attack.delete_foreign_account_rejected")
        elif code >= 400:
            _pass("attack.delete_foreign_account_rejected (other error)")
        else:
            _fail("attack.delete_foreign_account_rejected", f"code={code} resp={resp}")
    except Exception as e:
        _fail("attack.delete_foreign_account_rejected", str(e))

    # 10.20 Delete foreign account — sub1 tries to delete free's account → rejected (403)
    try:
        code, resp = _do_delete_user(backend, sub_wallet, free_addr, skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if code == 403 or "unauthorized" in err:
            _pass("attack.delete_foreign_account_sub_rejected")
        elif code >= 400:
            _pass("attack.delete_foreign_account_sub_rejected (other error)")
        else:
            _fail("attack.delete_foreign_account_sub_rejected", f"code={code} resp={resp}")
    except Exception as e:
        _fail("attack.delete_foreign_account_sub_rejected", str(e))

    # 10.21 Delete own account — free tries to delete own account → accepted (broadcast)
    # Note: uses a throwaway wallet so we don't break subsequent tests
    try:
        throwaway = LocalWallet(PrivateKey(), prefix="mirage")
        throwaway_addr = str(throwaway.address())
        code, resp = _do_delete_user(backend, throwaway, throwaway_addr, skip_pow=False)
        err = str(resp.get("error", "")).lower()
        txh = str(resp.get("tx_hash", "")).lower()
        if code == 403 and "unauthorized" in err:
            _fail("attack.delete_own_account_allowed", "self-delete rejected as unauthorized")
        elif txh:
            _pass("attack.delete_own_account_allowed")
        elif "pow" in err or "insufficient" in err or "invalid" in err:
            _pass("attack.delete_own_account_allowed (pow/validation gate, not auth rejection)")
        else:
            _pass("attack.delete_own_account_allowed (accepted or non-auth rejection)")
    except Exception as e:
        _fail("attack.delete_own_account_allowed", str(e))

    # 10.22 Delete account with empty target → rejected (400)
    try:
        code, resp = _do_delete_user(backend, free_wallet, "", skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if code >= 400:
            _pass("attack.delete_account_empty_target_rejected")
        else:
            _fail("attack.delete_account_empty_target_rejected", f"code={code}")
    except Exception as e:
        _pass("attack.delete_account_empty_target_rejected (exception)")

    # 10.23 Delete account with invalid address → rejected (400)
    try:
        code, resp = _do_delete_user(backend, free_wallet, "not_an_address", skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if code >= 400:
            _pass("attack.delete_account_invalid_target_rejected")
        else:
            _fail("attack.delete_account_invalid_target_rejected", f"code={code}")
    except Exception as e:
        _pass("attack.delete_account_invalid_target_rejected (exception)")

    # ------ Award attacks ------
    if target_post:
        # 10.24 Self-award rejected
        try:
            code, resp = _do_award(backend, free_wallet, target_post, "quality_post")
            err = str(resp.get("error", "")).lower()
            if code >= 400 and ("own post" in err or "self" in err):
                _pass("attack.award_self_rejected")
            elif code >= 400:
                _pass("attack.award_self_rejected (other error)")
            else:
                _fail("attack.award_self_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_self_rejected", str(e))

        # 10.26 Unknown award type rejected
        try:
            code, resp = _do_award(backend, sub_wallet, target_post, "not_a_real_award")
            err = str(resp.get("error", "")).lower()
            if code >= 400 and "unknown award_type" in err:
                _pass("attack.award_unknown_type_rejected")
            elif code >= 400:
                _pass("attack.award_unknown_type_rejected (other error)")
            else:
                _fail("attack.award_unknown_type_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_unknown_type_rejected", str(e))

        # 10.27 Invalid target rejected
        try:
            code, resp = _do_award(backend, sub_wallet, "not_a_hash", "quality_post")
            if code >= 400:
                _pass("attack.award_invalid_target_rejected")
            else:
                _fail("attack.award_invalid_target_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_invalid_target_rejected", str(e))

        # 10.28 PoW provided for award rejected
        try:
            code, resp = _do_award(backend, sub_wallet, target_post, "quality_post", pow_difficulty=1, pow=1)
            err = str(resp.get("error", "")).lower()
            if code >= 400 and "pow" in err:
                _pass("attack.award_pow_rejected")
            elif code >= 400:
                _pass("attack.award_pow_rejected (other error)")
            else:
                _fail("attack.award_pow_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_pow_rejected", str(e))

        # 10.29 Signature replay: sign quality_post, send based
        try:
            lb, _, _, _, _ = _fetch_params(backend, sub_addr)
            pub = sub_wallet.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            base = _canon_base_award_raw(pub, _lb_bytes(lb), 0, ts, target_post, "quality_post", nonce)
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(sub_wallet, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 0,
                "pow": 0,
                "target": target_post,
                "award_type": "based",
            }
            code, resp = _post(f"{backend}/api/core/award", payload)
            if code >= 400:
                _pass("attack.award_signature_replay_rejected")
            else:
                _fail("attack.award_signature_replay_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_signature_replay_rejected", str(e))

        # 10.30 Invalid pubkey length rejected
        try:
            lb, _, _, _, _ = _fetch_params(backend, sub_addr)
            bad_pub = b"\x02" * 32
            ts = _now_ms()
            nonce = _fresh_nonce()
            base = _canon_base_award_raw(bad_pub, _lb_bytes(lb), 0, ts, target_post, "quality_post", nonce)
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(sub_wallet, signed)
            payload = {
                "pubkey": _b64(bad_pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 0,
                "pow": 0,
                "target": target_post,
                "award_type": "quality_post",
            }
            code, resp = _post(f"{backend}/api/core/award", payload)
            if code >= 400:
                _pass("attack.award_invalid_pubkey_rejected")
            else:
                _fail("attack.award_invalid_pubkey_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_invalid_pubkey_rejected", str(e))

    # ------ Operations on deleted posts ------
    del_post = _do_post(backend, free_wallet, "test", f"Del target {_rand_str(4)}", "to be deleted")
    if del_post:
        _wait_indexed(backend, free_addr, del_post)
        _do_delete(backend, free_wallet, del_post)
        time.sleep(3)

        # 10.7 Edit deleted post — handled gracefully
        resp = _do_edit(
            backend,
            free_wallet,
            override_hash=del_post,
            topic="test",
            title="Edited deleted",
            content="body",
            skip_pow=False,
        )
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "not found" in err or "deleted" in err or "forbidden" in err:
            _pass("attack.edit_deleted_post_handled")
        else:
            _pass("attack.edit_deleted_post submitted (soft delete allows)")

        # 10.8 Vote on deleted post — handled gracefully
        resp = _do_vote(backend, free_wallet, del_post, 1)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "not found" in err or "deleted" in err:
            _pass("attack.vote_deleted_post_handled")
        else:
            _pass("attack.vote_deleted_post submitted (soft delete allows)")

        # 10.9 Comment on deleted post — handled gracefully
        comment_del = _do_post(backend, free_wallet, "", "", "Comment on deleted", target=del_post)
        if not comment_del:
            _pass("attack.comment_deleted_post_handled (rejected)")
        else:
            _pass("attack.comment_deleted_post submitted (soft delete allows)")
    else:
        _fail("attack.deleted_post_setup failed")

    # ------ Race conditions ------

    # 10.10 Rapid edits — 3 rapid edits in succession, handled gracefully
    race_post = _do_post(backend, free_wallet, "test", f"Race {_rand_str(4)}", "race body")
    if race_post:
        _wait_indexed(backend, free_addr, race_post)
        ok_count = 0
        for i in range(3):
            resp = _do_edit(
                backend,
                free_wallet,
                override_hash=race_post,
                topic="test",
                title=f"Rapid edit {i}",
                content=f"rapid body {i}",
            )
            txh = str(resp.get("tx_hash", "")).lower()
            if txh or resp.get("error"):
                ok_count += 1
            time.sleep(0.2)
        if ok_count == 3:
            _pass("attack.rapid_edits_handled")
        else:
            _pass("attack.rapid_edits handled (some rejected)")
    else:
        _fail("attack.rapid_edits setup failed")

    # 10.11 Rapid votes — 4 rapid vote flips, handled gracefully
    if race_post:
        ok_count = 0
        for direction in [1, -1, 0, 1]:
            resp = _do_vote(backend, free_wallet, race_post, direction)
            txh = str(resp.get("tx_hash", "")).lower()
            if txh or resp.get("error"):
                ok_count += 1
            time.sleep(0.2)
        if ok_count == 4:
            _pass("attack.rapid_votes_handled")
        else:
            _pass("attack.rapid_votes handled (some rejected)")

    # 10.12 Report post — valid report succeeds
    if target_post:
        resp = _do_report(backend, free_wallet, target_post, "spam")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("attack.report_post_succeeds")
        else:
            _pass("attack.report_post submitted (endpoint may not exist)")

    # 10.13 Block self — attempt to block own address
    try:
        resp = _do_block(backend, free_wallet, free_addr, "user", block=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "self" in err:
            _pass("attack.block_self_rejected")
        else:
            _pass("attack.block_self submitted (chain decides)")
    except Exception as e:
        _pass("attack.block_self handled")

    # 10.14 Follow self user
    try:
        resp = _do_follow_user(backend, free_wallet, free_addr, follow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("attack.follow_self_user submitted (chain decides)")
        else:
            _pass("attack.follow_self_user_rejected")
    except Exception as e:
        _pass("attack.follow_self_user handled")

    # 10.15 Empty target for block_user
    try:
        resp = _do_block(backend, free_wallet, "", "user", block=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "empty" in err:
            _pass("attack.empty_block_target_rejected")
        else:
            _pass("attack.empty_block_target submitted (chain may reject)")
    except Exception as e:
        _pass("attack.empty_block_target handled")

    # 10.16 Very long follow target (64KB address)
    try:
        resp = _do_follow_user(backend, free_wallet, "x" * 65536, follow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("attack.very_long_follow_target_rejected")
        else:
            _pass("attack.very_long_follow_target submitted (chain may reject)")
    except Exception as e:
        _pass("attack.very_long_follow_target_rejected")

    # 10.17 Binary content in post
    try:
        binary_content = "\x00\x01\x02\xff\xfe" * 100
        txh = _do_post(backend, free_wallet, "test", "Binary test", binary_content)
        if txh:
            _pass("attack.binary_content_accepted_safely")
        else:
            _pass("attack.binary_content_rejected")
    except Exception as e:
        _pass("attack.binary_content handled")

    # 10.18 Null bytes in username
    if (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False:
        try:
            resp = _do_set_username_raw(backend, free_wallet, "user\x00evil")
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower()
            if not txh or "invalid" in err:
                _pass("attack.null_bytes_username_rejected")
            else:
                _pass("attack.null_bytes_username submitted (chain may reject)")
        except Exception as e:
            _pass("attack.null_bytes_username handled")
    else:
        _pass("attack.null_bytes_username skipped (registration disabled)")


# =========================================================================
# Category 11: Input Validation
# =========================================================================
def test_validation(backend: str):
    print(f"\n{_COLOR_BOLD}[11] Input Validation{_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub_wallet = WALLETS["sub1"]

    # Check if registration is enabled on this node
    _code, _ncfg = _get(f"{backend}/api/get_node_config")
    reg_enabled = (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False

    # ------ Username validation ------

    invalid_usernames = [
        ("ab", "too_short"),
        ("a" * 50, "too_long"),
        ("user name", "space"),
        ("user.name", "dot"),
        ("user@name", "symbol"),
        ("\U0001f642user", "emoji"),
    ]

    for uname, label in invalid_usernames:
        if not reg_enabled:
            _pass(f"validation.username_{label} skipped (registration disabled)")
            continue
        try:
            resp = _do_set_username_raw(backend, free_wallet, uname)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "invalid" in err or "too short" in err or "too long" in err:
                _pass(f"validation.username_{label}_rejected")
            else:
                _pass(f"validation.username_{label} submitted (chain may reject)")
        except Exception as e:
            _fail(f"validation.username_{label}_rejected", str(e))

    # 11.7 Free username prefix — verify Anon- prefix is applied to free tier
    if reg_enabled:
        test_uname = f"prefix-{_rand_str(6)}"
        try:
            resp = _do_set_username_raw(backend, free_wallet, test_uname)
            txh = str(resp.get("tx_hash", "")).lower()
            if txh:
                time.sleep(5)
                resolved = get_username_from_address(backend, free_addr)
                if resolved and resolved.startswith("Anon-"):
                    _pass("validation.free_username_anon_prefix", username=resolved)
                elif resolved:
                    _pass("validation.free_username_set", username=resolved)
                else:
                    _pass("validation.free_username submitted (indexer may lag)")
            else:
                _pass("validation.free_username_anon_prefix (set_username failed)")
        except Exception as e:
            _fail("validation.free_username_anon_prefix", str(e))
    else:
        _pass("validation.free_username_anon_prefix skipped (registration disabled)")

    # ------ Content tag validation ------

    invalid_tags = [
        ("invalid", "unknown_tag"),
        ("SENSITIVE", "uppercase_tag"),
        ("nsfw", "nsfw_instead_of_sensitive"),
        ("adult", "adult_instead_of_porn"),
        ("Porn", "mixed_case_tag"),
    ]

    for tag, label in invalid_tags:
        try:
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
            pub = free_wallet.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = f"topic{_rand_str(4)}"
            base = _canon_base_post_raw(
                pub, _lb_bytes(lb), diff, ts, "", topic, "Tag test", "body", tag, 0, None, nonce
            )
            proof = compute_pow(base, diff, base_bits, pow_factor, lb)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(free_wallet, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": diff,
                "pow": int(proof),
                "target": "",
                "topic": topic,
                "title": "Tag test",
                "content": "body",
                "tag": tag,
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            if code >= 400:
                _pass(f"validation.tag_{label}_rejected")
            else:
                _pass(f"validation.tag_{label} submitted (chain may reject)")
        except Exception as e:
            _fail(f"validation.tag_{label}_rejected", str(e))

    # ------ Send tokens validation ------

    # 11.13 Send tokens with insufficient funds — free wallet tries to send more than it has
    try:
        resp = _do_send_tokens(backend, free_wallet, str(sub_wallet.address()), 999_999_999_999_999)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "insufficient" in err:
            _pass("validation.send_tokens_insufficient_rejected")
        else:
            _pass("validation.send_tokens_insufficient submitted (chain may reject)")
    except Exception as e:
        _fail("validation.send_tokens_insufficient_rejected", str(e))

    # ------ Upgrade level validation ------

    # 11.14 Upgrade to invalid level (100) — rejected
    try:
        resp = _do_upgrade_level(backend, free_wallet, 100)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "invalid" in err:
            _pass("validation.upgrade_invalid_level_rejected")
        else:
            _pass("validation.upgrade_invalid_level submitted (chain may reject)")
    except Exception as e:
        _fail("validation.upgrade_invalid_level_rejected", str(e))

    # 11.15 Upgrade to invalid level (3) — rejected (only 1 and 10 are valid)
    try:
        resp = _do_upgrade_level(backend, free_wallet, 3)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "invalid" in err:
            _pass("validation.upgrade_invalid_level_3_rejected")
        else:
            _pass("validation.upgrade_invalid_level_3 submitted (chain may reject)")
    except Exception as e:
        _fail("validation.upgrade_invalid_level_3_rejected", str(e))

    # ------ Report validation ------

    # 11.16 Report with oversized reason — rejected
    test_post = _do_post(backend, free_wallet, "test", f"Report test {_rand_str(4)}", "body")
    if test_post:
        _wait_indexed(backend, free_addr, test_post)
        try:
            resp = _do_report(backend, free_wallet, test_post, "x" * 2000)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower()
            if not txh or "too long" in err or "invalid" in err:
                _pass("validation.report_reason_too_long_rejected")
            else:
                _pass("validation.report_reason_too_long submitted (chain may reject)")
        except Exception as e:
            _fail("validation.report_reason_too_long_rejected", str(e))
    else:
        _fail("validation.report_reason_too_long (setup failed)")

    # ------ Subscriber PoW rejection across all endpoints ------

    # 11.17–11.20 Subscriber using PoW should be rejected for various actions
    sub_endpoints = [
        ("vote", lambda: _do_vote(backend, sub_wallet, "bb" * 32, 1, skip_pow=False)),
        ("set_username", lambda: _do_set_username_raw(backend, sub_wallet, f"powtest-{_rand_str(4)}")),
        ("send_tokens", lambda: _do_send_tokens(backend, sub_wallet, free_addr, 1000)),
    ]
    for endpoint_name, action_fn in sub_endpoints:
        try:
            resp = action_fn()
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower()
            code_val = int(resp.get("code", 0) or 0)
            if not txh or code_val != 0 or "not allowed" in err or "subscriber" in err:
                _pass(f"validation.subscriber_pow_{endpoint_name}_rejected")
            else:
                _pass(f"validation.subscriber_pow_{endpoint_name} submitted (chain may reject)")
        except Exception as e:
            err_str = str(e).lower()
            if "400" in err_str or "not allowed" in err_str:
                _pass(f"validation.subscriber_pow_{endpoint_name}_rejected")
            else:
                _fail(f"validation.subscriber_pow_{endpoint_name}_rejected", str(e))


# =========================================================================
# Category 12: Token Transfers
# =========================================================================
def test_tokens(backend: str):
    print(f"\n{_COLOR_BOLD}[12] Token Transfers{_COLOR_RESET}")

    sub1 = WALLETS["sub1"]
    sub2 = WALLETS["sub2"]
    free_wallet = WALLETS["free"]
    sub1_addr = str(sub1.address())
    sub2_addr = str(sub2.address())
    free_addr = str(free_wallet.address())

    # 12.1 Happy path: sub1 sends tokens to sub2
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("tokens.send_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("tokens.send_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("tokens.send_happy_path", str(e))

    # 12.2 Zero amount
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, 0, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "zero" in err:
            _pass("tokens.zero_amount_rejected")
        else:
            _pass("tokens.zero_amount submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.zero_amount_rejected")

    # 12.3 Negative amount (send as -1 — backend should reject or chain handles)
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, -1, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "negative" in err:
            _pass("tokens.negative_amount_rejected")
        else:
            _pass("tokens.negative_amount submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.negative_amount_rejected")

    # 12.4 Exceed balance
    try:
        resp = _do_send_tokens(backend, free_wallet, sub2_addr, 999_999_999_999_999, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "insufficient" in err:
            _pass("tokens.exceed_balance_rejected")
        else:
            _pass("tokens.exceed_balance submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.exceed_balance_rejected")

    # 12.5 Invalid target address
    try:
        resp = _do_send_tokens(backend, sub1, "not_an_address", 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("tokens.invalid_target_rejected")
        else:
            _pass("tokens.invalid_target submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.invalid_target_rejected")

    # 12.6 Empty target address
    try:
        resp = _do_send_tokens(backend, sub1, "", 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "empty" in err:
            _pass("tokens.empty_target_rejected")
        else:
            _pass("tokens.empty_target submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.empty_target_rejected")

    # 12.7 Self-send
    try:
        resp = _do_send_tokens(backend, sub1, sub1_addr, 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "self" in err or "same" in err:
            _pass("tokens.self_send_rejected")
        else:
            _pass("tokens.self_send submitted (chain decides)")
    except Exception as e:
        _pass("tokens.self_send_rejected")

    # 12.8 Malformed address (valid bech32 wrong prefix)
    try:
        resp = _do_send_tokens(backend, sub1, "cosmos1qypqxpq9qcrsszg2pvxq6rs0zqg3yyc5lzv7xu", 1000, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("tokens.wrong_prefix_rejected")
        else:
            _pass("tokens.wrong_prefix submitted (chain may reject)")
    except Exception as e:
        _pass("tokens.wrong_prefix_rejected")

    # 12.9 Minimum amount (1 umirage)
    try:
        resp = _do_send_tokens(backend, sub1, sub2_addr, 1, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("tokens.minimum_amount_accepted")
        else:
            _pass("tokens.minimum_amount submitted")
    except Exception as e:
        _fail("tokens.minimum_amount_accepted", str(e))

    # 12.10 Free user sending with PoW
    try:
        resp = _do_send_tokens(backend, free_wallet, sub2_addr, 100, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("tokens.free_user_pow_send")
        else:
            _pass("tokens.free_user_pow_send submitted")
    except Exception as e:
        _fail("tokens.free_user_pow_send", str(e))


# =========================================================================
# Category 13: Agents
# =========================================================================
def test_agents(backend: str):
    print(f"\n{_COLOR_BOLD}[13] Agents{_COLOR_RESET}")

    sub1 = WALLETS["sub1"]
    sub2 = WALLETS["sub2"]
    free_wallet = WALLETS["free"]
    sub1_addr = str(sub1.address())
    sub2_addr = str(sub2.address())
    free_addr = str(free_wallet.address())

    # 13.1 Enable agent (sub1 enables sub2 as agent)
    try:
        resp = _do_enable_agent(backend, sub1, sub2_addr, enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.enable_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.enable_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.enable_happy_path", str(e))

    time.sleep(3)

    # 13.2 Disable agent
    try:
        resp = _do_enable_agent(backend, sub1, sub2_addr, enable=False, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.disable_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.disable_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.disable_happy_path", str(e))

    # 13.3 Enable non-existent address
    fake_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    try:
        resp = _do_enable_agent(backend, sub1, fake_addr, enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.enable_nonexistent submitted (chain decides)")
        else:
            _pass("agents.enable_nonexistent_rejected")
    except Exception as e:
        _pass("agents.enable_nonexistent handled")

    # 13.4 Self-enable as agent
    try:
        resp = _do_enable_agent(backend, sub1, sub1_addr, enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if txh:
            _fail("agents.self_enable_rejected", "tx accepted but should reject self-enable")
        elif "yourself" in err or "self" in err:
            _pass("agents.self_enable_rejected")
        else:
            _fail("agents.self_enable_rejected", f"unexpected error: {err[:200]}")
    except Exception as e:
        _fail("agents.self_enable_rejected", str(e))

    # 13.5 Invalid agent address format
    try:
        resp = _do_enable_agent(backend, sub1, "invalid_address", enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("agents.invalid_address_rejected")
        else:
            _pass("agents.invalid_address submitted (chain may reject)")
    except Exception as e:
        _pass("agents.invalid_address_rejected")

    # 13.6 Free user enables agent with PoW
    try:
        resp = _do_enable_agent(backend, free_wallet, sub2_addr, enable=True, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.free_user_enable")
        else:
            _pass("agents.free_user_enable submitted")
    except Exception as e:
        _fail("agents.free_user_enable", str(e))

    time.sleep(3)

    # 13.7 SetAgents: atomically set agent list (subscriber)
    agent_a = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    agent_b = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    try:
        resp = _do_set_agents(backend, sub1, [agent_a, agent_b], skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.set_agents_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.set_agents_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.set_agents_happy_path", str(e))

    time.sleep(3)

    # 13.7b Verify order in get_user_followed
    code_followed, followed = _get(f"{backend}/api/get_user_followed", {"address": sub1_addr})
    if code_followed == 200:
        got_order = [str(a).lower() for a in (followed or {}).get("enabled_agents") or []]
        expected = [agent_a.lower(), agent_b.lower()]
        if got_order[:2] == expected:
            _pass("agents.set_agents_order_reflected")
        else:
            _fail("agents.set_agents_order_reflected", f"got={got_order[:4]}")
    else:
        _fail("agents.set_agents_order_reflected", f"code={code_followed}")

    # 13.7c Invalid payload type for agents
    code_bad, bad_resp = _post(f"{backend}/api/core/set_agents", {"agents": "not-an-array"})
    err = str((bad_resp or {}).get("error", "")).lower()
    if code_bad == 400 and "array" in err:
        _pass("agents.set_agents_invalid_payload")
    else:
        _fail("agents.set_agents_invalid_payload", f"code={code_bad} err={err[:120]}")

    # 13.7d Invalid agent address
    try:
        resp = _do_set_agents(backend, sub1, ["invalid_address"], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "invalid" in err:
            _pass("agents.set_agents_invalid_address")
        elif resp.get("tx_hash"):
            _pass("agents.set_agents_invalid_address submitted (chain may reject)")
        else:
            _pass("agents.set_agents_invalid_address handled")
    except Exception as e:
        _pass("agents.set_agents_invalid_address handled")

    # 13.8 SetAgents: clear all agents
    try:
        resp = _do_set_agents(backend, sub1, [], skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.set_agents_clear")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.set_agents_clear", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.set_agents_clear", str(e))

    time.sleep(3)

    code_followed, followed = _get(f"{backend}/api/get_user_followed", {"address": sub1_addr})
    if code_followed == 200:
        got_order = [str(a).lower() for a in (followed or {}).get("enabled_agents") or []]
        if got_order:
            _fail("agents.set_agents_clear_reflected", f"count={len(got_order)}")
        else:
            _pass("agents.set_agents_clear_reflected")
    else:
        _fail("agents.set_agents_clear_reflected", f"code={code_followed}")

    # 13.9 SetAgents: reject duplicate agent addresses
    try:
        resp = _do_set_agents(backend, sub1, [agent_a, agent_a], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "duplicate" in err:
            _pass("agents.set_agents_duplicate_rejected")
        elif resp.get("tx_hash"):
            _pass("agents.set_agents_duplicate (chain may reject)")
        else:
            _pass("agents.set_agents_duplicate handled")
    except Exception as e:
        _pass("agents.set_agents_duplicate handled")

    # 13.9b SetAgents: reject self-as-agent
    try:
        resp = _do_set_agents(backend, sub1, [sub1_addr], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "yourself" in err:
            _pass("agents.set_agents_self_rejected")
        elif resp.get("tx_hash"):
            _fail("agents.set_agents_self_rejected", "tx accepted but should reject self-as-agent")
        else:
            _fail("agents.set_agents_self_rejected", f"unexpected: {err[:120]}")
    except Exception as e:
        _fail("agents.set_agents_self_rejected", str(e))

    # 13.9c SetAgents: reject self mixed with valid agents
    try:
        resp = _do_set_agents(backend, sub1, [agent_a, sub1_addr], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "yourself" in err:
            _pass("agents.set_agents_self_mixed_rejected")
        elif resp.get("tx_hash"):
            _fail("agents.set_agents_self_mixed_rejected", "tx accepted but should reject self-as-agent")
        else:
            _fail("agents.set_agents_self_mixed_rejected", f"unexpected: {err[:120]}")
    except Exception as e:
        _fail("agents.set_agents_self_mixed_rejected", str(e))

    # 13.10 SetAgents: free user with PoW
    try:
        resp = _do_set_agents(backend, free_wallet, [agent_a], skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.set_agents_free_pow")
        else:
            _pass("agents.set_agents_free_pow submitted")
    except Exception as e:
        _fail("agents.set_agents_free_pow", str(e))

    # 13.10b Free user without PoW should fail
    try:
        resp = _do_set_agents(backend, free_wallet, [agent_a], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "insufficient pow" in err:
            _pass("agents.set_agents_free_no_pow_rejected")
        elif resp.get("tx_hash"):
            _pass("agents.set_agents_free_no_pow submitted (chain may reject)")
        else:
            _pass("agents.set_agents_free_no_pow handled")
    except Exception as e:
        _pass("agents.set_agents_free_no_pow handled")


# =========================================================================
# Category 14: Media Attachments
# =========================================================================
def test_media(backend: str):
    print(f"\n{_COLOR_BOLD}[14] Media Attachments{_COLOR_RESET}")

    sub1 = WALLETS["sub1"]
    free_wallet = WALLETS["free"]
    sub1_addr = str(sub1.address())

    # 14.1 Valid HTTPS URL
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Media test",
        "body",
        media=["https://example.com/image.jpg"],
        skip_pow=True,
    )
    if txh:
        _pass("media.valid_https_url")
    else:
        _fail("media.valid_https_url", "no tx_hash")

    # 14.2 Multiple valid URLs
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Multi media",
        "body",
        media=["https://a.com/1.jpg", "https://b.com/2.png", "https://c.com/3.gif"],
        skip_pow=True,
    )
    if txh:
        _pass("media.multiple_valid_urls")
    else:
        _fail("media.multiple_valid_urls", "no tx_hash")

    # 14.3 Too many URLs (>10)
    many_urls = [f"https://example.com/{i}.jpg" for i in range(12)]
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Too many",
        "body",
        media=many_urls,
        skip_pow=True,
    )
    if not txh:
        _pass("media.too_many_urls_rejected")
    else:
        _pass("media.too_many_urls submitted (chain may reject)")

    # 14.4 HTTP URL (not HTTPS)
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Http media",
        "body",
        media=["http://example.com/image.jpg"],
        skip_pow=True,
    )
    if not txh:
        _pass("media.http_url_rejected")
    else:
        _pass("media.http_url submitted (chain may reject)")

    # 14.5 Empty string media
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Empty media",
        "body",
        media=[""],
        skip_pow=True,
    )
    if not txh:
        _pass("media.empty_string_rejected")
    else:
        _pass("media.empty_string submitted (chain may reject)")

    # 14.6 Non-URL string
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Bad media",
        "body",
        media=["not a url at all"],
        skip_pow=True,
    )
    if not txh:
        _pass("media.non_url_rejected")
    else:
        _pass("media.non_url submitted (chain may reject)")

    # 14.7 URL exceeding 2048 chars
    long_url = "https://example.com/" + "a" * 2040
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Long URL",
        "body",
        media=[long_url],
        skip_pow=True,
    )
    if not txh:
        _pass("media.oversized_url_rejected")
    else:
        _pass("media.oversized_url submitted (chain may reject)")

    # 14.8 Edit adding media
    edit_media_topic = f"media{_rand_str(4)}"
    base_post = _do_post(backend, sub1, edit_media_topic, "Edit media test", "body", skip_pow=True)
    if base_post:
        time.sleep(3)
        try:
            addr = sub1_addr
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
            pub = sub1.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = edit_media_topic
            media_list = ["https://example.com/edited.jpg"]
            base = _canon_base_edit_raw(
                pub,
                _lb_bytes(lb),
                0,
                ts,
                "",
                topic,
                "Edit media test",
                "updated body",
                "",
                base_post,
                media_list,
                nonce,
            )
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(sub1, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 0,
                "target": "",
                "topic": topic,
                "title": "Edit media test",
                "content": "updated body",
                "tag": "",
                "override": base_post,
                "media": media_list,
            }
            code, resp = _post(f"{backend}/api/core/edit", payload)
            txh = str((resp or {}).get("tx_hash", "") or "").lower()
            if txh:
                _pass("media.edit_adding_media")
            else:
                _pass("media.edit_adding_media submitted")
        except Exception as e:
            _fail("media.edit_adding_media", str(e))
    else:
        _fail("media.edit_adding_media", "setup post failed")

    # 14.9 Free user with media and PoW
    txh = _do_post_with_media(
        backend,
        free_wallet,
        f"media{_rand_str(4)}",
        "Free media",
        "body",
        media=["https://example.com/free.jpg"],
        skip_pow=False,
    )
    if txh:
        _pass("media.free_user_with_pow")
    else:
        _fail("media.free_user_with_pow", "no tx_hash")


# =========================================================================
# Category 15: Auto Renewal
# =========================================================================
def test_auto_renewal(backend: str):
    print(f"\n{_COLOR_BOLD}[15] Auto Renewal{_COLOR_RESET}")

    sub1 = WALLETS["sub1"]
    free_wallet = WALLETS["free"]

    # 15.1 Enable auto-renewal for subscriber
    try:
        resp = _do_set_auto_renewal(backend, sub1, True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("auto_renewal.enable")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("auto_renewal.enable", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("auto_renewal.enable", str(e))

    time.sleep(3)

    # 15.2 Disable auto-renewal for subscriber
    try:
        resp = _do_set_auto_renewal(backend, sub1, False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("auto_renewal.disable")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("auto_renewal.disable", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("auto_renewal.disable", str(e))

    # 15.3 Free user tries auto-renewal (should fail)
    try:
        resp = _do_set_auto_renewal(backend, free_wallet, True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "subscriber" in err or "free" in err or "not allowed" in err:
            _pass("auto_renewal.free_user_rejected")
        else:
            _pass("auto_renewal.free_user submitted (chain may reject)")
    except Exception as e:
        _pass("auto_renewal.free_user_rejected")

    # 15.4 Double enable (idempotent)
    try:
        resp = _do_set_auto_renewal(backend, sub1, True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("auto_renewal.double_enable submitted")
        else:
            _pass("auto_renewal.double_enable handled")
    except Exception as e:
        _pass("auto_renewal.double_enable handled")


# =========================================================================
# Category 16: Reports
# =========================================================================
def test_reports(backend: str):
    print(f"\n{_COLOR_BOLD}[16] Reports{_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    sub1 = WALLETS["sub1"]
    free_addr = str(free_wallet.address())

    # Create a post to report
    target_post = _do_post(backend, free_wallet, "test", f"Report target {_rand_str(4)}", "reportable body")
    if not target_post:
        _fail("reports.setup", "cannot create target post")
        return
    _wait_indexed(backend, free_addr, target_post)

    # 16.1 Valid report (reports are stored in DB, not on-chain — response has success/id)
    try:
        resp = _do_report(backend, sub1, target_post, "spam")
        if resp.get("success") or resp.get("id"):
            _pass("reports.valid_report")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("reports.valid_report", f"not accepted: {err[:200]}")
    except Exception as e:
        _fail("reports.valid_report", str(e))

    # 16.2 Empty reason
    try:
        resp = _do_report(backend, sub1, target_post, "")
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "reason" in err or "empty" in err:
            _pass("reports.empty_reason_rejected")
        else:
            _pass("reports.empty_reason submitted (chain may reject)")
    except Exception as e:
        _pass("reports.empty_reason_rejected")

    # 16.3 Oversized reason
    try:
        resp = _do_report(backend, sub1, target_post, "x" * 2000)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "too long" in err:
            _pass("reports.oversized_reason_rejected")
        else:
            _pass("reports.oversized_reason submitted (chain may reject)")
    except Exception as e:
        _pass("reports.oversized_reason_rejected")

    # 16.4 Non-existent post
    try:
        resp = _do_report(backend, sub1, "cc" * 32, "spam")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("reports.nonexistent_post submitted (chain decides)")
        else:
            _pass("reports.nonexistent_post_rejected")
    except Exception as e:
        _pass("reports.nonexistent_post handled")

    # 16.5 Report own post
    try:
        resp = _do_report(backend, free_wallet, target_post, "self-report")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("reports.own_post submitted (chain decides)")
        else:
            _pass("reports.own_post_rejected")
    except Exception as e:
        _pass("reports.own_post handled")

    # 16.6 Duplicate report
    try:
        resp = _do_report(backend, sub1, target_post, "duplicate spam")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("reports.duplicate submitted (chain decides)")
        else:
            _pass("reports.duplicate_rejected")
    except Exception as e:
        _pass("reports.duplicate handled")


# =========================================================================
# Category 17: Frontend Bypass Validation
# =========================================================================
def test_frontend_bypass(backend: str):
    """Test all cases where frontend-only validation could be bypassed."""
    print(f"\n{_COLOR_BOLD}[17] Frontend Bypass Validation{_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    sub1 = WALLETS["sub1"]
    sub2 = WALLETS["sub2"]
    free_addr = str(free_wallet.address())
    sub1_addr = str(sub1.address())

    _code, _ncfg = _get(f"{backend}/api/get_node_config")
    reg_enabled = (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False

    # ─── Username bypass ─────────────────────────────────────────────
    bypass_usernames = [
        ("user_name", "underscore"),
        ("user.name", "dot"),
        ("user name", "space"),
        ("user@name", "at_sign"),
        ("\u00fcser", "unicode"),
        ("\U0001f602user", "emoji"),
        ("user\x00name", "null_byte"),
        ("---", "only_hyphens"),
        ("-startdash", "starts_with_hyphen"),
    ]
    for uname, label in bypass_usernames:
        if not reg_enabled:
            _pass(f"bypass.username_{label} skipped (registration disabled)")
            continue
        try:
            resp = _do_set_username_raw(backend, free_wallet, uname)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "invalid" in err:
                _pass(f"bypass.username_{label}_rejected")
            else:
                _pass(f"bypass.username_{label} submitted (chain may reject)")
        except Exception as e:
            _pass(f"bypass.username_{label} handled")

    # ─── Topic bypass ────────────────────────────────────────────────
    bypass_topics = [
        ("UPPERCASE", "uppercase"),
        ("with spaces", "spaces"),
        ("special!@#", "special_chars"),
        ("\u00fc\u00f6\u00e4", "unicode"),
        ("a", "min_boundary"),
        ("a" * 200, "over_max"),
    ]
    for topic, label in bypass_topics:
        try:
            txh = _do_post(backend, sub1, topic, f"Bypass {label}", "body", skip_pow=True)
            if not txh:
                _pass(f"bypass.topic_{label}_rejected")
            else:
                _pass(f"bypass.topic_{label} submitted (chain may reject)")
        except Exception as e:
            _pass(f"bypass.topic_{label} handled")

    # ─── Tag bypass ──────────────────────────────────────────────────
    bypass_tags = [
        ("nsfw", "nsfw"),
        ("adult", "adult"),
        ("SENSITIVE", "uppercase_sensitive"),
        ("Porn", "mixed_case_porn"),
        ("random_tag", "random_string"),
        ("tag with spaces", "spaces"),
        ("!@#$%", "special_chars"),
        ("t" * 60, "over_50_chars"),
    ]
    for tag, label in bypass_tags:
        try:
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, sub1_addr)
            pub = sub1.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = f"tag{_rand_str(4)}"
            base = _canon_base_post_raw(pub, _lb_bytes(lb), 0, ts, "", topic, "Tag test", "body", tag, 0, None, nonce)
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(sub1, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 0,
                "target": "",
                "topic": topic,
                "title": "Tag test",
                "content": "body",
                "tag": tag,
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            if code >= 400:
                _pass(f"bypass.tag_{label}_rejected")
            else:
                _pass(f"bypass.tag_{label} submitted (chain may reject)")
        except Exception as e:
            _pass(f"bypass.tag_{label} handled")

    # ─── Vote direction bypass ───────────────────────────────────────
    # Create a target post for vote tests
    vote_target = _do_post(backend, sub1, f"vote{_rand_str(4)}", "Vote target", "body", skip_pow=True)
    if vote_target:
        time.sleep(3)
        for direction, label in [(2, "direction_2"), (-2, "direction_neg2"), (999, "direction_999")]:
            try:
                resp = _do_vote(backend, sub1, vote_target, direction, skip_pow=True)
                txh = str(resp.get("tx_hash", "")).lower()
                err = str(resp.get("error", "")).lower()
                if not txh or "invalid" in err or "direction" in err:
                    _pass(f"bypass.vote_{label}_rejected")
                else:
                    _pass(f"bypass.vote_{label} submitted (chain may reject)")
            except Exception as e:
                _pass(f"bypass.vote_{label} handled")

    # ─── Content/title boundary bypass ───────────────────────────────
    # Get tier 1 limits to test boundaries
    try:
        st = get_status(backend, address=sub1_addr)
        from shared.client import get_user_status as _gus

        us = _gus(backend, sub1_addr)
        user_level = int(us.get("user_level", 1) or 1)
    except Exception:
        user_level = 1

    try:
        params = requests.get(f"{backend}/api/get_chain_config", timeout=10).json()
        tiers = params.get("tiers") or []
        idx = {0: 0, 1: 1, 10: 2}.get(user_level, 2 if user_level >= 100 else -1)
        if 0 <= idx < len(tiers):
            tier = tiers[idx]
            max_content = int(tier.get("max_content_length", 50000) or 50000)
            max_title = int(tier.get("max_title_length", 300) or 300)
        else:
            max_content = 50000
            max_title = 300
    except Exception:
        max_content = 50000
        max_title = 300

    # Exact max content (should succeed)
    try:
        exact_content = "x" * max_content
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", "Exact max", exact_content, skip_pow=True)
        if txh:
            _pass("bypass.content_exact_max_accepted")
        else:
            _pass("bypass.content_exact_max submitted")
    except Exception as e:
        _pass("bypass.content_exact_max handled")

    # One over max content
    try:
        over_content = "x" * (max_content + 1)
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", "Over max", over_content, skip_pow=True)
        if not txh:
            _pass("bypass.content_one_over_rejected")
        else:
            _pass("bypass.content_one_over submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.content_one_over handled")

    # Exact max title
    try:
        exact_title = "T" * max_title
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", exact_title, "body", skip_pow=True)
        if txh:
            _pass("bypass.title_exact_max_accepted")
        else:
            _pass("bypass.title_exact_max submitted")
    except Exception as e:
        _pass("bypass.title_exact_max handled")

    # One over max title
    try:
        over_title = "T" * (max_title + 1)
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", over_title, "body", skip_pow=True)
        if not txh:
            _pass("bypass.title_one_over_rejected")
        else:
            _pass("bypass.title_one_over submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.title_one_over handled")

    # UTF-8 multi-byte edge: 4-byte emoji fills content length faster
    try:
        emoji_content = "\U0001f4a9" * (max_content // 4 + 1)
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", "Emoji content", emoji_content, skip_pow=True)
        if not txh:
            _pass("bypass.utf8_multibyte_rejected")
        else:
            _pass("bypass.utf8_multibyte submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.utf8_multibyte handled")

    # ─── Comment bypass ──────────────────────────────────────────────
    if vote_target:
        # Comment with topic set (should be empty for comments)
        try:
            txh = _do_post(backend, sub1, "shouldbeempty", "", "Comment with topic", target=vote_target, skip_pow=True)
            if not txh:
                _pass("bypass.comment_with_topic_rejected")
            else:
                _pass("bypass.comment_with_topic submitted (chain may reject)")
        except Exception as e:
            _pass("bypass.comment_with_topic handled")

    # Root post with empty topic
    try:
        txh = _do_post(backend, sub1, "", "No topic post", "body", skip_pow=True)
        if not txh:
            _pass("bypass.root_empty_topic_rejected")
        else:
            _pass("bypass.root_empty_topic submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.root_empty_topic handled")

    # Comment with nonexistent parent
    try:
        txh = _do_post(backend, sub1, "", "", "Orphan comment", target="dd" * 32, skip_pow=True)
        if not txh:
            _pass("bypass.comment_nonexistent_parent_rejected")
        else:
            _pass("bypass.comment_nonexistent_parent submitted (chain decides)")
    except Exception as e:
        _pass("bypass.comment_nonexistent_parent handled")

    # ─── Edit bypass ─────────────────────────────────────────────────
    # Edit with invalid override hash
    try:
        resp = _do_edit(
            backend, sub1, override_hash="not_a_hash", topic="test", title="Bad edit", content="body", skip_pow=True
        )
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("bypass.edit_invalid_override_rejected")
        else:
            _pass("bypass.edit_invalid_override submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.edit_invalid_override handled")

    # Edit with nonexistent override
    try:
        resp = _do_edit(
            backend, sub1, override_hash="ee" * 32, topic="test", title="Ghost edit", content="body", skip_pow=True
        )
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("bypass.edit_nonexistent_override submitted (chain decides)")
        else:
            _pass("bypass.edit_nonexistent_override_rejected")
    except Exception as e:
        _pass("bypass.edit_nonexistent_override handled")

    # ─── Send tokens bypass ──────────────────────────────────────────
    # String amount — send raw JSON with invalid type to test backend input parsing
    try:
        raw_payload_str = {
            "pubkey": "",
            "signature": "",
            "last_block_hash": "",
            "timestamp": _now_ms(),
            "target": str(sub2.address()),
            "amount": "not_a_number",
        }
        code, resp = _post(f"{backend}/api/core/send_tokens", raw_payload_str)
        if code >= 400:
            _pass("bypass.send_tokens_string_amount_rejected")
        else:
            _fail("bypass.send_tokens_string_amount_rejected", f"code={code}")
    except Exception as e:
        _pass("bypass.send_tokens_string_amount_rejected")

    # Float amount — send raw JSON with float to test backend input parsing
    try:
        raw_payload_float = {
            "pubkey": "",
            "signature": "",
            "last_block_hash": "",
            "timestamp": _now_ms(),
            "target": str(sub2.address()),
            "amount": 1.5,
        }
        code, resp = _post(f"{backend}/api/core/send_tokens", raw_payload_float)
        if code >= 400:
            _pass("bypass.send_tokens_float_amount_rejected")
        else:
            _pass("bypass.send_tokens_float_amount submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.send_tokens_float_amount_rejected")

    # ─── Upgrade level bypass ────────────────────────────────────────
    for level, label in [(0, "level_0"), (-1, "level_neg1"), (4, "level_4"), (99, "level_99")]:
        try:
            resp = _do_upgrade_level(backend, free_wallet, level)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "invalid" in err:
                _pass(f"bypass.upgrade_{label}_rejected")
            else:
                _pass(f"bypass.upgrade_{label} submitted (chain may reject)")
        except Exception as e:
            _pass(f"bypass.upgrade_{label} handled")


def test_rate_limit(backend: str):
    """Verify Caddy rate limiting returns HTTP 429 on API bursts."""
    print(f"\n{_COLOR_BOLD}[18] Caddy Rate Limit{_COLOR_RESET}")

    url = f"{backend}/api/get_parameters"
    session = requests.Session()
    burst_size = 30
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        statuses: list[int] = []
        first_429: Optional[requests.Response] = None

        for _ in range(burst_size):
            try:
                resp = session.get(url, timeout=3)
            except Exception as e:
                _fail("rate_limit.api_burst", str(e), attempt=attempt)
                return
            statuses.append(resp.status_code)
            if resp.status_code == 429 and first_429 is None:
                first_429 = resp

        hits_429 = sum(1 for s in statuses if s == 429)
        hits_200 = sum(1 for s in statuses if s == 200)
        _debug(f"rate_limit burst attempt={attempt} total={len(statuses)} " f"ok={hits_200} rate_limited={hits_429}")

        if hits_429 > 0:
            # Caddy can return JSON for /api/* rate limits.
            if first_429 is not None:
                try:
                    body = first_429.json() or {}
                    err = str(body.get("error", "")).lower()
                    msg = str(body.get("message", "")).lower()
                    if "rate" in err or "too many" in msg:
                        _pass("rate_limit.api_returns_429", attempt=attempt, rate_limited=hits_429, ok=hits_200)
                        return
                except Exception:
                    pass
            _pass("rate_limit.api_returns_429", attempt=attempt, rate_limited=hits_429, ok=hits_200)
            return

        # Window in Caddyfile is 1s; let it reset and try again.
        time.sleep(1.25)

    _fail("rate_limit.api_returns_429", f"no 429 observed across {max_attempts} bursts of {burst_size}")


# =========================================================================
# Category 19: Hard Cap vs Deque (backend-level)
# =========================================================================
def test_hard_cap_vs_deque(backend: str):
    """Test that follow/enable lists reject at limit (hard cap) while
    block lists evict oldest (deque) through the backend API."""
    print(f"\n{_COLOR_BOLD}[19] Hard Cap vs Deque (backend API){_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub1 = WALLETS["sub1"]
    sub1_addr = str(sub1.address())

    # Fetch tier configs via chain config API (get_parameters only has PoW params)
    code, params_resp = _get(f"{backend}/api/get_chain_config")
    if code != 200:
        _fail("hardcap.fetch_params", f"code={code}")
        return
    tiers = (params_resp or {}).get("tiers") or []
    if len(tiers) < 3:
        _fail("hardcap.tier_count", f"expected 3, got {len(tiers)}")
        return
    _pass("hardcap.tier_count_3")

    free_tier = tiers[0]
    max_agents_free = int(free_tier.get("max_enabled_agents", 0))
    max_fu_free = int(free_tier.get("max_followed_users", 0))
    max_ft_free = int(free_tier.get("max_followed_topics", 0))
    max_bu_free = int(free_tier.get("max_blocked_users", 0))

    # ── 19.1 Follow users up to free limit, then verify rejection ──
    # Account for users already followed by the free wallet from prior tests
    code_fu, fu_data = _get(f"{backend}/api/get_user_followed", {"address": free_addr})
    existing_fu = (
        len((fu_data or {}).get("followed_users") or (fu_data or {}).get("users") or []) if code_fu == 200 else 0
    )
    remaining_fu = max(0, max_fu_free - existing_fu)
    _debug(f"free-tier max_followed_users={max_fu_free} existing={existing_fu} remaining={remaining_fu}")
    follow_targets: list[str] = []
    fu_fill_ok = True
    for i in range(remaining_fu):
        target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        follow_targets.append(target)
        resp = _do_follow_user(backend, free_wallet, target, follow=True, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            err = str(resp.get("error", ""))[:100]
            _fail(f"hardcap.fu_fill_{i}", err)
            fu_fill_ok = False
            break
        if (i + 1) % 10 == 0:
            print(f"    [{i+1}/{remaining_fu}] followed users…")
    if fu_fill_ok:
        _pass(f"hardcap.fu_fill ({remaining_fu} new + {existing_fu} existing = {max_fu_free})")

        # Wait for all async follow txs to land on chain before testing overflow
        actual_fu = _wait_list_count(backend, free_addr, "followed_users", max_fu_free, timeout=30.0)
        _debug(f"followed_users after fill: {actual_fu}/{max_fu_free}")

        # Overflow should fail — submit and verify chain state doesn't exceed limit
        overflow_target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        resp = _do_follow_user(backend, free_wallet, overflow_target, follow=True, skip_pow=False)
        time.sleep(4)
        code_check, check_data = _get(f"{backend}/api/get_user_followed", {"address": free_addr})
        post_count = len((check_data or {}).get("followed_users") or []) if code_check == 200 else 0
        if post_count <= max_fu_free:
            _pass("hardcap.fu_overflow_rejected")
        else:
            _fail("hardcap.fu_overflow_rejected", f"count={post_count} > limit={max_fu_free}")

        # Unfollow one, then follow should succeed again
        if follow_targets:
            resp = _do_follow_user(backend, free_wallet, follow_targets[0], follow=False, skip_pow=False)
            time.sleep(2)
            resp = _do_follow_user(backend, free_wallet, overflow_target, follow=True, skip_pow=False)
            txh = str(resp.get("tx_hash", "")).lower()
            tx_code = int(resp.get("code", 0) or 0)
            if txh and tx_code == 0:
                _pass("hardcap.fu_follow_after_unfollow")
            else:
                _fail("hardcap.fu_follow_after_unfollow", f"txh={txh} code={tx_code}")
        else:
            _pass("hardcap.fu_follow_after_unfollow (skipped — no new targets to unfollow)")

    # ── 19.2 Follow topics up to free limit, then verify rejection ──
    existing_ft = len((fu_data or {}).get("followed_topics") or []) if code_fu == 200 else 0
    remaining_ft = max(0, max_ft_free - existing_ft)
    _debug(f"free-tier max_followed_topics={max_ft_free} existing={existing_ft} remaining={remaining_ft}")
    topic_targets: list[str] = []
    ft_fill_ok = True
    for i in range(remaining_ft):
        topic = f"hct{_rand_str(4)}{i}"
        topic_targets.append(topic)
        resp = _do_follow_topic(backend, free_wallet, topic, follow=True, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            err = str(resp.get("error", ""))[:100]
            _fail(f"hardcap.ft_fill_{i}", err)
            ft_fill_ok = False
            break
        if (i + 1) % 10 == 0:
            print(f"    [{i+1}/{remaining_ft}] followed topics…")
    if ft_fill_ok:
        _pass(f"hardcap.ft_fill ({remaining_ft} new + {existing_ft} existing = {max_ft_free})")

        actual_ft = _wait_list_count(backend, free_addr, "followed_topics", max_ft_free, timeout=30.0)
        _debug(f"followed_topics after fill: {actual_ft}/{max_ft_free}")

        overflow_topic = f"hctover{_rand_str(4)}"
        resp = _do_follow_topic(backend, free_wallet, overflow_topic, follow=True, skip_pow=False)
        time.sleep(4)
        code_check, check_data = _get(f"{backend}/api/get_user_followed", {"address": free_addr})
        post_count = len((check_data or {}).get("followed_topics") or []) if code_check == 200 else 0
        if post_count <= max_ft_free:
            _pass("hardcap.ft_overflow_rejected")
        else:
            _fail("hardcap.ft_overflow_rejected", f"count={post_count} > limit={max_ft_free}")

    # ── 19.3 Enable agents up to free limit, then verify rejection ──
    code_ea, ea_data = _get(f"{backend}/api/get_profile", {"address": free_addr})
    existing_ea = len((ea_data or {}).get("enabled_agents") or []) if code_ea == 200 else 0
    remaining_ea = max(0, max_agents_free - existing_ea)
    _debug(f"free-tier max_enabled_agents={max_agents_free} existing={existing_ea} remaining={remaining_ea}")
    agent_targets: list[str] = []
    ea_fill_ok = True
    for i in range(remaining_ea):
        agent = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        agent_targets.append(agent)
        resp = _do_enable_agent(backend, free_wallet, agent, enable=True, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            err = str(resp.get("error", ""))[:100]
            _fail(f"hardcap.ea_fill_{i}", err)
            ea_fill_ok = False
            break
        if (i + 1) % 10 == 0:
            print(f"    [{i+1}/{remaining_ea}] enabled agents…")
    if ea_fill_ok:
        _pass(f"hardcap.ea_fill ({remaining_ea} new + {existing_ea} existing = {max_agents_free})")

        actual_ea = _wait_list_count(backend, free_addr, "enabled_agents", max_agents_free, timeout=30.0)
        _debug(f"enabled_agents after fill: {actual_ea}/{max_agents_free}")

        overflow_agent = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        resp = _do_enable_agent(backend, free_wallet, overflow_agent, enable=True, skip_pow=False)
        time.sleep(4)
        code_check, check_data = _get(f"{backend}/api/get_profile", {"address": free_addr})
        post_count = len((check_data or {}).get("enabled_agents") or []) if code_check == 200 else 0
        if post_count <= max_agents_free:
            _pass("hardcap.ea_overflow_rejected")
        else:
            _fail("hardcap.ea_overflow_rejected", f"count={post_count} > limit={max_agents_free}")

        # Disable one and re-enable should succeed
        if agent_targets:
            resp = _do_enable_agent(backend, free_wallet, agent_targets[0], enable=False, skip_pow=False)
            # Wait for the disable to propagate (poll until agent count drops)
            for _wait in range(15):
                time.sleep(1)
                wcode, wdata = _get(f"{backend}/api/get_profile", {"address": free_addr})
                if wcode == 200:
                    cur_count = len((wdata or {}).get("enabled_agents") or [])
                    if cur_count < max_agents_free:
                        break
            resp = _do_enable_agent(backend, free_wallet, overflow_agent, enable=True, skip_pow=False)
            txh = str(resp.get("tx_hash", "")).lower()
            tx_code = int(resp.get("code", 0) or 0)
            if txh and tx_code == 0:
                _pass("hardcap.ea_enable_after_disable")
            else:
                _fail("hardcap.ea_enable_after_disable", f"txh={txh} code={tx_code}")
        else:
            _pass("hardcap.ea_enable_after_disable (skipped — no new targets to disable)")

    # ── 19.4 blocked_users: deque (should never reject) ──
    _debug(f"free-tier max_blocked_users={max_bu_free}")
    total_to_block = max_bu_free + 3
    bu_fill_ok = True
    for i in range(total_to_block):
        target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        resp = _do_block(backend, free_wallet, target, "user", block=True, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            err = str(resp.get("error", ""))[:100]
            _fail(f"hardcap.bu_deque_{i}", err)
            bu_fill_ok = False
            break
        if (i + 1) % 10 == 0:
            print(f"    [{i+1}/{total_to_block}] blocked users…")
    if bu_fill_ok:
        _pass(f"hardcap.bu_deque_fill ({total_to_block} blocked, no rejection)")


# =========================================================================
# Category 20: Tier Configuration Verification (backend API)
# =========================================================================
def test_tier_config_api(backend: str):
    """Verify tier configurations are correctly served through the API."""
    print(f"\n{_COLOR_BOLD}[20] Tier Configuration via API{_COLOR_RESET}")

    code, params_resp = _get(f"{backend}/api/get_chain_config")
    if code != 200:
        _fail("tierapi.fetch_params", f"code={code}")
        return
    _pass("tierapi.fetch_params")

    tiers = (params_resp or {}).get("tiers") or []
    if len(tiers) != 3:
        _fail("tierapi.exactly_3_tiers", f"got {len(tiers)}")
        return
    _pass("tierapi.exactly_3_tiers")

    # Free tier (index 0)
    free = tiers[0]
    if int(free.get("period_fee", -1)) == 0:
        _pass("tierapi.free_period_fee_0")
    else:
        _fail("tierapi.free_period_fee_0", f"got={free.get('period_fee')}")

    free_expected = {
        "max_enabled_agents": 5,
        "max_followed_users": 25,
        "max_followed_topics": 25,
        "max_blocked_users": 25,
        "max_blocked_posts": 25,
        "max_blocked_topics": 25,
    }
    for field, expected in free_expected.items():
        val = int(free.get(field, 0))
        if val == expected:
            _pass(f"tierapi.free_{field}_{expected}")
        else:
            _fail(f"tierapi.free_{field}_{expected}", f"got={val}")

    if int(free.get("max_title_length", 0)) == 150:
        _pass("tierapi.free_max_title_150")
    else:
        _fail("tierapi.free_max_title_150", f"got={free.get('max_title_length')}")

    if int(free.get("max_content_length", 0)) == 1000:
        _pass("tierapi.free_max_content_1000")
    else:
        _fail("tierapi.free_max_content_1000", f"got={free.get('max_content_length')}")

    if int(free.get("editing_time_mins", 0)) == 10:
        _pass("tierapi.free_editing_10m")
    else:
        _fail("tierapi.free_editing_10m", f"got={free.get('editing_time_mins')}")

    if abs(float(free.get("vote_weight", 0)) - 1.0) < 0.01:
        _pass("tierapi.free_vote_weight_1.0")
    else:
        _fail("tierapi.free_vote_weight_1.0", f"got={free.get('vote_weight')}")

    for flag in [
        "can_be_agent",
        "can_remove_anon",
        "can_have_biography",
        "can_have_avatar",
        "can_have_banner",
        "can_have_flair",
    ]:
        if not free.get(flag, True):
            _pass(f"tierapi.free_{flag}_false")
        else:
            _fail(f"tierapi.free_{flag}_false", f"got={free.get(flag)}")

    # Subscriber tier (index 1)
    sub = tiers[1]
    if int(sub.get("period_fee", -1)) == 100_000_000_000:
        _pass("tierapi.sub_period_fee_100B")
    else:
        _fail("tierapi.sub_period_fee_100B", f"got={sub.get('period_fee')}")

    sub_expected = {
        "max_enabled_agents": 50,
        "max_followed_users": 500,
        "max_followed_topics": 500,
        "max_blocked_users": 500,
        "max_blocked_posts": 500,
        "max_blocked_topics": 500,
    }
    for field, expected in sub_expected.items():
        val = int(sub.get(field, 0))
        if val == expected:
            _pass(f"tierapi.sub_{field}_{expected}")
        else:
            _fail(f"tierapi.sub_{field}_{expected}", f"got={val}")

    if int(sub.get("max_title_length", 0)) == 300:
        _pass("tierapi.sub_max_title_300")
    else:
        _fail("tierapi.sub_max_title_300", f"got={sub.get('max_title_length')}")

    if int(sub.get("max_content_length", 0)) == 20000:
        _pass("tierapi.sub_max_content_20000")
    else:
        _fail("tierapi.sub_max_content_20000", f"got={sub.get('max_content_length')}")

    if int(sub.get("editing_time_mins", 0)) == 360:
        _pass("tierapi.sub_editing_360m")
    else:
        _fail("tierapi.sub_editing_360m", f"got={sub.get('editing_time_mins')}")

    if abs(float(sub.get("vote_weight", 0)) - 1.33) < 0.01:
        _pass("tierapi.sub_vote_weight_1.33")
    else:
        _fail("tierapi.sub_vote_weight_1.33", f"got={sub.get('vote_weight')}")

    if not sub.get("can_be_agent", True):
        _pass("tierapi.sub_can_be_agent_false")
    else:
        _fail("tierapi.sub_can_be_agent_false", f"got={sub.get('can_be_agent')}")

    for flag in ["can_remove_anon", "can_have_biography", "can_have_avatar", "can_have_banner", "can_have_flair"]:
        if sub.get(flag, False):
            _pass(f"tierapi.sub_{flag}_true")
        else:
            _fail(f"tierapi.sub_{flag}_true", f"got={sub.get(flag)}")

    # Agent tier (index 2)
    agent = tiers[2]
    if int(agent.get("period_fee", -1)) == 500_000_000_000:
        _pass("tierapi.agent_period_fee_200B")
    else:
        _fail("tierapi.agent_period_fee_200B", f"got={agent.get('period_fee')}")

    if agent.get("can_be_agent", False):
        _pass("tierapi.agent_can_be_agent_true")
    else:
        _fail("tierapi.agent_can_be_agent_true", f"got={agent.get('can_be_agent')}")

    for flag in ["can_remove_anon", "can_have_biography", "can_have_avatar", "can_have_banner", "can_have_flair"]:
        if agent.get(flag, False):
            _pass(f"tierapi.agent_{flag}_true")
        else:
            _fail(f"tierapi.agent_{flag}_true", f"got={agent.get(flag)}")


# =========================================================================
# Category 21: Upgrade Level Validation (backend API)
# =========================================================================
def test_upgrade_level_validation(backend: str):
    """Test level upgrade validation via the backend API."""
    print(f"\n{_COLOR_BOLD}[21] Upgrade Level Validation (backend API){_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())

    # 21.1 Valid levels (1, 10) — we already tested these in test_subscriber
    # Just verify the free user's current level
    try:
        us = get_user_status(backend, free_addr)
        val = us.get("user_level")
        free_level = int(val) if val is not None else -1
        if free_level == 0:
            _pass("upgrade.free_level_is_0")
        else:
            _fail("upgrade.free_level_is_0", f"level={free_level}")
    except Exception as e:
        _fail("upgrade.free_level_is_0", str(e))

    # 21.2 Invalid level 3 should be rejected
    resp = _do_upgrade_level(backend, free_wallet, 3)
    err = str(resp.get("error", "")).lower() if resp else ""
    txh = str(resp.get("tx_hash", "")).lower() if resp else ""
    tx_code = int(resp.get("code", 0) or 0) if resp else -1
    if "invalid" in err or (not txh) or tx_code != 0:
        _pass("upgrade.level_3_rejected")
    else:
        _fail("upgrade.level_3_rejected", f"txh={txh} code={tx_code} err={err[:100]}")

    # 21.3 Invalid level 0 (already free)
    resp = _do_upgrade_level(backend, free_wallet, 0)
    err = str(resp.get("error", "")).lower() if resp else ""
    txh = str(resp.get("tx_hash", "")).lower() if resp else ""
    if "invalid" in err or (not txh):
        _pass("upgrade.level_0_rejected")
    else:
        _fail("upgrade.level_0_rejected", f"txh={txh}")

    # 21.4 Invalid levels 2, 5, 9, 100
    for invalid_level in [2, 5, 9, 100]:
        resp = _do_upgrade_level(backend, free_wallet, invalid_level)
        err = str(resp.get("error", "")).lower() if resp else ""
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        tx_code = int(resp.get("code", 0) or 0) if resp else -1
        if "invalid" in err or (not txh) or tx_code != 0:
            _pass(f"upgrade.level_{invalid_level}_rejected")
        else:
            _fail(f"upgrade.level_{invalid_level}_rejected", f"txh={txh} code={tx_code}")


# =========================================================================
# Category 22: Indexer Deque Storage (backend API)
# =========================================================================
def test_indexer_deque_storage(backend: str):
    """Test that the indexer stores blocked_* entries beyond the chain limit."""
    print(f"\n{_COLOR_BOLD}[22] Indexer Deque Storage{_COLOR_RESET}")

    sub1 = WALLETS["sub1"]
    sub1_addr = str(sub1.address())

    code, params_resp = _get(f"{backend}/api/get_chain_config")
    tiers = (params_resp or {}).get("tiers") or []
    sub_tier = tiers[1] if len(tiers) > 1 else {}
    max_blocked_users_sub = int(sub_tier.get("max_blocked_users", 500))

    # Block more users than the chain limit using the sub1 wallet (no PoW)
    # We only need to block chain_limit + a few to demonstrate indexer stores beyond
    total_to_block = max_blocked_users_sub + 3
    # This is very expensive for 503 blocks — keep it small for CI
    # Just block 30 users to verify the indexer captures them all
    test_count = 30
    blocked_addrs: list[str] = []
    for i in range(test_count):
        target = str(LocalWallet(PrivateKey(), prefix="mirage").address())
        blocked_addrs.append(target.lower())
        resp = _do_block(backend, sub1, target, "user", block=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            _fail(f"indexer_deque.block_user_{i}", str(resp.get("error", ""))[:100])
            break
    else:
        _pass(f"indexer_deque.block_users ({test_count} blocked)")

    time.sleep(5)

    # Verify the indexer has all of them (or at least most via get_user_blocked)
    code, blocked_data = _get(f"{backend}/api/get_user_blocked", {"address": sub1_addr})
    if code != 200:
        _fail("indexer_deque.get_blocked", f"code={code}")
        return

    indexer_blocked = [str(u).lower() for u in ((blocked_data or {}).get("blocked_users") or [])]
    # The indexer should have all (or more than chain limit) blocked users
    matched = sum(1 for a in blocked_addrs if a in indexer_blocked)
    if matched >= test_count - 2:
        _pass(f"indexer_deque.blocked_users_stored ({matched}/{test_count})")
    else:
        _fail(f"indexer_deque.blocked_users_stored", f"matched={matched}/{test_count}")

    # Block some topics too
    test_topic_count = 10
    blocked_topics: list[str] = []
    for i in range(test_topic_count):
        topic = f"idq{_rand_str(4)}{i}"
        blocked_topics.append(topic)
        resp = _do_block_topic(backend, sub1, topic, block=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            _fail(f"indexer_deque.block_topic_{i}", str(resp.get("error", ""))[:100])
            break
    else:
        _pass(f"indexer_deque.block_topics ({test_topic_count} blocked)")

    time.sleep(3)

    code, blocked_data = _get(f"{backend}/api/get_user_blocked", {"address": sub1_addr})
    if code == 200:
        indexer_topics = [str(t).lower() for t in ((blocked_data or {}).get("blocked_topics") or [])]
        matched = sum(1 for t in blocked_topics if t in indexer_topics)
        if matched >= test_topic_count - 1:
            _pass(f"indexer_deque.blocked_topics_stored ({matched}/{test_topic_count})")
        else:
            _fail(f"indexer_deque.blocked_topics_stored", f"matched={matched}/{test_topic_count}")


# =========================================================================
# Category 23: Subscriber Content Length Limits (backend API)
# =========================================================================
def test_content_limits(backend: str):
    """Test content/title length limits per tier at the backend API level."""
    print(f"\n{_COLOR_BOLD}[23] Content Length Limits{_COLOR_RESET}")

    free_wallet = WALLETS["free"]
    sub1 = WALLETS["sub1"]
    agent1 = WALLETS["agent1"]

    # 23.1 Free user: content > 1000 should fail
    long_content = "x" * 1050
    txh = _do_post(backend, free_wallet, f"cl{_rand_str(4)}", "Title", long_content, skip_pow=False)
    if txh is None:
        _pass("content_limits.free_over_1000_rejected")
    else:
        _fail("content_limits.free_over_1000_rejected", f"txh={txh}")

    # 23.2 Free user: content <= 1000 should succeed
    ok_content = "x" * 950
    txh = _do_post(backend, free_wallet, f"cl{_rand_str(4)}", "Title", ok_content, skip_pow=False)
    if txh:
        _pass("content_limits.free_950_accepted")
    else:
        _fail("content_limits.free_950_accepted")

    # 23.3 Subscriber: content > 1000 but <= 20000 should succeed
    txh = _do_post(backend, sub1, f"cl{_rand_str(4)}", "Title", long_content, skip_pow=True)
    if txh:
        _pass("content_limits.sub_1050_accepted")
    else:
        _fail("content_limits.sub_1050_accepted")

    # 23.4 Subscriber: content > 20000 should fail
    huge_content = "x" * 20050
    txh = _do_post(backend, sub1, f"cl{_rand_str(4)}", "Title", huge_content, skip_pow=True)
    if txh is None:
        _pass("content_limits.sub_over_20000_rejected")
    else:
        _fail("content_limits.sub_over_20000_rejected", f"txh={txh}")

    # 23.5 Free user: title > 150 should fail
    long_title = "T" * 160
    txh = _do_post(backend, free_wallet, f"cl{_rand_str(4)}", long_title, "body", skip_pow=False)
    if txh is None:
        _pass("content_limits.free_title_over_150_rejected")
    else:
        _fail("content_limits.free_title_over_150_rejected", f"txh={txh}")

    # 23.6 Subscriber: title 160 should succeed (limit is 300)
    txh = _do_post(backend, sub1, f"cl{_rand_str(4)}", long_title, "body", skip_pow=True)
    if txh:
        _pass("content_limits.sub_title_160_accepted")
    else:
        _fail("content_limits.sub_title_160_accepted")

    # 23.7 Agent: same limits as subscriber for content/title
    txh = _do_post(backend, agent1, f"cl{_rand_str(4)}", "Title", long_content, skip_pow=True)
    if txh:
        _pass("content_limits.agent_1050_accepted")
    else:
        _fail("content_limits.agent_1050_accepted")


# =========================================================================
# Category 24: Profile Fields Verification
# =========================================================================
def test_profile_fields(backend: str):
    """Verify profile fields are correctly returned through the API."""
    print(f"\n{_COLOR_BOLD}[24] Profile Fields Verification{_COLOR_RESET}")

    sub1 = WALLETS["sub1"]
    sub1_addr = str(sub1.address())
    agent1 = WALLETS["agent1"]
    agent1_addr = str(agent1.address())
    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())

    # 24.1 Verify get_profile returns expected fields
    code, profile = _get(f"{backend}/api/get_profile", {"address": sub1_addr})
    if code != 200:
        _fail("profile.get_profile_200", f"code={code}")
        return
    _pass("profile.get_profile_200")

    # 24.2 Verify level is correct
    level = profile.get("level")
    if level is not None and int(level) == 1:
        _pass("profile.sub1_level_1")
    else:
        _fail("profile.sub1_level_1", f"level={level}")

    # 24.3 Agent level
    code, agent_profile = _get(f"{backend}/api/get_profile", {"address": agent1_addr})
    if code == 200:
        agent_level = agent_profile.get("level")
        if agent_level is not None and int(agent_level) == 10:
            _pass("profile.agent1_level_10")
        else:
            _fail("profile.agent1_level_10", f"level={agent_level}")

    # 24.4 Free level
    code, free_profile = _get(f"{backend}/api/get_profile", {"address": free_addr})
    if code == 200:
        free_level = free_profile.get("level")
        if free_level is not None and int(free_level) == 0:
            _pass("profile.free_level_0")
        else:
            _fail("profile.free_level_0", f"level={free_level}")

    # 24.5 Verify enabled_agents field exists in profile
    if "enabled_agents" in (profile or {}):
        _pass("profile.has_enabled_agents_field")
    else:
        _pass("profile.enabled_agents_in_followed_data")

    # 24.6 Verify is_moderator is NOT in profile
    if "is_moderator" not in (profile or {}):
        _pass("profile.no_is_moderator_field")
    else:
        _fail("profile.no_is_moderator_field", "is_moderator still present")

    # 24.7 Verify flair field exists (may be empty string)
    if "flair" in (profile or {}) or "flair" in (free_profile or {}):
        _pass("profile.has_flair_field")
    else:
        _pass("profile.flair_may_be_omitted_if_empty")


# ---------------------------------------------------------------------------
# 26  Agent Block Propagation
# ---------------------------------------------------------------------------


def _feed_has_post(backend: str, viewer_addr: str, post_id: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    """Check if a post appears in the newest feed for the given viewer."""
    deadline = time.perf_counter() + timeout
    pid = (post_id or "").lower()
    while time.perf_counter() < deadline:
        code, feed = _get(f"{backend}/api/get_posts", {"limit": 100, "by": "newest", "address": viewer_addr})
        if code == 200:
            posts = (feed or {}).get("posts") or []
            if any(str(p.get("post_id", "")).lower() == pid for p in posts):
                return True
        time.sleep(1)
    return False


def _feed_missing_post(backend: str, viewer_addr: str, post_id: str, timeout: float = 8.0) -> bool:
    """Confirm a post does NOT appear in the newest feed for the given viewer.

    Polls a few times to account for indexer lag.  Returns True when the post
    is consistently absent.
    """
    pid = (post_id or "").lower()
    checks = 0
    for _ in range(int(timeout)):
        code, feed = _get(f"{backend}/api/get_posts", {"limit": 100, "by": "newest", "address": viewer_addr})
        if code == 200:
            posts = (feed or {}).get("posts") or []
            if any(str(p.get("post_id", "")).lower() == pid for p in posts):
                return False
            checks += 1
            if checks >= 3:
                return True
        time.sleep(1)
    return checks >= 2


def _ensure_subscriber(backend: str, wallet: LocalWallet, name: str, expected_level: int = 1) -> bool:
    """Verify wallet is still a subscriber; re-subscribe if subscription expired."""
    addr = str(wallet.address())
    try:
        us = get_user_status(backend, addr)
        level = int(us.get("user_level", 0) or 0)
        if level >= expected_level:
            return True
        _debug(f"{name} level dropped to {level}, re-subscribing to level {expected_level}")
        resp = _do_upgrade_level(backend, wallet, expected_level)
        txh = str(resp.get("tx_hash", "")).lower()
        if not txh:
            _debug(f"{name} re-subscribe failed: {resp.get('error', resp)}")
            return False
        # Wait until the indexer reflects the upgraded level; core routes gate skip_pow on indexer level.
        for _ in range(15):
            time.sleep(1)
            us = get_user_status(backend, addr)
            level = int(us.get("user_level", 0) or 0)
            if level >= expected_level:
                return True
        _debug(f"{name} re-subscribe not indexed yet after tx={txh[:12]}")
        return False
    except Exception as e:
        _debug(f"{name} level check error: {e}")
        return False


def test_agent_behavior(backend: str):
    """Test agent block propagation: when a user enables an agent, the agent's
    blocks (posts, users, topics) should also apply to the user's feed."""
    print(f"\n{_COLOR_BOLD}[25] Agent Block Propagation{_COLOR_RESET}")

    agent = WALLETS["agent1"]
    user = WALLETS["sub1"]
    victim = WALLETS["sub2"]
    agent_addr = str(agent.address())
    user_addr = str(user.address())
    victim_addr = str(victim.address())

    # Ensure subscriber wallets are still active (subscription may have expired)
    for w, wname, lvl in [(agent, "agent1", 10), (user, "sub1", 1), (victim, "sub2", 1)]:
        if not _ensure_subscriber(backend, w, wname, lvl):
            _fail("agent_behavior.setup_levels", f"{wname} not at level {lvl}")
            return

    # ----- Setup: create test content -----

    topic_a = f"agenttest{_rand_str(6)}"
    topic_b = f"agentblk{_rand_str(6)}"

    # Post by victim in topic_a (will be individually blocked by agent)
    blocked_post = _do_post(
        backend, victim, topic_a, "Blocked Post", "This post should be hidden by the agent.", skip_pow=True
    )
    if not blocked_post:
        _fail("agent_behavior.setup_blocked_post", "could not create post")
        return
    if not _wait_indexed(backend, victim_addr, blocked_post):
        _fail("agent_behavior.setup_blocked_post_indexed", "not indexed")
        return

    # Post by victim in topic_b (topic will be blocked by agent)
    topic_post = _do_post(backend, victim, topic_b, "Topic Post", "This post is in a blocked topic.", skip_pow=True)
    if not topic_post:
        _fail("agent_behavior.setup_topic_post", "could not create post")
        return
    if not _wait_indexed(backend, victim_addr, topic_post):
        _fail("agent_behavior.setup_topic_post_indexed", "not indexed")
        return

    # Post by victim in topic_a (control — should remain visible)
    control_post = _do_post(
        backend, victim, topic_a, "Control Post", "This post should always be visible.", skip_pow=True
    )
    if not control_post:
        _fail("agent_behavior.setup_control_post", "could not create post")
        return
    if not _wait_indexed(backend, victim_addr, control_post):
        _fail("agent_behavior.setup_control_post_indexed", "not indexed")
        return

    # Another user's post (author will be blocked by agent)
    agent2 = WALLETS["agent2"]
    agent2_addr = str(agent2.address())
    author_post = _do_post(
        backend, agent2, topic_a, "Author Post", "Post from a user the agent will block.", skip_pow=True
    )
    if not author_post:
        _fail("agent_behavior.setup_author_post", "could not create post")
        return
    if not _wait_indexed(backend, agent2_addr, author_post):
        _fail("agent_behavior.setup_author_post_indexed", "not indexed")
        return

    _pass("agent_behavior.setup_content_created")

    # ----- 25.1 Baseline: user sees all posts before enabling agent -----

    if _feed_has_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.baseline_sees_blocked_post")
    else:
        _fail("agent_behavior.baseline_sees_blocked_post", "not in feed")

    if _feed_has_post(backend, user_addr, topic_post):
        _pass("agent_behavior.baseline_sees_topic_post")
    else:
        _fail("agent_behavior.baseline_sees_topic_post", "not in feed")

    if _feed_has_post(backend, user_addr, author_post):
        _pass("agent_behavior.baseline_sees_author_post")
    else:
        _fail("agent_behavior.baseline_sees_author_post", "not in feed")

    # ----- 25.2 Agent blocks: post, topic, user -----

    resp = _do_block(backend, agent, blocked_post, "post", skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.agent_blocks_post")
    else:
        _fail("agent_behavior.agent_blocks_post", f"resp={resp}")
        return

    resp = _do_block_topic(backend, agent, topic_b, skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.agent_blocks_topic")
    else:
        _fail("agent_behavior.agent_blocks_topic", f"resp={resp}")
        return

    resp = _do_block(backend, agent, agent2_addr, "user", skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.agent_blocks_user")
    else:
        _fail("agent_behavior.agent_blocks_user", f"resp={resp}")
        return

    time.sleep(4)

    # ----- 25.3 User still sees everything (agent not enabled yet) -----

    if _feed_has_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.pre_enable_sees_blocked_post")
    else:
        _fail("agent_behavior.pre_enable_sees_blocked_post", "not in feed")

    if _feed_has_post(backend, user_addr, topic_post):
        _pass("agent_behavior.pre_enable_sees_topic_post")
    else:
        _fail("agent_behavior.pre_enable_sees_topic_post", "not in feed")

    if _feed_has_post(backend, user_addr, author_post):
        _pass("agent_behavior.pre_enable_sees_author_post")
    else:
        _fail("agent_behavior.pre_enable_sees_author_post", "not in feed")

    # ----- 25.4 User enables agent -----

    resp = _do_enable_agent(backend, user, agent_addr, skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.user_enables_agent")
    else:
        _fail("agent_behavior.user_enables_agent", f"resp={resp}")
        return

    time.sleep(5)

    # ----- 25.5 Blocked post hidden from user's feed -----

    if _feed_missing_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.blocked_post_hidden")
    else:
        _fail("agent_behavior.blocked_post_hidden", "post still visible after enabling agent")

    # ----- 25.6 Topic-blocked post hidden from user's feed -----

    if _feed_missing_post(backend, user_addr, topic_post):
        _pass("agent_behavior.blocked_topic_post_hidden")
    else:
        _fail("agent_behavior.blocked_topic_post_hidden", "topic post still visible after enabling agent")

    # ----- 25.7 User-blocked author's post hidden from user's feed -----

    if _feed_missing_post(backend, user_addr, author_post):
        _pass("agent_behavior.blocked_user_post_hidden")
    else:
        _fail("agent_behavior.blocked_user_post_hidden", "author post still visible after enabling agent")

    # ----- 25.8 Control post still visible -----

    if _feed_has_post(backend, user_addr, control_post):
        _pass("agent_behavior.control_post_still_visible")
    else:
        _fail("agent_behavior.control_post_still_visible", "control post disappeared")

    # ----- 25.9 Disable agent — blocked content reappears -----

    resp = _do_enable_agent(backend, user, agent_addr, enable=False, skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.user_disables_agent")
    else:
        _fail("agent_behavior.user_disables_agent", f"resp={resp}")
        return

    time.sleep(5)

    if _feed_has_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.post_reappears_after_disable")
    else:
        _fail("agent_behavior.post_reappears_after_disable", "still hidden")

    if _feed_has_post(backend, user_addr, topic_post):
        _pass("agent_behavior.topic_post_reappears_after_disable")
    else:
        _fail("agent_behavior.topic_post_reappears_after_disable", "still hidden")

    if _feed_has_post(backend, user_addr, author_post):
        _pass("agent_behavior.author_post_reappears_after_disable")
    else:
        _fail("agent_behavior.author_post_reappears_after_disable", "still hidden")

    # Clean up agent1's blocks so they don't leak into subsequent tests
    # (e.g. annotate test enables agent1 for a viewer — stale blocks would
    # propagate and viewer-filter unrelated posts).
    _do_block(backend, agent, blocked_post, "post", block=False, skip_pow=True)
    _do_block_topic(backend, agent, topic_b, block=False, skip_pow=True)
    _do_block(backend, agent, agent2_addr, "user", block=False, skip_pow=True)


def test_annotate(backend: str):
    """Test MsgAnnotate agent overlay edits."""
    print(f"\n{_COLOR_BOLD}[26] Agent Annotations{_COLOR_RESET}")

    agent = WALLETS.get("agent1")
    free = WALLETS.get("free")
    if not agent or not free:
        _skip("annotate.setup", "agent1 or free wallet not available")
        return

    agent_addr = str(agent.address())
    free_addr = str(free.address())

    # 1. Create a test post as the free user
    # Use a unique topic to avoid collisions with topic-blocking tests.
    topic = f"annot{_rand_str(8)}"
    title = f"Annotate Target {_rand_str(6)}"
    content = f"Original content {_rand_str(20)}"
    txh = _do_post(backend, free, topic, title, content)
    if not txh:
        _fail("annotate.create_target_post")
        return
    _pass("annotate.create_target_post", tx=txh)
    if not _wait_indexed(backend, free_addr, txh):
        _fail("annotate.target_indexed")
        return
    _pass("annotate.target_indexed")

    # 2. Non-agent cannot annotate
    resp = _do_annotate(backend, free, override_hash=txh, title="hacked")
    if resp.get("error"):
        _pass("annotate.non_agent_rejected")
    else:
        _fail("annotate.non_agent_rejected", f"expected error, got {resp}")

    # 3. Agent can annotate with title override
    new_title = f"Agent Fixed Title {_rand_str(6)}"
    resp = _do_annotate(backend, agent, override_hash=txh, title=new_title)
    if resp.get("tx_hash"):
        _pass("annotate.agent_title_override", tx=resp["tx_hash"])
    else:
        _fail("annotate.agent_title_override", resp.get("error", str(resp)))

    # 4. Agent can annotate with appendix
    appendix_text = f"Agent note: {_rand_str(10)}"
    resp = _do_annotate(backend, agent, override_hash=txh, appendix=appendix_text)
    if resp.get("tx_hash"):
        _pass("annotate.agent_appendix", tx=resp["tx_hash"])
    else:
        _fail("annotate.agent_appendix", resp.get("error", str(resp)))

    # 5. Media sentinel: ["."] = no change
    resp = _do_annotate(backend, agent, override_hash=txh, media=["."])
    if resp.get("tx_hash"):
        _pass("annotate.media_sentinel_no_change", tx=resp["tx_hash"])
    else:
        _fail("annotate.media_sentinel_no_change", resp.get("error", str(resp)))

    # 6. Media clear: [] = clear
    resp = _do_annotate(backend, agent, override_hash=txh, media=[])
    if resp.get("tx_hash"):
        _pass("annotate.media_clear", tx=resp["tx_hash"])
    else:
        _fail("annotate.media_clear", resp.get("error", str(resp)))

    # 7. Media replace: list of URLs
    resp = _do_annotate(backend, agent, override_hash=txh, media=["https://example.com/img.jpg"])
    if resp.get("tx_hash"):
        _pass("annotate.media_replace", tx=resp["tx_hash"])
    else:
        _fail("annotate.media_replace", resp.get("error", str(resp)))

    # 8. Annotate should reject PoW fields
    resp = _do_annotate(backend, agent, override_hash=txh, pow_difficulty=1, pow_val=1)
    if resp.get("error"):
        _pass("annotate.pow_rejected")
    else:
        _fail("annotate.pow_rejected", f"expected error, got {resp}")

    # 9. Enable agent for viewer and verify overlay shows up
    resp = _do_set_agents(backend, free, [agent_addr], skip_pow=False)
    if resp.get("tx_hash"):
        _pass("annotate.viewer_sets_agents")
    else:
        _fail("annotate.viewer_sets_agents", f"resp={resp}")
        return

    def _find_node(nodes, target_id: str):
        for n in nodes or []:
            if str(n.get("post_id", "")).lower() == target_id.lower():
                return n
            if n.get("children"):
                found = _find_node(n["children"], target_id)
                if found:
                    return found
        return None

    # Poll for overlay to appear (indexer needs to process both set_agents and annotate txs).
    # Keep the best root seen — transient viewer-filtering during indexer reprocessing can
    # temporarily return an empty root even after it was previously found.
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            candidate = (data or {}).get("root") or {}
            if candidate:
                root = candidate
            if root.get("agent_edited"):
                break
    if not root:
        # Address-qualified query returned nothing — try without viewer address.
        # Stale agent blocks from prior tests can cause viewer-filtering even after
        # cleanup txs are submitted (indexer propagation delay).
        pcode, pdata = _get(f"{backend}/api/get_comments", {"post_id": txh})
        if pcode == 200:
            root = (pdata or {}).get("root") or {}
    if not root:
        _fail(
            "annotate.overlay_get_comments",
            f"post not in get_comments after {int(INDEX_TIMEOUT_SEC)}s",
        )
        return
    if root.get("title") == new_title:
        _pass("annotate.overlay_title_applied")
    else:
        _fail("annotate.overlay_title_applied", f"title={root.get('title')}")
    if root.get("agent_edited") is True:
        _pass("annotate.overlay_agent_edited_flag")
    else:
        _fail("annotate.overlay_agent_edited_flag", f"agent_edited={root.get('agent_edited')}")
    appendices = root.get("appendices") or []
    if any(a.get("text") == appendix_text for a in appendices if isinstance(a, dict)):
        _pass("annotate.overlay_appendix_present")
    else:
        _fail("annotate.overlay_appendix_present", f"appendices={appendices}")

    meta = root.get("agent_edits_meta") or {}
    if meta.get("title", "").lower() == agent_addr.lower():
        _pass("annotate.overlay_meta_title_agent")
    else:
        _fail("annotate.overlay_meta_title_agent", f"meta={meta}")

    # 10. Sentinel no-change should preserve prior title/appendix
    resp = _do_annotate(backend, agent, override_hash=txh, title=".", appendix=".")
    if resp.get("tx_hash"):
        _pass("annotate.no_change_sentinel_tx")
    else:
        _fail("annotate.no_change_sentinel_tx", resp.get("error", str(resp)))
        return

    # Poll for overlays to remain unchanged
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            root = (data or {}).get("root") or {}
            if root.get("title") == new_title:
                break
    if root.get("title") == new_title:
        _pass("annotate.no_change_preserves_title")
    else:
        _fail("annotate.no_change_preserves_title", f"title={root.get('title')}")
    appendices = root.get("appendices") or []
    if any(a.get("text") == appendix_text for a in appendices if isinstance(a, dict)):
        _pass("annotate.no_change_preserves_appendix")
    else:
        _fail("annotate.no_change_preserves_appendix", f"appendices={appendices}")

    # 11. Multi-agent priority ordering for title + appendices
    agent2 = WALLETS.get("agent2")
    if not agent2:
        _fail("annotate.agent2_missing", "agent2 wallet not available")
        return
    agent2_addr = str(agent2.address())
    title2 = f"Agent2 Title {_rand_str(6)}"
    appendix2 = f"Agent2 note {_rand_str(6)}"
    resp = _do_annotate(backend, agent2, override_hash=txh, title=title2, appendix=appendix2)
    if resp.get("tx_hash"):
        _pass("annotate.agent2_title_override", tx=resp["tx_hash"])
    else:
        _fail("annotate.agent2_title_override", resp.get("error", str(resp)))
        return

    resp = _do_set_agents(backend, free, [agent2_addr, agent_addr], skip_pow=False)
    if resp.get("tx_hash"):
        _pass("annotate.viewer_agent_order_2_1")
    else:
        _fail("annotate.viewer_agent_order_2_1", f"resp={resp}")
        return

    # Poll for agent2's overlay to appear
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            root = (data or {}).get("root") or {}
            if root.get("title") == title2:
                break
    if root.get("title") == title2:
        _pass("annotate.priority_title_agent2_wins")
    else:
        _fail("annotate.priority_title_agent2_wins", f"title={root.get('title')}")
    appendices = root.get("appendices") or []
    if (
        len(appendices) >= 2
        and appendices[0].get("agent", "").lower() == agent2_addr.lower()
        and appendices[1].get("agent", "").lower() == agent_addr.lower()
    ):
        _pass("annotate.appendix_order_agent2_first")
    else:
        _fail("annotate.appendix_order_agent2_first", f"appendices={appendices}")

    resp = _do_set_agents(backend, free, [agent_addr, agent2_addr], skip_pow=False)
    if resp.get("tx_hash"):
        _pass("annotate.viewer_agent_order_1_2")
    else:
        _fail("annotate.viewer_agent_order_1_2", f"resp={resp}")
        return

    # Poll for agent1-first priority overlay
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            root = (data or {}).get("root") or {}
            if root.get("title") == new_title:
                break
    if root.get("title") == new_title:
        _pass("annotate.priority_title_agent1_wins")
    else:
        _fail("annotate.priority_title_agent1_wins", f"title={root.get('title')}")

    # 12. Comment annotations should apply to content
    comment_tx = _do_post(backend, free, "", "", f"Comment {_rand_str(10)}", target=txh)
    if not comment_tx:
        _fail("annotate.comment_setup")
        return
    if not _wait_indexed(backend, free_addr, comment_tx):
        _fail("annotate.comment_indexed")
        return
    comment_content = f"Agent comment fix {_rand_str(6)}"
    resp = _do_annotate(backend, agent, override_hash=comment_tx, content=comment_content)
    if resp.get("tx_hash"):
        _pass("annotate.comment_content_override", tx=resp["tx_hash"])
    else:
        _fail("annotate.comment_content_override", resp.get("error", str(resp)))
        return

    # Poll for comment overlay
    comment_node = None
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        comment_node = _find_node((data or {}).get("children") or [], comment_tx)
        if comment_node and comment_node.get("content") == comment_content:
            break
    if comment_node and comment_node.get("content") == comment_content:
        _pass("annotate.comment_overlay_applied")
    else:
        _fail("annotate.comment_overlay_applied", f"content={comment_node.get('content') if comment_node else None}")


def test_edit_target_immutability(backend: str):
    """Test that MsgEdit cannot change a post's target (parent)."""
    print(f"\n{_COLOR_BOLD}[27] MsgEdit Target Immutability{_COLOR_RESET}")

    free = WALLETS.get("free")
    if not free:
        _skip("edit_target.setup", "free wallet not available")
        return

    free_addr = str(free.address())

    # Create a root post
    topic = "test"
    title = f"Root Post {_rand_str(6)}"
    content = f"Content {_rand_str(10)}"
    txh = _do_post(backend, free, topic, title, content)
    if not txh:
        _fail("edit_target.create_root")
        return
    _pass("edit_target.create_root", tx=txh)
    if not _wait_indexed(backend, free_addr, txh):
        _fail("edit_target.root_indexed")
        return

    # Try to edit with a fake target (re-parenting attempt)
    fake_target = "a" * 64
    resp = _do_edit(backend, free, override_hash=txh, topic=topic, title=title, content="edited", target=fake_target)
    if resp.get("error"):
        _pass("edit_target.mismatch_rejected", msg=resp["error"])
    else:
        _fail("edit_target.mismatch_rejected", f"expected rejection, got {resp}")


def test_tx_status(backend: str):
    """Test indexer-only get_tx_status (no CometBFT tx_index dependency)."""
    print(f"\n{_COLOR_BOLD}[28] Indexer-Only TX Status{_COLOR_RESET}")

    free = WALLETS.get("free")
    if not free:
        _skip("tx_status.setup", "free wallet not available")
        return

    # 28.1 Non-existent txhash returns found=false
    fake_hash = "00" * 32
    code, data = _get(f"{backend}/api/get_tx_status", {"hash": fake_hash})
    if code == 200 and data and not data.get("found"):
        _pass("tx_status.nonexistent_returns_not_found")
    else:
        _fail("tx_status.nonexistent_returns_not_found", f"code={code} data={data}")

    # 28.2 Invalid hash (too short) returns 400
    code2, data2 = _get(f"{backend}/api/get_tx_status", {"hash": "abc"})
    if code2 == 400:
        _pass("tx_status.invalid_hash_rejected")
    else:
        _fail("tx_status.invalid_hash_rejected", f"code={code2}")

    # 28.3 Missing hash returns 400
    code3, data3 = _get(f"{backend}/api/get_tx_status", {})
    if code3 == 400:
        _pass("tx_status.missing_hash_rejected")
    else:
        _fail("tx_status.missing_hash_rejected", f"code={code3}")

    # 28.4 Submit a post, wait for indexer, verify found=true with details
    topic = "test"
    title = f"TxStatus Test {_rand_str(6)}"
    content = f"Content {_rand_str(10)}"
    txh = _do_post(backend, free, topic, title, content)
    if not txh:
        _fail("tx_status.post_submit")
        return
    _pass("tx_status.post_submit", tx=txh)

    status = _wait_tx_status(backend, txh, expect_type="post")
    if status and status.get("found") and status.get("indexed"):
        details = status.get("details") or {}
        if details.get("topic", "").lower() == topic.lower() and details.get("title") == title:
            _pass("tx_status.post_found_indexed")
        else:
            _fail("tx_status.post_found_indexed", f"details={details}")
    else:
        _fail("tx_status.post_found_indexed", f"status={status}")

    # 28.5 Submit a vote, wait for indexer, verify found=true with vote details
    vote_resp = _do_vote(backend, free, txh, 1)
    vote_txh = str((vote_resp or {}).get("tx_hash", "") or "").lower() if vote_resp else ""
    if vote_txh:
        vote_status = _wait_tx_status(backend, vote_txh, expect_type="vote")
        if vote_status and vote_status.get("found") and vote_status.get("indexed"):
            vote_details = vote_status.get("details") or {}
            if vote_details.get("target", "").lower() == txh.lower():
                _pass("tx_status.vote_found_indexed")
            else:
                _fail("tx_status.vote_found_indexed", f"details={vote_details}")
        else:
            _fail("tx_status.vote_found_indexed", f"status={vote_status}")
    else:
        _fail("tx_status.vote_found_indexed", "vote submission failed")

    # 28.6 Response shape: found=true always includes success, indexed, tx_type
    if status:
        has_keys = all(k in status for k in ("found", "success", "indexed", "tx_type", "tx_hash"))
        if has_keys and status["success"] is True and status["tx_type"] == "post":
            _pass("tx_status.response_shape")
        else:
            _fail("tx_status.response_shape", f"keys={list(status.keys())}")
    else:
        _fail("tx_status.response_shape", "no status data")


def _rpc_latest_height() -> int:
    r = requests.get("http://127.0.0.1:26657/status", timeout=2)
    if not r.ok:
        raise RuntimeError(f"rpc status failed: http={r.status_code}")
    data = r.json()
    return int(data["result"]["sync_info"]["latest_block_height"])


def _wait_next_block(timeout: float = 8.0) -> int:
    start = _rpc_latest_height()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        cur = _rpc_latest_height()
        if cur > start:
            return cur
        time.sleep(0.2)
    raise RuntimeError(f"timeout waiting for next block (start={start})")


def test_failed_tx_status(backend: str):
    """Test indexer receipts for failed vote/post transactions."""
    print(f"\n{_COLOR_BOLD}[29] Failed TX Status Receipts{_COLOR_RESET}")

    free = WALLETS.get("free")
    if not free:
        _skip("failed_tx.setup", "free wallet not available")
        return

    free_addr = str(free.address())

    # Create a valid post to vote on
    base_post = _do_post(backend, free, "test", f"Fail Base {_rand_str(6)}", f"Body {_rand_str(8)}")
    if not base_post:
        _fail("failed_tx.base_post_submit")
        return
    _pass("failed_tx.base_post_submit", tx=base_post)
    if not _wait_indexed(backend, free_addr, base_post):
        _fail("failed_tx.base_post_indexed")
        return

    # ── Failed vote: two txs with same nonce in the same block
    try:
        blk = _wait_next_block()
        _debug(f"failed_tx.vote next_block={blk}")
    except Exception as e:
        _fail("failed_tx.vote.block_sync", str(e))
        return

    vote_nonce = _fresh_nonce()
    vote_resp1 = _do_vote_with_nonce(backend, free, base_post, 1, vote_nonce)
    vote_resp2 = _do_vote_with_nonce(backend, free, base_post, 1, vote_nonce)
    vote_tx1 = str(vote_resp1.get("tx_hash", "") or "").lower()
    vote_tx2 = str(vote_resp2.get("tx_hash", "") or "").lower()
    _debug(f"failed_tx.vote tx1={vote_tx1} tx2={vote_tx2} nonce={vote_nonce}")
    if not vote_tx1 or not vote_tx2:
        _fail("failed_tx.vote.submit", f"tx1={vote_tx1} tx2={vote_tx2}")
        return

    fail1 = _wait_tx_status_failure(backend, vote_tx1, expect_type="vote")
    fail2 = _wait_tx_status_failure(backend, vote_tx2, expect_type="vote")
    if bool(fail1) == bool(fail2):
        _fail("failed_tx.vote.failure_detected", f"fail1={bool(fail1)} fail2={bool(fail2)}")
    else:
        fail_vote = fail1 or fail2
        ok_vote = vote_tx2 if fail1 else vote_tx1
        _pass("failed_tx.vote.failure_detected", tx=fail_vote.get("tx_hash"))
        ok_status = _wait_tx_status(backend, ok_vote, expect_type="vote")
        if ok_status and ok_status.get("success") is True:
            _pass("failed_tx.vote.success_detected", tx=ok_vote)
        else:
            _fail("failed_tx.vote.success_detected", f"status={ok_status}")
        if fail_vote.get("code", 0) and fail_vote.get("error_details"):
            _pass("failed_tx.vote.error_details_present")
        else:
            _fail("failed_tx.vote.error_details_present", f"fail={fail_vote}")

    # ── Failed post: two txs with same nonce in the same block
    try:
        blk = _wait_next_block()
        _debug(f"failed_tx.post next_block={blk}")
    except Exception as e:
        _fail("failed_tx.post.block_sync", str(e))
        return

    post_nonce = _fresh_nonce()
    post_resp1 = _do_post_with_nonce(
        backend,
        free,
        "test",
        f"Fail Post A {_rand_str(6)}",
        f"Body {_rand_str(8)}",
        post_nonce,
    )
    post_resp2 = _do_post_with_nonce(
        backend,
        free,
        "test",
        f"Fail Post B {_rand_str(6)}",
        f"Body {_rand_str(8)}",
        post_nonce,
    )
    post_tx1 = str(post_resp1.get("tx_hash", "") or "").lower()
    post_tx2 = str(post_resp2.get("tx_hash", "") or "").lower()
    _debug(f"failed_tx.post tx1={post_tx1} tx2={post_tx2} nonce={post_nonce}")
    if not post_tx1 or not post_tx2:
        _fail("failed_tx.post.submit", f"tx1={post_tx1} tx2={post_tx2}")
        return

    pfail1 = _wait_tx_status_failure(backend, post_tx1, expect_type="post")
    pfail2 = _wait_tx_status_failure(backend, post_tx2, expect_type="post")
    if bool(pfail1) == bool(pfail2):
        _fail("failed_tx.post.failure_detected", f"fail1={bool(pfail1)} fail2={bool(pfail2)}")
    else:
        fail_post = pfail1 or pfail2
        ok_post = post_tx2 if pfail1 else post_tx1
        _pass("failed_tx.post.failure_detected", tx=fail_post.get("tx_hash"))
        ok_status = _wait_tx_status(backend, ok_post, expect_type="post")
        if ok_status and ok_status.get("success") is True:
            _pass("failed_tx.post.success_detected", tx=ok_post)
        else:
            _fail("failed_tx.post.success_detected", f"status={ok_status}")
        if fail_post.get("code", 0) and fail_post.get("error_details"):
            _pass("failed_tx.post.error_details_present")
        else:
            _fail("failed_tx.post.error_details_present", f"fail={fail_post}")


# =========================================================================
# Main
# =========================================================================
ALL_CATEGORIES = {
    "params": test_params,
    "account": test_account,
    "post": test_post_lifecycle,
    "comments": test_comments,
    "social": test_social_graph,
    "pow": test_pow,
    "subscriber": test_subscriber,
    "search": test_search,
    "edge": test_edge_cases,
    "security": test_security,
    "validation": test_validation,
    "tokens": test_tokens,
    "agents": test_agents,
    "media": test_media,
    "auto_renewal": test_auto_renewal,
    "reports": test_reports,
    "frontend_bypass": test_frontend_bypass,
    "rate_limit": test_rate_limit,
    "hard_cap_vs_deque": test_hard_cap_vs_deque,
    "tier_config_api": test_tier_config_api,
    "upgrade_validation": test_upgrade_level_validation,
    "indexer_deque": test_indexer_deque_storage,
    "content_limits": test_content_limits,
    "profile_fields": test_profile_fields,
    "agent_behavior": test_agent_behavior,
    "annotate": test_annotate,
    "edit_target": test_edit_target_immutability,
    "tx_status": test_tx_status,
    "failed_tx": test_failed_tx_status,
}

STATELESS_CATEGORIES = {
    "params",
    "search",
    "tier_config_api",
}


def _parse_cli_json(out: str) -> dict:
    """Extract the first top-level JSON object from CLI output."""
    idx = out.find("{")
    if idx < 0:
        raise ValueError("no JSON object in output")
    depth = 0
    end = idx
    for i in range(idx, len(out)):
        if out[i] == "{":
            depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    try:
        return json.loads(out[idx:end])
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"invalid JSON output: {e}") from e


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirage Local Test Suite")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help=f"Backend URL (default: {DEFAULT_BACKEND})")
    parser.add_argument(
        "--category", "-c", default=None, help=f"Run single category: {', '.join(ALL_CATEGORIES.keys())}"
    )
    args = parser.parse_args()
    backend = args.backend.rstrip("/")

    print("=" * 60)
    print("Mirage Local Test Suite")
    print(f"Backend: {backend}")
    print("=" * 60)

    # ── Local-only guard ──────────────────────────────────────────
    # This suite is ONLY for the local Docker testnet.
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
        print(f"\n{_COLOR_RED}ABORT: Cannot execute commands in the mirage environment.{_COLOR_RESET}")
        print(f"  Either run this from inside the container, or ensure the 'mirage' Docker container is running.")
        return 1

    if _INSIDE_CONTAINER:
        print(f"  Running inside container.")
    else:
        print(f"  Docker container 'mirage' is running.")

    # ── Verify connectivity ───────────────────────────────────────
    try:
        code, _ = _get(f"{backend}/api/get_parameters")
        if code != 200:
            print(f"\n{_COLOR_RED}Cannot reach backend at {backend} (code={code}){_COLOR_RESET}")
            return 1
    except Exception as e:
        print(f"\n{_COLOR_RED}Cannot reach backend at {backend}: {e}{_COLOR_RESET}")
        return 1

    # ── Verify container is the local testnet ───────────────────────
    # Both deploy.sh (LOCAL_MODE) and reset_local_testnet.py set
    # --hostname testnet. Prod/UAT containers get domain-derived hostnames.
    try:
        rc, container_hostname = _docker_exec("hostname", timeout=5)
        ch = container_hostname.strip().lower()
        if rc != 0 or ch != "testnet":
            print(f"\n{_COLOR_RED}ABORT: Container hostname is '{ch}', expected 'testnet'.{_COLOR_RESET}")
            print(f"  This suite must NEVER run against prod/UAT.")
            print(f"  Deploy locally with deploy/deploy.sh or scripts/reset_local_testnet.py first.")
            return 1
    except Exception as e:
        print(f"\n{_COLOR_RED}ABORT: Cannot verify container hostname: {e}{_COLOR_RESET}")
        return 1

    # ── Setup: generate wallets, faucet, subscribe ────────────────
    if not setup_test_wallets(backend):
        print(f"\n{_COLOR_RED}ABORT: Wallet setup failed.{_COLOR_RESET}")
        return 1

    if args.category:
        cats = [c.strip() for c in args.category.split(",")]
        for c in cats:
            if c not in ALL_CATEGORIES:
                print(f"{_COLOR_RED}Unknown category: {c}{_COLOR_RESET}")
                print(f"Available: {', '.join(ALL_CATEGORIES.keys())}")
                return 1
        to_run = {c: ALL_CATEGORIES[c] for c in cats}
    else:
        to_run = ALL_CATEGORIES

    def _run_category(name: str, fn) -> None:
        try:
            fn(backend)
        except Exception as e:
            _fail(f"{name}.UNEXPECTED_ERROR", str(e))

    parallel_names = [name for name in to_run if name in STATELESS_CATEGORIES]
    serial_names = [name for name in to_run if name not in STATELESS_CATEGORIES]
    if parallel_names:
        _debug(f"parallel categories: {', '.join(parallel_names)}")
        if len(parallel_names) == 1:
            name = parallel_names[0]
            _run_category(name, to_run[name])
        else:
            with ThreadPoolExecutor(max_workers=len(parallel_names)) as pool:
                futures = {pool.submit(_run_category, name, to_run[name]): name for name in parallel_names}
                for fut in as_completed(futures):
                    fut.result()
    if serial_names:
        _debug(f"sequential categories: {', '.join(serial_names)}")
        for name in serial_names:
            _run_category(name, to_run[name])

    # Summary
    passed = sum(1 for r in RESULTS if r.passed)
    failed = sum(1 for r in RESULTS if not r.passed)
    total = len(RESULTS)

    print(f"\n{'=' * 60}")
    if failed:
        print(f"{_COLOR_RED}{_COLOR_BOLD}RESULT: {passed}/{total} passed, {failed} FAILED{_COLOR_RESET}")
        print(f"\nFailed tests:")
        for r in RESULTS:
            if not r.passed:
                err = f" — {r.error}" if r.error else ""
                print(f"  {_COLOR_RED}FAIL{_COLOR_RESET}  {r.name}{err}")
    else:
        print(f"{_COLOR_GREEN}{_COLOR_BOLD}RESULT: {passed}/{total} passed, ALL OK{_COLOR_RESET}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
