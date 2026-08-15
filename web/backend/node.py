from __future__ import annotations

"""Node and runtime helpers.

Functions:
- initialize_runtime(): Resolve URLs and local keys at startup.
- require_runtime(): Return initialized runtime or raise.
- assert_node_home_ready(): Validate node directories/files.
- get_rpc_url/get_grpc_url/get_grpc_target(): URL helpers.
- min_gas_price_umirage(): Minimum gas price for umirage.
- startup_grace_seconds(): Budget for chain-dependent startup queries.
- resolve_validator_payer_address(): Fee payer address.
- resolve_validator_pubkey_bytes(): Validator pubkey bytes.
- find_local_operator_address(): miragevaloper address.
- find_local_consensus_address(): miragevalcons address.
- derive_address_from_pubkey(pubkey, hrp): Account bech32 address.
"""

import base64
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional, Tuple
import tomllib as _toml

from bech32 import bech32_encode, bech32_decode, convertbits  # type: ignore

from shared.config import get_config

from paths import project_root

KEYRING_BACKEND = get_config().get_keyring_backend()

_log = logging.getLogger("node")

# Startup retry pacing for chain-dependent queries.
_STARTUP_LOG_INTERVAL_SEC = 30.0
_STARTUP_MAX_BACKOFF_SEC = 30.0

REWARDS_POOL_KEY_NAME = "rewards_pool"


@dataclass
class Runtime:
    rpc_url: str
    api_url: str
    grpc_url: str
    grpc_target: str
    validator_payer_addr: str
    validator_pubkey_bytes: bytes
    validator_privkey_bytes: bytes
    validator_account_number: int
    chain_id: str
    validator_operator_address: str
    validator_consensus_address: str
    min_gas_price_umirage: float
    # Rewards-pool signer, loaded only when QUESTS_PAYOUTS_ENABLED is true.
    rewards_pool_addr: Optional[str] = None
    rewards_pool_pubkey_bytes: Optional[bytes] = None
    rewards_pool_privkey_bytes: Optional[bytes] = None
    rewards_pool_account_number: Optional[int] = None


_RUNTIME: Optional[Runtime] = None


def assert_node_home_ready() -> None:
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    if not os.path.isdir(home):
        raise RuntimeError(f"node home not found: {home}")
    must_files = [
        os.path.join(home, "config", "app.toml"),
        os.path.join(home, "config", "config.toml"),
    ]
    for p in must_files:
        if not os.path.isfile(p):
            raise RuntimeError(f"missing required file: {p}")
    keyring_dir = os.path.join(home, f"keyring-{KEYRING_BACKEND}")
    if not os.path.isdir(keyring_dir):
        raise RuntimeError(f"missing keyring: {keyring_dir}")


def get_rpc_url() -> str:
    cfg = get_config()
    return cfg.get_node_config()["urls"]["rpc"].rstrip("/")


def get_api_url() -> str:
    cfg = get_config()
    return cfg.get_node_config()["urls"]["rest"].rstrip("/")


def get_grpc_url() -> str:
    if _RUNTIME is not None:
        return _RUNTIME.grpc_url
    cfg = get_config()
    derived = str(cfg.get_node_config()["urls"]["grpc"]).strip()
    if not derived:
        raise RuntimeError("derived grpc url missing from config")
    home = cfg.get_node_config()["home"]
    path = os.path.join(home, "config", "app.toml")
    with open(path, "rb") as f:
        data = _toml.load(f)
    app_addr = str(((data.get("grpc") or {}).get("address") or "")).strip()
    if not app_addr:
        raise RuntimeError("grpc.address missing in app.toml")

    def _parse_host_port(s: str) -> Tuple[str, int]:
        parts = s.rsplit(":", 1)
        if len(parts) != 2:
            raise RuntimeError(f"invalid grpc address: {s}")
        h, p = parts[0].strip(), int(parts[1])
        if h == "localhost":
            h = "127.0.0.1"
        return h, p

    d_host, d_port = _parse_host_port(derived)
    a_host, a_port = _parse_host_port(app_addr)
    if a_port != d_port:
        raise RuntimeError(f"grpc.address port mismatch: app.toml={app_addr} expected_port={d_port}")
    url = f"{d_host}:{d_port}"
    if not url.startswith("grpc+http://"):
        url = f"grpc+http://{url}"
    return url


