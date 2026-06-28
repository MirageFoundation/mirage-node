#!/usr/bin/env python3
"""Generate Caddy's trusted-proxy config for the edge in front of this node.

Caddy needs to know which upstream IPs are allowed to set the real-client-IP
header, and which header to read, so that {client_ip} (used for rate limiting,
logging, and abuse handling) is the real visitor and not the CDN edge.

This is driven by EDGE_PROVIDER so the same image works whether a node sits
behind Cloudflare (today) or Bunny (after the cutover), with no per-node
hand-edited Caddyfile:

  EDGE_PROVIDER=cloudflare (default)  -> trust Cloudflare (dynamic plugin),
                                          read CF-Connecting-IP. Identical to
                                          the prior hard-coded behavior.
  EDGE_PROVIDER=bunny                 -> trust Bunny edge ranges (fetched),
                                          read X-Real-IP.
  EDGE_PROVIDER=both                  -> trust Cloudflare + Bunny ranges,
                                          read CF-Connecting-IP then X-Real-IP.
                                          Use during the transition window.

Output is written as a Caddy snippet file that the Caddyfile imports inside its
global `servers { }` block:  import trusted-proxies.caddy

It is resilient: on a fetch failure it keeps the existing file if present, so a
transient network blip at startup never produces a broken Caddy config.

Run at container startup (before Caddy starts) and periodically. Bunny edge IPs
change rarely, so a refresh per container start plus a daily refresh is enough.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

CADDY_DIR = Path(os.environ.get("CADDY_DIR", "/etc/caddy"))
OUT_FILE = CADDY_DIR / "trusted-proxies.caddy"
BUNNY_IPS_FILE = CADDY_DIR / "bunny-ips.txt"  # plain list, also used by the host firewall

BUNNY_IPV4_URL = "https://api.bunny.net/system/edgeserverlist"
BUNNY_IPV6_URL = "https://api.bunny.net/system/edgeserverlist/ipv6"
CLOUDFLARE_IPV4_URL = "https://www.cloudflare.com/ips-v4"
CLOUDFLARE_IPV6_URL = "https://www.cloudflare.com/ips-v6"

CLOUDFLARE_SNIPPET = """\
# EDGE_PROVIDER=cloudflare — trust Cloudflare edge (auto-updated via plugin).
trusted_proxies cloudflare {
\tinterval 12h
\ttimeout 15s
}
client_ip_headers CF-Connecting-IP
"""


def _log(msg: str) -> None:
    print(f"[refresh_edge_ips] {msg}", flush=True)


def _fetch(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "mirage-node/refresh-edge-ips"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted URLs)
        return resp.read().decode("utf-8", "replace")


def _fetch_bunny() -> list[str]:
    """Return Bunny edge IPv4 + IPv6 (JSON arrays of bare IPs)."""
    ips: list[str] = []
    for url in (BUNNY_IPV4_URL, BUNNY_IPV6_URL):
        try:
            data = json.loads(_fetch(url))
            if isinstance(data, list):
                ips.extend(str(x).strip() for x in data if str(x).strip())
        except Exception as e:  # noqa: BLE001
            _log(f"WARN: failed to fetch {url}: {e}")
    return ips


def _fetch_cloudflare() -> list[str]:
    """Return Cloudflare IPv4 + IPv6 CIDRs (newline-delimited text)."""
    cidrs: list[str] = []
    for url in (CLOUDFLARE_IPV4_URL, CLOUDFLARE_IPV6_URL):
        try:
            cidrs.extend(line.strip() for line in _fetch(url).splitlines() if line.strip())
        except Exception as e:  # noqa: BLE001
            _log(f"WARN: failed to fetch {url}: {e}")
    return cidrs


def _static_snippet(ranges: list[str], headers: str, label: str) -> str:
    # De-dupe, keep order stable for diff-friendliness.
    seen: set[str] = set()
    uniq = [r for r in ranges if not (r in seen or seen.add(r))]
    joined = " ".join(uniq)
    return (
        f"# EDGE_PROVIDER={label} — trust fetched edge ranges ({len(uniq)} entries).\n"
        f"trusted_proxies static {joined}\n"
        f"client_ip_headers {headers}\n"
    )


def _write_if_changed(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() == content:
        _log(f"{path} already up to date")
        return False
    path.write_text(content)
    _log(f"wrote {path}")
    return True


def _reload_caddy() -> None:
    """Best-effort hot reload; ignored if Caddy isn't running yet (startup)."""
    caddyfile = CADDY_DIR / "Caddyfile"
    if not caddyfile.exists():
        return
    try:
        r = subprocess.run(
            ["caddy", "reload", "--config", str(caddyfile), "--adapter", "caddyfile"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            _log("caddy reloaded")
        else:
            _log(f"caddy reload skipped/failed (likely not running yet): {r.stderr.strip()[:200]}")
    except Exception as e:  # noqa: BLE001
        _log(f"caddy reload skipped: {e}")


def main() -> int:
    provider = os.environ.get("EDGE_PROVIDER", "cloudflare").strip().lower() or "cloudflare"
    if provider not in ("cloudflare", "bunny", "both"):
        _log(f"unknown EDGE_PROVIDER={provider!r}; falling back to cloudflare")
        provider = "cloudflare"

    if provider == "cloudflare":
        changed = _write_if_changed(OUT_FILE, CLOUDFLARE_SNIPPET)
        if changed:
            _reload_caddy()
        return 0

    # bunny / both: build a static list from fetched ranges.
    ranges: list[str] = []
    headers = "X-Real-IP"
    if provider == "both":
        ranges.extend(_fetch_cloudflare())
        headers = "CF-Connecting-IP X-Real-IP"
    bunny = _fetch_bunny()
    ranges.extend(bunny)

    if bunny:
        # Persist a plain list for the host-side origin firewall to consume.
        _write_if_changed(BUNNY_IPS_FILE, "\n".join(bunny) + "\n")

    if not ranges:
        if OUT_FILE.exists():
            _log("fetch produced no ranges; keeping existing trusted-proxies.caddy")
            return 0
        # No prior config and nothing fetched: write a safe minimal snippet so
        # Caddy can still start. Without trusted_proxies, headers are ignored and
        # {client_ip} falls back to the direct peer (no spoofing risk).
        _log("WARN: no ranges fetched and no existing file; writing header-only fallback")
        _write_if_changed(OUT_FILE, f"client_ip_headers {headers}\n")
        return 1

    if _write_if_changed(OUT_FILE, _static_snippet(ranges, headers, provider)):
        _reload_caddy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
