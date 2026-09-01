"""Proof that whoever answers at an address holds a given validator's key.

/network lists the sites the network runs on, and the only thing behind an entry
used to be a validator's moniker -- free text its operator edits. A moniker
naming a domain asserted the domain and nothing ever checked that the domain
agreed, so the list was a set of claims presented as facts. It also meant a node
whose operator wrote a nickname had no address at all and vanished from the
page, which is how a running third-party validator stayed invisible.

An address is confirmed here by challenge and response. The verifier picks a
nonce, names the origin it dialed, and the node signs both with its validator
account key. Deriving the account address from the pubkey and re-encoding it
with the `miragevaloper` prefix yields the operator address -- the two are the
same twenty bytes under different prefixes -- so the signature says "the key
behind this bonded validator is answering at this origin, now". Binding the
origin is what makes a captured response useless somewhere else, and binding the
nonce is what makes it useless later.

The signature is the trust anchor, not the transport. A node with no domain can
hold no certificate and serves plain http; requiring TLS to believe it would
re-create the exact hole this replaces.

On signing verifier-chosen bytes: the payload is netstring-framed under a fixed
ASCII prefix, and `origin` and `nonce` are validated against narrow grammars
before anything is signed. `node_identity:v1|` cannot begin a Cosmos SignDoc --
the first byte would have to be 0x0a for field 1, and `n` is 0x6e, which decodes
as field 13 with wire type 6 and no such field exists -- so a response can never
be lifted into a transaction.
"""

from __future__ import annotations

import base64
import ipaddress
import re
import secrets
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils

from shared.client import der_to_compact_sig

IDENTITY_PREFIX = "node_identity:v1"
VALOPER_HRP = "miragevaloper"

