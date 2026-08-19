#!/usr/bin/env python3
"""Verify and restore a Mirage online backup without touching consensus signing."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
MIRAGE = HOME / ".mirage"
BACKUP_DIR = MIRAGE / "backups"
LOCK_PATH = MIRAGE / "backup.lock"
FORBIDDEN_NAMES = {
    "priv_validator_state.json",
    "application.db",
    "blockstore.db",
    "state.db",
    "evidence.db",
    "cs.wal",
    "tx_index.db",
}


class RestoreError(Exception):
    pass


def log(msg: str) -> None:
    print(msg, flush=True)


def acquire_lock() -> int:
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise RestoreError("another backup or restore is already running") from e
    return fd


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def svctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["supervisorctl", "-c", "/etc/supervisor/supervisord.conf", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def extract_archive(archive: Path, dest: Path) -> None:
    if archive.stat().st_mode & 0o077:
        raise RestoreError(f"{archive} must be mode 0600 (group/other bits are set)")
    raw_tar = dest / "archive.tar"
    result = subprocess.run(["zstd", "-d", "-f", str(archive), "-o", str(raw_tar)], check=False)
    if result.returncode != 0:
        raise RestoreError("failed to decompress archive")
    with tarfile.open(raw_tar, "r") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("./"):
                name = name[2:]
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts:
                raise RestoreError(f"refusing path traversal in archive: {member.name}")
            base = Path(name).name
            if base in FORBIDDEN_NAMES or any(part in FORBIDDEN_NAMES for part in parts):
                raise RestoreError(f"archive contains forbidden path {member.name}")
        try:
            tar.extractall(dest / "root", filter="data")
        except (tarfile.OutsideDestinationError, tarfile.FilterError) as e:
            raise RestoreError(f"refusing path traversal in archive: {e}") from e
    raw_tar.unlink()


def verify_extracted(root: Path) -> dict:
    manifest_path = root / "MANIFEST.json"
    if not manifest_path.is_file():
        raise RestoreError("archive missing MANIFEST.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema") != "mirage-backup-v1":
        raise RestoreError(f"unsupported backup schema {manifest.get('schema')!r}")
    if not manifest.get("release_id") or not manifest.get("image"):
        raise RestoreError("archive missing release identity")
    required = ("dumps/indexer.dump", "dumps/backend.dump")
    have = {entry["path"] for entry in manifest["contents"]}
    missing = [path for path in required if path not in have]
    if missing:
        raise RestoreError(f"archive missing required contents: {missing}")
    for entry in manifest["contents"]:
        path = root / entry["path"]
        if not path.is_file():
            raise RestoreError(f"missing {entry['path']}")
        if sha256_file(path) != entry["sha256"]:
            raise RestoreError(f"hash mismatch for {entry['path']}")
        if path.stat().st_size != int(entry["bytes"]):
            raise RestoreError(f"size mismatch for {entry['path']}")
    return manifest


def space_ok(root: Path) -> None:
    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    free = shutil.disk_usage(str(MIRAGE)).free
    if free < total * 2:
        raise RestoreError(f"need at least {total * 2} free bytes under {MIRAGE}, have {free}")


def restore_data(root: Path, manifest: dict) -> None:
    env_src = root / "env"
    if env_src.is_dir():
        dest = MIRAGE / "env"
        dest.mkdir(parents=True, exist_ok=True)
        for src in env_src.iterdir():
            shutil.copy2(src, dest / src.name)
    cfg_src = root / "node" / "config"
    if cfg_src.is_dir():
        dest = MIRAGE / "node" / "config"
        dest.mkdir(parents=True, exist_ok=True)
        for src in cfg_src.rglob("*"):
            if src.is_file() and src.name != "priv_validator_state.json":
                target = dest / src.relative_to(cfg_src)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)
    for keyring in (root / "node").glob("keyring-*"):
        dest = MIRAGE / "node" / keyring.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(keyring, dest)
    if manifest.get("with_media") and (root / "media").exists():
        dest = MIRAGE / "media"
        dest.mkdir(parents=True, exist_ok=True)
        for src in (root / "media").rglob("*"):
            if src.is_file():
                target = dest / src.relative_to(root / "media")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, target)

    from deploy.online_backup import read_env_url

    indexer_url = read_env_url("INDEXER_DB_URL")
    backend_url = read_env_url("BACKEND_DB_URL")
    for dump, url in ((root / "dumps" / "indexer.dump", indexer_url), (root / "dumps" / "backend.dump", backend_url)):
        result = subprocess.run(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-acl", "--dbname", url, str(dump)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RestoreError(f"pg_restore failed for {dump.name}: {result.stderr.strip()}")


def wait_backend(budget: int = 180) -> None:
    start = time.time()
    while time.time() - start < budget:
        result = subprocess.run(
            ["curl", "-sf", "--max-time", "2", "http://127.0.0.1:5000/api/get_node_config"],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            return
        time.sleep(2)
    raise RestoreError("backend did not become healthy after restore")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or restore a Mirage online backup")
    parser.add_argument("backup", help="path to a .tar.zst backup")
    parser.add_argument("--check", action="store_true", help="verify without mutating")
    parser.add_argument("--yes", action="store_true", help="already confirmed by the host wrapper")
    args = parser.parse_args()
    archive = Path(args.backup)
    if not archive.is_file():
        print(f"ERROR: backup not found: {archive}", file=sys.stderr)
        return 1

    lock_fd = acquire_lock()
    extracted = Path(tempfile.mkdtemp(prefix="mirage-restore-", dir=str(BACKUP_DIR)))
    try:
        os.chmod(extracted, 0o700)
        log("decompressing and verifying archive...")
        extract_archive(archive, extracted)
        root = extracted / "root"
        manifest = verify_extracted(root)
        space_ok(root)
        log(f"archive ok: schema={manifest['schema']} files={len(manifest['contents'])}")
        if args.check:
            log("check complete; no changes made")
            return 0
        if not args.yes:
            raise RestoreError("restore requires host confirmation")

        Path("/etc/caddy/.maintenance").write_text("restore\n", encoding="utf-8")
        log("stopping indexer and backend; miraged keeps signing")
        svctl("stop", "indexer", "backend")
        try:
            restore_data(root, manifest)
        except Exception:
            Path("/etc/caddy/.maintenance").unlink(missing_ok=True)
            svctl("start", "indexer")
            svctl("start", "backend")
            raise
        svctl("start", "indexer")
        svctl("start", "backend")
        wait_backend()
        Path("/etc/caddy/.maintenance").unlink(missing_ok=True)
        log("restore complete")
        return 0
    except RestoreError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(extracted, ignore_errors=True)
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
