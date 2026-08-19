#!/usr/bin/env python3
"""Report the configured domain, DNS match, and HTTPS health."""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import requests

NODE_ENV = Path.home() / ".mirage" / "env" / "node.env"


def read_domain() -> str:
    if not NODE_ENV.is_file():
        raise SystemExit("ERROR: node.env is missing")
    matches = []
    for line in NODE_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("DOMAIN="):
            matches.append(line.split("=", 1)[1].strip().strip("\"'"))
    if len(matches) > 1:
        raise SystemExit("ERROR: duplicate DOMAIN entries in node.env")
    return matches[0] if matches else ""


def public_ip() -> str:
    resp = requests.get("https://api.ipify.org", timeout=10)
    resp.raise_for_status()
    return resp.text.strip()


def resolve_a(name: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as e:
        print(f"DNS:     lookup failed ({e})")
        return []
    addrs = sorted({item[4][0] for item in infos})
    return addrs


def main() -> int:
    domain = read_domain()
    if not domain:
        print("Domain:  (none) — node is in IP/HTTP mode")
        return 0
    print(f"Domain:  {domain}")
    ip = public_ip()
    print(f"Public:  {ip}")
    addrs = resolve_a(domain)
    if not addrs:
        return 1
    print(f"DNS A:   {', '.join(addrs)}")
    if ip not in addrs:
        print("ERROR: DNS does not match this host's public IP")
        return 1
    print("DNS:     matches this host")
    url = f"https://{domain}/api/get_node_config"
    try:
        resp = requests.get(url, timeout=10)
    except Exception as e:
        print(f"HTTPS:   request failed: {e}")
        return 1
    print(f"HTTPS:   HTTP {resp.status_code}")
    if resp.status_code >= 400:
        return 1
    result = subprocess.run(
        ["openssl", "s_client", "-connect", f"{domain}:443", "-servername", domain],
        input=b"",
        capture_output=True,
        timeout=15,
        check=False,
    )
    text = (result.stdout or b"").decode("utf-8", errors="replace")
    if "Verify return code: 0 (ok)" in text:
        print("Cert:    valid")
        return 0
    print("ERROR: TLS certificate is not valid")
    return 1


if __name__ == "__main__":
    sys.exit(main())
