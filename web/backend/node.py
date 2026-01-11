from __future__ import annotations

"""Node and runtime helpers.

Functions:
- initialize_runtime(): Resolve URLs, keys; verify gRPC.
- require_runtime(): Return initialized runtime or raise.
- assert_node_home_ready(): Validate node directories/files.
- get_rpc_url/get_grpc_url/get_grpc_target(): URL helpers.
- min_gas_price_umirage(): Minimum gas price for umirage.
- resolve_validator_payer_address(): Fee payer address.
- resolve_validator_pubkey_bytes(): Validator pubkey bytes.
- find_local_operator_address(): miragevaloper address.
- find_local_consensus_address(): miragevalcons address.
- derive_address_from_pubkey(pubkey, hrp): Account bech32 address.
"""

import base64
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple
import grpc as _grpc

import tomllib as _toml

from bech32 import bech32_encode, bech32_decode, convertbits  # type: ignore

from shared.config import get_config

from paths import project_root

KEYRING_BACKEND = get_config().get_keyring_backend()


@dataclass
class Runtime:
    rpc_url: str
    api_url: str
    grpc_url: str
    grpc_target: str
    validator_payer_addr: str
    validator_pubkey_bytes: bytes


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
    url = get_grpc_url()
    if url.startswith("grpc+http://"):
        url = url[len("grpc+http://") :]
    if url.startswith("http://"):
        url = url[len("http://") :]
    if url.startswith("https://"):
        url = url[len("https://") :]
    return url


def min_gas_price_umirage() -> float:
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


def find_local_operator_address() -> str:
    local_cons_pub = _get_node_consensus_pubkey_bytes()
    import urllib.request as _url
    import json as _json

    rpc = get_rpc_url()
    url = f"{rpc}/validators"
    with _url.urlopen(url, timeout=2) as resp:
        data = _json.loads(resp.read().decode("utf-8"))
    vals = ((data or {}).get("result") or {}).get("validators") or []
    for ent in vals:
        pk_b64 = str(((ent or {}).get("pub_key") or {}).get("value") or "")
        if not pk_b64:
            continue
        try:
            if base64.b64decode(pk_b64) == local_cons_pub:
                break
        except Exception:
            continue
    else:
        raise RuntimeError("local consensus key not found in current validator set")

    addr = resolve_validator_payer_address()
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


def find_local_consensus_address() -> str:
    import hashlib as _hl

    cons_pub = _get_node_consensus_pubkey_bytes()
    if not cons_pub:
        raise RuntimeError("missing consensus pubkey bytes")
    h20 = _hl.sha256(cons_pub).digest()[:20]
    data5 = convertbits(h20, 8, 5)
    if not data5:
        raise RuntimeError("bech32 convertbits 8->5 failed for valcons")
    return bech32_encode("miragevalcons", data5)


def resolve_validator_payer_address() -> str:
    cfg = get_config()
    home = cfg.get_node_config()["home"]
    bin_path = os.path.abspath(os.path.join(project_root(), "blockchain", "miraged"))
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
    bin_path = os.path.abspath(os.path.join(project_root(), "blockchain", "miraged"))
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


def initialize_runtime() -> Runtime:
    global _RUNTIME
    assert_node_home_ready()
    rpc_url = get_rpc_url()
    api_url = get_api_url()
    grpc_url = get_grpc_url()
    grpc_target = get_grpc_target()
    validator_payer_addr = resolve_validator_payer_address()
    validator_pubkey_bytes = resolve_validator_pubkey_bytes()
    _RUNTIME = Runtime(
        rpc_url=rpc_url,
        api_url=api_url,
        grpc_url=grpc_url,
        grpc_target=grpc_target,
        validator_payer_addr=validator_payer_addr,
        validator_pubkey_bytes=validator_pubkey_bytes,
    )
    assert_grpc_ready(timeout_s=2.0)
    return _RUNTIME


def require_runtime() -> Runtime:
    if _RUNTIME is None:
        raise RuntimeError("runtime not initialized")
    return _RUNTIME


def assert_grpc_ready(timeout_s: float = 2.0) -> None:
    target = require_runtime().grpc_target
    ch = _grpc.insecure_channel(target)
    _grpc.channel_ready_future(ch).result(timeout=timeout_s)


__all__ = [
    "Runtime",
    "initialize_runtime",
    "require_runtime",
    "assert_grpc_ready",
    "assert_node_home_ready",
    "get_rpc_url",
    "get_api_url",
    "get_grpc_url",
    "get_grpc_target",
    "min_gas_price_umirage",
    "resolve_validator_payer_address",
    "resolve_validator_pubkey_bytes",
    "find_local_operator_address",
    "find_local_consensus_address",
    "derive_address_from_pubkey",
]
