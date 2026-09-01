"""Proof that the address you dialed is the same node you are peered with.

/network exists so a user can find another node and move to it, and the mobile
app turns those entries into a server switcher. That makes the list a security
surface: an entry the app will connect to is an endorsement, and an operator's
moniker is free text that costs nothing to write. Something has to tie a claimed
address to a node the network already knows.

The p2p handshake is what makes that possible. A CometBFT node ID is
`sha256(pubkey)[:20]`, and peers exchange and authenticate those IDs when they
connect, so of everything this node believes about a peer, its node ID is the
part nobody asserted -- it was proved by the connection itself. A remote address
is therefore confirmed by asking whoever answers there to sign a challenge with
the p2p key behind that same node ID.

Two properties matter, and both come from what is *not* in the payload:

- **Nothing a caller sends is signed except the nonce.** The node states its own
  chain, its own node ID, its own validator and its own addresses. A verifier
  cannot get it to sign a sentence about anywhere else, so a response says only
  "this node is here, now".
- **The expected node ID comes from our own peer table, never from the reply.**
  Relaying is the obvious attack -- `evil.example` forwards our challenge to a
  real node and returns its answer verbatim -- and it fails because the answer
  carries that node's ID while we are checking it against the ID of the peer
  whose address we are testing. A valid signature for the wrong node is simply
  the wrong node.

The address a document declares is a hint about where else to look, never a
result. Only a URL this node actually dialed and verified is reported as
reachable, so a node cannot claim someone else's domain into its own entry.

A node ID says which node answered, not what stake stands behind it, and anyone
can run a node. So the operator address carries a second signature from the
validator account key, and the two answer different questions: the p2p proof
decides whether an address is *reachable* and safe to offer as a destination,
the validator proof decides whether it may be *trusted* with a forwarded
credential. Only the second is a claim on the chain's authority.

On signing verifier-chosen bytes with the p2p key: the CometBFT handshake signs
a bare 32-byte transcript hash, while everything here is netstring-framed under
a fixed ASCII prefix and is never 32 bytes long. A signature produced here can
therefore never be replayed as a handshake.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, utils as asym_utils

from shared.client import der_to_compact_sig

IDENTITY_PREFIX = "node_identity:v1"
VALOPER_HRP = "miragevaloper"

# Wide enough that a verifier cannot be talked into a trivially guessable
# challenge, bounded so the signed payload stays a fixed small size.
_NONCE_RE = re.compile(r"\A[0-9a-f]{32}\Z")
_HOSTNAME_RE = re.compile(r"\A[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_NODE_ID_RE = re.compile(r"\A[0-9a-f]{40}\Z")
_MAX_ORIGIN_LEN = 255
# A node describes where it can be reached, not the whole internet. The cap
# bounds both the signed payload and how many addresses a probe will chase.
_MAX_ADDRESSES = 4


@dataclass(frozen=True)
class IdentityProof:
    """What a verified response established.

    `addresses` are the node's own declared locations, useful as further probe
    candidates. `operator_address` is set only when the validator signature also
    verified, and is empty for a node that runs no validator.
    """

    node_id: str
    addresses: List[str] = field(default_factory=list)
    operator_address: str = ""


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


def node_id_from_pubkey(pubkey: bytes) -> str:
    """The CometBFT node ID an ed25519 p2p public key produces."""
    return hashlib.sha256(pubkey).hexdigest()[:40]


def valoper_from_pubkey(pubkey_bytes: bytes) -> str:
    from node import derive_address_from_pubkey

    return derive_address_from_pubkey(pubkey_bytes, hrp=VALOPER_HRP)


def _canonical_payload(
    chain_id: str,
    node_id: str,
    operator_address: str,
    addresses: List[str],
    nonce: str,
) -> bytes:
    """Netstring framing so no field can be shifted into another.

    Joining these with a separator would be ambiguous: an address legitimately
    contains `:` and `//`, and the list is variable length, so the count is
    signed too -- otherwise dropping a trailing address would leave a payload
    that still parses.
    """
    fields = [chain_id, node_id, operator_address, nonce, str(len(addresses))] + list(addresses)
    body = "|".join(f"{len(f)}:{f}" for f in fields)
    return f"{IDENTITY_PREFIX}|{body}".encode("utf-8")


def local_addresses() -> List[str]:
    """Where this node says it can be reached, or [] when it has no name.

    `DOMAIN` is the public address and `ORIGIN_DOMAIN` the direct one that stays
    pointed at the host when a CDN is put in front. Both are worth publishing:
    the first is what a user should browse, the second is the one that still
    resolves to this machine.
    """
    out: List[str] = []
    for var in ("DOMAIN", "ORIGIN_DOMAIN"):
        name = (os.environ.get(var, "") or "").strip().lower()
        if not name:
            continue
        url = normalize_origin(f"https://{name}")
        if url and url not in out:
            out.append(url)
    return out[:_MAX_ADDRESSES]


def build_local_identity(nonce_raw: str) -> Dict[str, Any]:
    """Sign this node's own identity against a verifier's nonce.

    Raises ValueError when the nonce is malformed, which the endpoint turns into
    a 400. The nonce is the only caller input and it cannot name a subject.
    """
    from node import require_runtime

    nonce = (nonce_raw or "").strip()
    if not _NONCE_RE.fullmatch(nonce):
        raise ValueError("nonce must be 32 lowercase hex characters")

    rt = require_runtime()
    addresses = local_addresses()
    payload = _canonical_payload(
        rt.chain_id, rt.node_id, rt.validator_operator_address, addresses, nonce
    )

    node_sig = ed25519.Ed25519PrivateKey.from_private_bytes(rt.node_privkey_bytes).sign(payload)
    if len(node_sig) != 64:
        raise RuntimeError(f"node signature must be 64 bytes, got {len(node_sig)}")

    priv = ec.derive_private_key(
        int.from_bytes(rt.validator_privkey_bytes, "big"), ec.SECP256K1(), default_backend()
    )
    validator_sig = der_to_compact_sig(priv.sign(payload, ec.ECDSA(hashes.SHA256())))
    if len(validator_sig) != 64:
        raise RuntimeError(f"validator signature must be 64 bytes, got {len(validator_sig)}")

    return {
        "chain_id": rt.chain_id,
        "node_id": rt.node_id,
        "operator_address": rt.validator_operator_address,
        "addresses": addresses,
        "nonce": nonce,
        "pubkey": base64.b64encode(rt.node_pubkey_bytes).decode("ascii"),
        "signature": base64.b64encode(node_sig).decode("ascii"),
        "validator_pubkey": base64.b64encode(rt.validator_pubkey_bytes).decode("ascii"),
        "validator_signature": base64.b64encode(validator_sig).decode("ascii"),
    }


def _verify_validator_claim(doc: Dict[str, Any], payload: bytes, claimed: str) -> str:
    """The operator address the validator signature proves, or "".

    A failure here is not a failure of the document. The node ID proof stands on
    its own, and a node that runs no validator has nothing to add -- so this
    downgrades to "no operator proved" rather than rejecting the response.
    """
    if not claimed.startswith(VALOPER_HRP + "1"):
        return ""
    try:
        pubkey = base64.b64decode(str(doc.get("validator_pubkey", "")), validate=True)
        signature = base64.b64decode(str(doc.get("validator_signature", "")), validate=True)
    except Exception:
        return ""
    if len(pubkey) != 33 or len(signature) != 64:
        return ""
    if valoper_from_pubkey(pubkey) != claimed:
        return ""

    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")
    try:
        der = asym_utils.encode_dss_signature(r, s)
        key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), pubkey)
        key.verify(der, payload, ec.ECDSA(hashes.SHA256()))
    except Exception:
        return ""
    return claimed


def verify_identity(
    doc: Any,
    *,
    expect_nonce: str,
    expect_chain_id: str,
    expect_node_id: str,
) -> Optional[IdentityProof]:
    """What this response proves, or None if it proves nothing.

    `expect_node_id` must come from this node's own p2p connections. Passing in
    a value taken from the response would verify that a signature is internally
    consistent and nothing else, which is exactly the relay this prevents.
    """
    if not isinstance(doc, dict):
        return None
    if not _NODE_ID_RE.fullmatch(expect_node_id or ""):
        return None
    if str(doc.get("chain_id", "")) != expect_chain_id:
        return None
    if str(doc.get("nonce", "")) != expect_nonce:
        return None
    if str(doc.get("node_id", "")) != expect_node_id:
        return None

    raw_addresses = doc.get("addresses")
    if not isinstance(raw_addresses, list) or len(raw_addresses) > _MAX_ADDRESSES:
        return None
    addresses: List[str] = []
    for entry in raw_addresses:
        if not isinstance(entry, str):
            return None
        # Re-normalising rather than trusting the string keeps the payload this
        # node rebuilds byte-identical to the one that was signed.
        if normalize_origin(entry) != entry:
            return None
        addresses.append(entry)

    claimed_operator = str(doc.get("operator_address", "") or "").strip()

    try:
        pubkey = base64.b64decode(str(doc.get("pubkey", "")), validate=True)
        signature = base64.b64decode(str(doc.get("signature", "")), validate=True)
    except Exception:
        return None
    if len(pubkey) != 32 or len(signature) != 64:
        return None
    if node_id_from_pubkey(pubkey) != expect_node_id:
        return None

    payload = _canonical_payload(
        expect_chain_id, expect_node_id, claimed_operator, addresses, expect_nonce
    )
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(pubkey).verify(signature, payload)
    except Exception:
        return None

    return IdentityProof(
        node_id=expect_node_id,
        addresses=addresses,
        operator_address=_verify_validator_claim(doc, payload, claimed_operator),
    )


__all__ = [
    "IDENTITY_PREFIX",
    "IdentityProof",
    "build_local_identity",
    "local_addresses",
    "new_nonce",
    "node_id_from_pubkey",
    "normalize_origin",
    "valoper_from_pubkey",
    "verify_identity",
]
