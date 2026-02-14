import time
import base64
import hashlib
import requests
import urllib3
import ssl
import math
from typing import Optional
from dataclasses import dataclass, field
from cosmpy.aerial.wallet import LocalWallet

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ---------------------------------------------------------------------------
# User level cache (avoid repeated API calls for subscriber checks)
# ---------------------------------------------------------------------------
@dataclass
class _UserLevelCache:
    """In-memory cache for user levels with TTL."""

    data: dict = field(default_factory=dict)  # address -> (timestamp, level)
    ttl: float = 30.0  # seconds

    def get(self, addr: str) -> Optional[int]:
        key = addr.lower()
        entry = self.data.get(key)
        if entry and (time.time() - entry[0]) < self.ttl:
            return entry[1]
        return None

    def set(self, addr: str, level: int) -> None:
        key = addr.lower()
        self.data[key] = (time.time(), level)
        # Bound cache size
        if len(self.data) > 1000:
            oldest = min(self.data.items(), key=lambda kv: kv[1][0])[0]
            self.data.pop(oldest, None)

    def invalidate(self, addr: str) -> None:
        self.data.pop(addr.lower(), None)

    def clear(self) -> None:
        self.data.clear()


_level_cache = _UserLevelCache()

# Create a permissive SSL context for production servers with SSL issues
_ssl_context = ssl.create_default_context()
_ssl_context.check_hostname = False
_ssl_context.verify_mode = ssl.CERT_NONE
try:
    _ssl_context.set_ciphers("DEFAULT:@SECLEVEL=1")
except Exception:
    pass  # Some systems don't support SECLEVEL

# Create a custom requests session with permissive SSL
from urllib3.util.ssl_ import create_urllib3_context


class CustomHTTPAdapter(requests.adapters.HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        # Create SSL context from scratch for maximum control
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        # Set permissive ciphers
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except Exception:
            try:
                ctx.set_ciphers("ALL:@SECLEVEL=1")
            except Exception:
                pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)

    def cert_verify(self, conn, url, verify, cert):
        # Override cert verification to always skip
        conn.cert_reqs = "CERT_NONE"
        conn.ca_certs = None
        conn.ca_cert_dir = None
        conn.cert_file = None
        conn.key_file = None


_session = requests.Session()
_session.mount("https://", CustomHTTPAdapter())
_session.verify = False
# Set headers that might help with SSL handshake
_session.headers.update(
    {
        "User-Agent": "MirageRedditBot/1.0",
        "Accept": "application/json",
        "Connection": "keep-alive",
    }
)
# Disable SSL warnings
import warnings

warnings.filterwarnings("ignore", message="Unverified HTTPS request")
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import utils as crypto_utils
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from shared.canon import (
    canon_base_set_username as _canon_base_set_username,
    canon_base_post as _canon_base_post,
    canon_base_vote as _canon_base_vote,
    canon_signed_with_pow,
    uvarint,
)

try:
    from argon2.low_level import hash_secret_raw as _argon2_hash_raw, Type as _Argon2Type
except Exception:
    _argon2_hash_raw = None
    _Argon2Type = None


def _log(msg: str) -> None:
    try:
        print(msg, flush=True)
    except Exception:
        pass


_BASE_DIFFICULTY_FACTOR = 1000
_MAX_SAFE_DIFFICULTY_FACTOR = (1 << 53) - 1


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _difficulty_factor(difficulty_steps: int, pow_difficulty_step: float) -> int | None:
    if difficulty_steps < 0:
        return None
    if not math.isfinite(pow_difficulty_step) or pow_difficulty_step <= 0 or pow_difficulty_step > 1:
        return None
    if difficulty_steps == 0:
        return _BASE_DIFFICULTY_FACTOR
    try:
        factor = _BASE_DIFFICULTY_FACTOR * math.pow(1.0 + pow_difficulty_step, float(difficulty_steps))
    except Exception:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if not math.isfinite(factor):
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if factor > _MAX_SAFE_DIFFICULTY_FACTOR:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    rounded = _round_half_up(factor)
    return max(_BASE_DIFFICULTY_FACTOR, rounded)


