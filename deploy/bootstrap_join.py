#!/usr/bin/env python3
"""Install the mirage-1 genesis and derive state-sync trust for a joining node.

A new node only ever joins the existing network, so `miraged init`'s generated
genesis is never the right one: it describes a brand-new single-validator chain
at height 1. This fetches the real genesis and pins it by hash. The immutable
genesis carries the core parameter JSON schema from chain launch, so after
verification its obsolete core params are replaced with the current binary's
generated defaults; state sync restores the current on-chain values.

State sync is not optional here. Genesis carries initial_height 2096156 while
nodes retain RETENTION_BLOCKS (~7 days) of blocks, so no peer can serve the
several million blocks a block-syncing node would ask for.

Writes genesis.json unless --trust-only is used, then prints STATESYNC_*
KEY=VALUE lines on stdout for the caller to parse (init.sh validates each key
and never evals them). Any verification or schema failure exits non-zero
without touching genesis.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request

# sha256 of the canonical (sorted keys, compact separators) mirage-1 source
# genesis. Genesis is immutable, so this pin never needs updating. It is what
# stops a compromised bootstrap RPC from joining a new node to a different
# chain. The installed file differs only in app_state.core.params, as described
# in install_genesis().
GENESIS_SHA256 = "79eb6a81a83707cfd34f69e6f17bf6006ffa9f521b130f51dded92e04c6cfc8d"

# How far below the chosen snapshot to place the light-client trust height.
# The snapshot must be strictly after this height or CometBFT rejects it.
# Must stay inside RETENTION_BLOCKS so every endpoint can still serve the block.
TRUST_LOOKBACK = 2000

HTTP_TIMEOUT = 60

# A CometBFT block hash is exactly 32 bytes hex-encoded. Nothing else may reach
# the caller's shell.
BLOCK_HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def rpc(endpoint: str, path: str) -> dict:
    url = f"{endpoint.rstrip('/')}/{path.lstrip('/')}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                fail(f"{url} returned HTTP {resp.status}")
            body = resp.read()
    except Exception as e:
        fail(f"{url} unreachable: {e}")
    try:
        data = json.loads(body)
    except Exception as e:
        fail(f"{url} returned non-JSON ({len(body)} bytes): {e}")
    if "result" not in data:
        fail(f"{url} returned no result field: {str(data)[:200]}")
    return data["result"]


def rpc_post(endpoint: str, method: str, params: dict) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(
        endpoint.rstrip("/") + "/",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as resp:
            response_body = resp.read()
    except Exception as e:
        fail(f"{endpoint} does not accept CometBFT JSON-RPC POST: {e}")
    try:
        data = json.loads(response_body)
    except Exception as e:
        fail(f"{endpoint} returned non-JSON to CometBFT JSON-RPC POST: {e}")
    if data.get("error"):
        fail(f"{endpoint} returned JSON-RPC error: {data['error']}")
    if "result" not in data:
        fail(f"{endpoint} returned no JSON-RPC result: {str(data)[:200]}")
    return data["result"]


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def install_genesis(endpoint: str, chain_id: str, target: str) -> None:
    genesis = rpc(endpoint, "genesis").get("genesis")
    if not genesis:
        fail(f"{endpoint} /genesis returned no genesis document")

    blob = canonical(genesis)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != GENESIS_SHA256:
        fail(
            f"genesis hash mismatch from {endpoint}: expected {GENESIS_SHA256} got {digest}. "
            "This is not the mirage-1 genesis; refusing to join."
        )
    if genesis.get("chain_id") != chain_id:
        fail(f"genesis chain_id is {genesis.get('chain_id')!r}, expected {chain_id!r}")
    genesis = json.loads(blob)

    # miraged init created target immediately before this function runs. Its
    # params are the exact JSON schema understood by this binary. The immutable
    # network genesis predates several field removals and renames; feeding those
    # old names to a current binary makes InitGenesis abort before state sync can
    # restore the current chain state. Keep every other byte of chain state, but
    # use current defaults for this transient pre-snapshot state.
    try:
        with open(target, encoding="utf-8") as f:
            generated = json.load(f)
        current_params = generated["app_state"]["core"]["params"]
    except Exception as e:
        fail(f"cannot read current core params from generated {target}: {e}")
    if not isinstance(current_params, dict) or not current_params:
        fail(f"generated {target} has no current core params")
    try:
        core = genesis["app_state"]["core"]
    except Exception as e:
        fail(f"verified genesis has no app_state.core object: {e}")
    if not isinstance(core, dict) or "params" not in core:
        fail("verified genesis has no app_state.core.params")
    core["params"] = current_params
    installed_blob = canonical(genesis)

    d = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".genesis-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(installed_blob)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    print(
        f"==> Installed verified mirage-1 genesis "
        f"(initial_height={genesis.get('initial_height')}, source_sha256={digest[:16]}..., "
        f"current core params applied)",
        file=sys.stderr,
    )


def snapshot_interval() -> int:
    raw = os.environ.get("SNAPSHOT_INTERVAL", "")
    if not raw.isdigit() or int(raw) <= 0:
        fail("SNAPSHOT_INTERVAL is not a positive integer")
    return int(raw)


def trust_height_for_head(head: int, interval: int) -> int:
    """Pin trust below a snapshot peers already keep, not below live head.

    Snapshots land on interval multiples. Head-minus-lookback often sits in
    the gap after the last snapshot, so state-sync discovers forever and
    never applies. Prefer the previous completed interval: keep-recent=2
    peers still have it, and the newest one may still be in flight.
    """
    if interval <= 0:
        fail(f"SNAPSHOT_INTERVAL must be a positive integer, got {interval}")
    latest_snapshot = (head // interval) * interval
    if latest_snapshot < interval:
        fail(
            f"chain head {head} has not completed a snapshot interval of {interval}; " "cannot derive state-sync trust"
        )
    snapshot_height = latest_snapshot - interval
    if snapshot_height <= 0:
        snapshot_height = latest_snapshot
    trust_height = snapshot_height - TRUST_LOOKBACK
    if trust_height <= 0:
        fail(f"snapshot height {snapshot_height} is below the {TRUST_LOOKBACK}-block trust lookback")
    return trust_height


def derive_trust(endpoints: list[str]) -> tuple[int, str]:
    """Pick a trust height below a kept snapshot and confirm its hash on every endpoint.

    There is no hash to pin for a live block, so agreement across independent
    endpoints is the check. One lying server cannot move the trust hash alone.
    """
    head = int(rpc(endpoints[0], "status")["sync_info"]["latest_block_height"])
    trust_height = trust_height_for_head(head, snapshot_interval())

    hashes: dict[str, str] = {}
    for ep in endpoints:
        block = rpc(ep, f"block?height={trust_height}")
        h = str(((block.get("block_id") or {}).get("hash") or ""))
        if not h:
            fail(f"{ep} returned no block_id.hash for height {trust_height}")
        # The caller puts this value into a shell variable, so anything that is
        # not a bare block hash is rejected here rather than passed on.
        if not BLOCK_HASH_RE.match(h):
            fail(f"{ep} returned a malformed block_id.hash for height {trust_height}: {h!r}")
        hashes[ep] = h

    distinct = set(hashes.values())
    if len(distinct) != 1:
        fail(f"endpoints disagree on the hash of block {trust_height}: {hashes}")

    return trust_height, distinct.pop()


def state_sync_servers(persistent_peers: str, trust_height: int, trust_hash: str) -> list[str]:
    peers = [peer.strip() for peer in persistent_peers.split(",") if peer.strip()]
    if len(peers) < 2:
        fail("PERSISTENT_PEERS must contain at least two peers for state sync")

    servers = []
    for peer in peers[:2]:
        if peer.count("@") != 1:
            fail(f"malformed persistent peer: {peer!r}")
        peer_id, address = peer.split("@", 1)
        if not re.fullmatch(r"[0-9A-Fa-f]{40}", peer_id):
            fail(f"persistent peer has malformed node ID: {peer!r}")
        parsed = urllib.parse.urlsplit(f"tcp://{address}")
        try:
            p2p_port = parsed.port
        except ValueError as e:
            fail(f"persistent peer has malformed address {address!r}: {e}")
        if not parsed.hostname or not p2p_port:
            fail(f"persistent peer has malformed address: {address!r}")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        servers.append(f"http://{host}:26657")

    for server in servers:
        block = rpc_post(server, "block", {"height": str(trust_height)})
        block_hash = str(((block.get("block_id") or {}).get("hash") or ""))
        if block_hash != trust_hash:
            fail(f"{server} returned block hash {block_hash!r} at height {trust_height}, " f"expected {trust_hash}")
    return servers


def main(trust_only: bool = False) -> None:
    endpoints = [e.strip() for e in os.environ.get("BOOTSTRAP_RPC", "").split(",") if e.strip()]
    persistent_peers = os.environ.get("PERSISTENT_PEERS", "")
    chain_id = os.environ.get("CHAIN_ID", "")
    node_home = os.environ.get("NODE_HOME", "")

    if not endpoints:
        fail("BOOTSTRAP_RPC is not set. A joining node needs at least two chain RPC endpoints.")
    if len(endpoints) < 2:
        fail(
            f"BOOTSTRAP_RPC has {len(endpoints)} endpoint; state sync needs at least two so the "
            "light client can cross-check the trust hash. Add another node's RPC."
        )
    if not chain_id:
        fail("CHAIN_ID is not set")
    if not node_home:
        fail("NODE_HOME is not set")

    if not trust_only:
        install_genesis(endpoints[0], chain_id, os.path.join(node_home, "config", "genesis.json"))
    trust_height, trust_hash = derive_trust(endpoints)
    servers = state_sync_servers(persistent_peers, trust_height, trust_hash)
    print(f"==> State sync trust height {trust_height} hash {trust_hash}", file=sys.stderr)

    print("STATESYNC_ENABLE=true")
    print(f"STATESYNC_RPC_SERVERS={','.join(servers)}")
    print(f"STATESYNC_TRUST_HEIGHT={trust_height}")
    print(f"STATESYNC_TRUST_HASH={trust_hash}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--trust-only",
        action="store_true",
        help="derive fresh state-sync trust without replacing genesis.json",
    )
    main(parser.parse_args().trust_only)
