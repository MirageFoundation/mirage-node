#!/usr/bin/env python3
"""Post-deploy verification for the v1.37.0 installer and recovery-hardening release."""

from __future__ import annotations

import hashlib
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

VERSION = "v1.37.0"
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


def _bash_function(text: str, name: str) -> str:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line == f"{name}() {{")
    end = next(i for i, line in enumerate(lines[start + 1 :], start + 1) if line == "}")
    return "\n".join(lines[start : end + 1])


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

    if network["generation"] == 2 and network["min_release"] == "v1.36.4":
        ok("network policy generation and minimum release are current")
    else:
        fail(
            f"network policy generation/min_release={network['generation']}/{network['min_release']}, "
            "expected 2/v1.36.4"
        )
    if network["min_release"] != VERSION:
        ok(f"min_release stays at {network['min_release']}: {VERSION} adds no requirement older nodes fail")
    else:
        fail(f"min_release was raised to {VERSION} without a chain-level reason to exclude older nodes")
    if len(network["persistent_peers"]) == 4:
        ok("signed network policy contains all four persistent peers")
    else:
        fail(f"signed network policy contains {len(network['persistent_peers'])} peers, expected 4")

    if release["version"] != VERSION:
        fail(f"release manifest version={release['version']!r}, expected {VERSION}")
    elif not re.fullmatch(r"ghcr\.io/miragefoundation/mirage-node@sha256:[0-9a-f]{64}", release["image"]):
        fail(f"release image is not digest-pinned: {release['image']!r}")
    elif release["activation"] != "ordinary" or release["consensus_breaking"]:
        fail(f"{VERSION} release manifest must be ordinary and non-consensus-breaking")
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
        ROOT / "deploy/load_env_exports.py",
        ROOT / "shared/asn_layout.py",
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
    tick = _bash_function(update_text, "tick")
    activate = _bash_function(update_text, "activate_staged")
    if "install_hosttools_from_image" in tick:
        fail("hourly tick still installs host tools from a staged image")
    elif "install_hosttools_from_image" not in activate:
        fail("activation no longer installs host tools after a healthy launch")
    else:
        ok("host tools install on activation, not on hourly tick")

    entry = (ROOT / "deploy/entrypoint.sh").read_text(encoding="utf-8")
    recover = (ROOT / "scripts/recover.sh").read_text(encoding="utf-8")
    watchdog = (ROOT / "scripts/divergence_watchdog.py").read_text(encoding="utf-8")
    indexer = (ROOT / "indexer/main.py").read_text(encoding="utf-8")
    if "load_env_exports.py" not in entry:
        fail("entrypoint no longer loads env files as literals")
    else:
        ok("entrypoint loads env files as literals")
    if "peer_require_source_ahead" not in recover:
        fail("peer-pull no longer requires a peer strictly ahead of local height")
    else:
        ok("peer-pull refuses unless a peer is strictly ahead")
    if "during upgrade halt; refusing restart/wipe" not in watchdog:
        fail("watchdog no longer refuses destructive recovery on upgrade halt")
    else:
        ok("watchdog treats upgrade halt as a binary swap")
    if "tx.decode_failed" not in indexer or "DecodeError" not in indexer:
        fail("indexer still aborts the block on an undecodable memo")
    else:
        ok("indexer records undecodable memos and continues")


def check_no_release_is_unreachable() -> None:
    """A node any number of releases behind must be able to install this one.

    min_prior_version let a release demand that the node already run the
    immediately preceding one, a value CI derived from tag history rather than
    from any real requirement. A node two releases behind could not comply,
    because only the newest manifest is ever published: the intermediate release
    it was told to install first could not be fetched.
    """
    for relative in ("deploy/hosttools/mirage-update", "deploy/release_verify.py", "release/manifest.schema.json"):
        path = ROOT / relative
        if "min_prior" in path.read_text(encoding="utf-8"):
            fail(f"{relative} still carries a per-step version requirement")
            return
    ok("neither the updater, the verifier nor the schema can demand an intermediate release")

    # This is what a skipped release would have carried, and it is applied by what
    # the node has not run yet rather than by version distance.
    runner = (ROOT / "deploy/migrations/__init__.py").read_text(encoding="utf-8")
    if "key not in completed" in runner:
        ok("deploy migrations are selected by what this node has not applied")
    else:
        fail("deploy migrations are no longer selected by what the node has not applied")


def check_bootstrap_pins() -> None:
    """install.sh hash-pins what it downloads, and a stale pin refuses every install."""
    install = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    for variable, relative in (
        ("EXPECTED_HARDEN_SHA256", "deploy/harden_server.sh"),
        ("EXPECTED_VERIFY_SHA256", "deploy/release_verify.py"),
    ):
        pin = re.search(rf'^{variable}="([0-9a-f]{{64}})"$', install, re.MULTILINE)
        actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if pin and pin.group(1) == actual:
            ok(f"{variable} matches the deployed {Path(relative).name}")
        else:
            fail(f"{variable} is stale: pin={pin.group(1) if pin else None} actual={actual}")


def main() -> int:
    print(f"verify_upgrade.py for {VERSION} (patch release; no chain code, no handler, no plan)")
    checks = (
        check_versions,
        check_no_upgrade_plan,
        check_progress,
        check_manifests,
        check_installer_payload,
        check_no_release_is_unreachable,
        check_bootstrap_pins,
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
