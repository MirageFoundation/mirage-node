"""Which nodes are in the fleet, where to reach them, and which addresses proved it.

Membership is a chain fact, not operator configuration: a fleet member is a
bonded validator. Nobody maintains a list, so a node that joins the active set
shows up on its own and a node that dies is gone once the chain jails it.

Finding a member's *address* is the harder half, and reading it off the moniker
alone was never enough. The moniker is free text, so an operator who wrote a
nickname had published no address and dropped off /network entirely even while
signing every block -- and an operator who wrote a domain was believed without
anything checking that the domain agreed. Two sources answer that now:

- the moniker, when it names a host. The validator itself put it on chain, so
  the claim costs a signed transaction and a bonded stake.
- the address a node is actually peered from, taken from this node's own P2P
  connections. This is what makes an operator who chose a nickname visible: it
  needs nothing published, and the address is the TCP peer, not a claim.

A peer address is only a hint that something is there, so it is listed only once
a challenge proves a bonded validator is answering at it (see `node_identity`).
A moniker is chain-attested and stays listed on its own, with the same challenge
deciding whether the entry is marked confirmed. So the page shows every node
that is genuinely reachable, and says which of those addresses were proved to
belong to the validator that named them, rather than presenting both alike.

Being listed and being trusted with a credential remain separate questions. The
stats fan-out forwards the admin's signed proof, which is replayable for its
lifetime, so it may only send where a certificate proves the name claimed:
``authenticated_node_sites`` is that subset -- https, and a name rather than a
bare address. Widening what gets *listed* must never widen what gets *trusted*,
which is why these are separate functions over one cache.

The cache is why probing every candidate is affordable. `/api/get_peers` is
public and unauthenticated, and a page view must not become a fan of outbound
requests, so a good answer is held for hours and a failure is retried in
minutes. Callers that forward the admin proof re-validate at send time anyway,
so the cache only ever decides who is asked, never where a request lands.
"""

from __future__ import annotations

import ipaddress
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Optional

from chain import get_active_validators, get_connected_peers
from fleet_url import get_json, validate_fleet_endpoint
from logging_utils import logger
from node_identity import announced_site, new_nonce, verify_identity

# A confirmed address is a durable fact -- it changes when an operator moves a
# node, not between page views. A failure is not durable, so it is retried on a
# much shorter leash without turning the page into a probe loop.
ACTIVE_SITES_TTL = 6 * 3600.0
ACTIVE_SITES_FAILURE_TTL = 300.0

# Probes run concurrently against a handful of hosts. The timeout is what bounds
# the first uncached request, and an unreachable node must not hold the page.
PROBE_TIMEOUT = 3.0
PROBE_WORKERS = 8


@dataclass(frozen=True)
class NodeSite:
    """A node a visitor can open, and what is actually known about it."""

    url: str
    operator_address: str
    verified: bool

    @property
    def authenticated(self) -> bool:
        """Whether the destination's certificate can prove it is the name it claims.

        Requires https, and a name rather than an address: no certificate
        authority issues for a bare IP, so pinning the handshake to one proves
        nothing. Both conditions have to hold before this node forwards the
        admin's proof.
        """
        if not self.url.startswith("https://"):
            return False
        host = self.url[len("https://") :].split(":")[0].strip("[]")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return True
        return False


_sites_cache: List[NodeSite] = []
_sites_cached_at: float = 0.0
_sites_cache_ttl: float = 0.0
_sites_lock = threading.Lock()


def _local_operator() -> str:
    """This node's own validator operator address."""
    from node import require_runtime

    return require_runtime().validator_operator_address


def _probe(url: str) -> Optional[str]:
    """Challenge the node at `url`; return the operator address it proved, or None.

    The nonce and the origin are both chosen here and both signed, so a reply
    captured from another node, or from this one earlier, does not verify.
    """
    endpoint = validate_fleet_endpoint(url, allow_ip_literal=True)
    if endpoint is None or endpoint.url != url:
        return None

    from node import require_runtime

    nonce = new_nonce()
    doc = get_json(endpoint, "/api/node_identity", {"origin": url, "nonce": nonce}, PROBE_TIMEOUT)
    if doc is None:
        return None

    operator = verify_identity(
        doc,
        expect_origin=url,
        expect_nonce=nonce,
        expect_chain_id=require_runtime().chain_id,
    )
    if operator is None:
        logger().debug("fleet.probe_unverified url=%s", url)
        return None
    logger().debug("fleet.probe_verified url=%s operator=%s site=%s", url, operator, announced_site(doc))
    return operator


