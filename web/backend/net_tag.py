"""Epoch-scoped network tag for relayed transactions.

    tag = HMAC-SHA256(SECRET, canonical(domain, iso_year, iso_week, family, ip))[:16]

A keyed MAC rather than a salted hash because IPv4 has only 2^32 values: any
publicly evaluable function of an address is invertible by enumeration in
minutes, so a published salt is equivalent to publishing the address. Without
the key a tag cannot be evaluated at all.

The key's scope is a trust domain, and it may be shared exactly as far as the
parties already trusted with the raw client IPs and no further. Whoever holds it
can evaluate the HMAC offline over the whole IPv4 space and rebuild the phone
book the secret exists to prevent. The official frontends share one value so a
tag matches whichever door a user comes through; an independent operator
generates their own and never receives ours.

The epoch is an input rather than a rotating secret: same privacy property with
no distribution ceremony, no window where nodes disagree, and every node derives
the same epoch by construction. Weekly, because farms raid in hours, so the
window costs almost no detection power while capping how much linkage history
accumulates in public.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import os
import struct
from datetime import datetime, timezone
from typing import Optional, Tuple

from flask import g, has_request_context

from asn_db import classify_ip
from client_ip import get_trusted_client_ip
from shared.nettag import (
    NAMESPACE_BYTES,
    TAG_BYTES,
    b64u_encode,
    encode_memo,
    format_epoch,
)

_log = logging.getLogger("net_tag")

_TAG_DOMAIN = b"nettag:v1"
_NAMESPACE_DOMAIN = b"nettag-namespace:v1"
_MIN_KEY_BYTES = 32

_raw_key = os.environ.get("NET_TAG_HMAC_KEY", "").strip()
if not _raw_key:
    raise RuntimeError(
        "NET_TAG_HMAC_KEY is required and must be a non-empty hex string. "
        "Run deploy migration v1_36_1_ensure_net_tag_key (or set it in backend.env)."
    )
try:
    _NET_TAG_KEY = bytes.fromhex(_raw_key)
except ValueError as e:
    raise RuntimeError(f"NET_TAG_HMAC_KEY must be a hex string (got {len(_raw_key)} chars): {e}") from e
if len(_NET_TAG_KEY) < _MIN_KEY_BYTES:
    raise RuntimeError(
        f"NET_TAG_HMAC_KEY too short ({len(_NET_TAG_KEY)} bytes); need at least {_MIN_KEY_BYTES}"
    )

# Stable across epochs and safe to publish. It lets an agent tell which tags are
# even comparable, since tags from different trust domains never match. It is
# NOT proof of domain membership: a malicious relay can copy any public
# namespace, so agents must scope comparisons to relayers they trust.
_NAMESPACE_B64 = b64u_encode(
    hmac.new(_NET_TAG_KEY, _NAMESPACE_DOMAIN, hashlib.sha256).digest()[:NAMESPACE_BYTES]
)

_G_CACHE_ATTR = "_net_tag_memo"


def namespace() -> str:
    return _NAMESPACE_B64


def _canonical(iso_year: int, iso_week: int, family: int, packed_ip: bytes) -> bytes:
    """Unambiguous fixed encoding of the HMAC input.

    Length-prefixed rather than concatenated so no two different inputs can
    produce the same byte string.
    """
    return b"".join(
        (
            struct.pack("!B", len(_TAG_DOMAIN)),
            _TAG_DOMAIN,
            struct.pack("!HBB", iso_year, iso_week, family),
            struct.pack("!B", len(packed_ip)),
            packed_ip,
        )
    )


def parse_client_ip(ip_str: Optional[str]) -> Optional[Tuple[int, bytes]]:
    """(family, packed network bytes) from a trusted client IP.

    IPv4 is used exactly. IPv6 is already bucketed to /64 by
    get_trusted_client_ip, which is per-subscriber and unaffected by RFC 4941
    privacy extensions since those rotate the interface identifier, not the
    prefix. Only the 8 prefix bytes go into the MAC.
    """
    text = (ip_str or "").strip()
    if not text:
        return None
    try:
        if "/" in text:
            network = ipaddress.ip_network(text, strict=False)
            if network.version != 6:
                return None
            return 6, network.network_address.packed[:8]
        address = ipaddress.ip_address(text)
    except ValueError:
        return None
    if address.version == 4:
        return 4, address.packed
    return 6, ipaddress.ip_network(f"{address}/64", strict=False).network_address.packed[:8]


def current_epoch() -> Tuple[int, int]:
    """ISO year and ISO week, both from one isocalendar() call.

    Pairing a calendar year with an ISO week is a bug: late December can be ISO
    week 1 of the following year.
    """
    iso = datetime.now(timezone.utc).isocalendar()
    return int(iso[0]), int(iso[1])


def compute_tag(family: int, packed_ip: bytes, iso_year: int, iso_week: int) -> bytes:
    return hmac.new(
        _NET_TAG_KEY, _canonical(iso_year, iso_week, family, packed_ip), hashlib.sha256
    ).digest()[:TAG_BYTES]


def build_memo(ip_str: Optional[str]) -> str:
    """Memo for one client address. Empty string when there is nothing to say."""
    parsed = parse_client_ip(ip_str)
    if parsed is None:
        return ""
    family, packed_ip = parsed
    iso_year, iso_week = current_epoch()
    tag = compute_tag(family, packed_ip, iso_year, iso_week)
    return encode_memo(
        namespace_b64=_NAMESPACE_B64,
        epoch=format_epoch(iso_year, iso_week),
        family=family,
        tag_b64=b64u_encode(tag),
        net_class=classify_ip(ip_str),
    )


def request_memo() -> str:
    """Memo for the in-flight request, computed once and cached.

    The cache is a correctness requirement, not an optimization. Each relay
    route builds the transaction up to four times — the gas estimator's size
    probe, the transaction handed to simulate, the broadcast, and a rebuild on
    an unordered-nonce collision — and all of them must be byte-identical or the
    simulated transaction differs in size from the broadcast one. Recomputing
    would let an ISO-week rollover or an ASN dataset refresh land mid-request.

    Returns "" outside a request context, so reward payouts stay untagged.
    """
    if not has_request_context():
        return ""
    cached = getattr(g, _G_CACHE_ATTR, None)
    if cached is not None:
        return cached
    memo = build_memo(get_trusted_client_ip())
    setattr(g, _G_CACHE_ATTR, memo)
    if memo:
        _log.debug("net_tag.memo built len=%d", len(memo))
    else:
        _log.debug("net_tag.memo omitted (no trusted client IP)")
    return memo
