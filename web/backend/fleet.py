"""Which nodes are in the fleet, and where to reach them.

Membership is a chain fact, not operator configuration: a fleet member is a
bonded validator whose moniker names a reachable site. Nobody maintains a list,
so a node that joins the active set shows up on its own and a node that dies is
gone once the chain jails it for downtime.

Being listed and being trusted with a credential are two different questions,
and answering both with "https only" was wrong. A node that serves plain http --
which is every node reached by IP, since no certificate can be issued for one --
is still a real node a visitor can open, and hiding it made /network claim the
network was two servers when it was four. So discovery keeps every node whose
moniker names somewhere reachable, and the scheme is reported rather than used
as a filter.

The credential boundary moves to the one caller that needs it. The stats fan-out
forwards the admin's signed proof, which is replayable for its lifetime, so it
may only send to a destination whose certificate proves the name it claims:
``authenticated_node_sites`` is that subset -- https, and a name rather than a
bare address -- and the send site validates again at the moment it builds the
request. Widening what gets *listed* must never widen what gets *trusted*, which
is why the two are separate functions over one cache rather than one function
with a flag.

The list is cached briefly: `/api/get_peers` is public and unauthenticated, and
resolving every moniker on every page load would turn a page view into a fan of
DNS lookups. Callers that forward the admin proof re-validate at send time
anyway, so the cache only ever decides who is asked, never where the request
actually lands.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from typing import List, Tuple

from chain import get_active_validators
from fleet_url import validate_fleet_endpoint
from logging_utils import logger

ACTIVE_SITES_TTL = 60.0

_sites_cache: List[Tuple[str, bool]] = []
_sites_cached_at: float = 0.0
_sites_lock = threading.Lock()


def _is_authenticated(endpoint) -> bool:
    """Whether the destination's certificate can prove it is the name it claims.

    Requires https, and a name rather than an address: no certificate authority
    issues for a bare IP, so pinning the handshake to one proves nothing. Both
    conditions have to hold before this node will forward the admin's proof.
    """
    if endpoint.scheme != "https":
        return False
    try:
        ipaddress.ip_address(endpoint.hostname)
    except ValueError:
        return True
    return False


def _discover_active_sites() -> List[Tuple[str, bool]]:
    """(url, authenticated) for every active node whose moniker names a host.

    IP literals are accepted here. A validator that has no domain can still be
    browsed at its address, and refusing to name it does not make it any less
    part of the network -- it only hides it. The literal must still be a global
    address, so this cannot be used to point the node at its own network.
    """
    sites: List[Tuple[str, bool]] = []
    seen: set[str] = set()
    for validator in get_active_validators():
        moniker = validator["moniker"]
        endpoint = validate_fleet_endpoint(moniker, allow_ip_literal=True)
        if endpoint is None:
            logger().debug(
                "fleet.site_skipped operator=%s moniker=%r reason=%s",
                validator["operator_address"],
                moniker,
                "unresolvable_or_not_a_host",
            )
            continue
        if endpoint.url in seen:
            continue
        seen.add(endpoint.url)
        sites.append((endpoint.url, _is_authenticated(endpoint)))
    logger().debug("fleet.sites_discovered count=%d sites=%s", len(sites), sites)
    return sorted(sites)


def _cached_sites() -> List[Tuple[str, bool]]:
    global _sites_cache, _sites_cached_at
    now = time.monotonic()
    with _sites_lock:
        if _sites_cache and now - _sites_cached_at < ACTIVE_SITES_TTL:
            return list(_sites_cache)
    sites = _discover_active_sites()
    with _sites_lock:
        _sites_cache = sites
        _sites_cached_at = now
    return list(sites)


def active_node_sites() -> List[str]:
    """Base URL of every active node, http included, for display."""
    return [url for url, _ in _cached_sites()]


def authenticated_node_sites() -> List[str]:
    """The subset whose certificate proves the name, for forwarding a credential."""
    return [url for url, authenticated in _cached_sites() if authenticated]
