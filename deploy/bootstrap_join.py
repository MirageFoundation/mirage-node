#!/usr/bin/env python3
"""Install the mirage-1 genesis and derive state-sync trust for a joining node.

A new node only ever joins the existing network, so `miraged init`'s generated
genesis is never the right one: it describes a brand-new single-validator chain
at height 1. This fetches the real genesis instead and pins it by hash.

State sync is not optional here. Genesis carries initial_height 2096156 while
nodes retain RETENTION_BLOCKS (~7 days) of blocks, so no peer can serve the
several million blocks a block-syncing node would ask for.

Writes genesis.json and prints STATESYNC_* KEY=VALUE lines on stdout for the
caller to parse (init.sh validates each key and never evals them). Any
verification failure exits non-zero without touching genesis.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request

# sha256 of the canonical (sorted keys, compact separators) mirage-1 genesis.
# Genesis is immutable, so this pin never needs updating. It is what stops a
# compromised bootstrap RPC from joining a new node to a different chain.
GENESIS_SHA256 = "79eb6a81a83707cfd34f69e6f17bf6006ffa9f521b130f51dded92e04c6cfc8d"

# How far below the head to place the light-client trust height. Must stay
# inside RETENTION_BLOCKS so every endpoint can still serve the block.
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

    # Written in the same canonical form that was hashed, so the pin can be
    # re-checked later with a plain sha256sum of the file on disk.
    d = os.path.dirname(target)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".genesis-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    print(
        f"==> Installed verified mirage-1 genesis "
        f"(initial_height={genesis.get('initial_height')}, sha256={digest[:16]}...)",
        file=sys.stderr,
    )


def derive_trust(endpoints: list[str]) -> tuple[int, str]:
    """Pick a trust height below the head and confirm its hash on every endpoint.

    There is no hash to pin for a live block, so agreement across independent
    endpoints is the check. One lying server cannot move the trust hash alone.
    """
    head = int(rpc(endpoints[0], "status")["sync_info"]["latest_block_height"])
    trust_height = head - TRUST_LOOKBACK
    if trust_height <= 0:
        fail(f"chain head {head} is below the {TRUST_LOOKBACK}-block trust lookback")

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


def main() -> None:
    endpoints = [e.strip() for e in os.environ.get("BOOTSTRAP_RPC", "").split(",") if e.strip()]
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

    install_genesis(endpoints[0], chain_id, os.path.join(node_home, "config", "genesis.json"))
    trust_height, trust_hash = derive_trust(endpoints)
    print(f"==> State sync trust height {trust_height} hash {trust_hash}", file=sys.stderr)

    print("STATESYNC_ENABLE=true")
    print(f"STATESYNC_RPC_SERVERS={','.join(endpoints)}")
    print(f"STATESYNC_TRUST_HEIGHT={trust_height}")
    print(f"STATESYNC_TRUST_HASH={trust_hash}")


if __name__ == "__main__":
    main()