def get_grpc_target() -> str:
    if _RUNTIME is not None:
        return _RUNTIME.grpc_target
    url = get_grpc_url()
    if url.startswith("grpc+http://"):
        url = url[len("grpc+http://") :]
    if url.startswith("http://"):
        url = url[len("http://") :]
    if url.startswith("https://"):
        url = url[len("https://") :]
    return url


def min_gas_price_umirage() -> float:
    rt = require_runtime()
    return float(rt.min_gas_price_umirage)


def _get_node_consensus_pubkey_bytes() -> bytes:
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    path = os.path.join(home, "config", "priv_validator_key.json")
    with open(path, "r") as f:
        data = json.load(f)
    b64 = str(data.get("pub_key", {}).get("value", ""))
    if not b64:
        raise RuntimeError("missing consensus pubkey in priv_validator_key.json")
    return base64.b64decode(b64)


_CACHED_OPERATOR_ADDRESS: Optional[str] = None
_CACHED_CONSENSUS_ADDRESS: Optional[str] = None


def find_local_operator_address() -> str:
    """Return cached validator operator address (loaded at startup)."""
    rt = require_runtime()
    return rt.validator_operator_address


def find_local_consensus_address() -> str:
    """Return cached validator consensus address (loaded at startup)."""
    rt = require_runtime()
    return rt.validator_consensus_address


def _derive_valoper_from_account(addr: str) -> str:
    hrp, data5 = bech32_decode(addr)
    if not hrp or not data5:
        raise RuntimeError("invalid bech32 account address for validator key")
    data8 = convertbits(data5, 5, 8, False)
    if not data8:
        raise RuntimeError("bech32 convertbits 5->8 failed")
    data5_new = convertbits(bytes(data8), 8, 5)
    if not data5_new:
        raise RuntimeError("bech32 convertbits 8->5 failed")
    return bech32_encode("miragevaloper", data5_new)


def _derive_valcons_from_pubkey(cons_pub: bytes) -> str:
    import hashlib as _hl

    if not cons_pub:
        raise RuntimeError("missing consensus pubkey bytes")
    h20 = _hl.sha256(cons_pub).digest()[:20]
    data5 = convertbits(h20, 8, 5)
    if not data5:
        raise RuntimeError("bech32 convertbits 8->5 failed for valcons")
    return bech32_encode("miragevalcons", data5)


def _load_min_gas_price_umirage() -> float:
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    path = os.path.join(home, "config", "app.toml")
    with open(path, "rb") as f:
        data = _toml.load(f)
    raw = str(((data.get("minimum-gas-prices") or data.get("minimum_gas_prices")))).strip()
    if not raw:
        raise RuntimeError("minimum-gas-prices missing in app.toml")
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise RuntimeError("minimum-gas-prices empty")
    for p in parts:
        if p.endswith("umirage"):
            try:
                return float(p[:-7])
            except Exception:
                raise RuntimeError(f"invalid minimum-gas-prices entry: {p}")
    raise RuntimeError("minimum-gas-prices must include umirage entry")


def resolve_validator_payer_address() -> str:
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    bin_path = os.path.abspath(os.path.join(project_root(), "blockchain", "bin", "miraged"))
    cmd = [bin_path, "keys", "list", "--output", "json", "--home", home, "--keyring-backend", KEYRING_BACKEND]
    out = subprocess.check_output(cmd, timeout=5).decode("utf-8").strip()
    data = json.loads(out)
    for entry in data or []:
        if str(entry.get("name", "")) == "validator":
            addr = str(entry.get("address", "")).strip()
            if addr and re.fullmatch(r"mirage1[0-9a-z]{38}", addr):
                return addr
            raise RuntimeError("validator key found but address invalid")
    raise RuntimeError("validator key not found in keyring")


