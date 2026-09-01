"""Which nodes the network runs on, where to reach them, and which addresses proved it.

Membership comes from this node's own P2P connections. Every peer arrives with
an IP and a node ID that the CometBFT handshake already authenticated, so the
list needs nothing published and nothing maintained: a node that joins shows up
on its own, and one that dies drops out when the connection does. This is what
makes an operator who chose a nickname visible at all -- the previous source was
the on-chain moniker, so a validator that wrote anything other than a URL had
published no address and vanished from /network while signing every block.

An IP is enough to *list* a node and never enough to *reach* one: no certificate
authority issues for a bare address, so an app pointed at `http://<ip>` has no
way to tell it is still talking to the same machine, and both mobile platforms
block cleartext by default. Reaching a node means having a name, and a name is
worth nothing unless something ties it to the node that claimed it. That is what
`node_identity` settles: an address is reported as reachable only after whoever
answers there signs a challenge with the p2p key behind the node ID we are
already connected to. Anything unproved is still listed -- with its IP, and its
moniker as written -- it simply is not offered as a destination.

Listing and trusting stay separate questions, and they now rest on separate
proofs. The stats fan-out forwards the admin's signed proof, which is replayable
for its lifetime, so it may only send where two things hold at once: a
certificate can prove the name (https, and a name rather than an address), and
the validator signature in the same document proves a *bonded* operator is
behind it. Being reachable is about a node ID, which anyone can have; being
trusted is about stake. `authenticated_node_sites` is that narrower subset.

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
from typing import Dict, List, Optional, Tuple

from chain import get_active_validators, get_connected_peers
from fleet_url import get_json, validate_fleet_endpoint
from logging_utils import logger
from node_identity import IdentityProof, local_addresses, new_nonce, verify_identity

# A confirmed address is a durable fact -- it changes when an operator moves a
# node, not between page views. A failure is not durable, so it is retried on a
# much shorter leash without turning the page into a probe loop.
ACTIVE_SITES_TTL = 6 * 3600.0
ACTIVE_SITES_FAILURE_TTL = 300.0

# Probes run concurrently across peers. The timeout is what bounds the first
# uncached request, and an unreachable node must not hold the page.
PROBE_TIMEOUT = 3.0
PROBE_WORKERS = 8


@dataclass(frozen=True)
class NetworkNode:
    """A node on the network, and what is actually known about it."""

    node_id: str
    ip: str
    moniker: str
    api_base: str
    operator_address: str
    is_self: bool = False

    @property
    def reachable(self) -> bool:
        """Whether an app can be pointed at this node."""
        return bool(self.api_base)

    @property
    def authenticated(self) -> bool:
        """Whether the destination's certificate can prove it is the name it claims.

        Requires https, and a name rather than an address: no certificate
        authority issues for a bare IP, so pinning the handshake to one proves
        nothing.
        """
        if not self.api_base.startswith("https://"):
            return False
        host = self.api_base[len("https://") :].split(":")[0].strip("[]")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return True
        return False

    @property
    def display_name(self) -> str:
        """What to call this node: its moniker if it set one, else its address."""
        return self.moniker or self.api_base or (f"http://{self.ip}" if self.ip else self.node_id)


_nodes_cache: List[NetworkNode] = []
_nodes_cached_at: float = 0.0
_nodes_cache_ttl: float = 0.0
_nodes_lock = threading.Lock()


def _probe(url: str, expect_node_id: str) -> Optional[IdentityProof]:
    """Challenge whoever answers at `url`; return what they proved, or None.

    The nonce is chosen here and signed there, so a reply captured from this
    node earlier does not verify. `expect_node_id` comes from the caller's peer
    table, which is what stops the answer of a relayed challenge from counting.
    """
    endpoint = validate_fleet_endpoint(url, allow_ip_literal=True)
    if endpoint is None or endpoint.url != url:
        return None

    from node import require_runtime

    nonce = new_nonce()
    doc = get_json(endpoint, "/api/node_identity", {"nonce": nonce}, PROBE_TIMEOUT)
    if doc is None:
        return None

    proof = verify_identity(
        doc,
        expect_nonce=nonce,
        expect_chain_id=require_runtime().chain_id,
        expect_node_id=expect_node_id,
    )
    if proof is None:
        logger().debug("fleet.probe_unverified url=%s node_id=%s", url, expect_node_id)
        return None
    logger().debug(
        "fleet.probe_verified url=%s node_id=%s operator=%s declared=%s",
        url,
        expect_node_id,
        proof.operator_address or "-",
        proof.addresses,
    )
    return proof


def _rank(url: str) -> int:
    """How good a destination a proved URL is. Lower is better.

    An https name is the only thing a client can authenticate on its own, so it
    outranks everything. A bare address still works for a node that has no
    domain, and beats having nowhere to send anyone.
    """
    if not url.startswith("https://"):
        return 3
    host = url[len("https://") :].split(":")[0].strip("[]")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return 0
    return 1


def _candidate_urls(peer: Dict[str, str]) -> List[str]:
    """Where to look for a peer, best first.

    The moniker is tried before the address because an operator who wrote one is
    naming where they want to be reached. The address needs nothing published,
    which is the whole point of it -- but plain http, since a node with no domain
    holds no certificate.
    """
    out: List[str] = []
    endpoint = validate_fleet_endpoint(peer["moniker"], allow_ip_literal=True)
    if endpoint is not None:
        out.append(endpoint.url)

    ip = peer["ip"]
    if ip:
        try:
            if ipaddress.ip_address(ip).is_global:
                url = f"http://[{ip}]" if ipaddress.ip_address(ip).version == 6 else f"http://{ip}"
                if url not in out:
                    out.append(url)
        except ValueError:
            pass
    return out


def _resolve_peer(peer: Dict[str, str]) -> NetworkNode:
    """Probe a peer's candidate addresses and settle on the best proved one."""
    node_id = peer["node_id"]
    base = NetworkNode(
        node_id=node_id,
        ip=peer["ip"],
        moniker=peer["moniker"],
        api_base="",
        operator_address="",
    )
    if not node_id:
        # Nothing to check an answer against, so nothing here can be proved. The
        # node is still listed from its IP.
        logger().debug("fleet.peer_without_node_id ip=%s", peer["ip"])
        return base

    proved: List[Tuple[str, IdentityProof]] = []
    tried: set = set()

    def run(urls: List[str]) -> None:
        for url in urls:
            # An authenticated https name is the best a destination can be, so
            # once one answers there is nothing left to look for. Without this a
            # node that names its domain is still dialled a second time at its
            # bare address on every cache miss, for an answer that could not win.
            if any(_rank(url_) == 0 for url_, _ in proved):
                return
            if url in tried:
                continue
            tried.add(url)
            proof = _probe(url, node_id)
            if proof is not None:
                proved.append((url, proof))

    run(_candidate_urls(peer))
    # A node reached at its bare address can still name the domain it serves, so
    # a second round follows what it declared. This is how a node whose operator
    # published nothing on chain still ends up offered over https.
    run([url for _, proof in list(proved) for url in proof.addresses])

    if not proved:
        return base

    best_url, best_proof = min(proved, key=lambda item: _rank(item[0]))
    return NetworkNode(
        node_id=node_id,
        ip=peer["ip"],
        moniker=peer["moniker"],
        api_base=best_url,
        operator_address=best_proof.operator_address,
    )


