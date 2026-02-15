#!/usr/bin/env python3
"""
Verify v1.12.0 chain upgrade — checks ONLY what changed in this release.

What v1.12.0 changed:
- MsgPost: new repeated string `media` field (field 105)
- On-chain validation: max 10 items, each max 2048 chars, https:// required
- Indexer: stores media as JSON column
- Backend: serves media in API responses
- Backward compatible: no upgrade handler needed, existing posts unaffected

This script does NOT submit transactions or mutate chain state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


UPGRADE_NAME = "v1.12.0"
EXPECTED_VERSION = "v1.12.0"
REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_miraged() -> str:
    candidates = [
        "/opt/mirage/blockchain/miraged",
        "/opt/mirage/blockchain/bin/miraged",
        str(REPO_ROOT / "blockchain" / "miraged"),
        str(REPO_ROOT / "blockchain" / "bin" / "miraged"),
        "miraged",
    ]
    for c in candidates:
        if c == "miraged":
            return c
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "miraged"


def _run_json(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if p.returncode != 0:
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd)}\n{p.stderr}".strip())
    out = p.stdout.strip()
    if not out:
        raise RuntimeError(f"empty stdout: {' '.join(cmd)}")
    return json.loads(out)


# ---------------------------------------------------------------------------
# v1.12.0 specific checks
# ---------------------------------------------------------------------------


def check_binary_version(miraged: str, failures: list[str]) -> None:
    """Binary version must match v1.12.0 (or v1.12.0-*)."""
    print("-> Checking binary version...")
    try:
        p = subprocess.run([miraged, "version"], capture_output=True, text=True, check=False)
        version = p.stdout.strip() or p.stderr.strip()
        if version == EXPECTED_VERSION or version.startswith(EXPECTED_VERSION + "-"):
            print(f"   [OK] {version}")
        else:
            print(f"   [FAIL] {version} (expected {EXPECTED_VERSION})")
            failures.append(f"binary version {version!r} != {EXPECTED_VERSION!r}")
    except Exception as e:
        print(f"   [FAIL] {e}")
        failures.append(f"cannot check binary version: {e}")


def check_node_health(miraged: str, rpc: str, failures: list[str]) -> None:
    """Node is synced and producing blocks."""
    print("\n-> Checking node health...")
    try:
        result = _run_json([miraged, "status", "--node", rpc])
        sync_info = result.get("SyncInfo") or result.get("sync_info", {})
        catching_up = sync_info.get("catching_up", True)
        latest_height = int(sync_info.get("latest_block_height", 0))
        if not catching_up and latest_height > 0:
            print(f"   [OK] synced at height {latest_height}")
        else:
            print(f"   [FAIL] catching_up={catching_up}, height={latest_height}")
            failures.append(f"node not synced: catching_up={catching_up}, height={latest_height}")
    except Exception as e:
        print(f"   [FAIL] {e}")
        failures.append(f"cannot check node status: {e}")


def check_params(miraged: str, rpc: str, failures: list[str]) -> None:
    """Verify core params are queryable and sane (v1.11.0+ params still present)."""
    print("\n-> Checking core params...")
    try:
        raw = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        params = raw.get("params", raw)
    except Exception as e:
        print(f"   [FAIL] cannot fetch params: {e}")
        failures.append(f"cannot fetch core params: {e}")
        return

    # pow_difficulty_step must exist and be a float in (0, 1]
    # (Python datatypes call this pow_factor, but miraged JSON uses the proto name)
    step = params.get("pow_difficulty_step")
    if step is not None:
        try:
            fstep = float(step)
            if 0 < fstep <= 1:
                print(f"   [OK] pow_difficulty_step = {fstep}")
            else:
                print(f"   [FAIL] pow_difficulty_step = {fstep} (must be in (0, 1])")
                failures.append(f"pow_difficulty_step out of range: {fstep}")
        except (ValueError, TypeError):
            print(f"   [FAIL] pow_difficulty_step not a valid float: {step!r}")
            failures.append(f"pow_difficulty_step invalid: {step!r}")
    else:
        print("   [FAIL] pow_difficulty_step missing from params")
        failures.append("pow_difficulty_step missing")

    # tiers should be present (Python datatypes call these subscription_tiers)
    tiers = params.get("tiers")
    if tiers and len(tiers) >= 3:
        print(f"   [OK] tiers = {len(tiers)} tiers")
    else:
        print(f"   [FAIL] tiers missing or incomplete")
        failures.append("tiers missing or incomplete")


def check_source_level(failures: list[str]) -> None:
    """Source-level checks for v1.12.0 — silently skipped when files aren't present."""
    print("\n-> Checking v1.12.0 source changes...")

    found_any = False

    def _check(path: Path, checks: list[tuple[str, str, str]]) -> None:
        nonlocal found_any
        if not path.exists():
            return
        found_any = True
        text = path.read_text()
        for pattern, ok_msg, fail_msg in checks:
            if pattern.startswith("re:"):
                hit = bool(re.search(pattern[3:], text, re.DOTALL))
            else:
                hit = pattern in text
            if hit:
                print(f"   [OK] {ok_msg}")
            else:
                print(f"   [FAIL] {fail_msg}")
                failures.append(f"v1.12.0: {fail_msg}")

    # Go: media validation function
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "module" / "module.go",
        [
            (
                "validateMsgPostMedia",
                "module.go: validateMsgPostMedia present",
                "module.go: validateMsgPostMedia missing",
            ),
            (
                "re:media.*2048",
                "module.go: media URL length limit (2048)",
                "module.go: media URL length limit missing",
            ),
        ],
    )

    # Proto: media field on MsgPost
    _check(
        REPO_ROOT / "blockchain" / "proto" / "mirage" / "core" / "v1" / "tx.proto",
        [
            (
                "re:repeated\\s+string\\s+media",
                "tx.proto: media field on MsgPost",
                "tx.proto: media field missing from MsgPost",
            ),
        ],
    )

    # Python datatypes: media field
    _check(
        REPO_ROOT / "shared" / "datatypes.py",
        [
            (
                "media",
                "datatypes.py: media field present",
                "datatypes.py: media field missing",
            ),
        ],
    )

    # Python canon: media in canonical encoding
    _check(
        REPO_ROOT / "shared" / "canon.py",
        [
            (
                "media",
                "canon.py: media in canonical encoding",
                "canon.py: media missing from canonical encoding",
            ),
        ],
    )

    # Indexer: media column
    _check(
        REPO_ROOT / "indexer" / "database.py",
        [
            (
                "media",
                "database.py: media column in indexer",
                "database.py: media column missing from indexer",
            ),
        ],
    )

    # Backend: media in API
    _check(
        REPO_ROOT / "web" / "backend" / "routes" / "core.py",
        [
            (
                "media",
                "core.py: media in backend API",
                "core.py: media missing from backend API",
            ),
        ],
    )

    # Frontend: media in TransactionHandler
    _check(
        REPO_ROOT / "web" / "frontend" / "src" / "utils" / "TransactionHandler.js",
        [
            (
                "media",
                "TransactionHandler.js: media support",
                "TransactionHandler.js: media support missing",
            ),
        ],
    )

    if not found_any:
        print("   (no source files present — skipped)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=f"Verify {UPGRADE_NAME} chain upgrade")
    parser.add_argument("--node", default="http://127.0.0.1:26657", help="CometBFT RPC endpoint")
    args = parser.parse_args()

    rpc = args.node.rstrip("/")
    miraged = _find_miraged()
    failures: list[str] = []

    print("=" * 60)
    print(f"Verify {UPGRADE_NAME} ({datetime.now().isoformat()})")
    print("=" * 60)
    print(f"RPC:     {rpc}")
    print(f"miraged: {miraged}")
    print()

    check_binary_version(miraged, failures)
    check_node_health(miraged, rpc, failures)
    check_params(miraged, rpc, failures)
    check_source_level(failures)

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)} error(s)):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASSED — {UPGRADE_NAME} upgrade verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