# Wide enough that a verifier cannot be talked into a trivially guessable
# challenge, bounded so the signed payload stays a fixed small size.
_NONCE_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_HOSTNAME_RE = re.compile(r"\A[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_MAX_ORIGIN_LEN = 255


def new_nonce() -> str:
    return secrets.token_hex(16)


def normalize_origin(raw: str) -> Optional[str]:
    """`scheme://host[:port]` with nothing else, or None.

    Deliberately syntactic: this runs on a public endpoint before any signing,
    and resolving names here would let a caller aim this node's DNS traffic.
    Reachability is the verifier's problem -- it dialed the origin already.
    """
    value = (raw or "").strip()
    if not value or len(value) > _MAX_ORIGIN_LEN or any(ch.isspace() for ch in value):
        return None
    if not value.startswith(("http://", "https://")):
        return None

    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.username or parts.password or parts.query or parts.fragment:
        return None
    if parts.path not in ("", "/"):
        return None

    try:
        hostname = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if not hostname:
        return None
    hostname = hostname.lower()
    if port is not None and not 1 <= port <= 65535:
        return None

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        host_part = f"[{hostname}]" if literal.version == 6 else hostname
    else:
        if hostname.count(".") < 1 or len(hostname) > 253:
            return None
        if not all(_HOSTNAME_RE.fullmatch(label) for label in hostname.split(".")):
            return None
        host_part = hostname

    netloc = f"{host_part}:{port}" if port else host_part
    return f"{parts.scheme}://{netloc}"


def _canonical_payload(chain_id: str, operator_address: str, origin: str, site: str, nonce: str) -> bytes:
    """Netstring framing so no field can be shifted into another.

    Joining these with a separator would be ambiguous: an origin legitimately
    contains `:` and `//`, and the whole point of the payload is that the origin
    it names cannot be read as anything else.
    """
    fields = (chain_id, operator_address, origin, site, nonce)
    body = "|".join(f"{len(f)}:{f}" for f in fields)
    return f"{IDENTITY_PREFIX}|{body}".encode("utf-8")


def local_site() -> str:
    """This node's canonical public URL, or "" when it has no domain.

    A node reached by its address cannot state a canonical URL: it does not know
    which of its addresses a visitor used, and nothing issues a certificate for
    one. Empty is the honest answer, and the verifier falls back to the origin
    it dialed -- which is signed either way.
    """
    import os

    domain = (os.environ.get("DOMAIN", "") or "").strip().lower()
    if not domain:
        return ""
    return normalize_origin(f"https://{domain}") or ""


def build_local_identity(origin_raw: str, nonce_raw: str) -> Dict[str, Any]:
    """Sign this node's identity against a verifier's challenge.

    Raises ValueError when the challenge is malformed, which the endpoint turns
    into a 400. Nothing is signed before both inputs pass their grammar.
    """
    from node import require_runtime

    origin = normalize_origin(origin_raw)
    if origin is None:
        raise ValueError("origin must be scheme://host[:port]")
    nonce = (nonce_raw or "").strip()
    if not _NONCE_RE.fullmatch(nonce):
        raise ValueError("nonce must be 32 lowercase hex characters")

    rt = require_runtime()
    site = local_site()
    payload = _canonical_payload(rt.chain_id, rt.validator_operator_address, origin, site, nonce)

    priv = ec.derive_private_key(int.from_bytes(rt.validator_privkey_bytes, "big"), ec.SECP256K1(), default_backend())
    signature = der_to_compact_sig(priv.sign(payload, ec.ECDSA(hashes.SHA256())))
    if len(signature) != 64:
        raise RuntimeError(f"identity signature must be 64 bytes, got {len(signature)}")

    return {
        "chain_id": rt.chain_id,
        "operator_address": rt.validator_operator_address,
        "site": site,
        "origin": origin,
        "nonce": nonce,
        "pubkey": base64.b64encode(rt.validator_pubkey_bytes).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def valoper_from_pubkey(pubkey_bytes: bytes) -> str:
    from node import derive_address_from_pubkey

    return derive_address_from_pubkey(pubkey_bytes, hrp=VALOPER_HRP)


def verify_identity(doc: Any, *, expect_origin: str, expect_nonce: str, expect_chain_id: str) -> Optional[str]:
    """The operator address this response proves, or None.

    Proving membership of the active set is not this function's job -- the
    caller holds the validator set and checks bondedness against it. All that
    is settled here is that the holder of this key answered this challenge.
    """
    if not isinstance(doc, dict):
        return None
    if str(doc.get("chain_id", "")) != expect_chain_id:
        return None
    if str(doc.get("origin", "")) != expect_origin:
        return None
    if str(doc.get("nonce", "")) != expect_nonce:
        return None

    claimed = str(doc.get("operator_address", "") or "").strip()
    site = str(doc.get("site", "") or "")
    if not claimed.startswith(VALOPER_HRP + "1"):
        return None
    if site and normalize_origin(site) != site:
        return None

    try:
        pubkey = base64.b64decode(str(doc.get("pubkey", "")), validate=True)
        signature = base64.b64decode(str(doc.get("signature", "")), validate=True)
    except Exception:
        return None
    if len(pubkey) != 33 or len(signature) != 64:
        return None
    if valoper_from_pubkey(pubkey) != claimed:
        return None

    payload = _canonical_payload(expect_chain_id, claimed, expect_origin, site, expect_nonce)
    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    try:
        der = asym_utils.encode_dss_signature(r, s)
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pubkey)
        key.verify(der, payload, ec.ECDSA(hashes.SHA256()))
    except Exception:
        return None
    return claimed


def announced_site(doc: Any) -> str:
    """The canonical URL a verified response asked to be listed under."""
    if not isinstance(doc, dict):
        return ""
    site = str(doc.get("site", "") or "")
    return site if site and normalize_origin(site) == site else ""


__all__ = [
    "IDENTITY_PREFIX",
    "announced_site",
    "build_local_identity",
    "local_site",
    "new_nonce",
    "normalize_origin",
    "valoper_from_pubkey",
    "verify_identity",
]
