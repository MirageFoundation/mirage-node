#!/usr/bin/env python3
"""
Post-deploy verification for v1.32.0.

Per the /upgrade workflow this file is rewritten every release to check ONLY
what THIS release changes:

  python scripts/verify_upgrade.py
  docker exec mirage python3 /opt/mirage/scripts/verify_upgrade.py

What v1.32.0 changes (deploy-visible)
------------------------------------
Consensus-breaking ante fix (C-1): relay gas payer must sign the outer tx.
No relay fee ceiling: the payer signs the amount, so magnitude is not bounded.

  1. Frontend version.txt reports v1.32.0.
  2. Chain binary version reports v1.32.0.
  3. Upgrade handler name v1.32.0 is applied (applied_plan query).
  4. Chain is live (indexer / comet producing blocks).
  5. Committed relay txs carry a real 64-byte outer signature and are unordered
     (the placeholder signature is what C-1 exploited).
  6. No relay fee is capped at relay_max_gas_fee. An interim version of the C-1
     fix capped the fee at min(gas * relay_min_gas_price, relay_max_gas_fee),
     which crosses the CheckTx min-gas-price floor at 500k gas and made every
     larger relay tx unpayable (posts over ~10.7k chars, bulk follows).

Checks 5 and 6 scan committed blocks, bounded below by the pruning boundary and
by the upgrade height (older blocks were produced by the old binary).

This script is read-only: it never broadcasts. Check 6 is therefore
traffic-dependent and reports informationally when the deployed traffic does not
happen to exceed the old bound. The authoritative proof is
tests/test_blockchain.py --category c1_gas_payer (c1.high_gas_relay_accepted),
which submits above the old cap on a local node.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

RELEASE_VERSION = "v1.32.0"
COMET_RPC_URL = "http://127.0.0.1:26657"
REST_URL = "http://127.0.0.1:1317"
SCAN_DEPTH = 200

passed = 0
failed = 0


def ok(msg: str) -> None:
    global passed
    passed += 1
    print(f"  PASS  {msg}")


def fail(msg: str) -> None:
    global failed
    failed += 1
    print(f"  FAIL  {msg}")


def note(msg: str) -> None:
    """Informational only — does not affect the exit code."""
    print(f"  NOTE  {msg}")


def http_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # urllib's message is just the status line; the gRPC-gateway puts the
        # actual reason in the body, which is the only useful part here.
        raise RuntimeError(f"HTTP {e.code} from {url}: {e.read().decode()[:300]}") from None


def check_version_txt() -> None:
    candidates = [
        Path("/opt/mirage/web/frontend/build/version.txt"),
        Path("/opt/mirage/web/frontend/public/version.txt"),
        Path(__file__).resolve().parent.parent / "web" / "frontend" / "public" / "version.txt",
    ]
    for p in candidates:
        if p.is_file():
            ver = p.read_text().strip()
            if ver == RELEASE_VERSION:
                ok(f"version.txt={ver} ({p})")
            else:
                fail(f"version.txt={ver!r} want {RELEASE_VERSION} ({p})")
            return
    fail("version.txt not found")


def check_binary_version() -> None:
    bin_candidates = [
        "/usr/local/bin/miraged",
        "/root/go/bin/miraged",
        str(Path(__file__).resolve().parent.parent / "blockchain" / "bin" / "miraged"),
    ]
    for b in bin_candidates:
        if not os.path.isfile(b):
            continue
        try:
            out = subprocess.check_output([b, "version", "--long"], stderr=subprocess.STDOUT, timeout=10).decode()
        except Exception as e:
            fail(f"miraged version failed ({b}): {e}")
            return
        if RELEASE_VERSION.lstrip("v") in out or RELEASE_VERSION in out:
            ok(f"binary version contains {RELEASE_VERSION} ({b})")
        else:
            fail(f"binary version {out.strip()[:120]!r} does not contain {RELEASE_VERSION} ({b})")
        return
    fail("miraged binary not found")


def applied_upgrade_height() -> int:
    """Height at which the RELEASE_VERSION plan was applied. Raises if not applied."""
    data = http_json(f"{REST_URL}/cosmos/upgrade/v1beta1/applied_plan/{RELEASE_VERSION}")
    height = int(data.get("height") or data.get("Height") or 0)
    if height <= 0:
        raise RuntimeError(f"upgrade {RELEASE_VERSION} not applied: {data}")
    return height


def check_upgrade_applied() -> None:
    try:
        height = applied_upgrade_height()
    except Exception as e:
        fail(f"applied_plan check failed: {e}")
        return
    ok(f"upgrade {RELEASE_VERSION} applied at height={height}")


def _scan_range(depth: int = SCAN_DEPTH) -> tuple[int, int]:
    """Inclusive (head, floor) block range for a relay-tx scan.

    The floor is clamped by two hard limits, so a scan never asks for a block
    that cannot answer the question:

      * earliest_block_height — below the pruning boundary the node has no block
        and the tx service returns HTTP 500.
      * the v1.32.0 upgrade height — blocks below it were produced by the old
        binary and carry the old wire format, so they must not be judged against
        the new rules.
    """
    sync = http_json(f"{COMET_RPC_URL}/status")["result"]["sync_info"]
    head = int(sync["latest_block_height"])
    earliest = int(sync["earliest_block_height"])
    floor = max(head - depth + 1, earliest, applied_upgrade_height())
    return head, floor


def _iter_relay_txs(head: int, floor: int):
    """Yield (height, tx) for committed mirage.core relay txs, newest block first.

    Tx indexing is disabled, so txs are decoded from their block rather than
    fetched by hash. Raises on an RPC/REST failure so each caller reports it
    against its own check.
    """
    for height in range(head, floor - 1, -1):
        try:
            block = http_json(f"{REST_URL}/cosmos/tx/v1beta1/txs/block/{height}")
        except Exception as e:
            raise RuntimeError(f"block {height} (scan range {floor}..{head}): {e}") from None
        for tx in block.get("txs") or []:
            messages = ((tx.get("body") or {}).get("messages")) or []
            if messages and str(messages[0].get("@type", "")).startswith("/mirage.core.v1."):
                yield height, tx


def check_relay_txs_signed() -> None:
    """C-1: committed relay txs must carry a real outer signature and be unordered.

    Walks back from the head until a mirage.core relay tx is found, then checks
    the wire format the v1.32.0 ante requires. A 1-byte signature means a node
    is still broadcasting the pre-v1.32.0 placeholder.
    """
    try:
        head, floor = _scan_range()
        for height, tx in _iter_relay_txs(head, floor):
            body = tx.get("body") or {}
            sigs = tx.get("signatures") or []
            lengths = [len(base64.b64decode(s)) for s in sigs]
            if lengths != [64]:
                fail(f"relay tx at height={height} has outer signature lengths {lengths}, want exactly one 64-byte sig")
                return
            if body.get("unordered") is not True:
                fail(f"relay tx at height={height} is not unordered: unordered={body.get('unordered')!r}")
                return
            if not str(body.get("timeout_timestamp") or "").strip():
                fail(f"relay tx at height={height} missing timeout_timestamp (unordered nonce)")
                return
            ok(f"relay tx at height={height} signed (64-byte sig, unordered, {body['messages'][0]['@type']})")
            return
    except Exception as e:
        fail(f"relay signature check: block scan failed: {e}")
        return

    fail(f"no mirage.core relay tx found in blocks {floor}..{head} — cannot verify C-1")


def check_relay_fee_uncapped() -> None:
    """v1.32.0 enforces no ceiling on the relay gas payment.

    An interim form of the C-1 fix bounded the fee at
    min(gas * relay_min_gas_price, relay_max_gas_fee). That bound crosses the
    CheckTx minimum-gas-price floor at relay_max_gas_fee / relay_min_gas_price
    gas, so above the crossing the fee a node must offer exceeds the fee the
    chain accepts and no valid tx exists. The payer signs the SignDoc, which
    covers the fee, so consent is already proven and no bound is needed.

    Read-only detection: a committed relay tx above the crossing whose fee
    exceeds relay_max_gas_fee proves no ceiling is applied. A fee pinned exactly
    at relay_max_gas_fee at that gas is the signature of a ceiling being
    reintroduced, and fails.
    """
    try:
        params = (http_json(f"{REST_URL}/mirage/core/v1/params").get("params")) or {}
        relay_min = int(params["relay_min_gas_price"])
        relay_max = int(params["relay_max_gas_fee"])
    except Exception as e:
        fail(f"relay fee ceiling check: params query failed: {e}")
        return
    if relay_min <= 0 or relay_max <= 0:
        fail(f"relay gas params misconfigured: relay_min_gas_price={relay_min} relay_max_gas_fee={relay_max}")
        return

    crossing = relay_max // relay_min
    seen = 0
    max_gas = 0
    max_fee = 0
    try:
        head, floor = _scan_range()
        for height, tx in _iter_relay_txs(head, floor):
            fee = ((tx.get("auth_info") or {}).get("fee")) or {}
            gas = int(fee.get("gas_limit") or 0)
            amt = sum(int(c.get("amount") or 0) for c in (fee.get("amount") or []) if c.get("denom") == "umirage")
            seen += 1
            max_gas = max(max_gas, gas)
            max_fee = max(max_fee, amt)
            if gas > crossing:
                if amt > relay_max:
                    ok(
                        f"relay tx at height={height} paid {amt} umirage at gas={gas}, "
                        f"above relay_max_gas_fee={relay_max} — no fee ceiling applied"
                    )
                    return
                if amt == relay_max:
                    fail(
                        f"relay tx at height={height} has gas={gas} (above the {crossing} crossing) but a fee "
                        f"pinned exactly at relay_max_gas_fee={relay_max} — a fee ceiling appears to be enforced"
                    )
                    return
    except Exception as e:
        fail(f"relay fee ceiling check: block scan failed: {e}")
        return

    if seen == 0:
        note(f"relay fee ceiling not exercised: no relay tx in blocks {floor}..{head} (check 5 reports this)")
        return
    note(
        f"relay fee ceiling not exercised by live traffic: {seen} relay tx(s) scanned, max gas={max_gas} "
        f"(crossing is {crossing}), max fee={max_fee} umirage. Nothing was near the old bound, so this is "
        f"expected on quiet nodes. Proof lives in tests/test_blockchain.py --category c1_gas_payer."
    )


def check_chain_live() -> None:
    try:
        data = http_json(f"{COMET_RPC_URL}/status")
        height = int(data["result"]["sync_info"]["latest_block_height"])
    except Exception as e:
        fail(f"comet status failed: {e}")
        return
    if height > 0:
        ok(f"chain live at height={height}")
    else:
        fail(f"chain height={height}")


def main() -> int:
    print(f"verify_upgrade.py for {RELEASE_VERSION}")
    check_version_txt()
    check_binary_version()
    check_upgrade_applied()
    check_chain_live()
    check_relay_txs_signed()
    check_relay_fee_uncapped()
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