def resolve_validator_pubkey_bytes() -> bytes:
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    bin_path = os.path.abspath(os.path.join(project_root(), "blockchain", "bin", "miraged"))
    cmd = [
        bin_path,
        "keys",
        "show",
        "validator",
        "--output",
        "json",
        "--home",
        home,
        "--keyring-backend",
        KEYRING_BACKEND,
    ]
    out = subprocess.check_output(cmd, timeout=5).decode("utf-8").strip()
    try:
        data = json.loads(out)
    except Exception:
        raise RuntimeError(f"validator keys show output not JSON: {out[:200]}")
    pk_field = (data or {}).get("pubkey")
    if not pk_field:
        raise RuntimeError("validator pubkey missing in keys show output")
    if isinstance(pk_field, str):
        try:
            pk_obj = json.loads(pk_field)
        except Exception:
            raise RuntimeError(f"invalid pubkey field format: {pk_field[:200]}")
    elif isinstance(pk_field, dict):
        pk_obj = pk_field
    else:
        raise RuntimeError("unexpected pubkey field type")
    key_b64 = (pk_obj or {}).get("key")
    if not key_b64:
        raise RuntimeError("validator pubkey missing in keys show output")
    pk = base64.b64decode(key_b64)
    if len(pk) != 33:
        raise RuntimeError("validator pubkey must be 33 bytes (compressed secp256k1)")
    return pk


def derive_address_from_pubkey(pubkey_bytes: bytes, hrp: str = "mirage") -> str:
    import hashlib as _hl

    if not pubkey_bytes or len(pubkey_bytes) != 33:
        return ""
    sha = _hl.sha256(pubkey_bytes).digest()
    ripemd = _hl.new("ripemd160")
    ripemd.update(sha)
    digest20 = ripemd.digest()
    data5 = convertbits(digest20, 8, 5)
    if not data5:
        return ""
    return bech32_encode(hrp, data5)


def resolve_validator_privkey_bytes() -> bytes:
    """Export the validator account private key once at startup (test keyring).

    C-1: the backend must sign the outer Cosmos tx so the gas payer proves consent.
    Keyring backend is `test` (plaintext on disk); this loads it into process memory.
    """
    return _export_privkey_bytes("validator")


def _export_privkey_bytes(key_name: str) -> bytes:
    if not re.fullmatch(r"[a-z0-9_]{1,32}", key_name):
        raise RuntimeError(f"invalid keyring key name: {key_name!r}")
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    bin_path = os.path.abspath(os.path.join(project_root(), "blockchain", "bin", "miraged"))
    cmd = [
        bin_path,
        "keys",
        "export",
        key_name,
        "--unarmored-hex",
        "--unsafe",
        "-y",
        "--output",
        "text",
        "--home",
        home,
        "--keyring-backend",
        KEYRING_BACKEND,
    ]
    out = subprocess.check_output(cmd, timeout=10, stderr=subprocess.STDOUT).decode("utf-8").strip()
    # CLI may print log lines before the hex key; take the last 64-hex token.
    hex_key = ""
    for line in reversed(out.splitlines()):
        token = line.strip()
        if re.fullmatch(r"[0-9a-fA-F]{64}", token):
            hex_key = token
            break
    if not hex_key:
        # Deliberately does not echo `out`. The only reason no token matched is
        # that the key was printed in a shape this loop did not recognise — for
        # example with a same-line prefix — so the output being described is
        # exactly the output most likely to contain the private key, and startup
        # runs at import under gunicorn, which would land it in the startup log.
        raise RuntimeError(f"{key_name} privkey export: no 64-hex key in {len(out.splitlines())} line(s) of CLI output")
    pk = bytes.fromhex(hex_key)
    if len(pk) != 32:
        raise RuntimeError(f"{key_name} privkey must be 32 bytes, got {len(pk)}")
    return pk