def check_pow_target(digest: bytes, difficulty_steps: int, min_difficulty: int, pow_difficulty_step: float) -> bool:
    """Target-based PoW check. difficulty is steps (0=base, 1=+step, 2=+step^2)."""
    if min_difficulty <= 0 or min_difficulty > 256:
        return False
    factor = _difficulty_factor(difficulty_steps, pow_difficulty_step)
    if factor is None:
        return False
    base_target = 1 << (256 - min_difficulty)
    eff_target = base_target * _BASE_DIFFICULTY_FACTOR // factor
    return int.from_bytes(digest, "big") <= eff_target


def canon_base_set_username(
    pubkey: bytes, last_block_hash_hex: str, difficulty: int, _fees: int, target: str, username: str
) -> bytes:
    """
    Backwards-compatible wrapper for shared.canon.canon_base_set_username.

    Older callers passed (pubkey, last_block_hash_hex, difficulty, fees, target, username).
    We now ignore fees and supply an envelope_timestamp derived from wall-clock time.
    """
    ts_ms = int(time.time() * 1000)
    return _canon_base_set_username(
        pubkey, bytes.fromhex(last_block_hash_hex), int(difficulty), ts_ms, target, username
    )


def canon_base_post(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    topic: str,
    title: str,
    content: str,
) -> bytes:
    """
    Backwards-compatible wrapper for shared.canon.canon_base_post.

    Older callers passed (pubkey, last_block_hash_hex, difficulty, target, topic, title, content)
    with a single topic string. We now:
    - derive envelope_timestamp from wall-clock time
    - use empty tag and pow_val=0
    """
    ts_ms = int(time.time() * 1000)
    return _canon_base_post(
        pubkey,
        bytes.fromhex(last_block_hash_hex),
        int(difficulty),
        ts_ms,
        target,
        topic or "",
        title,
        content,
        "",
        0,
    )


def canon_base_vote(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    _fees: int,
    target: str,
    direction: int,
) -> bytes:
    """
    Backwards-compatible wrapper for shared.canon.canon_base_vote.

    Older callers passed (pubkey, last_block_hash_hex, difficulty, fees, target, direction).
    We now ignore fees and derive envelope_timestamp from wall-clock time.
    """
    ts_ms = int(time.time() * 1000)
    return _canon_base_vote(
        pubkey,
        bytes.fromhex(last_block_hash_hex),
        int(difficulty),
        ts_ms,
        target,
        int(direction),
    )


def compute_pow(base: bytes, difficulty_steps: int, min_difficulty: int, pow_difficulty_step: float, lb_hash: str) -> int:
    if _argon2_hash_raw is None:
        raise RuntimeError("argon2-cffi is required for PoW")
    if difficulty_steps < 0:
        raise ValueError("difficulty must be >= 0")
    if min_difficulty <= 0 or min_difficulty > 256:
        raise ValueError("min_difficulty must be in [1, 256]")
    try:
        salt = bytes.fromhex(lb_hash.strip())
    except Exception:
        salt = lb_hash.encode()

    mem_kib = 4096
    time_cost = 1
    parallelism = 1

    _log(
        f"[pow] argon2id: difficulty_steps={difficulty_steps} min_difficulty={min_difficulty} step={pow_difficulty_step} mem_kib={mem_kib} t={time_cost} p={parallelism}"
    )

    proof = 0
    attempts = 0
    start = time.perf_counter()
    next_report = start

    while True:
        now = time.perf_counter()
        if now >= next_report:
            rate = attempts / max(1e-6, (now - start))
            _log(f"[pow] attempts={attempts} elapsed={now - start:.2f}s rate={rate:.1f}/s")
            next_report = now + 0.5

        digest = _argon2_hash_raw(
            base + b":" + uvarint(int(proof)),
            salt,
            time_cost=time_cost,
            memory_cost=mem_kib,
            parallelism=parallelism,
            hash_len=32,
            type=_Argon2Type.ID,
        )
        attempts += 1
        if check_pow_target(digest, difficulty_steps, min_difficulty, pow_difficulty_step):
            total = time.perf_counter() - start
            rate = attempts / max(1e-6, total)
            _log(
                f"[pow] success proof={proof} difficulty={difficulty} attempts={attempts} time={total:.2f}s rate={rate:.1f}/s"
            )
            return proof
        proof += 1


