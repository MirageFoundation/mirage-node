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

  1. Frontend version.txt reports v1.32.0.
  2. Chain binary version reports v1.32.0.
  3. Upgrade handler name v1.32.0 is applied (applied_plan query).
  4. Chain is live (indexer / comet producing blocks).
  5. Committed relay txs carry a real 64-byte outer signature and are unordered
     (the placeholder signature is what C-1 exploited).
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


def http_json(url: str, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


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


def check_upgrade_applied() -> None:
    url = f"{REST_URL}/cosmos/upgrade/v1beta1/applied_plan/{RELEASE_VERSION}"
    try:
        data = http_json(url)
    except Exception as e:
        fail(f"applied_plan query failed: {e}")
        return
    height = data.get("height") or data.get("Height")
    if height and str(height) not in ("0", ""):
        ok(f"upgrade {RELEASE_VERSION} applied at height={height}")
    else:
        fail(f"upgrade {RELEASE_VERSION} not applied: {data}")


def check_relay_txs_signed() -> None:
    """C-1: committed relay txs must carry a real outer signature and be unordered.

    Walks back from the head until a mirage.core relay tx is found, then checks
    the wire format the v1.32.0 ante requires. A 1-byte signature means a node
    is still broadcasting the pre-v1.32.0 placeholder.
    """
    try:
        status = http_json(f"{COMET_RPC_URL}/status")
        head = int(status["result"]["sync_info"]["latest_block_height"])
    except Exception as e:
        fail(f"relay signature check: comet status failed: {e}")
        return

    # Tx indexing is disabled, so decode txs from their block rather than by hash.
    for height in range(head, max(head - 200, 0), -1):
        try:
            block = http_json(f"{REST_URL}/cosmos/tx/v1beta1/txs/block/{height}")
        except Exception as e:
            fail(f"relay signature check: block {height} query failed: {e}")
            return
        for tx in block.get("txs") or []:
            body = tx.get("body") or {}
            messages = body.get("messages") or []
            if not messages or not str(messages[0].get("@type", "")).startswith("/mirage.core.v1."):
                continue

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
            ok(f"relay tx at height={height} signed (64-byte sig, unordered, {messages[0]['@type']})")
            return

    fail(f"no mirage.core relay tx found in blocks {max(head - 200, 0)}..{head} — cannot verify C-1")


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
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
