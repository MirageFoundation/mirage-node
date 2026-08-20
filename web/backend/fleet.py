"""Which nodes are in the fleet, and where to reach them.

Membership is a chain fact, not operator configuration: a fleet member is a
bonded validator whose moniker names an https site. Nobody maintains a list, so
a node that joins the active set shows up on its own and a node that dies is
gone once the chain jails it for downtime.

Only https. A moniker is free-form text chosen by whoever runs that validator,
so the one thing this node can insist on is a destination whose certificate
proves the name — an `http://` moniker or a bare IP is skipped rather than
contacted, because neither can be authenticated and the stats fan-out sends the
admin's signed proof to whatever comes back from here.

The list is cached briefly: `/api/get_peers` is public and unauthenticated, and
resolving every moniker on every page load would turn a page view into a fan of
DNS lookups. Callers that forward the admin proof re-validate at send time
anyway, so the cache only ever decides who is asked, never where the request
actually lands.
"""

from __future__ import annotations

import threading
import time
from typing import List

from chain import get_active_validators
from fleet_url import validate_fleet_endpoint
from logging_utils import logger

ACTIVE_SITES_TTL = 60.0

_sites_cache: List[str] = []
_sites_cached_at: float = 0.0
_sites_lock = threading.Lock()


def _discover_active_sites() -> List[str]:
    sites: List[str] = []
    seen: set[str] = set()
    for validator in get_active_validators():
        moniker = validator["moniker"]
        endpoint = validate_fleet_endpoint(moniker)
        if endpoint is None or endpoint.scheme != "https":
            logger().debug(
                "fleet.site_skipped operator=%s moniker=%r reason=%s",
                validator["operator_address"],
                moniker,
                "unresolvable_or_not_a_host" if endpoint is None else "not_https",
            )
            continue
        if endpoint.url in seen:
            continue
        seen.add(endpoint.url)
        sites.append(endpoint.url)
    logger().debug("fleet.sites_discovered count=%d sites=%s", len(sites), sites)
    return sorted(sites)


def active_node_sites() -> List[str]:
    """Base https URL of every active node, deduped and in a stable order."""
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
