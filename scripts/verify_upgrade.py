#!/usr/bin/env python3
"""
Verify v1.11.0 chain upgrade — checks ONLY what changed in this release.

What v1.11.0 changed:
- PoW difficulty: bit-count/factor → step-based (0 = base)
- Effective factor: 1000 * (1 + pow_difficulty_step)^difficulty
- pow_difficulty_step: new governable double param (default 0.25)
- subscription_reserve_percent: integer percent → double fraction [0,1]
- bridge_attestation_threshold: basis points → double fraction [0,1]
- Upgrade handler migrates old difficulty values to step counts

General node health (bridge CLI, gov params, tiers, etc.) is covered by tests.
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


UPGRADE_NAME = "v1.11.0"
EXPECTED_VERSION = "v1.11.0"
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
# v1.11.0 specific checks
# ---------------------------------------------------------------------------


def check_binary_version(miraged: str, failures: list[str]) -> None:
    """Binary version must match v1.11.0 (or v1.11.0-*)."""
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


def check_upgrade_applied(miraged: str, rpc: str, failures: list[str]) -> None:
    """v1.11.0 upgrade must be applied (height > 0 in upgrade plan)."""
    print("\n-> Checking v1.11.0 upgrade applied...")
    try:
        result = _run_json([miraged, "q", "upgrade", "applied", UPGRADE_NAME, "--node", rpc, "-o", "json"])
        height = int(result.get("height", 0))
        if height > 0:
            print(f"   [OK] applied at height {height}")
        else:
            print(f"   [FAIL] not applied (height={height})")
            failures.append(f"v1.11.0 upgrade not applied")
    except Exception as e:
        print(f"   [FAIL] {e}")
        failures.append(f"cannot check upgrade state: {e}")


def check_difficulty_steps(miraged: str, rpc: str, failures: list[str]) -> None:
    """current_difficulty must be >= 0 (step-based, not old factor format)."""
    print("\n-> Checking difficulty (step format)...")
    try:
        d = _run_json([miraged, "q", "core", "difficulty", "--node", rpc, "-o", "json"])
        cur = int(d.get("current_difficulty", -1))
        if cur >= 0:
            print(f"   [OK] current_difficulty = {cur} steps")
        else:
            print(f"   [FAIL] current_difficulty = {cur}")
            failures.append(f"current_difficulty must be >= 0, got {cur}")
    except Exception as e:
        print(f"   [FAIL] {e}")
        failures.append(f"cannot check difficulty: {e}")


def check_param_types(miraged: str, rpc: str, failures: list[str]) -> None:
    """Verify v1.11.0 param type changes: new doubles, new pow_difficulty_step."""
    print("\n-> Checking v1.11.0 param types...")
    try:
        raw = _run_json([miraged, "q", "core", "params", "--node", rpc, "-o", "json"])
        params = raw.get("params", raw)
    except Exception as e:
        print(f"   [FAIL] cannot fetch params: {e}")
        failures.append(f"cannot fetch core params: {e}")
        return

    # pow_difficulty_step must exist and be a float in (0, 1]
    step = params.get("pow_difficulty_step")
    if step is not None:
        try:
            fstep = float(step)
            if 0 < fstep <= 1:
                print(f"   [OK] pow_difficulty_step = {fstep}")
            else:
                print(f"   [FAIL] pow_difficulty_step = {fstep} (must be in (0, 1])")
                failures.append(f"pow_difficulty_step out of range: {fstep}")
        except (ValueError, TypeError) as e:
            print(f"   [FAIL] pow_difficulty_step not a valid float: {step!r}")
            failures.append(f"pow_difficulty_step invalid: {step!r}")
    else:
        print("   [FAIL] pow_difficulty_step missing from params")
        failures.append("pow_difficulty_step missing")

    # subscription_reserve_percent must be a float in [0, 1]
    srp = params.get("subscription_reserve_percent")
    if srp is not None:
        try:
            fsrp = float(srp)
            if 0 <= fsrp <= 1:
                print(f"   [OK] subscription_reserve_percent = {fsrp} (double fraction)")
            else:
                print(f"   [FAIL] subscription_reserve_percent = {fsrp} (expected [0, 1])")
                failures.append(f"subscription_reserve_percent out of range: {fsrp}")
        except (ValueError, TypeError):
            print(f"   [FAIL] subscription_reserve_percent not float: {srp!r}")
            failures.append(f"subscription_reserve_percent invalid: {srp!r}")
    else:
        print("   [FAIL] subscription_reserve_percent missing")
        failures.append("subscription_reserve_percent missing")

    # bridge_attestation_threshold must be a float in [0, 1]
    bat = params.get("bridge_attestation_threshold")
    if bat is not None:
        try:
            fbat = float(bat)
            if 0 <= fbat <= 1:
                print(f"   [OK] bridge_attestation_threshold = {fbat} (double fraction)")
            else:
                print(f"   [FAIL] bridge_attestation_threshold = {fbat} (expected [0, 1])")
                failures.append(f"bridge_attestation_threshold out of range: {fbat}")
        except (ValueError, TypeError):
            print(f"   [FAIL] bridge_attestation_threshold not float: {bat!r}")
            failures.append(f"bridge_attestation_threshold invalid: {bat!r}")
    else:
        print("   [FAIL] bridge_attestation_threshold missing")
        failures.append("bridge_attestation_threshold missing")


def check_source_level(failures: list[str]) -> None:
    """Source-level checks — silently skipped when files aren't present."""
    print("\n-> Checking v1.11.0 source changes...")

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
                failures.append(f"v1.11.0: {fail_msg}")

    def _check_absent(path: Path, pattern: str, ok_msg: str, fail_msg: str) -> None:
        nonlocal found_any
        if not path.exists():
            return
        found_any = True
        text = path.read_text()
        hit = bool(re.search(pattern[3:], text, re.DOTALL)) if pattern.startswith("re:") else (pattern in text)
        if not hit:
            print(f"   [OK] {ok_msg}")
        else:
            print(f"   [FAIL] {fail_msg}")
            failures.append(f"v1.11.0: {fail_msg}")

    # Go
    _check(
        REPO_ROOT / "blockchain" / "app" / "upgrades.go",
        [
            ("v1.11.0", "upgrades.go: v1.11.0 handler", "upgrades.go: v1.11.0 handler missing"),
        ],
    )
    _check(
        REPO_ROOT / "blockchain" / "app" / "ante_pow.go",
        [
            (
                "computeDifficultyFactor",
                "ante_pow.go: computeDifficultyFactor",
                "ante_pow.go: computeDifficultyFactor missing",
            ),
            (
                "MaxSafeDifficultyFactor",
                "ante_pow.go: MaxSafeDifficultyFactor cap",
                "ante_pow.go: MaxSafeDifficultyFactor missing",
            ),
        ],
    )
    _check(
        REPO_ROOT / "blockchain" / "x" / "core" / "keeper" / "keeper.go",
        [
            ("BaseDifficultySteps", "keeper.go: BaseDifficultySteps", "keeper.go: BaseDifficultySteps missing"),
            ("BaseDifficultyFactor", "keeper.go: BaseDifficultyFactor", "keeper.go: BaseDifficultyFactor missing"),
        ],
    )

    # Python backend
    _check(
        REPO_ROOT / "web" / "backend" / "pow.py",
        [
            ("_BASE_DIFFICULTY_FACTOR", "pow.py: step-based factor", "pow.py: step-based factor missing"),
            ("pow_difficulty_step", "pow.py: pow_difficulty_step", "pow.py: pow_difficulty_step missing"),
        ],
    )
    _check(
        REPO_ROOT / "web" / "backend" / "params.py",
        [
            (
                "re:_REQUIRED_FLOAT_PARAMS.*pow_difficulty_step",
                "params.py: pow_difficulty_step as float",
                "params.py: pow_difficulty_step not float",
            ),
        ],
    )
    _check_absent(
        REPO_ROOT / "web" / "backend" / "routes" / "core.py",
        r"re:not\s*\(\s*int\(difficulty\)\s*>\s*0\s+and\s+proof\s*\)",
        "core.py: old difficulty=0 rejection removed",
        "core.py: still rejects difficulty=0",
    )

    # Frontend
    _check(
        REPO_ROOT / "web" / "frontend" / "public" / "pow" / "worker.js",
        [
            (
                "BASE_DIFFICULTY_FACTOR",
                "worker.js: BASE_DIFFICULTY_FACTOR",
                "worker.js: BASE_DIFFICULTY_FACTOR missing",
            ),
        ],
    )
    _check(
        REPO_ROOT / "web" / "frontend" / "src" / "utils" / "TransactionHandler.js",
        [
            (
                "pow_difficulty_step",
                "TransactionHandler.js: pow_difficulty_step",
                "TransactionHandler.js: pow_difficulty_step missing",
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
    check_upgrade_applied(miraged, rpc, failures)
    check_difficulty_steps(miraged, rpc, failures)
    check_param_types(miraged, rpc, failures)
    check_source_level(failures)

    print("\n" + "=" * 60)
    if failures:
        print(f"FAILED ({len(failures)} error(s)):")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASSED — v1.11.0 upgrade verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
