#!/usr/bin/env python3
"""
Verify v1.13.0 chain upgrade — checks ONLY what changed in this release.

What v1.13.0 changed:
- Topic blocking: new MsgBlockTopic / MsgUnblockTopic message types
- TierConfig: max_quality_posts (field 7) renamed to max_blocked_topics
- Tier limits: 10 (free) / 125 (T1) / 500 (T2) / 1000 (T3)
- KV store: plist_quality/ prefix replaced with plist_btopics/
- Keeper: quality_posts helpers replaced with blocked_topics helpers
- Indexer: quality_posts table replaced with blocked_topics table
- quality_posts feature fully removed
- Upgrade handler: updates tier params + cleans up orphaned plist_quality/ data
- Follow/block mutual exclusion: blocking removes follow and vice versa
- Relay ante handler: MsgBlockTopic/MsgUnblockTopic routed through relay ante
- Relay ante handler: CheckTx enforces min-gas-prices for relay txs
- Indexer: block removes follow / follow removes block in DB
- Frontend: /follows and /blocks routes, unfollow/unblock UI, tx.js exports
- MintQuantity: 350 MIRAGE → 125,000 MIRAGE per 10min (~357x increase)
- Server page: 24h minting earnings display

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


UPGRADE_NAME = "v1.13.0"
EXPECTED_VERSION = "v1.13.0"
REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_MAX_BLOCKED_TOPICS = [10, 125, 500, 1000]


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
    """Verify core params: tiers have correct max_blocked_topics values."""
    print("\n-> Checking core params...")
    try:
        raw = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        params = raw.get("params", raw)
    except Exception as e:
        print(f"   [FAIL] cannot fetch params: {e}")
        failures.append(f"cannot fetch core params: {e}")
        return

    tiers = params.get("tiers")
    if not tiers or len(tiers) < 4:
        print(f"   [FAIL] tiers missing or incomplete (got {len(tiers) if tiers else 0}, need 4)")
        failures.append("tiers missing or incomplete")
        return

    print(f"   [OK] tiers = {len(tiers)} tiers")

    # Verify max_blocked_topics for each tier
    actual_limits = []
    for i, tier in enumerate(tiers[:4]):
        val = tier.get("max_blocked_topics", 0)
        actual_limits.append(int(val))

    if actual_limits == EXPECTED_MAX_BLOCKED_TOPICS:
        print(f"   [OK] max_blocked_topics = {actual_limits}")
    else:
        print(f"   [FAIL] max_blocked_topics = {actual_limits} (expected {EXPECTED_MAX_BLOCKED_TOPICS})")
        failures.append(f"max_blocked_topics {actual_limits} != {EXPECTED_MAX_BLOCKED_TOPICS}")

    # Verify the old max_quality_posts field is gone
    for i, tier in enumerate(tiers[:4]):
        if "max_quality_posts" in tier:
            print(f"   [FAIL] tier {i} still has max_quality_posts key")
            failures.append(f"tier {i} still has max_quality_posts")

    # Verify MintQuantity is 125,000 MIRAGE (125_000_000_000 umirage)
    mint_qty = params.get("mint_quantity")
    if mint_qty is not None:
        try:
            mq = int(mint_qty)
            if mq == 125_000_000_000:
                print(f"   [OK] mint_quantity = {mq} (125,000 MIRAGE)")
            else:
                print(f"   [FAIL] mint_quantity = {mq} (expected 125000000000)")
                failures.append(f"mint_quantity {mq} != 125000000000")
        except (ValueError, TypeError):
            print(f"   [FAIL] mint_quantity not a valid int: {mint_qty!r}")
            failures.append(f"mint_quantity invalid: {mint_qty!r}")
    else:
        print("   [FAIL] mint_quantity missing from params")
        failures.append("mint_quantity missing")

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
    """Source-level checks for v1.13.0 — silently skipped when files aren't present."""
    print("\n-> Checking v1.13.0 source changes...")

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
                failures.append(f"v1.13.0: {fail_msg}")

    # --- Blockchain (Go) ---

    # Module: BlockTopic / UnblockTopic handlers + topic validation + mutual exclusion
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "module" / "module.go",
        [
            (
                "BlockTopic",
                "module.go: BlockTopic handler present",
                "module.go: BlockTopic handler missing",
            ),
            (
                "UnblockTopic",
                "module.go: UnblockTopic handler present",
                "module.go: UnblockTopic handler missing",
            ),
            (
                "validateTopic",
                "module.go: validateTopic function present",
                "module.go: validateTopic function missing",
            ),
            (
                "BlockUser removed follow",
                "module.go: BlockUser removes followed user (mutual exclusion)",
                "module.go: BlockUser->unfollow mutual exclusion missing",
            ),
            (
                "BlockTopic removed follow",
                "module.go: BlockTopic removes followed topic (mutual exclusion)",
                "module.go: BlockTopic->unfollow mutual exclusion missing",
            ),
            (
                "FollowUser removed block",
                "module.go: FollowUser removes blocked user (mutual exclusion)",
                "module.go: FollowUser->unblock mutual exclusion missing",
            ),
            (
                "FollowTopic removed block",
                "module.go: FollowTopic removes blocked topic (mutual exclusion)",
                "module.go: FollowTopic->unblock mutual exclusion missing",
            ),
        ],
    )

    # App: relay ante handler routes BlockTopic/UnblockTopic
    _check(
        REPO_ROOT / "blockchain" / "app" / "app.go",
        [
            (
                "*coretypes.MsgBlockTopic",
                "app.go: MsgBlockTopic in relay ante allowlist",
                "app.go: MsgBlockTopic missing from relay ante allowlist",
            ),
            (
                "*coretypes.MsgUnblockTopic",
                "app.go: MsgUnblockTopic in relay ante allowlist",
                "app.go: MsgUnblockTopic missing from relay ante allowlist",
            ),
        ],
    )

    # Keeper: blocked_topics helpers + plist_btopics prefix
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "keeper" / "keeper.go",
        [
            (
                "SetProfileBlockedTopics",
                "keeper.go: SetProfileBlockedTopics present",
                "keeper.go: SetProfileBlockedTopics missing",
            ),
            (
                "GetProfileBlockedTopics",
                "keeper.go: GetProfileBlockedTopics present",
                "keeper.go: GetProfileBlockedTopics missing",
            ),
            (
                "plist_btopics/",
                "keeper.go: plist_btopics/ KV prefix present",
                "keeper.go: plist_btopics/ KV prefix missing",
            ),
            (
                "!:plist_quality/",
                "keeper.go: plist_quality/ removed",
                "keeper.go: plist_quality/ still present (should be removed)",
            ),
            (
                "!:SetProfileQualityPosts",
                "keeper.go: SetProfileQualityPosts removed",
                "keeper.go: SetProfileQualityPosts still present (should be removed)",
            ),
        ],
    )

    # Ante handler: signature verification for topic blocking
    _check(
        REPO_ROOT / "blockchain" / "app" / "ante_metasig.go",
        [
            (
                "MsgBlockTopic",
                "ante_metasig.go: MsgBlockTopic signature verification",
                "ante_metasig.go: MsgBlockTopic signature verification missing",
            ),
            (
                "MsgUnblockTopic",
                "ante_metasig.go: MsgUnblockTopic signature verification",
                "ante_metasig.go: MsgUnblockTopic signature verification missing",
            ),
            (
                "CheckTx enforces min-gas",
                "ante_metasig.go: relay CheckTx min-gas enforcement noted",
                "ante_metasig.go: relay CheckTx min-gas enforcement missing",
            ),
        ],
    )

    # Ante handler: PoW validation for topic blocking
    _check(
        REPO_ROOT / "blockchain" / "app" / "ante_pow.go",
        [
            (
                "MsgBlockTopic",
                "ante_pow.go: MsgBlockTopic PoW validation",
                "ante_pow.go: MsgBlockTopic PoW validation missing",
            ),
            (
                "buildCanonForBlockTopic",
                "ante_pow.go: buildCanonForBlockTopic helper",
                "ante_pow.go: buildCanonForBlockTopic helper missing",
            ),
            (
                "buildCanonForUnblockTopic",
                "ante_pow.go: buildCanonForUnblockTopic helper",
                "ante_pow.go: buildCanonForUnblockTopic helper missing",
            ),
        ],
    )

    # Codec: message registration
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "codec.go",
        [
            (
                "MsgBlockTopic",
                "codec.go: MsgBlockTopic registered",
                "codec.go: MsgBlockTopic registration missing",
            ),
            (
                "MsgUnblockTopic",
                "codec.go: MsgUnblockTopic registered",
                "codec.go: MsgUnblockTopic registration missing",
            ),
        ],
    )

    # Upgrade handler
    _check(
        REPO_ROOT / "blockchain" / "app" / "upgrades.go",
        [
            (
                '"v1.13.0"',
                "upgrades.go: v1.13.0 upgrade handler registered",
                "upgrades.go: v1.13.0 upgrade handler missing",
            ),
            (
                "MaxBlockedTopics",
                "upgrades.go: MaxBlockedTopics migration in upgrade handler",
                "upgrades.go: MaxBlockedTopics migration missing from upgrade handler",
            ),
            (
                "plist_quality",
                "upgrades.go: plist_quality cleanup in upgrade handler",
                "upgrades.go: plist_quality cleanup missing from upgrade handler",
            ),
            (
                "125_000_000_000",
                "upgrades.go: MintQuantity updated to 125,000 MIRAGE in upgrade handler",
                "upgrades.go: MintQuantity 125,000 MIRAGE migration missing from upgrade handler",
            ),
        ],
    )

    # Params default: MintQuantity should be 125,000 MIRAGE
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "types" / "params.go",
        [
            (
                "125_000_000_000",
                "params.go: DefaultMintQuantity = 125,000 MIRAGE",
                "params.go: DefaultMintQuantity not set to 125,000 MIRAGE",
            ),
        ],
    )

    # Proto: MsgBlockTopic / MsgUnblockTopic definitions
    _check(
        REPO_ROOT / "blockchain" / "proto" / "mirage" / "core" / "v1" / "tx.proto",
        [
            (
                "MsgBlockTopic",
                "tx.proto: MsgBlockTopic defined",
                "tx.proto: MsgBlockTopic missing",
            ),
            (
                "MsgUnblockTopic",
                "tx.proto: MsgUnblockTopic defined",
                "tx.proto: MsgUnblockTopic missing",
            ),
        ],
    )

    # Proto: max_blocked_topics in TierConfig (was max_quality_posts)
    _check(
        REPO_ROOT / "blockchain" / "proto" / "mirage" / "core" / "v1" / "params.proto",
        [
            (
                "max_blocked_topics",
                "params.proto: max_blocked_topics field present",
                "params.proto: max_blocked_topics field missing",
            ),
            (
                "!:max_quality_posts",
                "params.proto: max_quality_posts removed",
                "params.proto: max_quality_posts still present (should be renamed)",
            ),
        ],
    )

    # --- Python ---

    # Canon: block_topic canonical encoding
    _check(
        REPO_ROOT / "shared" / "canon.py",
        [
            (
                "block_topic",
                "canon.py: block_topic canonical encoding present",
                "canon.py: block_topic canonical encoding missing",
            ),
            (
                "unblock_topic",
                "canon.py: unblock_topic canonical encoding present",
                "canon.py: unblock_topic canonical encoding missing",
            ),
        ],
    )

    # Datatypes: blocked_topics field
    _check(
        REPO_ROOT / "shared" / "datatypes.py",
        [
            (
                "blocked_topics",
                "datatypes.py: blocked_topics field present",
                "datatypes.py: blocked_topics field missing",
            ),
            (
                "!:quality_posts",
                "datatypes.py: quality_posts removed",
                "datatypes.py: quality_posts still present (should be removed)",
            ),
        ],
    )

    # Indexer: blocked_topics table
    _check(
        REPO_ROOT / "indexer" / "database.py",
        [
            (
                "blocked_topics",
                "database.py: blocked_topics table in indexer",
                "database.py: blocked_topics table missing from indexer",
            ),
            (
                "!:quality_posts",
                "database.py: quality_posts removed from indexer",
                "database.py: quality_posts still present in indexer (should be removed)",
            ),
        ],
    )

    # Indexer: mutual exclusion (block removes follow, follow removes block)
    _check(
        REPO_ROOT / "indexer" / "message_processor.py",
        [
            (
                "Block user removed follow",
                "message_processor.py: block_user removes follow in indexer",
                "message_processor.py: block_user->unfollow missing in indexer",
            ),
            (
                "Block topic removed follow",
                "message_processor.py: block_topic removes follow in indexer",
                "message_processor.py: block_topic->unfollow missing in indexer",
            ),
            (
                "Follow user removed block",
                "message_processor.py: follow_user removes block in indexer",
                "message_processor.py: follow_user->unblock missing in indexer",
            ),
            (
                "Follow topic removed block",
                "message_processor.py: follow_topic removes block in indexer",
                "message_processor.py: follow_topic->unblock missing in indexer",
            ),
        ],
    )

    # Backend: block_topic / unblock_topic endpoints
    _check(
        REPO_ROOT / "web" / "backend" / "routes" / "core.py",
        [
            (
                "block_topic",
                "core.py: block_topic endpoint present",
                "core.py: block_topic endpoint missing",
            ),
            (
                "unblock_topic",
                "core.py: unblock_topic endpoint present",
                "core.py: unblock_topic endpoint missing",
            ),
        ],
    )

    # Backend public: blocked_topics in get_user_blocked + earned_24h in get_network_stats
    _check(
        REPO_ROOT / "web" / "backend" / "routes" / "public.py",
        [
            (
                "blocked_topics",
                "public.py: blocked_topics in get_user_blocked",
                "public.py: blocked_topics missing from get_user_blocked",
            ),
            (
                '"earned_24h"',
                "public.py: earned_24h in get_network_stats response",
                "public.py: earned_24h missing from get_network_stats response",
            ),
        ],
    )

    # --- Frontend ---

    # TransactionHandler: blockTopic / unblockTopic methods
    _check(
        REPO_ROOT / "web" / "frontend" / "src" / "utils" / "TransactionHandler.js",
        [
            (
                "blockTopic",
                "TransactionHandler.js: blockTopic method present",
                "TransactionHandler.js: blockTopic method missing",
            ),
            (
                "unblockTopic",
                "TransactionHandler.js: unblockTopic method present",
                "TransactionHandler.js: unblockTopic method missing",
            ),
            (
                "MsgBlockTopic",
                "TransactionHandler.js: MsgBlockTopic canonical signing",
                "TransactionHandler.js: MsgBlockTopic canonical signing missing",
            ),
        ],
    )

    # tx.js: follow/unfollow/block/unblock exports
    _check(
        REPO_ROOT / "web" / "frontend" / "src" / "utils" / "tx.js",
        [
            (
                "unfollowTopic",
                "tx.js: unfollowTopic export present",
                "tx.js: unfollowTopic export missing",
            ),
            (
                "unfollowUser",
                "tx.js: unfollowUser export present",
                "tx.js: unfollowUser export missing",
            ),
            (
                "unblockUser",
                "tx.js: unblockUser export present",
                "tx.js: unblockUser export missing",
            ),
            (
                "unblockTopic",
                "tx.js: unblockTopic export present",
                "tx.js: unblockTopic export missing",
            ),
        ],
    )

    # NetworkView: 24h minting earnings display
    _check(
        REPO_ROOT / "web" / "frontend" / "src" / "views" / "NetworkView.js",
        [
            (
                "Earned (24h)",
                "NetworkView.js: 24h minting earnings display present",
                "NetworkView.js: 24h minting earnings display missing",
            ),
        ],
    )

    # App.js: /follows and /blocks routes
    _check(
        REPO_ROOT / "web" / "frontend" / "src" / "App.js",
        [
            (
                "/follows",
                "App.js: /follows route present",
                "App.js: /follows route missing",
            ),
            (
                "/blocks",
                "App.js: /blocks route present",
                "App.js: /blocks route missing",
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
