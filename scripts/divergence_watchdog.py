#!/usr/bin/env python3
"""
divergence_watchdog.py — long-running supervisor that detects when miraged is
forked / app-hash-diverged from the rest of the network and triggers a
recovery script to bring it back automatically.

Default recovery command: scripts/recover.sh peer-pull (chain-data tar pulled
directly from a healthy peer). State-sync remains available as an opt-in
alternative - set:
   RECOVERY_MODE=state-sync
to switch back. The default was flipped after the May 25 2026 incident where
a cosmos-sdk v0.53 state-sync bug left staking.bond_denom empty, causing
mint.BeginBlocker to panic on the next block.

Designed to run inside the mirage container, in its own tmux window, started
by deploy/entrypoint.sh.

Detection signals (any one triggers recovery):
  1) miraged's CometBFT log contains the line
       "wrong Block.Header.AppHash"        (committed block diverged)
     or
       "CONSENSUS FAILURE!!!"              (panicking / catastrophic)
     in the last DETECTION_WINDOW seconds.
  2) /status reports the same latest_block_height for STALL_BLOCKS consecutive
     polls AND >=2 healthy peers report a strictly higher block (we're stuck).
  3) /status is unreachable for DEAD_THRESHOLD consecutive polls, the miraged
     process is gone, and >=2 healthy peers are reachable (we crashed).

Safety guards before recovering:
  - Cool-down marker (~/.mirage/.divergence_recovery_lock) — refuse to recover
    again within COOLDOWN_SECONDS (default 6h).
  - Disable marker (~/.mirage/.recovery_disabled) — opt out completely.
  - >=2 healthy peers reachable AND agreeing on the same recent app_hash
    (delegated to recover.sh which double-checks).
  - DRY_RUN env var (or --dry-run flag) — only log the trigger, do not act.
  - Refuses to act if /status shows catching_up=true (state-sync already in
    progress — let it finish).

Logs to stdout (cronologged by the entrypoint wiring).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

# ── Config (env-overridable) ────────────────────────────────────────────
NODE_HOME = Path(os.environ.get("NODE_HOME", "/root/.mirage/node"))
LOGS_DIR = Path(os.environ.get("LOGS_DIR", "/root/.mirage/logs"))
LOCK = Path(os.environ.get("LOCK", "/root/.mirage/.divergence_recovery_lock"))
DISABLE_MARKER = Path(os.environ.get("DISABLE_MARKER", "/root/.mirage/.recovery_disabled"))
RECOVERY_SCRIPT = Path(os.environ.get("RECOVERY_SCRIPT", "/opt/mirage/scripts/recover.sh"))
RECOVERY_MODE = os.environ.get("RECOVERY_MODE", "peer-pull")
LOCAL_RPC = os.environ.get("LOCAL_RPC", "http://127.0.0.1:26657")

POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
DETECTION_WINDOW = int(os.environ.get("DETECTION_WINDOW", "300"))  # 5 min log lookback
STALL_BLOCKS = int(os.environ.get("STALL_BLOCKS", "10"))  # ~10 polls = 10 min
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "21600"))  # 6h
PEER_AHEAD_THRESHOLD = int(os.environ.get("PEER_AHEAD_THRESHOLD", "20"))
DEAD_THRESHOLD = int(os.environ.get("DEAD_THRESHOLD", "3"))

DIVERGENCE_PATTERNS = (
    "wrong Block.Header.AppHash",
    "CONSENSUS FAILURE!!!",
)


# ── Logging ─────────────────────────────────────────────────────────────
def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


# ── Helpers ─────────────────────────────────────────────────────────────
def get_status(rpc: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(f"{rpc}/status", timeout=timeout) as r:
            return json.load(r)["result"]
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        TimeoutError,
        ConnectionError,
        OSError,
    ) as e:
        return None


def miraged_running() -> bool:
    rv = subprocess.run(
        ["pgrep", "-f", "miraged start"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return rv.returncode == 0


def latest_log_file() -> Path | None:
    """Return today's miraged log file (or yesterday's if today is missing)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    candidates = [
        LOGS_DIR / "node" / f"miraged-{today}.log",
    ]
    # Fall back to most-recent miraged-*.log
    log_dir = LOGS_DIR / "node"
    if log_dir.exists():
        all_logs = sorted(log_dir.glob("miraged-*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        candidates += all_logs[:2]
    for c in candidates:
        if c.is_file():
            return c
    return None


def tail_recent(path: Path, max_bytes: int = 256 * 1024) -> str:
    """Read the last `max_bytes` of a file (good enough for log scanning)."""
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            f.read(1)  # discard partial line
            data = f.read()
        else:
            data = f.read()
    try:
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


# Strip ANSI color codes from log lines
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# Match CometBFT log timestamps like "2:57AM" or "11:23PM"
TS_RE = re.compile(r"\b(\d{1,2}):(\d{2})(AM|PM)\b")


def log_window_has_pattern(text: str, patterns: tuple[str, ...], window_secs: int) -> str | None:
    """
    Scan recent log text and return the first matching pattern that appears
    within `window_secs` of the current UTC time.

    CometBFT logs use 12h timestamps without dates ("2:57AM"). We treat them
    as today's UTC and tolerate a 24h wraparound.
    """
    if not text:
        return None
    text = ANSI_RE.sub("", text)
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    cutoff = now_utc.timestamp() - window_secs

    for line in text.splitlines():
        # Quick filter
        if not any(p in line for p in patterns):
            continue
        m = TS_RE.search(line)
        if not m:
            # No parseable timestamp — assume recent (conservative match)
            for p in patterns:
                if p in line:
                    return p
            continue
        hh, mm, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
        if ampm == "PM" and hh != 12:
            hh += 12
        if ampm == "AM" and hh == 12:
            hh = 0
        try:
            ts = datetime(today.year, today.month, today.day, hh, mm, tzinfo=timezone.utc)
        except ValueError:
            continue
        # Allow times within the last 24h (handle midnight wraparound)
        if ts.timestamp() > now_utc.timestamp():
            ts = ts.replace(day=today.day - 1) if today.day > 1 else ts
        if ts.timestamp() >= cutoff:
            for p in patterns:
                if p in line:
                    return p
    return None


def cooldown_active() -> bool:
    if not LOCK.exists():
        return False
    age = time.time() - LOCK.stat().st_mtime
    return age < COOLDOWN_SECONDS


def get_persistent_peer_ips() -> list[str]:
    cfg = NODE_HOME / "config" / "config.toml"
    try:
        text = cfg.read_text()
    except OSError:
        return []
    m = re.search(r'^persistent_peers\s*=\s*"([^"]*)"', text, re.M)
    if not m:
        return []
    ips = []
    for spec in m.group(1).split(","):
        spec = spec.strip()
        if "@" not in spec:
            continue
        ip = spec.split("@", 1)[1].split(":", 1)[0]
        if ip:
            ips.append(ip)
    return ips


def healthy_peers_height() -> tuple[int, int]:
    """Return (count_of_healthy_peers, max_peer_height_reported)."""
    ips = get_persistent_peer_ips()
    count, max_h = 0, 0
    for ip in ips:
        st = get_status(f"http://{ip}:26657", timeout=4)
        if not st:
            continue
        try:
            if not st["sync_info"]["catching_up"]:
                h = int(st["sync_info"]["latest_block_height"])
                count += 1
                if h > max_h:
                    max_h = h
        except (KeyError, ValueError):
            continue
    return count, max_h


# ── Core loop ───────────────────────────────────────────────────────────
def run(dry_run: bool) -> int:
    log(
        f"divergence_watchdog starting "
        f"(poll={POLL_SECONDS}s, window={DETECTION_WINDOW}s, "
        f"stall={STALL_BLOCKS}, cooldown={COOLDOWN_SECONDS}s, "
        f"dead_threshold={DEAD_THRESHOLD}, dry_run={dry_run})"
    )

    height_history: deque[int] = deque(maxlen=STALL_BLOCKS + 1)
    consecutive_unreachable = 0

    while True:
        try:
            if DISABLE_MARKER.exists():
                log(f"recovery disabled by marker {DISABLE_MARKER}, sleeping {POLL_SECONDS}s")
                time.sleep(POLL_SECONDS)
                continue

            if cooldown_active():
                # Still poll so we don't go silent, but don't act.
                age = int(time.time() - LOCK.stat().st_mtime)
                left = COOLDOWN_SECONDS - age
                log(f"cool-down active ({age}s into {COOLDOWN_SECONDS}s, {left}s remaining), monitoring only")

            triggered_by = None
            force_recover = False

            local = get_status(LOCAL_RPC)
            if not local:
                consecutive_unreachable += 1
                log(f"local /status unreachable ({consecutive_unreachable}/{DEAD_THRESHOLD})")
                if consecutive_unreachable < DEAD_THRESHOLD:
                    time.sleep(POLL_SECONDS)
                    continue
                if miraged_running():
                    log("miraged process still running; treating unreachable /status as transient")
                    time.sleep(POLL_SECONDS)
                    continue
                healthy, peer_max = healthy_peers_height()
                if healthy < 2:
                    log(f"miraged process is dead, but only {healthy} healthy peer(s) reachable; refusing recovery")
                    time.sleep(POLL_SECONDS)
                    continue
                triggered_by = (
                    f"process-dead: local /status unreachable for {consecutive_unreachable} polls, "
                    f"miraged process absent, {healthy} peers healthy at max height {peer_max}"
                )
                force_recover = True
            else:
                consecutive_unreachable = 0

            if local:
                try:
                    local_h = int(local["sync_info"]["latest_block_height"])
                    catching_up = bool(local["sync_info"]["catching_up"])
                except (KeyError, ValueError):
                    log("local /status missing sync_info, skipping")
                    time.sleep(POLL_SECONDS)
                    continue

                if catching_up:
                    log(f"local catching_up=true at height={local_h}; not a divergence")
                    height_history.clear()
                    time.sleep(POLL_SECONDS)
                    continue

                height_history.append(local_h)
                log(f"local height={local_h} catching_up=False (history={list(height_history)})")

                # Signal 1: log pattern
                log_path = latest_log_file()
                if log_path:
                    tail = tail_recent(log_path)
                    hit = log_window_has_pattern(tail, DIVERGENCE_PATTERNS, DETECTION_WINDOW)
                    if hit:
                        triggered_by = f"log pattern: {hit!r} in {log_path.name}"

                # Signal 2: stall vs peers
                if not triggered_by and len(height_history) == height_history.maxlen:
                    if len(set(height_history)) == 1:
                        healthy, peer_max = healthy_peers_height()
                        if healthy >= 2 and peer_max > local_h + PEER_AHEAD_THRESHOLD:
                            triggered_by = (
                                f"stall: local stuck at {local_h} for {STALL_BLOCKS} polls "
                                f"while {healthy} peers at {peer_max}"
                            )

            if not triggered_by:
                time.sleep(POLL_SECONDS)
                continue

            log(f"DIVERGENCE DETECTED — {triggered_by}")

            if cooldown_active() and not force_recover:
                log("cool-down still active; refusing to act this cycle")
                time.sleep(POLL_SECONDS)
                continue
            if force_recover and cooldown_active():
                log("process-dead recovery bypassing cool-down via --force")

            if dry_run:
                log("DRY RUN — would invoke recovery script. Not acting.")
                time.sleep(POLL_SECONDS)
                continue

            recovery_args = ["bash", str(RECOVERY_SCRIPT), RECOVERY_MODE, "--auto"]
            if force_recover:
                recovery_args.append("--force")
            log(f"invoking {' '.join(recovery_args)}")
            try:
                rv = subprocess.run(
                    recovery_args,
                    check=False,
                )
                log(f"recovery script exit code: {rv.returncode}")
            except (subprocess.SubprocessError, OSError) as e:
                log(f"ERROR invoking recovery script: {e!r}")

            # After triggering recovery, reset history and wait an extra cycle
            # before resuming detection (give miraged time to come back up).
            height_history.clear()
            time.sleep(POLL_SECONDS * 5)

        except KeyboardInterrupt:
            log("shutting down (SIGINT)")
            return 0
        except Exception as e:  # noqa: BLE001 — defensive top-level guard
            log(f"unexpected error: {e!r}")
            time.sleep(POLL_SECONDS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("DRY_RUN", "").lower() in {"1", "true", "yes"},
        help="Log triggers but do NOT invoke the recovery script.",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