def resolve_rewards_pool_signer(api_url: str, key_name: str, expected_address: str) -> Tuple[bytes, bytes, str, int]:
    """Load the rewards-pool signer once at startup.

    Returns (privkey_bytes, pubkey_bytes, address, account_number). The derived
    address must equal the configured pool address — a mismatch means payouts
    would be signed by the wrong account, so it is a hard startup failure.
    """
    from cosmpy.crypto.keypairs import PrivateKey as _Priv

    privkey = _export_privkey_bytes(key_name)
    pubkey = _Priv(privkey).public_key.public_key_bytes
    address = derive_address_from_pubkey(pubkey)
    if not address:
        raise RuntimeError(f"rewards pool key {key_name} produced no address")
    if address != str(expected_address or "").strip().lower():
        raise RuntimeError(
            f"rewards pool key {key_name} address {address} does not match "
            f"QUESTS_REWARDS_POOL_ADDRESS {expected_address}"
        )
    account_number = resolve_account_number(api_url, address)
    return privkey, pubkey, address, account_number


def resolve_chain_id() -> str:
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    path = os.path.join(home, "config", "client.toml")
    with open(path, "rb") as f:
        data = _toml.load(f)
    chain_id = str(data.get("chain-id") or data.get("chain_id") or "").strip()
    if not chain_id:
        raise RuntimeError("chain-id missing in client.toml")
    return chain_id


def startup_grace_seconds() -> float:
    """How long chain-dependent startup work may wait for the node to serve queries.

    Sized for a coordinated chain upgrade, not for a process restart: past the
    halt height the REST API stays up but answers height-dependent queries with
    sdk code 26 until 2/3+ of voting power is back on the new binary, which takes
    as long as the fleet rollout takes.
    """
    raw = os.environ.get("CHAIN_STARTUP_GRACE_SECONDS", "1800").strip()
    try:
        value = float(raw)
    except ValueError as e:
        raise RuntimeError(f"CHAIN_STARTUP_GRACE_SECONDS is not a number: {raw!r}") from e
    if value <= 0:
        raise RuntimeError(f"CHAIN_STARTUP_GRACE_SECONDS must be > 0, got {value}")
    return value


def resolve_account_number(api_url: str, address: str, wait_budget_sec: Optional[float] = None) -> int:
    """Fetch account_number once at startup (stable for the life of the account).

    The entrypoint only waits for the node's RPC port before starting gunicorn, so
    the REST API may not be bound yet, and during an upgrade halt it answers but
    cannot serve a height. Retry within the startup grace budget, then fail.
    """
    import requests

    if wait_budget_sec is None:
        wait_budget_sec = startup_grace_seconds()

    url = f"{api_url.rstrip('/')}/cosmos/auth/v1beta1/accounts/{address}"
    started = time.monotonic()
    deadline = started + wait_budget_sec
    last_err = ""
    attempts = 0
    delay = 2.0
    last_log = 0.0
    while True:
        attempts += 1
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                break
            last_err = f"http {resp.status_code}: {resp.text[:300]}"
        except Exception as e:
            last_err = str(e)
        now = time.monotonic()
        elapsed = now - started
        if now >= deadline:
            raise RuntimeError(
                f"account query failed after {elapsed:.0f}s and {attempts} attempts "
                f"waiting for node API: {last_err}"
            )
        # Every gunicorn worker runs this, so one line per attempt floods the log
        # for the whole halt. Report the first attempt, then once per interval.
        if attempts == 1 or now - last_log >= _STARTUP_LOG_INTERVAL_SEC:
            _log.warning(
                "account query not ready after %.0fs (%d attempts, %.0fs of grace left): %s",
                elapsed,
                attempts,
                deadline - now,
                last_err[:200],
            )
            last_log = now
        time.sleep(min(delay, max(0.0, deadline - now)))
        delay = min(delay * 2, _STARTUP_MAX_BACKOFF_SEC)
    body = resp.json()
    acc = body.get("account") or {}
    # Some deployments wrap BaseAccount under a nested key.
    if "base_account" in acc:
        acc = acc["base_account"] or {}
    raw = acc.get("account_number")
    if raw is None or str(raw).strip() == "":
        raise RuntimeError(f"account_number missing for {address}: {str(body)[:200]}")
    return int(raw)


