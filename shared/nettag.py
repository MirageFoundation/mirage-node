"""Wire format for epoch-scoped network tags carried in the relay tx memo.

The relaying backend publishes a pseudonymous per-network tag so that any
third-party agent can cluster accounts acting from the same network without any
IP being disclosed. This module owns the format only: the encoder, the decoder
and the vocabulary. The keyed construction that produces a tag lives in
``web/backend/net_tag.py`` because it needs the secret; nothing here does, which
is why the indexer can import it.

Memo shape, namespaced under a single ``nettag`` key so other consumers can
share the field later::

    {"nettag":{"v":1,"n":"<ns>","e":"2026-W33","f":4,"t":"<tag>","c":"isp"}}

``c`` is omitted entirely when the relay had no classification data. That is a
different fact from ``"unknown"``, which means the relay classified against real
data and found no match, and conflating them would mislead every agent.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Optional

MEMO_KEY = "nettag"
MEMO_VERSION = 1

# The chain's max_memo_characters is 256 and the SDK compares it against a byte
# length. The payload is ASCII-only so characters and bytes are the same number.
MEMO_MAX_BYTES = 256

NAMESPACE_BYTES = 8
TAG_BYTES = 16

FAMILY_V4 = 4
FAMILY_V6 = 6
VALID_FAMILIES = (FAMILY_V4, FAMILY_V6)

# "unknown" means classified against real data with no keyword match. An absent
# key means the relay had no data at all.
NET_CLASSES = ("hosting", "vpn", "cellular", "isp", "unknown")

_EPOCH_RE = re.compile(r"^(\d{4})-W(\d{2})$")
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Outcomes recorded against a transaction.
STATUS_ABSENT = "absent"
STATUS_VALID = "valid"
STATUS_INVALID = "invalid"


def b64u_encode(raw: bytes) -> str:
    """Unpadded base64url. 8 bytes -> 11 chars, 16 bytes -> 22 chars."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64u_decode(text: str, expect_bytes: int) -> Optional[bytes]:
    """Strict inverse of b64u_encode. None if it is not exactly expect_bytes."""
    if not text or not _B64URL_RE.match(text):
        return None
    padded = text + "=" * (-len(text) % 4)
    try:
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        return None
    if len(raw) != expect_bytes:
        return None
    # Reject non-canonical encodings so one tag has exactly one spelling.
    if b64u_encode(raw) != text:
        return None
    return raw


def format_epoch(iso_year: int, iso_week: int) -> str:
    return f"{int(iso_year):04d}-W{int(iso_week):02d}"


def encode_memo(namespace_b64: str, epoch: str, family: int, tag_b64: str, net_class: Optional[str]) -> str:
    """Serialize the memo. Key order is fixed; separators are compact."""
    payload = {
        "v": MEMO_VERSION,
        "n": namespace_b64,
        "e": epoch,
        "f": int(family),
        "t": tag_b64,
    }
    if net_class is not None:
        payload["c"] = net_class
    memo = json.dumps({MEMO_KEY: payload}, separators=(",", ":"), ensure_ascii=True)
    encoded_len = len(memo.encode("ascii"))
    if encoded_len > MEMO_MAX_BYTES:
        raise RuntimeError(f"nettag memo is {encoded_len} bytes, over the {MEMO_MAX_BYTES} limit: {memo!r}")
    return memo


class ParsedMemo:
    """Result of reading an untrusted memo.

    ``status`` is one of absent / valid / invalid. Fields are populated only
    when status is valid. ``reason`` explains an invalid result for the log.
    """

    __slots__ = ("status", "namespace", "epoch", "family", "tag", "net_class", "reason")

    def __init__(self, status, namespace=None, epoch=None, family=None, tag=None, net_class=None, reason=None):
        self.status = status
        self.namespace = namespace
        self.epoch = epoch
        self.family = family
        self.tag = tag
        self.net_class = net_class
        self.reason = reason

    def __repr__(self):
        if self.status == STATUS_VALID:
            return f"ParsedMemo(valid, epoch={self.epoch}, family={self.family}, class={self.net_class})"
        return f"ParsedMemo({self.status}, reason={self.reason!r})"


def parse_memo(memo: Optional[str]) -> ParsedMemo:
    """Read a memo written by an arbitrary relayer.

    Every relayer controls its own memo, so this must never raise and never
    trust what came back from the JSON decoder: a caller that lets a malformed
    memo propagate hands any fee-paying relay an indexer-kill primitive.
    """
    if memo is None:
        return ParsedMemo(STATUS_ABSENT)
    text = memo.strip()
    if not text:
        return ParsedMemo(STATUS_ABSENT)

    # Bound the input before handing it to the parser, and cheaply reject the
    # overwhelming majority of memos that are not ours.
    if len(text.encode("utf-8", errors="replace")) > MEMO_MAX_BYTES:
        return ParsedMemo(STATUS_ABSENT if MEMO_KEY not in text else STATUS_INVALID, reason="memo over byte limit")
    if MEMO_KEY not in text:
        return ParsedMemo(STATUS_ABSENT)

    try:
        decoded = json.loads(text)
    except Exception as e:
        return ParsedMemo(STATUS_INVALID, reason=f"not JSON: {e}")

    if not isinstance(decoded, dict):
        return ParsedMemo(STATUS_ABSENT)
    if MEMO_KEY not in decoded:
        return ParsedMemo(STATUS_ABSENT)

    payload = decoded[MEMO_KEY]
    if not isinstance(payload, dict):
        return ParsedMemo(STATUS_INVALID, reason="nettag value is not an object")

    version = payload.get("v")
    # bool is an int subclass; reject it explicitly so True does not pass as 1.
    if isinstance(version, bool) or not isinstance(version, int):
        return ParsedMemo(STATUS_INVALID, reason=f"v is not an integer: {type(version).__name__}")
    if version != MEMO_VERSION:
        return ParsedMemo(STATUS_INVALID, reason=f"unsupported version {version}")

    namespace = payload.get("n")
    if not isinstance(namespace, str) or b64u_decode(namespace, NAMESPACE_BYTES) is None:
        return ParsedMemo(STATUS_INVALID, reason="n is not an 8-byte base64url namespace")

    epoch = payload.get("e")
    if not isinstance(epoch, str):
        return ParsedMemo(STATUS_INVALID, reason="e is not a string")
    epoch_match = _EPOCH_RE.match(epoch)
    if not epoch_match:
        return ParsedMemo(STATUS_INVALID, reason=f"e is not YYYY-Www: {epoch!r}")
    week = int(epoch_match.group(2))
    if not 1 <= week <= 53:
        return ParsedMemo(STATUS_INVALID, reason=f"ISO week out of range: {week}")

    family = payload.get("f")
    if isinstance(family, bool) or not isinstance(family, int) or family not in VALID_FAMILIES:
        return ParsedMemo(STATUS_INVALID, reason=f"f is not 4 or 6: {family!r}")

    tag = payload.get("t")
    if not isinstance(tag, str) or b64u_decode(tag, TAG_BYTES) is None:
        return ParsedMemo(STATUS_INVALID, reason="t is not a 16-byte base64url tag")

    net_class = payload.get("c")
    if net_class is not None:
        if not isinstance(net_class, str) or net_class not in NET_CLASSES:
            return ParsedMemo(STATUS_INVALID, reason=f"c is not a known class: {net_class!r}")

    return ParsedMemo(
        STATUS_VALID,
        namespace=namespace,
        epoch=epoch,
        family=family,
        tag=tag,
        net_class=net_class,
    )
