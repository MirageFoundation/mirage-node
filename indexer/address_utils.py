"""
Address derivation utilities for the indexer.
"""

import base64
import hashlib
from hashlib import sha256


def bech32_polymod(values):
    generator = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = (chk >> 25) & 0xFF
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            if ((b >> i) & 1) != 0:
                chk ^= generator[i]
    return chk


def bech32_hrp_expand(hrp: str):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def bech32_create_checksum(hrp: str, data):
    values = bech32_hrp_expand(hrp) + data
    polymod = bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def addr_from_pubkey(pubkey_bytes: bytes, hrp: str = "mirage") -> str:
    if not pubkey_bytes or len(pubkey_bytes) != 33:
        return ""
    h = sha256(pubkey_bytes).digest()
    try:
        ripemd = hashlib.new("ripemd160")
    except Exception:
        return ""
    ripemd.update(h)
    digest20 = ripemd.digest()
    data5 = convertbits(digest20, 8, 5)
    if not data5:
        return ""
    return bech32_encode(hrp, data5)


def bech32_encode(hrp: str, data):
    CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    combined = data + bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join([CHARSET[d] for d in combined])


def convertbits(data: bytes, frombits: int, tobits: int, pad: bool = True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for b in data:
        acc = (acc << frombits) | b
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def module_address(name: str, hrp: str = "mirage") -> str:
    """Bech32 account address of a cosmos module.

    authtypes.NewModuleAddress hashes the module name with SHA-256 and keeps the
    first 20 bytes. Derived rather than hardcoded because the core module is the
    sender on every mint payout: a stale constant would not error, it would
    silently attribute zero earnings.
    """
    digest = hashlib.sha256(name.encode("utf-8")).digest()[:20]
    return bech32_encode(hrp, convertbits(digest, 8, 5))


def derive_owner_from_msg(msg_dict: dict) -> str:
    pub_b64 = msg_dict.get("envelope_pubkey")
    if not pub_b64:
        raise RuntimeError("Missing envelope_pubkey in message")
    pub = base64.b64decode(pub_b64)
    addr = addr_from_pubkey(pub)
    if not addr:
        raise RuntimeError(f"Failed to derive address from pubkey: {pub_b64[:20]}...")
    return addr


def derive_owner_from_dict(msg_dict: dict) -> str:
    """
    Derive the acting user from a message dict, matching derive_owner_from_msg semantics.
    IMPORTANT:
    - Meta-signed user messages do NOT set authority/owner; only envelope_pubkey is trustworthy.
    - Governance/node relays set authority to the module account (or node), so never assume it is the user.
    - The envelope signer wins over any explicit owner field, because owner is unsigned message
      content that a relayer can set freely. Only fall back to owner, then authority, when the
      message carries no envelope at all.
    """
    pub_b64 = msg_dict.get("envelope_pubkey")
    if pub_b64:
        pb = base64.b64decode(str(pub_b64))
        addr = addr_from_pubkey(pb)
        if not addr:
            raise RuntimeError(f"Failed to derive address from envelope_pubkey: {str(pub_b64)[:20]}...")
        return addr

    owner = (msg_dict.get("owner") or "").strip().lower()
    if owner:
        return owner

    authority = (msg_dict.get("authority") or "").strip().lower()
    if authority:
        return authority

    raise RuntimeError("Missing owner, envelope_pubkey, and authority in message dict")
