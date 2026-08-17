"""Local IP-to-network-class lookup, shared across workers via mmap.

Classifies a client address as hosting / vpn / cellular / isp so an agent can
read a network tag correctly: forty votes across two hosting tags is damning,
forty across two cellular tags is probably just carrier NAT.

Why mmap and not Python objects. gunicorn_config.py sizes the pool at
(2 * cpu_count) + 1 sync workers with no preload_app, so module state is built
independently in every worker after fork with no copy-on-write sharing. Holding
the ranges as Python lists would cost one full copy per worker. A fixed-width
record file read through mmap is shared by the OS page cache across all of them
at effectively zero incremental RSS, and binary search over record offsets is
still O(log n). It also avoids turning on preload_app, which would change fork
semantics for every other piece of module state as a side effect.

Staleness is a deliberate, logged fallback rather than a hard failure: letting a
third-party dataset outage take down the posting path would be a far worse
failure than a slightly stale class. Age is logged at every load, escalating to
an error past STALE_ERROR_DAYS. When no dataset exists at all the caller gets
None and omits the class from the memo entirely.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import mmap
import os
import struct
import time
from pathlib import Path
from typing import Optional

_log = logging.getLogger("asn_db")

MAGIC_V4 = b"MIRASNV4"
MAGIC_V6 = b"MIRASNV6"
FORMAT_VERSION = 1

# magic(8) + format version(2) + record count(4) + reserved(2)
HEADER_STRUCT = struct.Struct("!8sHIH")
HEADER_SIZE = HEADER_STRUCT.size

# start, end, class byte
V4_RECORD = struct.Struct("!IIB")
V6_RECORD = struct.Struct("!QQB")

# Wire codes for the class byte. Kept numeric so records stay fixed-width.
CLASS_CODES = {
    0: "unknown",
    1: "isp",
    2: "hosting",
    3: "vpn",
    4: "cellular",
}
CLASS_TO_CODE = {name: code for code, name in CLASS_CODES.items()}

STALE_WARN_DAYS = 7
STALE_ERROR_DAYS = 30

# A refresh replaces the file by rename, which leaves an existing mmap pointing
# at the old unlinked inode. Re-stat occasionally so a long-lived worker picks
# up a refresh without waiting for a restart.
_RESTAT_INTERVAL_S = 300

_V4_FILE = "asn_v4.bin"
_V6_FILE = "asn_v6.bin"
_META_FILE = "meta.json"


def db_dir() -> Path:
    override = os.environ.get("ASN_DB_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".mirage" / "asn"


class _Table:
    """One mmapped fixed-width range file."""

    __slots__ = ("mm", "count", "record", "path", "mtime", "inode")

    def __init__(self, mm, count, record, path, mtime, inode):
        self.mm = mm
        self.count = count
        self.record = record
        self.path = path
        self.mtime = mtime
        self.inode = inode

    def lookup(self, needle: int) -> Optional[int]:
        """Binary search for the range containing needle; None if in a gap."""
        lo, hi = 0, self.count - 1
        size = self.record.size
        while lo <= hi:
            mid = (lo + hi) // 2
            start, end, code = self.record.unpack_from(self.mm, HEADER_SIZE + mid * size)
            if needle < start:
                hi = mid - 1
            elif needle > end:
                lo = mid + 1
            else:
                return code
        return None

    def close(self):
        try:
            self.mm.close()
        except Exception:
            pass


class _State:
    __slots__ = ("v4", "v6", "built_at", "loaded_at")

    def __init__(self, v4, v6, built_at, loaded_at):
        self.v4 = v4
        self.v6 = v6
        self.built_at = built_at
        self.loaded_at = loaded_at

    @property
    def available(self) -> bool:
        return self.v4 is not None or self.v6 is not None


_state: Optional[_State] = None
_last_stat_check = 0.0


def _open_table(path: Path, magic: bytes, record: struct.Struct) -> Optional[_Table]:
    if not path.exists():
        return None
    st = path.stat()
    if st.st_size < HEADER_SIZE:
        _log.error("[asn_db] %s is %d bytes, smaller than its header; ignoring", path, st.st_size)
        return None
    fd = os.open(str(path), os.O_RDONLY)
    try:
        mm = mmap.mmap(fd, 0, access=mmap.ACCESS_READ)
    finally:
        os.close(fd)

    got_magic, version, count, _reserved = HEADER_STRUCT.unpack_from(mm, 0)
    if got_magic != magic:
        _log.error("[asn_db] %s has magic %r, expected %r; ignoring", path, got_magic, magic)
        mm.close()
        return None
    if version != FORMAT_VERSION:
        _log.error("[asn_db] %s is format version %d, expected %d; ignoring", path, version, FORMAT_VERSION)
        mm.close()
        return None
    expected = HEADER_SIZE + count * record.size
    if len(mm) != expected:
        _log.error("[asn_db] %s is %d bytes, expected %d for %d records; ignoring", path, len(mm), expected, count)
        mm.close()
        return None
    if count == 0:
        _log.error("[asn_db] %s declares zero records; ignoring", path)
        mm.close()
        return None
    return _Table(mm, count, record, path, st.st_mtime, st.st_ino)


def _read_built_at(directory: Path) -> Optional[int]:
    meta_path = directory / _META_FILE
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text())
    except Exception as e:
        _log.error("[asn_db] %s is unreadable: %s", meta_path, e)
        return None
    built_at = meta.get("built_at")
    if not isinstance(built_at, (int, float)):
        return None
    return int(built_at)


def _log_freshness(state: _State) -> None:
    v4 = state.v4.count if state.v4 else 0
    v6 = state.v6.count if state.v6 else 0
    if not state.available:
        _log.error(
            "[asn_db] no dataset in %s; network class will be omitted from tags "
            "until deploy/refresh_asn_db.py succeeds",
            db_dir(),
        )
        return
    if state.built_at is None:
        _log.warning("[asn_db] loaded v4=%d v6=%d ranges but build date is unknown", v4, v6)
        return
    age_days = (time.time() - state.built_at) / 86400.0
    msg = "[asn_db] loaded v4=%d v6=%d ranges, dataset built %.1f days ago"
    if age_days >= STALE_ERROR_DAYS:
        _log.error(msg + " (over %d days; refresh is failing)", v4, v6, age_days, STALE_ERROR_DAYS)
    elif age_days >= STALE_WARN_DAYS:
        _log.warning(msg + " (over %d days)", v4, v6, age_days, STALE_WARN_DAYS)
    else:
        _log.info(msg, v4, v6, age_days)


def _load() -> _State:
    directory = db_dir()
    v4 = _open_table(directory / _V4_FILE, MAGIC_V4, V4_RECORD)
    try:
        v6 = _open_table(directory / _V6_FILE, MAGIC_V6, V6_RECORD)
    except Exception:
        if v4 is not None:
            v4.close()
        raise
    state = _State(v4, v6, _read_built_at(directory), time.time())
    _log_freshness(state)
    return state


def _changed_on_disk(state: _State) -> bool:
    directory = db_dir()
    for table, name in ((state.v4, _V4_FILE), (state.v6, _V6_FILE)):
        path = directory / name
        exists = path.exists()
        if table is None:
            if exists:
                return True
            continue
        if not exists:
            return True
        st = path.stat()
        if st.st_ino != table.inode or st.st_mtime != table.mtime:
            return True
    return False


def _current() -> _State:
    """Return the loaded dataset, reloading if the files changed on disk."""
    global _state, _last_stat_check
    now = time.monotonic()
    if _state is None:
        try:
            _state = _load()
        except Exception:
            # This dataset is advisory. An I/O failure must not turn every
            # relayed action into HTTP 500; omit the class and retry after the
            # bounded restat interval. The tag itself is still produced.
            _log.exception("[asn_db] initial dataset load failed; network class will be omitted")
            _state = _State(None, None, None, time.time())
        _last_stat_check = now
        return _state
    if now - _last_stat_check >= _RESTAT_INTERVAL_S:
        _last_stat_check = now
        try:
            changed = _changed_on_disk(_state)
        except Exception:
            # Keep the already-mapped dataset. A transient stat/permission
            # error is not evidence that stale-but-valid data became unusable.
            _log.exception("[asn_db] dataset restat failed; keeping loaded dataset")
            return _state
        if changed:
            _log.info("[asn_db] dataset changed on disk; reloading")
            old = _state
            try:
                replacement = _load()
            except Exception:
                # Atomic refresh means an old mmap remains valid after rename.
                # Keep it until a complete replacement can be loaded.
                _log.exception("[asn_db] dataset reload failed; keeping loaded dataset")
                return _state
            _state = replacement
            for table in (old.v4, old.v6):
                if table is not None:
                    table.close()
    return _state


def classify_ip(ip_str: Optional[str]) -> Optional[str]:
    """Class for a trusted client IP, or None when no dataset is available.

    None and "unknown" are different answers. None means this relay had no
    classification data at all and the caller must omit the class rather than
    claim one. "unknown" means the dataset was consulted and the address fell
    outside every known range.
    """
    text = (ip_str or "").strip()
    if not text:
        return None
    state = _current()
    if not state.available:
        return None

    try:
        if "/" in text:
            network = ipaddress.ip_network(text, strict=False)
            version = network.version
            address = network.network_address
        else:
            address = ipaddress.ip_address(text)
            version = address.version
    except ValueError:
        return None

    if version == 4:
        if state.v4 is None:
            return None
        code = state.v4.lookup(int(address))
    else:
        if state.v6 is None:
            return None
        # Only the high 64 bits matter: the caller has already bucketed to /64.
        code = state.v6.lookup(int(address) >> 64)

    if code is None:
        return "unknown"
    return CLASS_CODES.get(code, "unknown")


def dataset_status() -> dict:
    """Operator-facing snapshot, used by tests and diagnostics."""
    state = _current()
    age_days = None
    if state.built_at is not None:
        age_days = round((time.time() - state.built_at) / 86400.0, 2)
    return {
        "available": state.available,
        "built_at": state.built_at,
        "age_days": age_days,
        "v4_ranges": state.v4.count if state.v4 else 0,
        "v6_ranges": state.v6.count if state.v6 else 0,
        "dir": str(db_dir()),
    }
