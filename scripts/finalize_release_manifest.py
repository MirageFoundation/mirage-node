#!/usr/bin/env python3
"""Validate a CI candidate image, then write and offline-sign release/manifest.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from deploy.release_verify import (  # noqa: E402
    canonical_bytes,
    openssl_sign,
    openssl_verify,
    require_release_policy,
    validate_manifest,
)

DEFAULT_PRIVATE_KEY = REPO_ROOT / ".release_signing.pem"
DEFAULT_PUBLIC_KEY = REPO_ROOT / "deploy" / "hosttools" / "pubkey.pem"
DEFAULT_OUTPUT = REPO_ROOT / "release" / "manifest.json"


def run(command: list[str]) -> str:
    print(f"[release-finalize] run={' '.join(command[:3])}")
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result.stdout


def check_image(manifest: dict) -> None:
    image = manifest["image"]
    expected_digest = image.rsplit("@", 1)[1]
    raw = run(["docker", "buildx", "imagetools", "inspect", image, "--format", "{{json .Manifest}}"])
    try:
        actual_digest = json.loads(raw)["digest"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read registry digest for {image}: {exc}") from exc
    if actual_digest != expected_digest:
        raise SystemExit(f"registry digest mismatch: manifest={expected_digest} registry={actual_digest}")

    files = (
        ("VERSION", "/opt/mirage/VERSION"),
        ("deploy/install.sh", "/opt/mirage/deploy/install.sh"),
        ("deploy/bootstrap_join.py", "/opt/mirage/deploy/bootstrap_join.py"),
        ("deploy/init.sh", "/opt/mirage/deploy/init.sh"),
        ("deploy/entrypoint.sh", "/opt/mirage/deploy/entrypoint.sh"),
        ("deploy/harden_server.sh", "/opt/mirage/deploy/harden_server.sh"),
        ("deploy/release_verify.py", "/opt/mirage/deploy/release_verify.py"),
        ("deploy/hosttools/pubkey.pem", "/opt/mirage/deploy/hosttools/pubkey.pem"),
        ("scripts/status_dashboard.py", "/opt/mirage/scripts/status_dashboard.py"),
        ("deploy/hosttools/mirage-launch", "/opt/mirage/deploy/hosttools/mirage-launch"),
        ("deploy/hosttools/mirage-update", "/opt/mirage/deploy/hosttools/mirage-update"),
        ("release/network.json", "/opt/mirage/release/network.json"),
        ("release/network.json.sig", "/opt/mirage/release/network.json.sig"),
    )
    shell = 'set -e; test "$(cat /opt/mirage/VERSION)" = "$EXPECTED_VERSION"; sha256sum ' + " ".join(
        image_path for _, image_path in files
    )
    output = run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "-e",
            f"EXPECTED_VERSION={manifest['version']}",
            "--entrypoint",
            "/bin/bash",
            image,
            "-lc",
            shell,
        ]
    )
    image_hashes = {}
    for line in output.splitlines():
        digest, image_path = line.split(maxsplit=1)
        image_hashes[image_path] = digest
    for local_path, image_path in files:
        expected = hashlib.sha256((REPO_ROOT / local_path).read_bytes()).hexdigest()
        if image_hashes.get(image_path) != expected:
            raise SystemExit(
                f"candidate payload mismatch for {image_path}: "
                f"image={image_hashes.get(image_path)} local={expected}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="release-manifest.candidate.json from CI")
    parser.add_argument("--private-key", type=Path, default=DEFAULT_PRIVATE_KEY)
    parser.add_argument("--public-key", type=Path, default=DEFAULT_PUBLIC_KEY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    manifest = json.loads(args.candidate.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise SystemExit("candidate manifest must be a JSON object")
    require_release_policy(manifest)

    version = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if manifest["version"] != version:
        raise SystemExit(f"candidate version {manifest['version']} does not match VERSION {version}")
    head = run(["git", "rev-parse", "HEAD"]).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head) or manifest["commit"] != head:
        raise SystemExit(f"candidate commit {manifest['commit']} does not match HEAD {head}")

    network_path = REPO_ROOT / "release" / "network.json"
    network = validate_manifest(json.loads(network_path.read_text(encoding="utf-8")))
    openssl_verify(
        args.public_key,
        canonical_bytes(network),
        network_path.with_suffix(".json.sig").read_bytes(),
    )
    check_image(manifest)
    payload = canonical_bytes(manifest)
    signature = openssl_sign(args.private_key, payload)
    openssl_verify(args.public_key, payload, signature)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    manifest_tmp = args.output.with_suffix(args.output.suffix + ".tmp")
    signature_path = args.output.with_suffix(args.output.suffix + ".sig")
    signature_tmp = signature_path.with_suffix(signature_path.suffix + ".tmp")
    manifest_tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    signature_tmp.write_bytes(signature)
    os.chmod(manifest_tmp, 0o644)
    os.chmod(signature_tmp, 0o644)
    os.replace(manifest_tmp, args.output)
    os.replace(signature_tmp, signature_path)
    print(f"[release-finalize] wrote={args.output}")
    print(f"[release-finalize] wrote={signature_path}")


if __name__ == "__main__":
    main()
