#!/usr/bin/env python3
"""Refresh the local IP-to-network-class dataset used by network tags.

Downloads the IPtoASN dataset (public domain, PDDL), reduces it to fixed-width
range records with a one-byte class, and writes them to the persistent volume.
The org strings are discarded: only the class is needed at request time, and
dropping them is what keeps the files small enough to mmap cheaply.

Deliberately NOT baked into the image. A baked snapshot ages with the image, so
a node running a two-month-old image would classify against two-month-old data
while reporting nothing wrong, and a refresh written into the container
filesystem would be discarded on the next redeploy. Writing to ~/.mirage/asn
means a refresh survives restarts.

Run at container startup and once daily from entrypoint.sh, mirroring
refresh_edge_ips.py. A failed fetch leaves the previous dataset in place and is
logged; it is never allowed to take down the posting path.

Usage:
    python3 deploy/refresh_asn_db.py [--out DIR] [--url URL] [--force]
"""

from __future__ import annotations

import argparse
import gzip
import ipaddress
import json
import os
import struct
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.asn_class import classify_org  # noqa: E402
from shared.asn_layout import (  # noqa: E402
    CLASS_TO_CODE,
    FORMAT_VERSION,
    HEADER_STRUCT,
    MAGIC_V4,
    MAGIC_V6,
    V4_RECORD,
    V6_RECORD,
)

DEFAULT_URL = "https://iptoasn.com/data/ip2asn-combined.tsv.gz"
DOWNLOAD_TIMEOUT_S = 120

# A truncated download must never be allowed to replace a good dataset. The real
# IPv4 table has hundreds of thousands of ranges, so anything near these floors
# means the fetch or the parse went wrong.
MIN_V4_RECORDS = 100_000
MIN_V6_RECORDS = 10_000


def _log(msg: str) -> None:
    print(f"[refresh_asn_db] {msg}", flush=True)


def _download(url: str) -> bytes:
    _log(f"downloading {url}")
    started = time.time()
    request = urllib.request.Request(url, headers={"User-Agent": "mirage-node/refresh_asn_db"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:
        payload = response.read()
    _log(f"downloaded {len(payload)} bytes in {time.time() - started:.1f}s")
    return payload


def _parse(raw_gz: bytes):
    """Parse the TSV into (v4_records, v6_records), each (start, end, code)."""
    v4 = []
    v6 = []
    skipped_unrouted = 0
    malformed = 0

    text = gzip.decompress(raw_gz).decode("utf-8", errors="replace")
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            malformed += 1
            continue
        start_s, end_s, asn_s, _country, description = parts[0], parts[1], parts[2], parts[3], parts[4]

        # IPtoASN uses AS0 for unrouted space. Leaving those out turns them into
        # gaps, which the lookup reports as "unknown" rather than inventing a
        # class for an address that is not announced by anyone.
        if asn_s.strip() in ("", "0"):
            skipped_unrouted += 1
            continue

        try:
            start_ip = ipaddress.ip_address(start_s)
            end_ip = ipaddress.ip_address(end_s)
        except ValueError:
            malformed += 1
            continue
        if start_ip.version != end_ip.version:
            malformed += 1
            continue

        code = CLASS_TO_CODE[classify_org(description)]
        if start_ip.version == 4:
            v4.append((int(start_ip), int(end_ip), code))
        else:
            # Only the /64 prefix matters, because the client address has
            # already been bucketed to /64 before it is ever classified.
            v6.append((int(start_ip) >> 64, int(end_ip) >> 64, code))

    _log(f"parsed v4={len(v4)} v6={len(v6)} unrouted_skipped={skipped_unrouted} malformed={malformed}")
    return v4, v6


def _disjoint(records):
    """Sort and drop overlaps so binary search is well defined.

    Truncating IPv6 bounds to their high 64 bits collapses every allocation
    finer than a /64 onto the same prefix, so overlaps and exact duplicates are
    expected there rather than exceptional. First range wins, which is stable
    because the input is sorted.
    """
    records.sort(key=lambda r: (r[0], r[1]))
    out = []
    dropped = 0
    for start, end, code in records:
        if out and start <= out[-1][1]:
            if end > out[-1][1] and code == out[-1][2]:
                out[-1] = (out[-1][0], end, code)
            else:
                dropped += 1
            continue
        out.append((start, end, code))
    return out, dropped


def _write_table(path: Path, magic: bytes, record: struct.Struct, rows) -> None:
    """Write header + records to a temp file, then rename over the target."""
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(tmp_fd, "wb") as handle:
            handle.write(HEADER_STRUCT.pack(magic, FORMAT_VERSION, len(rows), 0))
            for start, end, code in rows:
                handle.write(record.pack(start, end, code))
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates at 0600. The dataset is public data and is read by
        # whatever user the backend runs as, which need not be the refresher.
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, str(path))
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    _log(f"wrote {path} ({len(rows)} records, {path.stat().st_size} bytes)")


def refresh(out_dir: Path, url: str, force: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        raw_gz = _download(url)
        v4_raw, v6_raw = _parse(raw_gz)
    except Exception as e:
        existing = (out_dir / "asn_v4.bin").exists()
        _log(f"ERROR: refresh failed: {e}")
        if existing:
            _log("keeping the existing dataset; network class stays available but ages")
            return 0
        _log("no existing dataset; network class will be omitted from tags until this succeeds")
        return 1

    v4, v4_dropped = _disjoint(v4_raw)
    v6, v6_dropped = _disjoint(v6_raw)
    _log(f"disjoint v4={len(v4)} (dropped {v4_dropped}) v6={len(v6)} (dropped {v6_dropped})")

    if not force and (len(v4) < MIN_V4_RECORDS or len(v6) < MIN_V6_RECORDS):
        _log(
            f"ERROR: refusing to install a suspiciously small dataset "
            f"(v4={len(v4)} < {MIN_V4_RECORDS} or v6={len(v6)} < {MIN_V6_RECORDS}); "
            f"keeping the previous one. Use --force to override."
        )
        return 1

    _write_table(out_dir / "asn_v4.bin", MAGIC_V4, V4_RECORD, v4)
    _write_table(out_dir / "asn_v6.bin", MAGIC_V6, V6_RECORD, v6)

    meta = {
        "built_at": int(time.time()),
        "source": url,
        "format_version": FORMAT_VERSION,
        "v4_records": len(v4),
        "v6_records": len(v6),
    }
    meta_path = out_dir / "meta.json"
    tmp_meta = meta_path.with_suffix(".json.tmp")
    tmp_meta.write_text(json.dumps(meta, indent=2) + "\n")
    os.replace(str(tmp_meta), str(meta_path))
    _log(f"refresh complete: {meta}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the local IP-to-network-class dataset")
    parser.add_argument(
        "--out",
        default=os.environ.get("ASN_DB_DIR", "").strip() or str(Path.home() / ".mirage" / "asn"),
        help="output directory (default: $ASN_DB_DIR or ~/.mirage/asn)",
    )
    parser.add_argument("--url", default=os.environ.get("ASN_DB_URL", "").strip() or DEFAULT_URL)
    parser.add_argument(
        "--force",
        action="store_true",
        help="install the dataset even if it is smaller than the sanity floor",
    )
    args = parser.parse_args()
    return refresh(Path(args.out), args.url, args.force)


if __name__ == "__main__":
    sys.exit(main())
