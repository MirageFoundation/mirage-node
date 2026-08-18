#!/usr/bin/env python3
"""Post-deploy verification for the v1.36.4 public validator installer release."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path("/opt/mirage")
if not ROOT.is_dir():
    ROOT = Path(__file__).resolve().parent.parent

VERSION = "v1.36.4"
RPC = "http://127.0.0.1:26657"
REST = "http://127.0.0.1:1317"
passed = 0
failed = 0


def ok(message: str) -> None:
    global passed
    passed += 1
    print(f"  PASS  {message}")


def fail(message: str) -> None:
    global failed
    failed += 1
    print(f"  FAIL  {message}")


def http_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode())


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout


def check_versions() -> None:
    release = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if release == VERSION:
        ok(f"VERSION={release}")
    else:
        fail(f"VERSION={release!r}, expected {VERSION}")

    frontend = (ROOT / "web/frontend/build/version.txt").read_text(encoding="utf-8").strip()
    if frontend == VERSION:
        ok(f"frontend version={frontend}")
    else:
        fail(f"frontend version={frontend!r}, expected {VERSION}")

    output = run([str(ROOT / "blockchain/bin/miraged"), "version", "--long"])
    reported = next((line.split(":", 1)[1].strip() for line in output.splitlines() if line.startswith("version:")), "")
    if reported.lstrip("v") == VERSION.lstrip("v"):
        ok(f"chain binary version={reported}")
    else:
        fail(f"chain binary version={reported!r}, expected {VERSION}")


def check_no_upgrade_plan() -> None:
    plan = http_json(f"{REST}/cosmos/upgrade/v1beta1/current_plan").get("plan")
    if plan:
        fail(f"unexpected software-upgrade plan: {plan}")
    else:
        ok("no software-upgrade plan scheduled")


def comet_height() -> int:
    return int(http_json(f"{RPC}/status")["result"]["sync_info"]["latest_block_height"])


def check_progress() -> None:
    first = comet_height()
    time.sleep(8)
    second = comet_height()
    if second > first:
        ok(f"chain advancing: {first} -> {second}")
    else:
        fail(f"chain stalled at {second}")

    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        fail("INDEXER_DB_URL missing from deployed environment")
        return
    import psycopg

    def indexed_height() -> int:
        with psycopg.connect(db_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT value FROM meta WHERE key = 'last_height'")
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("indexer meta.last_height is missing")
        return int(row[0])

    indexed_first = indexed_height()
    time.sleep(10)
    indexed_second = indexed_height()
    if indexed_second > indexed_first:
        ok(f"indexer advancing: {indexed_first} -> {indexed_second}")
    else:
        fail(f"indexer stalled at {indexed_second}")


def verify_manifest(path: Path) -> dict:
    output = run(
        [
            sys.executable,
            str(ROOT / "deploy/release_verify.py"),
            "verify",
            "--manifest",
            str(path),
            "--pubkey",
            str(ROOT / "deploy/hosttools/pubkey.pem"),
        ]
    )
    ok(output.strip())
    return json.loads(path.read_text(encoding="utf-8"))


def check_manifests() -> None:
    network = verify_manifest(ROOT / "release/network.json")
    release = verify_manifest(ROOT / "release/manifest.json")

    if network["generation"] == 2 and network["min_release"] == VERSION:
        ok("network policy generation and minimum release are current")
    else:
        fail(
            f"network policy generation/min_release={network['generation']}/{network['min_release']}, "
            f"expected 2/{VERSION}"
        )
    if len(network["persistent_peers"]) == 4:
        ok("signed network policy contains all four persistent peers")
    else:
        fail(f"signed network policy contains {len(network['persistent_peers'])} peers, expected 4")

    if release["version"] != VERSION:
        fail(f"release manifest version={release['version']!r}, expected {VERSION}")
    elif not re.fullmatch(r"ghcr\.io/miragefoundation/mirage-node@sha256:[0-9a-f]{64}", release["image"]):
        fail(f"release image is not digest-pinned: {release['image']!r}")
    elif release["activation"] != "ordinary" or release["consensus_breaking"]:
        fail("v1.36.4 release manifest must be ordinary and non-consensus-breaking")
    else:
        ok("release manifest is ordinary, non-consensus-breaking and digest-pinned")


def check_installer_payload() -> None:
    required = [
        ROOT / "deploy/install.sh",
        ROOT / "deploy/harden_server.sh",
        ROOT / "deploy/release_verify.py",
        ROOT / "deploy/hosttools/mirage-launch",
        ROOT / "deploy/hosttools/mirage-update",
        ROOT / "deploy/hosttools/mirage-enroll",
        ROOT / "deploy/hosttools/pubkey.pem",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        fail(f"installer payload missing: {missing}")
        return
    run(["bash", "-n", *(str(path) for path in required if path.suffix == ".sh" or path.name.startswith("mirage-"))])
    ok("installer and host-tool payload is complete with valid shell syntax")

    install_text = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    update_text = (ROOT / "deploy/hosttools/mirage-update").read_text(encoding="utf-8")
    if "</dev/tty" in install_text and "EXPECTED_VERIFY_SHA256" in install_text:
        ok("one-line installer uses the controlling TTY and hash-pins bootstrap helpers")
    else:
        fail("one-line installer TTY or bootstrap hash pin missing")
    if "install_hosttools_from_image" in update_text and "staged_rollback_safe" in update_text:
        ok("updater refreshes host tools and enforces signed rollback policy")
    else:
        fail("updater host-tool refresh or rollback policy missing")


def check_transaction_policy() -> None:
    create_validator = (ROOT / "deploy/create_validator.sh").read_text(encoding="utf-8")
    stake = (ROOT / "scripts/stake.py").read_text(encoding="utf-8")
    if "--unordered --timeout-duration 2m" in create_validator:
        ok("validator registration uses an unordered transaction")
    else:
        fail("validator registration is not unordered")
    if '"--unordered"' in stake and '"--timeout-duration"' in stake:
        ok("additional self-delegation uses an unordered transaction")
    else:
        fail("additional self-delegation is not unordered")


def main() -> int:
    print(f"verify_upgrade.py for {VERSION} (ordinary release; no chain upgrade)")
    checks = (
        check_versions,
        check_no_upgrade_plan,
        check_progress,
        check_manifests,
        check_installer_payload,
        check_transaction_policy,
    )
    for check in checks:
        try:
            check()
        except Exception as error:
            fail(f"{check.__name__}: {error}")
    print(f"\nResult: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
