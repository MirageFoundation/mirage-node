#!/usr/bin/env python3
"""Post-deploy verification for the v1.37.0 installer setup-questions release."""

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


def bash(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, **(env or {})},
    )


def installer_functions() -> str:
    """The installer's functions with its final main call removed."""
    lines = (ROOT / "deploy/install.sh").read_text(encoding="utf-8").splitlines()
    if lines[-1].strip() != 'main "$@"':
        raise RuntimeError('install.sh no longer ends with main "$@"')
    return "\n".join(lines[:-1]) + "\n"


def check_setup_questions() -> None:
    """v1.37.0 asks the operator for a name, a domain and an uploads policy.

    Every question has to be answerable from the environment, or an unattended
    install blocks forever on a prompt nobody is there to see.
    """
    install = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")

    if re.search(r"if ! state_at_least configured; then\n\s+prompt_settings\n\s+configure\n", install):
        ok("the questions are asked once, immediately before the node is configured")
    else:
        fail("prompt_settings does not run exactly once before configure")

    script = (
        installer_functions()
        + 'USERNAME=fallback-name\nPUBLIC_IP=203.0.113.7\n'
        + 'prompt_settings >/dev/null\n'
        + 'printf "%s|%s|%s" "$MONIKER_CHOICE" "$DOMAIN_ARG" "$MEDIA_UPLOADS"\n'
    )
    answered = bash(script, {"MIRAGE_MONIKER": "chosen-name", "MIRAGE_DOMAIN": "", "MIRAGE_MEDIA_UPLOADS": "yes"})
    if answered.returncode == 0 and answered.stdout == "chosen-name||true":
        ok("answers supplied by environment variables are taken without prompting")
    else:
        fail(f"env-answered setup returned rc={answered.returncode} out={answered.stdout!r}")

    defaults = bash(script, {"MIRAGE_MONIKER": "", "MIRAGE_DOMAIN": "", "MIRAGE_MEDIA_UPLOADS": ""})
    if defaults.returncode == 0 and defaults.stdout == "fallback-name||false":
        ok("empty answers default to the account username, no domain and uploads off")
    else:
        fail(f"default setup returned rc={defaults.returncode} out={defaults.stdout!r}")

    rejected = bash(script, {"MIRAGE_MONIKER": "", "MIRAGE_DOMAIN": "", "MIRAGE_MEDIA_UPLOADS": "maybe"})
    if rejected.returncode != 0 and "ERROR" in rejected.stderr:
        ok("an answer that is neither yes nor no stops the install by name")
    else:
        fail("the uploads question accepts an answer it cannot interpret")

    # A domain that does not resolve is a warning, never an abort: getent exits 2
    # for an unknown name and pipefail turned that into a bare failure.
    unresolved = bash(
        installer_functions() + 'PUBLIC_IP=203.0.113.7\nwarn_domain_dns nonexistent.invalid\n'
    )
    if unresolved.returncode == 0 and "does not resolve yet" in unresolved.stderr:
        ok("a domain with no DNS record warns and continues")
    else:
        fail(f"unresolved domain returned rc={unresolved.returncode} err={unresolved.stderr[-160:]!r}")


def check_answers_are_persisted() -> None:
    """The answers have to reach the file whose reader looks for them."""
    install = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    required = (
        'write_env_key MONIKER "$MONIKER_CHOICE"',
        "write_env_key WATCHDOG_AUTORECOVER true",
        'write_env_key MEDIA_UPLOADS_ENABLED "$MEDIA_UPLOADS" /root/.mirage/env/backend.env',
    )
    missing = [line for line in required if line not in install]
    if missing:
        fail(f"configure does not persist: {missing}")
    else:
        ok("name, recovery policy and uploads policy are written to their own env files")

    if 'write_env_key MONIKER "$USERNAME"' in install:
        fail("configure still writes the username over the operator's chosen name")
    else:
        ok("the chosen name is no longer overwritten by the account username")

    template = (ROOT / "deploy/templates/env/frontend.env").read_text(encoding="utf-8")
    if re.search(r"^VITE_API_BASE=\s*$", template, re.MULTILINE):
        ok("a fresh node's frontend config points at itself, not another operator's node")
    else:
        fail("the frontend template still ships a node URL")


def check_moniker_precedence() -> None:
    """A name the operator chose must survive a domain being set.

    init.sh overwrote MONIKER with https://DOMAIN whenever a domain was present,
    and that value is what create_validator.sh records on-chain at registration.
    """
    init_sh = (ROOT / "deploy/init.sh").read_text(encoding="utf-8")
    if 'if [ -z "${MONIKER:-}" ] && [ -n "${DOMAIN:-}" ]; then' not in init_sh:
        fail("init.sh no longer guards the domain-derived name behind an unset name")
        return

    lines = init_sh.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith('if [ -z "${MONIKER:-}" ]'))
    end = next(i for i, line in enumerate(lines[start:], start) if line == 'MONIKER="${MONIKER:-validator}"')
    snippet = "\n".join(lines[start : end + 1]) + '\nprintf %s "$MONIKER"\n'
    for moniker, domain, expected in (
        ("chosen", "example.com", "chosen"),
        ("", "example.com", "https://example.com"),
        ("", "", "validator"),
    ):
        result = bash(snippet, {"MONIKER": moniker, "DOMAIN": domain})
        if result.returncode != 0 or result.stdout != expected:
            fail(f"MONIKER={moniker!r} DOMAIN={domain!r} rendered {result.stdout!r}, expected {expected!r}")
            return
    ok("an explicit name wins over the domain, which is only the unnamed default")


def check_harden_pin() -> None:
    """install.sh changed this release, and a stale pin refuses every install."""
    install = (ROOT / "deploy/install.sh").read_text(encoding="utf-8")
    pin = re.search(r'^EXPECTED_HARDEN_SHA256="([0-9a-f]{64})"$', install, re.MULTILINE)
    actual = hashlib.sha256((ROOT / "deploy/harden_server.sh").read_bytes()).hexdigest()
    if pin and pin.group(1) == actual:
        ok("installer's pinned hardening hash matches the deployed script")
    else:
        fail(f"pinned hardening hash is stale: pin={pin.group(1) if pin else None} actual={actual}")


def main() -> int:
    print(f"verify_upgrade.py for {VERSION} (handler registered; no live chain plan)")
    checks = (
        check_versions,
        check_no_upgrade_plan,
        check_progress,
        check_manifests,
        check_installer_payload,
        check_setup_questions,
        check_answers_are_persisted,
        check_moniker_precedence,
        check_harden_pin,
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