def der_to_compact_sig(sig_der: bytes) -> bytes:
    if len(sig_der) == 64:
        sig = sig_der
    elif len(sig_der) == 65:
        sig = sig_der[:64]
    elif len(sig_der) < 8 or sig_der[0] != 0x30:
        return sig_der
    else:
        try:
            r, s = decode_dss_signature(sig_der)
            n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
            if s > n // 2:
                s = n - s
            r_bytes = r.to_bytes(32, "big")
            s_bytes = s.to_bytes(32, "big")
            return r_bytes + s_bytes
        except Exception:
            return sig_der

    if len(sig) != 64:
        return sig_der

    n = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
    r = sig[:32]
    s_bytes = sig[32:]
    s_int = int.from_bytes(s_bytes, "big")
    half_n = n // 2
    if s_int > half_n:
        s_int = n - s_int
        s_bytes = s_int.to_bytes(32, "big")
    return r + s_bytes


def sign_canonical(wallet: LocalWallet, canonical_bytes: bytes) -> bytes:
    priv_key_int = int.from_bytes(wallet.signer().private_key_bytes, "big")
    priv_key = ec.derive_private_key(priv_key_int, ec.SECP256K1(), default_backend())
    sig_der = priv_key.sign(canonical_bytes, ec.ECDSA(hashes.SHA256()))
    return der_to_compact_sig(sig_der)


def create_wallet_from_seed(seed_phrase: str, prefix: str = "mirage") -> LocalWallet:
    return LocalWallet.from_mnemonic(seed_phrase, prefix=prefix)


def get_status(backend: str, address: str | None = None) -> dict:
    params = {"address": address} if address else {}
    r = _session.get(f"{backend}/api/get_parameters", params=params, timeout=5)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError as e:
        raise ValueError(f"Invalid JSON response from {r.url}: status={r.status_code}, text={r.text[:200]}") from e


def get_chain_config(backend: str) -> dict:
    r = _session.get(f"{backend}/api/get_chain_config", timeout=5)
    r.raise_for_status()
    return r.json()


def get_node_config(backend: str) -> dict:
    r = _session.get(f"{backend}/api/get_node_config", timeout=5)
    r.raise_for_status()
    return r.json()


def get_user_status(backend: str, address: str) -> dict:
    r = _session.get(f"{backend}/api/get_user_status", params={"address": address}, timeout=5)
    r.raise_for_status()
    return r.json()


def get_config(*_args, **_kwargs) -> dict:
    raise RuntimeError("get_config endpoint removed; use get_chain_config/get_node_config")


def get_username_from_address(backend: str, address: str) -> str | None:
    try:
        r = _session.get(f"{backend}/api/get_profile", params={"address": address}, timeout=5)
        r.raise_for_status()
        profile = r.json()
        username = profile.get("username")
        return username if username else None
    except Exception:
        return None


def get_address_from_username(backend: str, username: str) -> str | None:
    try:
        r = _session.get(f"{backend}/api/get_address_from_username", params={"username": username}, timeout=5)
        r.raise_for_status()
        data = r.json()
        if data.get("exists"):
            return data.get("address")
        return None
    except Exception:
        return None


def is_username_available(backend: str, username: str) -> bool:
    """Check if a username is available (not taken by any address)."""
    return get_address_from_username(backend, username) is None


def get_user_level(backend: str, address: str, use_cache: bool = True) -> int:
    """
    Get the subscription level for an address.

    Returns:
        0 = free user
        1+ = subscriber (paid tier)
        100+ = admin/moderator

    Uses a local cache (30s TTL) to avoid hammering the backend.
    Set use_cache=False to force a fresh fetch.
    """
    addr = (address or "").strip()
    if not addr:
        return 0

    if use_cache:
        cached = _level_cache.get(addr)
        if cached is not None:
            return cached

    try:
        r = _session.get(f"{backend}/api/get_user_status", params={"address": addr}, timeout=5)
        r.raise_for_status()
        data = r.json()
        level = int(data.get("user_level", 0) or 0)
        _level_cache.set(addr, level)
        return level
    except Exception:
        return 0