def _self_node() -> NetworkNode:
    """This node's own entry, settled without a request.

    Asking itself would be a loopback through the public URL served by the very
    worker pool handling the page, so a burst of cold requests could starve the
    workers of the capacity needed to answer their own probes.
    """
    from node import require_runtime

    rt = require_runtime()
    addresses = local_addresses()
    return NetworkNode(
        node_id=rt.node_id,
        ip="",
        moniker=addresses[0] if addresses else "",
        api_base=addresses[0] if addresses else "",
        operator_address=rt.validator_operator_address,
        is_self=True,
    )


def _discover_network() -> List[NetworkNode]:
    peers = [p for p in get_connected_peers() if p["ip"] or p["node_id"]]

    nodes: List[NetworkNode] = [_self_node()]
    if peers:
        with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
            nodes.extend(pool.map(_resolve_peer, peers))

    seen: set = set()
    unique: List[NetworkNode] = []
    for node in nodes:
        key = node.node_id or node.ip
        if key in seen:
            continue
        seen.add(key)
        unique.append(node)

    unique.sort(key=lambda n: (not n.is_self, n.display_name))
    logger().debug(
        "fleet.network_discovered count=%d reachable=%d nodes=%s",
        len(unique),
        sum(1 for n in unique if n.reachable),
        [(n.display_name, n.api_base, n.operator_address) for n in unique],
    )
    return unique


def _cached_nodes() -> List[NetworkNode]:
    global _nodes_cache, _nodes_cached_at, _nodes_cache_ttl
    now = time.monotonic()
    with _nodes_lock:
        if _nodes_cache and now - _nodes_cached_at < _nodes_cache_ttl:
            return list(_nodes_cache)
    nodes = _discover_network()
    with _nodes_lock:
        _nodes_cache = nodes
        _nodes_cached_at = now
        _nodes_cache_ttl = ACTIVE_SITES_TTL if all(n.reachable for n in nodes) else ACTIVE_SITES_FAILURE_TTL
    return list(nodes)


def active_node_entries() -> List[NetworkNode]:
    """Every node on the network, reachable or not."""
    return _cached_nodes()


def active_node_sites() -> List[str]:
    """Base URL of every node that proved one, http included, for display."""
    return [node.api_base for node in _cached_nodes() if node.reachable]


def authenticated_node_sites() -> List[str]:
    """The subset a credential may be forwarded to: authenticated name, bonded stake.

    Both halves are required and they come from different proofs. Without the
    certificate the destination cannot be pinned to the name; without a bonded
    operator, any node that peers with us could stand in line for the admin's
    replayable proof simply by owning a domain.
    """
    bonded = {v["operator_address"] for v in get_active_validators() if v["operator_address"]}
    return [
        node.api_base
        for node in _cached_nodes()
        if node.authenticated and node.operator_address in bonded
    ]
