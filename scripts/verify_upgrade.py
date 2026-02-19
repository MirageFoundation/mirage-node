#!/usr/bin/env python3
"""
Verify v1.14.0 chain upgrade — checks ONLY what changed in this release.

What v1.14.0 changed:
- MsgDeleteUser: users can permanently delete their account (self-signed or governance)
- On-chain: DeleteUserState clears profile KV, lists, username, subscription; sweeps spendable to community pool
- Indexer: soft_delete_profile (deleted_at column), resolve excludes deleted; post attribution preserved
- upsert_profile / upsert_profile_full: clear deleted_at on conflict (re-register after delete)
- Backend routes: deleted_at IS NULL in username resolution, user listings, search
- No new chain params; no proto param changes

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


UPGRADE_NAME = "v1.14.0"
EXPECTED_VERSION = "v1.14.0"
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
# v1.13.0 specific checks
# ---------------------------------------------------------------------------


def check_binary_version(miraged: str, failures: list[str]) -> None:
    """Binary version must match v1.13.0 (or v1.13.0-*)."""
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
    """Verify core params (v1.14.0 does not change params; sanity checks from prior upgrades)."""
    print("\n-> Checking core params...")
    try:
        raw = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        params = raw.get("params", raw)
    except Exception as e:
        print(f"   [FAIL] cannot fetch params: {e}")
        failures.append(f"cannot fetch core params: {e}")
        return

    # pow_difficulty_step should be present from v1.11.0
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


def check_source_level(failures: list[str]) -> None:
    """Source-level checks for v1.14.0 — silently skipped when files aren't present."""
    print("\n-> Checking v1.14.0 source changes...")

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
            elif pattern.startswith("!:"):
                hit = pattern[2:] not in text
            else:
                hit = pattern in text
            if hit:
                print(f"   [OK] {ok_msg}")
            else:
                print(f"   [FAIL] {fail_msg}")
                failures.append(f"v1.14.0: {fail_msg}")

    # --- Blockchain (Go) ---

    # tx.pb.go: MsgDeleteUser / MsgDeleteUserResponse
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "tx.pb.go",
        [
            ("MsgDeleteUser", "tx.pb.go: MsgDeleteUser defined", "tx.pb.go: MsgDeleteUser missing"),
            (
                "MsgDeleteUserResponse",
                "tx.pb.go: MsgDeleteUserResponse defined",
                "tx.pb.go: MsgDeleteUserResponse missing",
            ),
        ],
    )

    # codec.go: MsgDeleteUser registered
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "codec.go",
        [("MsgDeleteUser", "codec.go: MsgDeleteUser registered", "codec.go: MsgDeleteUser registration missing")],
    )

    # module.go: DeleteUser handler
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "module" / "module.go",
        [
            ("DeleteUser", "module.go: DeleteUser handler present", "module.go: DeleteUser handler missing"),
            ("DeleteUserState", "module.go: DeleteUserState called", "module.go: DeleteUserState call missing"),
        ],
    )

    # keeper: DeleteUserState
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "keeper" / "keeper.go",
        [
            ("DeleteUserState", "keeper.go: DeleteUserState present", "keeper.go: DeleteUserState missing"),
            ("FundCommunityPool", "keeper.go: FundCommunityPool in DeleteUserState", "keeper.go: fund sweep missing"),
        ],
    )

    # Upgrade handler
    _check(
        REPO_ROOT / "blockchain" / "app" / "upgrades.go",
        [
            (
                '"v1.14.0"',
                "upgrades.go: v1.14.0 upgrade handler registered",
                "upgrades.go: v1.14.0 upgrade handler missing",
            )
        ],
    )

    # --- Python ---

    # Datatypes: MsgDeleteUser
    _check(
        REPO_ROOT / "shared" / "datatypes.py",
        [("MsgDeleteUser", "datatypes.py: MsgDeleteUser defined", "datatypes.py: MsgDeleteUser missing")],
    )

    # Indexer: soft_delete_profile, deleted_at
    _check(
        REPO_ROOT / "indexer" / "database.py",
        [
            (
                "soft_delete_profile",
                "database.py: soft_delete_profile present",
                "database.py: soft_delete_profile missing",
            ),
            ("deleted_at", "database.py: deleted_at column/migration", "database.py: deleted_at missing"),
            (
                "deleted_at=NULL",
                "database.py: upsert clears deleted_at on conflict",
                "database.py: upsert deleted_at clear missing",
            ),
        ],
    )

    # Indexer: _handle_delete_user
    _check(
        REPO_ROOT / "indexer" / "message_processor.py",
        [
            (
                "_handle_delete_user",
                "message_processor.py: _handle_delete_user present",
                "message_processor.py: _handle_delete_user missing",
            ),
            (
                "MsgDeleteUser",
                "message_processor.py: MsgDeleteUser in TYPE_URL_TO_PROTO",
                "message_processor.py: MsgDeleteUser missing from TYPE_URL_TO_PROTO",
            ),
        ],
    )

    # Backend public: deleted_at in username resolution
    _check(
        REPO_ROOT / "web" / "backend" / "routes" / "public.py",
        [
            (
                "deleted_at IS NULL",
                "public.py: deleted_at filter in username queries",
                "public.py: deleted_at filter missing in username queries",
            )
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
