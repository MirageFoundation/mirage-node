"""Classify an autonomous system's org description into a network class.

Used by deploy/refresh_asn_db.py to bake a class byte into the range files, and
by scripts/user_analysis.py for operator-side log analysis, so the vocabulary
lives in exactly one place.

Honest limits. This is keyword matching over a self-described org string. It
cannot detect residential proxies at all, and it cannot tell a home line from a
business line on the same access network. "isp" is therefore a weak negative
signal — "nothing here looked like hosting, a VPN or a carrier" — and never a
clean bill of health.
"""

from __future__ import annotations

# Checked first: a commercial VPN or proxy exit is the strongest signal that the
# address does not correspond to where the person actually is.
VPN_KEYWORDS = (
    "vpn",
    "proxy",
    "nordvpn",
    "expressvpn",
    "surfshark",
    "mullvad",
    "private internet",
    "cyberghost",
    "protonvpn",
    "torguard",
    "ipvanish",
    "purevpn",
    "windscribe",
    "tunnelbear",
)

# Checked before hosting: carriers often carry generic infrastructure words in
# their org names, and calling a carrier "hosting" is the more damaging error.
# It would make an ordinary CGNAT cluster look like a deliberate farm.
CELLULAR_KEYWORDS = (
    "mobile",
    "mobil",
    "cellular",
    "celular",
    "wireless",
    "gsm",
    "umts",
    "telecom mobile",
    "movil",
)

HOSTING_KEYWORDS = (
    "hosting",
    "datacenter",
    "data center",
    "dedicated server",
    "colocation",
    "colo ",
    "cloud",
    "digitalocean",
    "linode",
    "vultr",
    "hetzner",
    "ovh",
    "scaleway",
    "amazon",
    "aws",
    "google",
    "microsoft",
    "azure",
    "oracle",
    "alibaba",
    "tencent",
    "akamai",
    "cloudflare",
    "fastly",
    "leaseweb",
    "choopa",
    "contabo",
    "netcup",
    "hostinger",
    "godaddy",
    "namecheap",
    "servers",
    "vps",
)

CLASS_VPN = "vpn"
CLASS_CELLULAR = "cellular"
CLASS_HOSTING = "hosting"
CLASS_ISP = "isp"


def classify_org(org: str) -> str:
    """Network class for an AS org description.

    Returns one of vpn / cellular / hosting / isp. Never "unknown": that value
    is reserved for an address that falls outside every known range, which is a
    different fact from an org string that matched no keyword.
    """
    text = (org or "").lower()
    if not text:
        return CLASS_ISP
    if any(kw in text for kw in VPN_KEYWORDS):
        return CLASS_VPN
    if any(kw in text for kw in CELLULAR_KEYWORDS):
        return CLASS_CELLULAR
    if any(kw in text for kw in HOSTING_KEYWORDS):
        return CLASS_HOSTING
    return CLASS_ISP


def is_suspicious_org(org: str) -> bool:
    """True for hosting or VPN networks, the two that warrant a closer look."""
    return classify_org(org) in (CLASS_VPN, CLASS_HOSTING)