def initialize_runtime() -> Runtime:
    global _RUNTIME
    assert_node_home_ready()
    rpc_url = get_rpc_url()
    api_url = get_api_url()
    grpc_url = get_grpc_url()
    grpc_target = get_grpc_target()
    validator_payer_addr = resolve_validator_payer_address()
    validator_pubkey_bytes = resolve_validator_pubkey_bytes()
    validator_privkey_bytes = resolve_validator_privkey_bytes()
    # Pubkey derived from privkey must match the keyring pubkey.
    from cosmpy.crypto.keypairs import PrivateKey as _Priv

    derived_pub = _Priv(validator_privkey_bytes).public_key.public_key_bytes
    if derived_pub != validator_pubkey_bytes:
        raise RuntimeError("validator privkey/pubkey mismatch after export")
    chain_id = resolve_chain_id()
    validator_account_number = resolve_account_number(api_url, validator_payer_addr)
    validator_operator_address = _derive_valoper_from_account(validator_payer_addr)
    validator_consensus_address = _derive_valcons_from_pubkey(_get_node_consensus_pubkey_bytes())
    min_gas_price = _load_min_gas_price_umirage()

    from settings import QUESTS_PAYOUTS_ENABLED, QUESTS_REWARDS_POOL_ADDRESS

    pool_privkey = pool_pubkey = pool_addr = pool_account_number = None
    if QUESTS_PAYOUTS_ENABLED:
        pool_privkey, pool_pubkey, pool_addr, pool_account_number = resolve_rewards_pool_signer(
            api_url, REWARDS_POOL_KEY_NAME, QUESTS_REWARDS_POOL_ADDRESS
        )
        _log.info("rewards pool signer loaded addr=%s account_number=%d", pool_addr, pool_account_number)

    _RUNTIME = Runtime(
        rpc_url=rpc_url,
        api_url=api_url,
        grpc_url=grpc_url,
        grpc_target=grpc_target,
        validator_payer_addr=validator_payer_addr,
        validator_pubkey_bytes=validator_pubkey_bytes,
        validator_privkey_bytes=validator_privkey_bytes,
        validator_account_number=validator_account_number,
        chain_id=chain_id,
        validator_operator_address=validator_operator_address,
        validator_consensus_address=validator_consensus_address,
        min_gas_price_umirage=min_gas_price,
        rewards_pool_addr=pool_addr,
        rewards_pool_pubkey_bytes=pool_pubkey,
        rewards_pool_privkey_bytes=pool_privkey,
        rewards_pool_account_number=pool_account_number,
    )
    return _RUNTIME


def require_runtime() -> Runtime:
    if _RUNTIME is None:
        raise RuntimeError("runtime not initialized")
    return _RUNTIME


__all__ = [
    "Runtime",
    "initialize_runtime",
    "require_runtime",
    "assert_node_home_ready",
    "get_rpc_url",
    "get_api_url",
    "get_grpc_url",
    "get_grpc_target",
    "min_gas_price_umirage",
    "startup_grace_seconds",
    "resolve_validator_payer_address",
    "resolve_validator_pubkey_bytes",
    "resolve_validator_privkey_bytes",
    "resolve_rewards_pool_signer",
    "REWARDS_POOL_KEY_NAME",
    "find_local_operator_address",
    "find_local_consensus_address",
    "derive_address_from_pubkey",
]
