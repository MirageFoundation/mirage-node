#!/usr/bin/env python3
"""Zero-downtime logical backup of local Mirage data.

Keeps miraged, Caddy, and PostgreSQL online. Dumps are MVCC snapshots; chain
databases and signer watermarks are never included.
"""
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

ROOT = Path("/opt/mirage")
HOME = Path.home()
MIRAGE = HOME / ".mirage"
BACKUP_DIR = MIRAGE / "backups"
LOCK_PATH = MIRAGE / "backup.lock"
ENV_DIR = MIRAGE / "env"


class BackupError(Exception):
    pass


_LOG_STDERR = False


def log(msg: str) -> None:
    stream = sys.stderr if _LOG_STDERR else sys.stdout
    print(msg, file=stream, flush=True)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def acquire_lock() -> int:
    fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        os.close(fd)
        raise BackupError("another backup or restore is already running") from e
    return fd


def node_healthy() -> None:
    result = subprocess.run(
        ["curl", "-fsS", "--max-time", "3", "http://127.0.0.1:26657/status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise BackupError("node RPC became unreachable during backup")
    catching = json.loads(result.stdout)["result"]["sync_info"]["catching_up"]
    if catching is True or catching == "true":
        raise BackupError("node started catching up during backup; aborting")


def read_env_url(name: str) -> str:
    for env_path in sorted(ENV_DIR.glob("*.env")):
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    raise BackupError(f"{name} is missing from env files")


def pg_dump(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "nice",
        "-n",
        "15",
        "ionice",
        "-c",
        "2",
        "-n",
        "7",
        "pg_dump",
        "--format=custom",
        "--compress=6",
        "--no-owner",
        "--no-acl",
        "--dbname",
        url,
        "-f",
        str(dest),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise BackupError(f"pg_dump failed for {dest.name}: {result.stderr.strip()}")


def copy_tree(src: Path, dest: Path, ignore_names: set[str]) -> list[Path]:
    copied: list[Path] = []
    if not src.exists():
        return copied
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in ignore_names]
        rel_root = Path(root).relative_to(src)
        (dest / rel_root).mkdir(parents=True, exist_ok=True)
        for name in files:
            if name in ignore_names:
                continue
            src_file = Path(root) / name
            dest_file = dest / rel_root / name
            shutil.copy2(src_file, dest_file)
            copied.append(dest_file)
    return copied


def release_identity() -> tuple[str, str]:
    manifest = ENV_DIR / "release-manifest.json"
    if not manifest.is_file():
        raise BackupError("release-manifest.json is missing")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return str(data.get("release_id") or ""), str(data.get("image") or "")


def add_entry(entries: list[dict], path: Path, root: Path, kind: str, captured_at: str) -> None:
    rel = str(path.relative_to(root))
    entries.append(
        {
            "path": rel,
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "kind": kind,
            "captured_at": captured_at,
        }
    )


def build_archive(staging: Path, with_media: bool) -> dict:
    entries: list[dict] = []
    node_healthy()
    release_id, image = release_identity()

    dumps = staging / "dumps"
    dumps.mkdir(parents=True, exist_ok=True)
    indexer_url = read_env_url("INDEXER_DB_URL")
    backend_url = read_env_url("BACKEND_DB_URL")
    t0 = utcnow()
    log("dumping indexer database...")
    pg_dump(indexer_url, dumps / "indexer.dump")
    node_healthy()
    add_entry(entries, dumps / "indexer.dump", staging, "pg_dump", t0)
    t1 = utcnow()
    log("dumping backend database...")
    pg_dump(backend_url, dumps / "backend.dump")
    node_healthy()
    add_entry(entries, dumps / "backend.dump", staging, "pg_dump", t1)

    env_dest = staging / "env"
    env_dest.mkdir(parents=True, exist_ok=True)
    t_env = utcnow()
    for src in ENV_DIR.glob("*"):
        if src.is_file():
            shutil.copy2(src, env_dest / src.name)
            add_entry(entries, env_dest / src.name, staging, "env", t_env)

    config_src = MIRAGE / "node" / "config"
    config_dest = staging / "node" / "config"
    t_cfg = utcnow()
    for copied in copy_tree(config_src, config_dest, {"priv_validator_state.json"}):
        add_entry(entries, copied, staging, "config", t_cfg)

    for keyring in MIRAGE.glob("node/keyring-*"):
        dest = staging / "node" / keyring.name
        t_k = utcnow()
        for copied in copy_tree(keyring, dest, set()):
            add_entry(entries, copied, staging, "keyring", t_k)

    if with_media:
        media_src = MIRAGE / "media"
        if media_src.exists():
            t_m = utcnow()
            log("copying finalized media...")
            for copied in copy_tree(media_src, staging / "media", set()):
                add_entry(entries, copied, staging, "media", t_m)
            node_healthy()

    manifest = {
        "schema": "mirage-backup-v1",
        "created_utc": utcnow(),
        "release_id": release_id,
        "image": image,
        "with_media": with_media,
        "contents": entries,
        "excludes": [
            "chain databases",
            "raw PostgreSQL storage",
            "logs",
            "caches",
            "divergence forensics",
            "priv_validator_state.json",
        ],
        "note": "Each component records its own snapshot time. The two databases have separate ownership and are not one instant.",
    }
    manifest_path = staging / "MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    add_entry(entries, manifest_path, staging, "manifest", manifest["created_utc"])
    # Manifest hash of itself is omitted from contents to avoid recursion; rewrite without that last add.
    manifest["contents"] = [e for e in entries if e["path"] != "MANIFEST.json"]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def compress_staging(staging: Path, archive: Path) -> None:
    tar_path = archive.with_suffix("")  # strip .zst later
    # archive is foo.tar.zst
    raw_tar = Path(str(archive)[: -len(".zst")]) if str(archive).endswith(".zst") else archive.with_suffix(".tar")
    log("compressing archive...")
    with tarfile.open(raw_tar, "w") as tar:
        tar.add(staging, arcname=".")
    result = subprocess.run(
        [
            "nice",
            "-n",
            "15",
            "ionice",
            "-c",
            "2",
            "-n",
            "7",
            "zstd",
            "-T0",
            "-19",
            "-f",
            str(raw_tar),
            "-o",
            str(archive),
        ],
        check=False,
    )
    raw_tar.unlink(missing_ok=True)
    if result.returncode != 0:
        raise BackupError("zstd compression failed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a verified online Mirage backup")
    parser.add_argument("--output", help="archive path ending in .tar.zst")
    parser.add_argument("--stdout", action="store_true", help="write the verified archive to stdout")
    parser.add_argument("--with-media", action="store_true", help="include finalized uploaded media")
    args = parser.parse_args()
    if args.output and args.stdout:
        parser.error("--output and --stdout cannot be combined")
    global _LOG_STDERR
    _LOG_STDERR = bool(args.stdout)

    lock_fd = acquire_lock()
    staging = None
    dest = None
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        staging = Path(tempfile.mkdtemp(prefix="mirage-backup-", dir=str(BACKUP_DIR)))
        os.chmod(staging, 0o700)
        manifest = build_archive(staging, args.with_media)
        default_name = f"mirage-backup-{stamp}.tar.zst"
        if args.stdout:
            dest = BACKUP_DIR / f".partial-{default_name}"
        elif args.output:
            dest = Path(args.output)
            if dest.exists():
                raise BackupError(f"refusing to overwrite {dest}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            partial = dest.with_name("." + dest.name + ".partial")
            dest = partial
        else:
            dest = BACKUP_DIR / default_name
            if dest.exists():
                raise BackupError(f"refusing to overwrite {dest}")
            partial = dest.with_name("." + dest.name + ".partial")
            dest = partial
        dest.parent.mkdir(parents=True, exist_ok=True)
        compress_staging(staging, dest)
        digest = sha256_file(dest)
        (dest.parent / (dest.name + ".sha256")).write_text(digest + "\n", encoding="utf-8")
        os.chmod(dest, 0o600)
        if args.stdout:
            with dest.open("rb") as fh:
                shutil.copyfileobj(fh, sys.stdout.buffer)
            dest.unlink()
            (dest.parent / (dest.name + ".sha256")).unlink(missing_ok=True)
            return 0
        final = Path(args.output) if args.output else BACKUP_DIR / default_name
        os.replace(dest, final)
        sha_src = dest.parent / (dest.name + ".sha256")
        sha_dst = final.with_name(final.name + ".sha256")
        if sha_src.exists():
            os.replace(sha_src, sha_dst)
        else:
            sha_dst.write_text(digest + "\n", encoding="utf-8")
            os.chmod(sha_dst, 0o600)
        os.chmod(final, 0o600)
        log(f"backup written: {final}")
        log(f"sha256: {digest}")
        log(f"release: {manifest.get('release_id')} {manifest.get('image')}")
        log("this archive is secret operational material; copy it off-server")
        return 0
    except BackupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        if dest is not None:
            Path(str(dest)).unlink(missing_ok=True)
            Path(str(dest) + ".sha256").unlink(missing_ok=True)
        return 1
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