def is_subscriber(backend: str, address: str, use_cache: bool = True) -> bool:
    """
    Check if an address is a paid subscriber (level >= 1).

    Subscribers don't need PoW for transactions.
    Uses cached user level (30s TTL).
    """
    return get_user_level(backend, address, use_cache=use_cache) >= 1


def invalidate_user_cache(address: str) -> None:
    """Invalidate cached user level (e.g., after subscription change)."""
    _level_cache.invalidate(address)


def clear_user_cache() -> None:
    """Clear all cached user levels."""
    _level_cache.clear()


def set_username(
    backend: str,
    wallet: LocalWallet,
    username: str,
    skip_pow: Optional[bool] = None,
) -> dict:
    """
    Set username for a wallet.

    Args:
        backend: Backend URL
        wallet: User's wallet
        username: Desired username
        skip_pow: If True, skip PoW (subscriber mode). If None, auto-detect based on user level.
    """
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = st["last_block_hash"]
    diff = int(st["pow_difficulty"])
    min_diff = int(st["min_difficulty"])
    pow_step = float(st["pow_difficulty_step"])
    pub_bytes = wallet.public_key().public_key_bytes

    # Auto-detect subscriber status if not specified
    if skip_pow is None:
        skip_pow = is_subscriber(backend, addr)

    ts_ms = int(time.time() * 1000)

    if skip_pow:
        # Subscriber mode: no PoW, difficulty=0, pow=0
        base = _canon_base_set_username(pub_bytes, bytes.fromhex(lb), 0, ts_ms, addr, username)
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        req = {
            "username": username,
            "last_block_hash": lb,
            "timestamp": ts_ms,
            "pow_difficulty": 0,
            "pubkey": base64.b64encode(pub_bytes).decode(),
            "signature": base64.b64encode(sig).decode(),
        }
    else:
        # Free user mode: compute PoW
        base = _canon_base_set_username(pub_bytes, bytes.fromhex(lb), diff, ts_ms, addr, username)
        proof = compute_pow(base, diff, min_diff, pow_step, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        req = {
            "username": username,
            "last_block_hash": lb,
            "timestamp": ts_ms,
            "pow_difficulty": diff,
            "pow": int(proof),
            "pubkey": base64.b64encode(pub_bytes).decode(),
            "signature": base64.b64encode(sig).decode(),
        }

    r = _session.post(f"{backend}/api/core/set_username", json=req, timeout=20)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"status": r.status_code}


