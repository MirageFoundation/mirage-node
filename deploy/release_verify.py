#!/usr/bin/env python3
"""Verify and sign Mirage release/network manifests with the offline Ed25519 key.

Host installers must succeed with only this key (no Fulcio/Rekor). Canonical
form is RFC 8785-ish: UTF-8 JSON, sorted keys, no whitespace.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PUBKEY = Path(__file__).resolve().parent / "hosttools" / "pubkey.pem"


def die(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def canonical_bytes(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"manifest not found: {path}")
    except json.JSONDecodeError as e:
        die(f"manifest is not JSON: {path}: {e}")
    raise AssertionError("unreachable")


def openssl_verify(pubkey: Path, payload: bytes, signature: bytes) -> None:
    if not pubkey.is_file():
        die(f"public key not found: {pubkey}")
    if not signature:
        die("empty signature")
    with tempfile.TemporaryDirectory() as tmp:
        msg_path = Path(tmp) / "msg"
        sig_path = Path(tmp) / "sig"
        msg_path.write_bytes(payload)
        sig_path.write_bytes(signature)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(pubkey),
                "-rawin",
                "-in",
                str(msg_path),
                "-sigfile",
                str(sig_path),
            ],
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "openssl verify failed").strip()
        die(f"signature verification failed: {err}")


def openssl_sign(privkey: Path, payload: bytes) -> bytes:
    if not privkey.is_file():
        die(f"private key not found: {privkey}")
    with tempfile.TemporaryDirectory() as tmp:
        msg_path = Path(tmp) / "msg"
        msg_path.write_bytes(payload)
        result = subprocess.run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                str(privkey),
                "-rawin",
                "-in",
                str(msg_path),
            ],
            capture_output=True,
        )
    if result.returncode != 0:
        err = (result.stderr or b"openssl sign failed").decode("utf-8", "replace").strip()
        die(f"signing failed: {err}")
    if not result.stdout:
        die("signing produced empty signature")
    return result.stdout


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        die(f"{field} is not a UTC timestamp like 2026-08-17T00:00:00Z: {value!r}")
    raise AssertionError("unreachable")


def require_network_policy(manifest: dict) -> None:
    required = {
        "generation",
        "issued_at",
        "expires_at",
        "activation_balance_umirage",
        "self_delegation_umirage",
        "min_liquid_umirage",
        "chain_id",
        "genesis_sha256",
        "min_release",
        "rpc",
        "rest",
        "api",
        "persistent_peers",
    }
    for key in required:
        if key not in manifest:
            die(f"network manifest missing {key}")
    extra = set(manifest) - required
    if extra:
        die(f"network manifest has unknown fields: {', '.join(sorted(extra))}")
    if not isinstance(manifest["generation"], int) or manifest["generation"] < 1:
        die(f"network manifest generation must be a positive integer, got {manifest['generation']!r}")
    for key in ("rpc", "rest", "api"):
        urls = manifest[key]
        if not isinstance(urls, list) or len(urls) < 2:
            die(f"network manifest requires at least two {key} URLs")
        if len(set(urls)) != len(urls):
            die(f"network manifest {key} URLs contain duplicates")
        for url in urls:
            if not isinstance(url, str) or not re.fullmatch(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?", url):
                die(f"network manifest has invalid {key} URL: {url!r}")
    peers = manifest["persistent_peers"]
    if not isinstance(peers, list) or not peers:
        die("network manifest requires at least one persistent peer")
    if len(set(peers)) != len(peers):
        die("network manifest persistent_peers contains duplicates")
    for peer in peers:
        if not isinstance(peer, str) or not re.fullmatch(
            r"[0-9a-f]{40}@(?!0\.0\.0\.0:)(?:\[[0-9A-Fa-f:]+\]|[A-Za-z0-9.-]+):26656",
            peer,
        ):
            die(f"network manifest has invalid persistent peer: {peer!r}")
    if manifest["chain_id"] != "mirage-1":
        die(f"network manifest chain_id must be mirage-1, got {manifest['chain_id']!r}")
    if not isinstance(manifest["genesis_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", manifest["genesis_sha256"]
    ):
        die(f"network manifest has invalid genesis_sha256: {manifest['genesis_sha256']!r}")
    if not isinstance(manifest["min_release"], str) or not re.fullmatch(
        r"v\d+\.\d+\.\d+", manifest["min_release"]
    ):
        die(f"network manifest has invalid min_release: {manifest['min_release']!r}")
    amounts = {}
    for key in ("activation_balance_umirage", "self_delegation_umirage", "min_liquid_umirage"):
        value = manifest[key]
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
            die(f"network manifest has invalid {key}: {value!r}")
        amounts[key] = int(value)
    if amounts["activation_balance_umirage"] < (
        amounts["self_delegation_umirage"] + amounts["min_liquid_umirage"]
    ):
        die("activation balance must cover self-delegation plus the liquid floor")
    issued = parse_timestamp(manifest["issued_at"], "issued_at")
    expires = parse_timestamp(manifest["expires_at"], "expires_at")
    if expires <= issued:
        die(f"network manifest expires_at {manifest['expires_at']} is not after issued_at {manifest['issued_at']}")
    # A signature never expires on its own. Without this check an old manifest,
    # replayed with its still-valid signature, can pin a node to dead peers.
    now = datetime.now(timezone.utc)
    if now >= expires:
        die(f"network manifest expired at {manifest['expires_at']}; the foundation must publish a new generation")


def require_release_policy(manifest: dict) -> None:
    required = {
        "version",
        "release_id",
        "commit",
        "image",
        "min_prior_version",
        "activation",
        "upgrade_name",
        "rollback_safe",
        "consensus_breaking",
    }
    for key in required:
        if key not in manifest:
            die(f"release manifest missing {key}")
    extra = set(manifest) - required
    if extra:
        die(f"release manifest has unknown fields: {', '.join(sorted(extra))}")
    if not re.fullmatch(r"v\d+\.\d+\.\d+", manifest["version"]):
        die(f"release manifest version must be vX.Y.Z, got {manifest['version']!r}")
    if not isinstance(manifest["release_id"], int) or manifest["release_id"] < 1:
        die(f"release manifest release_id must be a positive integer, got {manifest['release_id']!r}")
    if not isinstance(manifest["commit"], str) or not re.fullmatch(r"[0-9a-f]{40}", manifest["commit"]):
        die(f"release manifest has invalid commit: {manifest['commit']!r}")
    if not re.fullmatch(r"ghcr\.io/miragefoundation/mirage-node@sha256:[0-9a-f]{64}", manifest["image"]):
        die(f"release manifest image must be digest-pinned, got {manifest['image']!r}")
    if not isinstance(manifest["min_prior_version"], str) or not re.fullmatch(
        r"v\d+\.\d+\.\d+", manifest["min_prior_version"]
    ):
        die(f"release manifest has invalid min_prior_version: {manifest['min_prior_version']!r}")
    if manifest["activation"] not in ("ordinary", "upgrade-halt"):
        die(f"release manifest activation must be ordinary or upgrade-halt, got {manifest['activation']!r}")
    if not isinstance(manifest["upgrade_name"], str):
        die("release manifest upgrade_name must be a string")
    if not isinstance(manifest["rollback_safe"], bool):
        die("release manifest rollback_safe must be a boolean")
    if not isinstance(manifest["consensus_breaking"], bool):
        die("release manifest consensus_breaking must be a boolean")
    if manifest["activation"] == "ordinary":
        if manifest["upgrade_name"]:
            die("ordinary release manifest must have an empty upgrade_name")
        if manifest["consensus_breaking"]:
            die("a consensus-breaking release must use upgrade-halt activation")
    else:
        if not manifest["upgrade_name"]:
            die("upgrade-halt release manifest requires upgrade_name")
        if not manifest["consensus_breaking"]:
            die("upgrade-halt release manifest must set consensus_breaking=true")
        if manifest["rollback_safe"]:
            die("consensus-breaking release manifest cannot set rollback_safe=true")


def validate_manifest(obj: object) -> dict:
    if not isinstance(obj, dict):
        die("manifest must be a JSON object")
    if "genesis_sha256" in obj:
        require_network_policy(obj)
    else:
        require_release_policy(obj)
    return obj


def cmd_verify(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    sig_path = Path(args.signature) if args.signature else path.with_suffix(path.suffix + ".sig")
    pubkey = Path(args.pubkey)
    obj = validate_manifest(load_json(path))
    try:
        signature = sig_path.read_bytes()
    except FileNotFoundError:
        die(f"signature not found: {sig_path}")
    openssl_verify(pubkey, canonical_bytes(obj), signature)
    if "genesis_sha256" in obj:
        print("verify ok (network)")
    else:
        print(f"verify ok (release {obj['version']} id {obj['release_id']})")


def cmd_sign(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    priv = Path(args.privkey)
    payload = canonical_bytes(validate_manifest(load_json(path)))
    signature = openssl_sign(priv, payload)
    out = Path(args.output) if args.output else path.with_suffix(path.suffix + ".sig")
    out.write_bytes(signature)
    os.chmod(out, 0o644)
    print(f"wrote {out}")


def cmd_canonical(args: argparse.Namespace) -> None:
    path = Path(args.manifest)
    sys.stdout.buffer.write(canonical_bytes(load_json(path)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Sign or verify a Mirage manifest")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify")
    p_verify.add_argument("--manifest", required=True)
    p_verify.add_argument("--signature", default="")
    p_verify.add_argument("--pubkey", default=str(DEFAULT_PUBKEY))
    p_verify.set_defaults(func=cmd_verify)

    p_sign = sub.add_parser("sign")
    p_sign.add_argument("--manifest", required=True)
    p_sign.add_argument("--privkey", required=True)
    p_sign.add_argument("--output", default="")
    p_sign.set_defaults(func=cmd_sign)

    p_canon = sub.add_parser("canonical")
    p_canon.add_argument("--manifest", required=True)
    p_canon.set_defaults(func=cmd_canonical)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
