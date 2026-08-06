"""Trusted client IP extraction and hashing."""

from __future__ import annotations

import hashlib
import ipaddress
import os

from flask import request

_raw_salt = os.environ.get("CLIENT_HASH_SALT", "").strip()
if not _raw_salt:
    raise RuntimeError(
        "CLIENT_HASH_SALT is required and must be a non-empty hex string. "
        "Run deploy migration v1_32_0_ensure_client_hash_salt (or set it in backend.env)."
    )
try:
    _CLIENT_HASH_SALT = bytes.fromhex(_raw_salt)
except ValueError as e:
    raise RuntimeError(
        f"CLIENT_HASH_SALT must be a hex string (got {len(_raw_salt)} chars): {e}"
    ) from e
if len(_CLIENT_HASH_SALT) < 16:
    raise RuntimeError(
        f"CLIENT_HASH_SALT too short ({len(_CLIENT_HASH_SALT)} bytes); need at least 16"
    )


def get_trusted_client_ip() -> str | None:
    """CF-Connecting-IP (Cloudflare, not spoofable) or raw TCP peer."""
    raw_ip = str(request.headers.get("CF-Connecting-IP", "") or "").strip()
    if not raw_ip:
        raw_ip = str(request.remote_addr or "").strip()
    if not raw_ip:
        return None
    try:
        ip_obj = ipaddress.ip_address(raw_ip)
    except ValueError:
        return None
    if ip_obj.version == 6 and ip_obj.ipv4_mapped:
        return str(ip_obj.ipv4_mapped)
    if ip_obj.version == 6:
        net = ipaddress.ip_network(f"{ip_obj}/64", strict=False)
        return f"{net.network_address}/{net.prefixlen}"
    return str(ip_obj)


def hash_client_ip(ip: str | None) -> str | None:
    """One-way salted hash of client IP. Salt is stable across workers."""
    if not ip:
        return None
    return hashlib.sha256(_CLIENT_HASH_SALT + ip.encode()).hexdigest()[:32]


def hash_visitor_id(raw: str | None) -> str | None:
    """One-way salted hash of a raw analytics visitor id.

    The raw id is the trackable, Mirage-private browser/device key and must
    never be stored in the clear. Same stable salt as the IP hash; distinct
    prefix domain-separates the two so an IP hash can never collide with a
    visitor hash.
    """
    s = (raw or "").strip()
    if not s:
        return None
    return hashlib.sha256(_CLIENT_HASH_SALT + b"visitor:" + s.encode()).hexdigest()