def post(
    backend: str,
    wallet: LocalWallet,
    topic: str,
    title: str,
    content: str,
    target: str = "",
    tag: str = "",
    skip_pow: Optional[bool] = None,
) -> str | None:
    """
    Create a post.

    Args:
        backend: Backend URL
        wallet: User's wallet
        topic: Topic/subreddit name
        title: Post title
        content: Post content
        target: Parent post hash (for comments) or empty for top-level
        tag: Content tag (e.g., "sensitive", "porn", "gore")
        skip_pow: If True, skip PoW (subscriber mode). If None, auto-detect.

    Returns:
        Transaction hash on success, None on failure.
    """
    safe_title = (title or "").strip()
    if len(safe_title) > 180:
        safe_title = safe_title[:177] + "..."

    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = st["last_block_hash"]
    diff = int(st["pow_difficulty"])
    min_diff = int(st["min_difficulty"])
    pow_step = float(st["pow_difficulty_step"])
    pub = wallet.public_key().public_key_bytes

    # Auto-detect subscriber status if not specified
    if skip_pow is None:
        skip_pow = is_subscriber(backend, addr)

    ts_ms = int(time.time() * 1000)

    if skip_pow:
        # Subscriber mode: no PoW
        base = _canon_base_post(
            pub,
            bytes.fromhex(lb),
            0,
            ts_ms,
            target or "",
            topic or "",
            safe_title,
            content,
            tag or "",
            0,
        )
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        req = {
            "pubkey": base64.b64encode(pub).decode(),
            "signature": base64.b64encode(sig).decode(),
            "last_block_hash": lb,
            "timestamp": ts_ms,
            "pow_difficulty": 0,
            "target": target,
            "topic": topic or "",
            "title": safe_title,
            "content": content,
            "tag": tag or "",
        }
    else:
        # Free user mode: compute PoW
        base = _canon_base_post(
            pub,
            bytes.fromhex(lb),
            diff,
            ts_ms,
            target or "",
            topic or "",
            safe_title,
            content,
            tag or "",
            0,
        )
        proof = compute_pow(base, diff, min_diff, pow_step, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        req = {
            "pubkey": base64.b64encode(pub).decode(),
            "signature": base64.b64encode(sig).decode(),
            "last_block_hash": lb,
            "timestamp": ts_ms,
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": target,
            "topic": topic or "",
            "title": safe_title,
            "content": content,
            "tag": tag or "",
        }

    r = _session.post(f"{backend}/api/core/post", json=req, timeout=20)
    try:
        data = r.json()
    except Exception:
        data = {"status": r.status_code}
    txh = str((data or {}).get("tx_hash", "") or "").lower()
    _log(f"--> created post: {txh or data}")
    return txh if txh else None


def vote(
    backend: str,
    wallet: LocalWallet,
    target: str,
    direction: int,
    skip_pow: Optional[bool] = None,
) -> dict:
    """
    Vote on a post.

    Args:
        backend: Backend URL
        wallet: User's wallet
        target: Post hash to vote on
        direction: 1 for upvote, -1 for downvote, 0 to remove vote
        skip_pow: If True, skip PoW (subscriber mode). If None, auto-detect.
    """
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = st["last_block_hash"]
    diff = int(st["pow_difficulty"])
    min_diff = int(st["min_difficulty"])
    pow_step = float(st["pow_difficulty_step"])
    pub = wallet.public_key().public_key_bytes

    # Auto-detect subscriber status if not specified
    if skip_pow is None:
        skip_pow = is_subscriber(backend, addr)

    ts_ms = int(time.time() * 1000)

    if skip_pow:
        # Subscriber mode: no PoW
        base = _canon_base_vote(pub, bytes.fromhex(lb), 0, ts_ms, target, int(direction))
        signed = canon_signed_with_pow(base, 0)
        sig = sign_canonical(wallet, signed)
        req = {
            "pubkey": base64.b64encode(pub).decode(),
            "signature": base64.b64encode(sig).decode(),
            "last_block_hash": lb,
            "timestamp": ts_ms,
            "pow_difficulty": 0,
            "target": target,
            "direction": direction,
        }
    else:
        # Free user mode: compute PoW
        base = _canon_base_vote(pub, bytes.fromhex(lb), diff, ts_ms, target, int(direction))
        proof = compute_pow(base, diff, min_diff, pow_step, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        req = {
            "pubkey": base64.b64encode(pub).decode(),
            "signature": base64.b64encode(sig).decode(),
            "last_block_hash": lb,
            "timestamp": ts_ms,
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": target,
            "direction": direction,
        }

    r = _session.post(f"{backend}/api/core/vote", json=req, timeout=20)
    return r.json() if r.headers.get("content-type", "").startswith("application/json") else {"status": r.status_code}


def comment(
    backend: str,
    wallet: LocalWallet,
    parent: str,
    content: str,
    skip_pow: Optional[bool] = None,
) -> str | None:
    """
    Create a comment on a post.

    Convenience wrapper around post() with target set to parent hash.

    Args:
        backend: Backend URL
        wallet: User's wallet
        parent: Parent post hash to comment on
        content: Comment content
        skip_pow: If True, skip PoW (subscriber mode). If None, auto-detect.

    Returns:
        Transaction hash on success, None on failure.
    """
    return post(
        backend=backend,
        wallet=wallet,
        topic="",
        title="",
        content=content,
        target=parent,
        tag="",
        skip_pow=skip_pow,
    )
