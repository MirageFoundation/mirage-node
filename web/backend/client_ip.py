"""Trusted client IP extraction and hashing."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import secrets

from flask import request

_log = logging.getLogger(__name__)

_raw_salt = os.environ.get("CLIENT_HASH_SALT", "").strip()
if not _raw_salt:
    _raw_salt = secrets.token_hex(32)
    os.environ["CLIENT_HASH_SALT"] = _raw_salt
    _log.warning("CLIENT_HASH_SALT missing; generated new salt")
    env_dir = os.environ.get("ENV_DIR", "").strip()
    if env_dir:
        try:
            env_path = os.path.join(env_dir, "backend.env")
            if os.path.isfile(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                updated = False
                for i, line in enumerate(lines):
                    if line.startswith("CLIENT_HASH_SALT="):
                        lines[i] = f"CLIENT_HASH_SALT={_raw_salt}\n"
                        updated = True
                        break
                if not updated:
                    lines.append(f"\nCLIENT_HASH_SALT={_raw_salt}\n")
                with open(env_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
        except Exception as e:
            _log.warning("Failed to persist CLIENT_HASH_SALT: %s", e)

try:
    _CLIENT_HASH_SALT = bytes.fromhex(_raw_salt)
except ValueError:
    _raw_salt = secrets.token_hex(32)
    os.environ["CLIENT_HASH_SALT"] = _raw_salt
    _CLIENT_HASH_SALT = bytes.fromhex(_raw_salt)
    _log.warning("CLIENT_HASH_SALT invalid; generated new salt")


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