def _moniker_candidates(validators: List[Dict[str, str]]) -> Dict[str, str]:
    """url -> operator address, for every moniker that names a host.

    IP literals are accepted. A validator with no domain can still be browsed at
    its address, and refusing to name it does not make it any less part of the
    network -- it only hides it. The literal must still be a global address, so
    this cannot point the node at its own network.
    """
    out: Dict[str, str] = {}
    for validator in validators:
        moniker = validator["moniker"]
        endpoint = validate_fleet_endpoint(moniker, allow_ip_literal=True)
        if endpoint is None:
            logger().debug(
                "fleet.moniker_names_nowhere operator=%s moniker=%r",
                validator["operator_address"],
                moniker,
            )
            continue
        out.setdefault(endpoint.url, validator["operator_address"])
    return out


def _peer_candidates(exclude: set) -> List[str]:
    """`http://<ip>` for every peer this node is connected to, minus known addresses.

    Plain http on purpose: a node with no domain holds no certificate, and this
    source exists precisely for the operator who published nothing. A node that
    does have a domain answers :80 with a redirect, the probe declines to follow
    it, and the node is listed from its moniker instead.
    """
    out: List[str] = []
    for peer in get_connected_peers():
        ip = peer["ip"]
        if not ip:
            continue
        try:
            if not ipaddress.ip_address(ip).is_global:
                continue
        except ValueError:
            continue
        url = f"http://{ip}"
        if url in exclude or url in out:
            continue
        out.append(url)
    return out


def _discover_active_sites() -> List[NodeSite]:
    validators = get_active_validators()
    bonded = {v["operator_address"] for v in validators if v["operator_address"]}
    local_operator = _local_operator()

    from_moniker = _moniker_candidates(validators)
    from_peers = _peer_candidates(set(from_moniker))

    # This node's own entry is settled without a request. Asking itself would be
    # a loopback through the public URL served by the very worker pool handling
    # the page, so a burst of cold requests could starve the workers of the
    # capacity needed to answer their own probes.
    candidates = [url for url, operator in from_moniker.items() if operator != local_operator] + from_peers

    proved: Dict[str, Optional[str]] = {
        url: local_operator for url, operator in from_moniker.items() if operator == local_operator
    }
    if candidates:
        with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
            proved.update(zip(candidates, pool.map(_probe, candidates)))

    sites: List[NodeSite] = []
    listed: set = set()

    for url, operator in from_moniker.items():
        confirmed = proved.get(url) == operator and operator in bonded
        sites.append(NodeSite(url=url, operator_address=operator, verified=confirmed))
        listed.add(operator)

    for url in from_peers:
        operator = proved.get(url)
        # An address nobody published is listed only on proof, and only for a
        # validator that published none -- an operator who did name an address is
        # represented by the one they chose, confirmed or not, rather than being
        # shown twice or having a transient failure swap it for a bare IP.
        if not operator or operator not in bonded or operator in listed:
            continue
        sites.append(NodeSite(url=url, operator_address=operator, verified=True))
        listed.add(operator)

    sites.sort(key=lambda s: s.url)
    logger().debug(
        "fleet.sites_discovered count=%d verified=%d sites=%s",
        len(sites),
        sum(1 for s in sites if s.verified),
        [(s.url, s.verified) for s in sites],
    )
    return sites


def _cached_sites() -> List[NodeSite]:
    global _sites_cache, _sites_cached_at, _sites_cache_ttl
    now = time.monotonic()
    with _sites_lock:
        if _sites_cache and now - _sites_cached_at < _sites_cache_ttl:
            return list(_sites_cache)
    sites = _discover_active_sites()
    with _sites_lock:
        _sites_cache = sites
        _sites_cached_at = now
        _sites_cache_ttl = ACTIVE_SITES_TTL if all(s.verified for s in sites) else ACTIVE_SITES_FAILURE_TTL
    return list(sites)


def active_node_entries() -> List[NodeSite]:
    """Every active node a visitor can open, with whether its address was proved."""
    return _cached_sites()


def active_node_sites() -> List[str]:
    """Base URL of every active node, http included, for display."""
    return [site.url for site in _cached_sites()]


def authenticated_node_sites() -> List[str]:
    """The subset whose certificate proves the name, for forwarding a credential."""
    return [site.url for site in _cached_sites() if site.authenticated]
