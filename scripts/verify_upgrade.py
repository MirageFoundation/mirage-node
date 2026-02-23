#!/usr/bin/env python3
"""
Verify v1.15.0 chain upgrade — checks ONLY what changed in this release.

What v1.15.0 changed:
- MsgAward: burn MIRAGE to give an award to a post/comment (free for level >= 100)
- award_configs added to Params (replaces unused award_permissions on TierConfig)
- Four default award types: quality_post (10k), original_content (5k), based (5k), receipts (5k)
- Indexer: awards table stores award records (one per owner+target)
- Backend: /api/core/award endpoint with self-award and duplicate checks
- Magic scoring: unique_awarders incorporated as sqrt component

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


UPGRADE_NAME = "v1.15.0"
EXPECTED_VERSION = "v1.15.0"
REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_AWARD_TYPES = {"quality_post", "original_content", "based", "receipts"}


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
# v1.15.0 specific checks
# ---------------------------------------------------------------------------


def check_binary_version(miraged: str, failures: list[str]) -> None:
    """Binary version must match v1.15.0 (or v1.15.0-*)."""
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
    """Verify core params — award_configs must be present with expected types."""
    print("\n-> Checking core params...")
    try:
        raw = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        params = raw.get("params", raw)
    except Exception as e:
        print(f"   [FAIL] cannot fetch params: {e}")
        failures.append(f"cannot fetch core params: {e}")
        return

    # award_configs must be present and non-empty
    award_configs = params.get("award_configs")
    if not award_configs or not isinstance(award_configs, list):
        print("   [FAIL] award_configs missing or empty")
        failures.append("award_configs missing or empty")
        return

    names = {ac.get("name") for ac in award_configs}
    if EXPECTED_AWARD_TYPES <= names:
        print(f"   [OK] award_configs has all expected types: {sorted(EXPECTED_AWARD_TYPES)}")
    else:
        missing = EXPECTED_AWARD_TYPES - names
        print(f"   [FAIL] award_configs missing types: {sorted(missing)}")
        failures.append(f"award_configs missing types: {sorted(missing)}")

    for ac in award_configs:
        name = ac.get("name", "?")
        cost = ac.get("cost")
        if cost is None:
            print(f"   [FAIL] award_configs[{name}]: cost missing")
            failures.append(f"award_configs[{name}]: cost missing")
        else:
            print(f"   [OK] award_configs[{name}]: cost={cost}")

    # pow_difficulty_step should still be present from v1.11.0
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
    """Source-level checks for v1.15.0 — silently skipped when files aren't present."""
    print("\n-> Checking v1.15.0 source changes...")

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
                failures.append(f"v1.15.0: {fail_msg}")

    # --- Blockchain (Go) ---

    # tx.pb.go: MsgAward / MsgAwardResponse
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "tx.pb.go",
        [
            ("MsgAward", "tx.pb.go: MsgAward defined", "tx.pb.go: MsgAward missing"),
            ("MsgAwardResponse", "tx.pb.go: MsgAwardResponse defined", "tx.pb.go: MsgAwardResponse missing"),
        ],
    )

    # params.pb.go: AwardConfig
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "params.pb.go",
        [("AwardConfig", "params.pb.go: AwardConfig defined", "params.pb.go: AwardConfig missing")],
    )

    # codec.go: MsgAward registered
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "codec.go",
        [("MsgAward", "codec.go: MsgAward registered", "codec.go: MsgAward registration missing")],
    )

    # params.go: DefaultAwardConfigs, GetAwardConfig
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "params.go",
        [
            ("DefaultAwardConfigs", "params.go: DefaultAwardConfigs present", "params.go: DefaultAwardConfigs missing"),
            ("GetAwardConfig", "params.go: GetAwardConfig present", "params.go: GetAwardConfig missing"),
            ("!:AwardPermissions", "params.go: AwardPermissions removed", "params.go: AwardPermissions still present"),
        ],
    )

    # module.go: Award handler
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "module" / "module.go",
        [
            ("func (am AppModule) Award(", "module.go: Award handler present", "module.go: Award handler missing"),
            ("BurnFromAccount", "module.go: BurnFromAccount in Award handler", "module.go: burn call missing"),
        ],
    )

    # Upgrade handler
    _check(
        REPO_ROOT / "blockchain" / "app" / "upgrades.go",
        [
            (
                '"v1.15.0"',
                "upgrades.go: v1.15.0 upgrade handler registered",
                "upgrades.go: v1.15.0 upgrade handler missing",
            ),
        ],
    )

    # ante_metasig.go: MsgAward case
    _check(
        REPO_ROOT / "blockchain" / "app" / "ante_metasig.go",
        [("MsgAward", "ante_metasig.go: MsgAward relay sig verification", "ante_metasig.go: MsgAward case missing")],
    )

    # ante_pow.go: MsgAward rejection + canon builder
    _check(
        REPO_ROOT / "blockchain" / "app" / "ante_pow.go",
        [
            (
                "MsgAward cannot use PoW",
                "ante_pow.go: MsgAward PoW rejection",
                "ante_pow.go: MsgAward PoW rejection missing",
            ),
            (
                "buildCanonForAward",
                "ante_pow.go: buildCanonForAward present",
                "ante_pow.go: buildCanonForAward missing",
            ),
        ],
    )

    # --- Python ---

    # Datatypes: MsgAward, AwardConfig
    _check(
        REPO_ROOT / "shared" / "datatypes.py",
        [
            ("MsgAward", "datatypes.py: MsgAward defined", "datatypes.py: MsgAward missing"),
            ("AwardConfig", "datatypes.py: AwardConfig defined", "datatypes.py: AwardConfig missing"),
            (
                "!:award_permissions",
                "datatypes.py: award_permissions removed",
                "datatypes.py: award_permissions still present",
            ),
        ],
    )

    # Canon: canon_base_award
    _check(
        REPO_ROOT / "shared" / "canon.py",
        [("canon_base_award", "canon.py: canon_base_award present", "canon.py: canon_base_award missing")],
    )

    # Indexer: awards table
    _check(
        REPO_ROOT / "indexer" / "database.py",
        [
            (
                "CREATE TABLE IF NOT EXISTS awards",
                "database.py: awards table defined",
                "database.py: awards table missing",
            ),
            (
                "uniq_awards_owner_target",
                "database.py: unique award constraint",
                "database.py: unique award constraint missing",
            ),
        ],
    )

    # Indexer: _handle_award
    _check(
        REPO_ROOT / "indexer" / "message_processor.py",
        [
            (
                "_handle_award",
                "message_processor.py: _handle_award present",
                "message_processor.py: _handle_award missing",
            ),
            (
                "MsgAward",
                "message_processor.py: MsgAward in TYPE_URL_TO_PROTO",
                "message_processor.py: MsgAward missing from TYPE_URL_TO_PROTO",
            ),
        ],
    )

    # Backend: /api/core/award endpoint
    _check(
        REPO_ROOT / "web" / "backend" / "routes" / "core.py",
        [
            ('"/api/core/award"', "core.py: /api/core/award endpoint", "core.py: /api/core/award endpoint missing"),
            ("cannot award your own post", "core.py: self-award check", "core.py: self-award check missing"),
            ("already awarded this post", "core.py: duplicate award check", "core.py: duplicate award check missing"),
        ],
    )

    # Backend public: _load_award_aggregates, magic scoring A component
    _check(
        REPO_ROOT / "web" / "backend" / "routes" / "public.py",
        [
            (
                "_load_award_aggregates",
                "public.py: _load_award_aggregates present",
                "public.py: _load_award_aggregates missing",
            ),
            (
                "unique_awarders",
                "public.py: unique_awarders in magic scoring",
                "public.py: unique_awarders missing from magic scoring",
            ),
        ],
    )

    # Migration
    _check(
        REPO_ROOT / "indexer" / "migrations" / "v2_0_6_awards.py",
        [("awards", "v2_0_6_awards.py: migration present", "v2_0_6_awards.py: migration missing")],
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
