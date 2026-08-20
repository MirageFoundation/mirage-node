#!/usr/bin/env python3
"""
divergence_watchdog.py — long-running observability + auto-recovery daemon.
Detects when miraged is stuck, crashed, or app-hash-diverged from the rest of
the network and, depending on the symptom, either restarts the process
(non-destructive) or invokes a destructive state-recovery script.

TWO-TIER RECOVERY MODEL (post-2026-06-14 incident)
--------------------------------------------------
There are two fundamentally different failure classes, and conflating them is
dangerous:

  * RUNTIME HANG  — the local chain STATE is correct (app_hash matches peers)
    but the process is wedged: a stuck consensus reactor, a hung goroutine, a
    crashed process. The fix is a cheap, NON-DESTRUCTIVE restart. This is the
    2026-06-14 mirage.talk incident: miraged frozen at height 5329009 step=3
    (prevote) for 30 minutes while peers advanced; app_hash at 5329009 matched
    mirage.vote exactly. A plain process restart fixed it in 45 seconds. The
    old watchdog had no restart action and would have escalated straight to a
    DB-wiping peer-pull on a perfectly healthy database.

  * STATE DIVERGENCE — the local chain state is WRONG (wrong Block.Header.AppHash,
    or a stall whose app_hash disagrees with peers). No restart can fix wrong
    state; the only cure is to replace the chain DB from a healthy peer
    (peer-pull), which is destructive.

The escalation ladder:

  log-pattern divergence  -> peer-pull            (gated by WATCHDOG_AUTORECOVER)
  stall + app_hash MATCH  -> restart              (ungated; non-destructive)
  stall + app_hash MISS   -> peer-pull            (gated by WATCHDOG_AUTORECOVER)
  process-dead            -> restart, then        (restart ungated;
                             peer-pull if restart   peer-pull gated)
                             does not recover
  restart recurrence      -> peer-pull            (3 restarts within 2h means
  (RESTART_ESCALATE_AFTER)                          this is not a transient hang)

GATING
------
  AUTO_DIVERGENCE_RECOVERY=true  → start the watchdog process at all (now the
                                   default on all validators, because the
                                   restart action cannot brick the set).
  WATCHDOG_AUTORECOVER=true      → permit DESTRUCTIVE peer-pull. Restart never
                                   needs this gate. Pre-2026-05-27 a default-on
                                   destructive watchdog wiped 3 of 4 validators
                                   on a benign upgrade halt; destructive
                                   recovery therefore stays opt-in per host.

Default destructive recovery command (when authorized): scripts/recover.sh
peer-pull. State-sync remains an opt-in alternative — set RECOVERY_MODE=state-sync.
peer-pull is the default after the May 25 2026 incident where a cosmos-sdk v0.53
state-sync bug left staking.bond_denom empty, panicking mint.BeginBlocker.

Designed to run inside the mirage container as its own Supervisor program,
started by deploy/entrypoint.sh.

Detection signals:
  1) miraged's CometBFT log contains "wrong Block.Header.AppHash" or
     "CONSENSUS FAILURE!!!" in the last DETECTION_WINDOW seconds.
     EXCEPTION: a "CONSENSUS FAILURE!!!" line whose err payload is the
     cosmos-sdk upgrade halt (matches UPGRADE_HALT_RE) is NOT a divergence; it
     is an operator-driven binary-swap event (the 2026-05-27 mass-wipe cause).
  2) /status reports the same latest_block_height for STALL_BLOCKS consecutive
     polls AND >=2 healthy peers report a strictly higher block.
  3) /status is unreachable for DEAD_THRESHOLD consecutive polls, the miraged
     process is gone. Peer health is logged and still required later by
     peer-pull, but it does not block a non-destructive restart.

Alert-only warnings (never dispatch recovery, each with its own dedup marker):
  [DISK] filesystem crossed DISK_ALERT_PCT.
  [LAG]  the node is behind healthy peers by more than LAG_ALERT_BLOCKS while
         STILL ADVANCING. Signal 2 above only fires on a FROZEN height, so a
         node that keeps committing blocks a minute behind the network was
         completely silent (2026-08-06: 21 blocks behind for ~5 min while the
         chain rejected relayed writes as "envelope_timestamp in future").
  [IO]   host disk latency above IO_AWAIT_ALERT_MS — the usual cause of the
         above, and invisible from inside CometBFT.

Safety guards:
  - Restart cool-down marker (~/.mirage/.restart_recovery_lock,
    RESTART_COOLDOWN_SECONDS default 15m) — separate from the destructive lock.
  - Destructive cool-down marker (~/.mirage/.divergence_recovery_lock,
    COOLDOWN_SECONDS default 6h) — written ONLY by recover.sh after a VERIFIED
    recovery. The watchdog never writes it (2026-06-12: alert dedup polluted it
    and pre-blocked a real recovery for 6h). Alert dedup uses a separate marker
    (~/.mirage/.divergence_alert_lock).
  - Disable marker (~/.mirage/.recovery_disabled) — opt out completely.
  - >=2 healthy peers agreeing on app_hash (delegated to recover.sh peer-pull).
  - DRY_RUN env var (or --dry-run flag) — only log the trigger, do not act.
  - Refuses to act if /status shows catching_up=true.

FORENSIC LOGGING
----------------
Every poll writes dense, tagged, greppable lines to BOTH stdout (Supervisor
capture) AND a durable daily file /root/.mirage/logs/watchdog/watchdog-YYYY-MM-DD.log
(90-day retention), so any incident is reconstructable months later. Tags:
STARTUP, POLL, PEER, GATE, TRIGGER, PRECHECK, DISPATCH, INVOKE, POSTCHECK,
COOLDOWN, ESCALATE, ALERT, DISK, LAG, IO, CRASH, SHUTDOWN. One-liner to
reconstruct every interesting event:
  grep -E '\\[(TRIGGER|DISPATCH|INVOKE|POSTCHECK|ESCALATE|ALERT|LAG|IO|CRASH)\\]' \\
    /root/.mirage/logs/watchdog/watchdog-*.log
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# ── Config (env-overridable) ────────────────────────────────────────────
NODE_HOME = Path(os.environ.get("NODE_HOME", "/root/.mirage/node"))
LOGS_DIR = Path(os.environ.get("LOGS_DIR", "/root/.mirage/logs"))
# Durable, dense forensic log directory. Daily file, 90-day retention.
WATCHDOG_LOG_DIR = Path(os.environ.get("WATCHDOG_LOG_DIR", str(LOGS_DIR / "watchdog")))
WATCHDOG_LOG_RETENTION_DAYS = int(os.environ.get("WATCHDOG_LOG_RETENTION_DAYS", "90"))
LOCK = Path(os.environ.get("LOCK", "/root/.mirage/.divergence_recovery_lock"))
# Short, NON-destructive restart cool-down. Distinct from the 6h destructive
# LOCK so a recent restart never blocks a real peer-pull and vice versa.
RESTART_LOCK = Path(os.environ.get("RESTART_LOCK", "/root/.mirage/.restart_recovery_lock"))
RESTART_COOLDOWN_SECONDS = int(os.environ.get("RESTART_COOLDOWN_SECONDS", "900"))  # 15 min
# Recurrence escalation: if the watchdog has invoked `restart` this many times
# within RESTART_ESCALATE_WINDOW_SECONDS, the next stall escalates straight to
# peer-pull (a recurring stall is not a transient hang any more).
RESTART_ESCALATE_AFTER = int(os.environ.get("RESTART_ESCALATE_AFTER", "3"))
RESTART_ESCALATE_WINDOW_SECONDS = int(os.environ.get("RESTART_ESCALATE_WINDOW_SECONDS", "7200"))  # 2h
# Alert-spam dedup marker for alert-only mode. MUST be distinct from LOCK:
# LOCK is the recovery cool-down that recover.sh checks before acting, and
# polluting it from the alert path locks operators out of recovery (2026-06-12).
ALERT_LOCK = Path(os.environ.get("ALERT_LOCK", "/root/.mirage/.divergence_alert_lock"))
ALERT_REPEAT_SECONDS = int(os.environ.get("ALERT_REPEAT_SECONDS", "1800"))  # re-alert every 30 min
# External push alert (independent of the Supervisor capture nobody is watching). When
# ALERT_WEBHOOK_URL is set the watchdog POSTs a one-line JSON {"text": ...} to it
# whenever it fires a loud alert OR dispatches a recovery, so a node crash /
# divergence pages a human. Provider-agnostic: Slack incoming webhook,
# Discord (append /slack), Mattermost, ntfy. Unset = disabled (no-op). It is
# strictly best-effort — short timeout, every error swallowed to the forensic
# log — so a flaky webhook can never wedge or crash the watchdog loop.
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
ALERT_WEBHOOK_TIMEOUT = float(os.environ.get("ALERT_WEBHOOK_TIMEOUT", "5"))
# Disk-pressure warning threshold (% used on the NODE_HOME filesystem). The
# watchdog already samples disk every poll for the [POLL] trail; this turns it
# into an actual warning so a slow squeeze is noticed early instead of at 100%.
# ALERT-ONLY by design — see _disk_alert_once. Its own dedup marker and a slow
# repeat, because disk fills over days, not minutes.
DISK_ALERT_PCT = int(os.environ.get("DISK_ALERT_PCT", "80"))
DISK_ALERT_LOCK = Path(os.environ.get("DISK_ALERT_LOCK", "/root/.mirage/.disk_alert_lock"))
DISK_ALERT_REPEAT_SECONDS = int(os.environ.get("DISK_ALERT_REPEAT_SECONDS", "21600"))  # 6h
# Peer-lag warning: the node is BEHIND the network but still committing blocks.
# The stall trigger cannot see this — it requires a frozen height — so on
# 2026-08-06 mirage.talk ran 21 blocks (~75s) behind for five minutes with
# catching_up=False and nothing alerted, while every relayed write was rejected
# by the ante handler for a stale block time. ALERT-ONLY: see _lag_alert_once.
# 10 blocks is ~36s at the observed 3.6s block time, well clear of the 1-3
# blocks of skew normally seen between the local poll and the peer probe.
LAG_ALERT_BLOCKS = int(os.environ.get("LAG_ALERT_BLOCKS", "10"))
LAG_ALERT_POLLS = int(os.environ.get("LAG_ALERT_POLLS", "3"))
LAG_ALERT_LOCK = Path(os.environ.get("LAG_ALERT_LOCK", "/root/.mirage/.lag_alert_lock"))
LAG_ALERT_REPEAT_SECONDS = int(os.environ.get("LAG_ALERT_REPEAT_SECONDS", "1800"))  # 30 min
# Host disk-latency warning. Consensus is fsync-bound, so storage latency is the
# root cause the node itself cannot report. On val1 the average service time sits
# at 3-4ms; during the 2026-08-06 stall it reached 281ms with the device busy 81%
# of the time while our own IOPS FELL — i.e. the volume degraded under us. 100ms
# sustained over two polls is far above anything healthy and far below the point
# where blocks start slipping.
IO_AWAIT_ALERT_MS = int(os.environ.get("IO_AWAIT_ALERT_MS", "100"))
IO_ALERT_POLLS = int(os.environ.get("IO_ALERT_POLLS", "2"))
IO_ALERT_LOCK = Path(os.environ.get("IO_ALERT_LOCK", "/root/.mirage/.io_alert_lock"))
IO_ALERT_REPEAT_SECONDS = int(os.environ.get("IO_ALERT_REPEAT_SECONDS", "1800"))  # 30 min
NODE_LABEL = os.environ.get("NODE_LABEL", "") or os.environ.get("MONIKER", "") or socket.gethostname()
DISABLE_MARKER = Path(os.environ.get("DISABLE_MARKER", "/root/.mirage/.recovery_disabled"))
RECOVERY_SCRIPT = Path(os.environ.get("RECOVERY_SCRIPT", "/opt/mirage/scripts/recover.sh"))
RECOVERY_MODE = os.environ.get("RECOVERY_MODE", "peer-pull")
# Private key used by recover.sh peer-pull to SSH into source peers. Installed
# by `recover.sh provision`. Checked at startup when autorecover is enabled so
# a missing key surfaces at deploy time, not mid-incident (2026-06-12: prod had
# autorecover docs but no key, so peer-pull could never have worked there).
RECOVERY_KEY = Path(os.environ.get("RECOVERY_KEY", "/root/.mirage/.ssh/recovery_id"))
LOCAL_RPC = os.environ.get("LOCAL_RPC", "http://127.0.0.1:26657")

POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
DETECTION_WINDOW = int(os.environ.get("DETECTION_WINDOW", "300"))  # 5 min log lookback
STALL_BLOCKS = int(os.environ.get("STALL_BLOCKS", "10"))  # ~10 polls = 10 min
# How long the local height must stay FROZEN while catching_up=True before we
# even consider it a possible divergence (a genuine block-sync advances, so its
# height is never frozen this long). Paired with a log-pattern hit + peers ahead
# to escalate. Default = STALL_BLOCKS polls, matching the not-catching-up stall.
CATCHUP_STALL_SECONDS = int(os.environ.get("CATCHUP_STALL_SECONDS", str(STALL_BLOCKS * POLL_SECONDS)))
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "21600"))  # 6h
PEER_AHEAD_THRESHOLD = int(os.environ.get("PEER_AHEAD_THRESHOLD", "20"))
DEAD_THRESHOLD = int(os.environ.get("DEAD_THRESHOLD", "3"))
# Restart verification budget the watchdog reports; recover.sh restart enforces
# its own (RECOVERY_VERIFY_SECONDS_RESTART) — kept aligned for clarity.
RECOVERY_VERIFY_SECONDS_RESTART = int(os.environ.get("RECOVERY_VERIFY_SECONDS_RESTART", "60"))

# Master gate on DESTRUCTIVE recovery (peer-pull / state-sync). Restart never
# needs this gate. Defaults to FALSE; operator opts in per host. See module
# docstring for rationale (2026-05-27 mass-wipe incident).
WATCHDOG_AUTORECOVER = os.environ.get("WATCHDOG_AUTORECOVER", "").lower() in {"1", "true", "yes"}

# Trigger type constants (kept as plain strings so decide_action stays trivially
# testable without importing an enum).
TRIGGER_LOG_PATTERN = "log_pattern"
TRIGGER_STALL = "stall"
TRIGGER_PROCESS_DEAD = "process_dead"

DIVERGENCE_PATTERNS = (
    "wrong Block.Header.AppHash",
    "CONSENSUS FAILURE!!!",
    # Mirage fail-fast pruning guard (blockchain/patches/iavl/nodedb.go): the node
    # panics rather than prune past a hole in version history. The local DB is
    # inconsistent; peer-pull (restore from a healthy peer) is the correct fix,
    # same as a divergence. Crashing also trips TRIGGER_PROCESS_DEAD, but matching
    # the marker classifies it precisely in the forensic trail.
    "CONSENSUS_FATAL:PRUNE_HOLE",
)

# A "CONSENSUS FAILURE!!!" line that is actually the cosmos-sdk upgrade halt
# looks like:
#   ERR CONSENSUS FAILURE!!! err="failed to apply block; error UPGRADE \"v1.26.0\" NEEDED at height: 4895581: " module=consensus
# (the upgrade module returns the error verbatim from
# x/upgrade.Keeper.PreBlocker when it has no handler registered for plan.Name).
# This is operator-fixable (swap binaries), NEVER recoverable by wiping the
# chain DBs. Treat it as non-divergence.
UPGRADE_HALT_RE = re.compile(r'UPGRADE\s+\\?"[^"\\]+\\?"\s+NEEDED\s+at\s+height:')

# A CONSENSUS_FATAL:* halt is the node refusing to commit state it cannot vouch
# for. Every peer executing the same block reaches the same conclusion at the
# same height, so there is no healthy peer to pull from and a wipe only destroys
# the one copy of the block that caused it. Like an upgrade halt this is
# operator-fixable — ship a corrected binary — and must never escalate to
# destructive recovery. On 2026-08-20 a supply-delta halt took all four
# validators at height 6969190; nothing was wiped only because a stale
# upgrade-halt line happened to trip the gate below.
#
# PRUNE_HOLE is deliberately excluded: that one means the LOCAL chain DB has a
# hole in its version history, which is exactly the case peer-pull repairs. It
# stays in DIVERGENCE_PATTERNS.
CONSENSUS_FATAL_HALT_RE = re.compile(r"CONSENSUS_FATAL:(?!PRUNE_HOLE\b)[A-Z][A-Z0-9_]*")


# ── Logging ─────────────────────────────────────────────────────────────
def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_log_file() -> Path:
    """Today's UTC daily forensic log file. Recomputed on every write so the
    daily roll happens automatically when the date flips — no cronolog, no
    external rotation."""
    return WATCHDOG_LOG_DIR / f"watchdog-{datetime.now(timezone.utc):%Y-%m-%d}.log"


def _write_line(line: str) -> None:
    """Dual-write: stdout (Supervisor capture / human eyeballing) AND the durable daily
    file (forensic trail). Logging must NEVER crash the watchdog, so all file
    I/O errors are swallowed."""
    print(line, flush=True)
    try:
        f = current_log_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _fmt_kv(kv: dict) -> str:
    parts = []
    for k, v in kv.items():
        s = str(v)
        if any(c in s for c in ' \t"='):
            s = '"' + s.replace('"', '\\"') + '"'
        parts.append(f"{k}={s}")
    return " ".join(parts)


def emit(tag: str, **kv) -> None:
    """Write one structured line: '[ts] [TAG] k1=v1 k2=v2 ...'. Values with
    spaces/quotes/equals are auto-quoted so every field stays greppable."""
    body = _fmt_kv(kv)
    _write_line(f"[{now()}] [{tag}]" + ((" " + body) if body else ""))


def log(msg: str) -> None:
    """Back-compat plain line, also dual-written to the daily file."""
    _write_line(f"[{now()}] {msg}")


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


def log_has_upgrade_halt(text: str) -> bool:
    """True when recent logs contain the cosmos-sdk upgrade-halt sentence.

    That halt stops miraged, so the watchdog's process-dead path would otherwise
    restart, fail to advance, and escalate to a chain-DB wipe. It is a binary
    swap, never a peer-pull.
    """
    if not text:
        return False
    return bool(UPGRADE_HALT_RE.search(ANSI_RE.sub("", text)))


def log_has_consensus_fatal_halt(text: str) -> bool:
    """True when recent logs show a CONSENSUS_FATAL halt that peer-pull cannot fix.

    Same disposition as an upgrade halt: alert and leave the node down for an
    operator, because the fault is deterministic and every peer has it too.
    """
    if not text:
        return False
    return bool(CONSENSUS_FATAL_HALT_RE.search(ANSI_RE.sub("", text)))


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
        # Suppress upgrade-halt false positives: a CONSENSUS FAILURE line whose
        # err payload is "UPGRADE \"...\" NEEDED at height:" is the cosmos-sdk
        # upgrade module refusing to apply a block because plan.Name has no
        # registered handler. That is a binary-swap event, not divergence.
        if UPGRADE_HALT_RE.search(line):
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


# ── Cool-down helpers ───────────────────────────────────────────────────
def cooldown_remaining_s(lock_path: Path, cooldown_s: int) -> int:
    """Seconds remaining on a cool-down marker, or 0 if expired/absent. Used
    for both the short RESTART_LOCK (15m) and the 6h destructive LOCK."""
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        return 0
    rem = int(cooldown_s - age)
    return rem if rem > 0 else 0


def marker_age_s(p: Path) -> int | None:
    try:
        return int(time.time() - p.stat().st_mtime)
    except OSError:
        return None


def path_is_file(p: Path) -> bool:
    """Path.is_file() that returns False instead of raising on a permission
    error (e.g. statting /root/.mirage/.ssh/recovery_id as a non-root user)."""
    try:
        return p.is_file()
    except OSError:
        return False


# ── Per-peer probe (structured, for [PEER] lines + stall decision) ──────
def probe_peers() -> list[dict]:
    """Probe every persistent peer's /status once. Returns one dict per peer
    with reachable/height/app_hash(at peer tip)/catching_up/rtt_ms/err. The
    tip app_hash is free from /status; the stall decision separately fetches
    app_hash AT the local stuck height (local_peer_app_hash_at)."""
    out = []
    for ip in get_persistent_peer_ips():
        rpc = f"http://{ip}:26657"
        t0 = time.time()
        st = get_status(rpc, timeout=4)
        rtt_ms = int((time.time() - t0) * 1000)
        if not st:
            out.append({"ip": ip, "reachable": False, "err": "status_unreachable", "rtt_ms": rtt_ms})
            continue
        try:
            si = st["sync_info"]
            out.append(
                {
                    "ip": ip,
                    "reachable": True,
                    "height": int(si["latest_block_height"]),
                    "app_hash": si.get("latest_app_hash", ""),
                    "catching_up": bool(si["catching_up"]),
                    "rtt_ms": rtt_ms,
                }
            )
        except (KeyError, ValueError) as e:
            out.append({"ip": ip, "reachable": True, "err": f"parse:{e!r}", "rtt_ms": rtt_ms})
    return out


def healthy_summary(peers: list[dict]) -> tuple[int, int]:
    """(count_healthy, max_height) derived from a probe_peers() result."""
    count, max_h = 0, 0
    for p in peers:
        if p.get("reachable") and not p.get("catching_up", True) and p.get("height", 0) > 0:
            count += 1
            if p["height"] > max_h:
                max_h = p["height"]
    return count, max_h


def get_block_app_hash(rpc: str, height: int, timeout: float = 4.0) -> str | None:
    try:
        with urllib.request.urlopen(f"{rpc}/block?height={height}", timeout=timeout) as r:
            d = json.load(r)
        return d["result"]["block"]["header"]["app_hash"]
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        KeyError,
        TimeoutError,
        ConnectionError,
        OSError,
    ):
        return None


def local_peer_app_hash_at(height: int, peers: list[dict]) -> tuple[str | None, dict]:
    """Apples-to-apples app_hash comparison AT a specific height: query
    /block?height=H on the local node and each healthy peer. Returns
    (local_app_hash, {ip: app_hash}). Used only when a stall fires."""
    local = get_block_app_hash(LOCAL_RPC, height)
    peer_hashes: dict[str, str] = {}
    for p in peers:
        if not (p.get("reachable") and not p.get("catching_up", True)):
            continue
        ah = get_block_app_hash(f"http://{p['ip']}:26657", height)
        if ah:
            peer_hashes[p["ip"]] = ah
    return local, peer_hashes


# ── Local process / host introspection (for forensic [POLL] state) ──────
def miraged_pid() -> int | None:
    rv = subprocess.run(["pgrep", "-f", "miraged start"], capture_output=True, text=True, check=False)
    if rv.returncode == 0 and rv.stdout.strip():
        try:
            return int(rv.stdout.split()[0])
        except ValueError:
            return None
    return None


def proc_rss_mb(pid: int | None) -> int | None:
    if not pid:
        return None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024  # kB -> MB
    except (OSError, ValueError, IndexError):
        return None
    return None


def disk_used_pct(path: Path) -> int | None:
    try:
        st = os.statvfs(str(path))
        total = st.f_blocks * st.f_frsize
        free = st.f_bfree * st.f_frsize
        if total == 0:
            return None
        return round(100 * (total - free) / total)
    except OSError:
        return None


# Whole disks only. vda1 and vda both appear in /proc/diskstats, and summing a
# partition with its parent double-counts every request.
_WHOLE_DISK_RE = re.compile(r"^(?:vd[a-z]+|sd[a-z]+|nvme\d+n\d+|xvd[a-z]+)$")


def read_disk_counters() -> tuple[int, int, int] | None:
    """(completed_ios, service_ms, busy_ms) summed from /proc/diskstats.

    diskstats is NOT namespaced, so inside the container these are the host's
    numbers — which is the whole point: the volume, not the cgroup, is what goes
    slow. Monotonic counters; meaningless until differenced by disk_pressure.
    """
    try:
        lines = Path("/proc/diskstats").read_text().splitlines()
    except OSError:
        return None
    ios = service_ms = busy_ms = 0
    for line in lines:
        f = line.split()
        if len(f) < 14 or not _WHOLE_DISK_RE.match(f[2]):
            continue
        try:
            ios += int(f[3]) + int(f[7])
            service_ms += int(f[6]) + int(f[10])
            busy_ms += int(f[12])
        except ValueError:
            continue
    if ios == 0 and busy_ms == 0:
        return None
    return ios, service_ms, busy_ms


def disk_pressure(
    prev: tuple[int, int, int] | None,
    cur: tuple[int, int, int] | None,
    elapsed_s: float,
) -> tuple[int, int] | None:
    """(await_ms, busy_pct) between two read_disk_counters() samples.

    PURE: no I/O, no clock — trivially unit-testable. await_ms is iostat's await
    (mean time a request spent in flight, queueing included); busy_pct is %util.
    None when a sample is missing, the interval completed no request (an average
    over zero requests is not a latency reading), or a counter went backwards
    because the host rebooted.
    """
    if prev is None or cur is None or elapsed_s <= 0:
        return None
    d_ios, d_service, d_busy = (cur[0] - prev[0], cur[1] - prev[1], cur[2] - prev[2])
    if d_ios <= 0 or d_service < 0 or d_busy < 0:
        return None
    return round(d_service / d_ios), round(100 * d_busy / (elapsed_s * 1000))


def read_priv_validator_step() -> tuple[int | None, int | None]:
    """step/round from priv_validator_state.json (~1KB). step=3 is prevote —
    exactly the value seen frozen during the 2026-06-14 stall."""
    p = NODE_HOME / "data" / "priv_validator_state.json"
    try:
        d = json.loads(p.read_text())
        step = d.get("step")
        rnd = d.get("round")
        return (int(step) if step is not None else None, int(rnd) if rnd is not None else None)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None, None


def file_sha256_short(p: Path) -> str:
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except OSError:
        return "unknown"


def cleanup_old_logs() -> int:
    """Delete watchdog-*.log older than WATCHDOG_LOG_RETENTION_DAYS. Returns
    the number of files removed. Runs once per UTC day from the loop."""
    removed = 0
    if not WATCHDOG_LOG_DIR.exists():
        return 0
    cutoff = time.time() - WATCHDOG_LOG_RETENTION_DAYS * 86400
    for f in WATCHDOG_LOG_DIR.glob("watchdog-*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


# ── Pure decision core (no I/O, no clock — trivially unit-testable) ─────
@dataclass
class Decision:
    """Result of the pure dispatcher. `argv` is what to exec ([] = nothing).
    `emits` is a list of (tag, kv-dict) the caller should emit()."""

    action: str  # 'restart' | 'peer-pull' | 'alert' | 'noop'
    argv: list[str]
    reason: str
    emits: list[tuple[str, dict]] = field(default_factory=list)


def _pull_argv(recovery_script: str, pull_mode: str, force: bool) -> list[str]:
    argv = ["bash", recovery_script, pull_mode, "--auto"]
    if force:
        argv.append("--force")
    return argv


def _restart_argv(recovery_script: str, force: bool) -> list[str]:
    argv = ["bash", recovery_script, "restart", "--auto"]
    if force:
        argv.append("--force")
    return argv


def is_catchup_divergence(
    last_advance_age_s: int,
    div_hit: str | None,
    healthy_peers: int,
    peer_max_height: int,
    local_h: int,
    catchup_stall_s: int = CATCHUP_STALL_SECONDS,
) -> bool:
    """True when a `catching_up=True` node is actually DIVERGED, not just syncing.

    A genuine block-sync/state-sync advances, so its height is never frozen for
    catchup_stall_s. Real divergence requires ALL of:
      - the local height has been FROZEN for >= catchup_stall_s;
      - an AppHash / consensus-failure line appeared in the detection window
        (div_hit is the matched pattern, or None);
      - >= 2 healthy peers are strictly ahead of us (the canonical chain moved on).
    PURE: no I/O, no clock — trivially unit-testable.
    """
    return bool(last_advance_age_s >= catchup_stall_s and div_hit and healthy_peers >= 2 and peer_max_height > local_h)


def lag_warning_due(
    consecutive_over_polls: int,
    stall_n: int,
    required_polls: int = LAG_ALERT_POLLS,
    stall_blocks: int = STALL_BLOCKS,
) -> bool:
    """True when a trailing-peers warning is warranted (see _lag_alert_once).

    The gap must hold for required_polls polls — a single poll can straddle a
    block and read behind for no reason — and we stand down once the height has
    been frozen long enough for the stall trigger to own the incident, so one
    event never produces two competing alert streams.
    PURE: no I/O, no clock — trivially unit-testable.
    """
    return consecutive_over_polls >= required_polls and stall_n < stall_blocks


def decide_action(
    trigger: str | None,
    local_h: int,
    local_app_hash: str | None,
    peer_app_hashes: dict,  # ip -> app_hash AT local_h (healthy peers)
    autorecover: bool,
    restart_cooldown_remaining_s: int,
    pull_cooldown_remaining_s: int,
    recent_restart_count: int,
    dry_run: bool = False,
    escalate_after: int = RESTART_ESCALATE_AFTER,
    recovery_script: str = str(RECOVERY_SCRIPT),
    pull_mode: str = RECOVERY_MODE,
    destructive_disabled_reason: str = "WATCHDOG_AUTORECOVER off",
    upgrade_halt: bool = False,
    halt_kind: str = "upgrade halt",
) -> Decision:
    """Map a fired trigger to a concrete action. PURE: every piece of
    side-effecting state (cool-down remainders, recent restart count, gate) is
    passed in, so tests need no filesystem or clock mocking.

    Ladder:
      log_pattern        -> peer-pull (gated)
      stall + ah match   -> restart (ungated), unless recurrence threshold hit
      stall + ah mismatch-> peer-pull (gated)
      process_dead       -> restart (ungated, force past restart cool-down)
      any trigger + halt -> alert (a halt is a binary swap, not a wipe)

    `halt_kind` names the halt in the alert so the operator is not sent after
    the wrong cause; it does not change the disposition.
    """
    if trigger is None:
        return Decision("noop", [], "no trigger")

    if upgrade_halt:
        # The process is supposed to be stopped. Restarting it hits the halt
        # again, fails to advance, and used to escalate to a chain-DB wipe.
        return Decision(
            "alert",
            [],
            f"{trigger} during {halt_kind}; refusing restart/wipe (swap binaries)",
            [
                (
                    "ALERT",
                    {
                        "kind": halt_kind.replace(" ", "-"),
                        "trigger": trigger,
                    },
                )
            ],
        )

    def peer_pull(reason: str, force: bool = False) -> Decision:
        if not autorecover:
            return Decision(
                "alert",
                [],
                reason + f" ({destructive_disabled_reason})",
                [
                    (
                        "ALERT",
                        {
                            "kind": "needs-peer-pull-no-autorecover",
                            "trigger": trigger,
                            "reason": reason,
                            "disabled_reason": destructive_disabled_reason,
                        },
                    )
                ],
            )
        if pull_cooldown_remaining_s > 0 and not force:
            return Decision(
                "noop",
                [],
                reason + " (peer-pull cool-down)",
                [
                    (
                        "COOLDOWN",
                        {
                            "suppressed": pull_mode,
                            "lock": "divergence_recovery_lock",
                            "remaining_s": pull_cooldown_remaining_s,
                            "trigger_was": trigger,
                        },
                    )
                ],
            )
        if dry_run:
            return Decision(
                "noop",
                _pull_argv(recovery_script, pull_mode, force),
                reason + " (dry-run)",
            )
        return Decision("peer-pull", _pull_argv(recovery_script, pull_mode, force), reason)

    def restart(reason: str, force: bool = False) -> Decision:
        if restart_cooldown_remaining_s > 0 and not force:
            return Decision(
                "noop",
                [],
                reason + " (restart cool-down)",
                [
                    (
                        "COOLDOWN",
                        {
                            "suppressed": "restart",
                            "lock": "restart_recovery_lock",
                            "remaining_s": restart_cooldown_remaining_s,
                            "trigger_was": trigger,
                        },
                    )
                ],
            )
        if dry_run:
            return Decision(
                "noop",
                _restart_argv(recovery_script, force),
                reason + " (dry-run)",
            )
        return Decision("restart", _restart_argv(recovery_script, force), reason)

    if trigger == TRIGGER_LOG_PATTERN:
        # Canonical divergence: state is wrong, restart cannot fix it.
        return peer_pull("log-pattern divergence; restart cannot fix wrong state")

    if trigger == TRIGGER_STALL:
        # Recurrence escalation: too many restarts in the window means this is
        # not a transient hang — go destructive (still gated).
        if recent_restart_count >= escalate_after:
            d = peer_pull(
                f"stall, but {recent_restart_count} restarts within window "
                f"(>= {escalate_after}); escalating to {pull_mode}"
            )
            d.emits.append(
                (
                    "ESCALATE",
                    {
                        "from": "restart",
                        "to": pull_mode,
                        "reason": "restart_recurrence_threshold",
                        "recent_restarts": recent_restart_count,
                        "escalate_after": escalate_after,
                    },
                )
            )
            return d
        # App_hash agreement gate: matching peers => local state is correct =>
        # a restart is the right, non-destructive fix.
        if local_app_hash and peer_app_hashes and all(h == local_app_hash for h in peer_app_hashes.values()):
            return restart("stall; app_hash matches all healthy peers at stuck height")
        return peer_pull("stall; app_hash mismatch/unknown vs peers — treat as divergence")

    if trigger == TRIGGER_PROCESS_DEAD:
        # Process is gone: bring it back via the supervisor. Force past the
        # restart cool-down because the node is fully down.
        return restart("process-dead; supervisor restart", force=True)

    return Decision("noop", [], f"unhandled trigger {trigger!r}")


def decide_escalation_after_restart(
    exit_code: int,
    autorecover: bool,
    pull_cooldown_remaining_s: int,
    force: bool = False,
    recovery_script: str = str(RECOVERY_SCRIPT),
    pull_mode: str = RECOVERY_MODE,
    destructive_disabled_reason: str = "WATCHDOG_AUTORECOVER off",
    upgrade_halt: bool = False,
    halt_kind: str = "upgrade halt",
) -> Decision:
    """Called when a `restart` action returned non-zero (5 = chain did not
    advance; other = error). PURE. Decides whether to escalate to peer-pull."""
    if exit_code == 0:
        return Decision("noop", [], "restart succeeded")
    if upgrade_halt:
        return Decision(
            "alert",
            [],
            f"restart exit {exit_code}; {halt_kind} in logs; refusing peer-pull",
            [
                (
                    "ALERT",
                    {
                        "kind": halt_kind.replace(" ", "-"),
                        "exit_code": exit_code,
                    },
                )
            ],
        )
    if not autorecover:
        return Decision(
            "alert",
            [],
            f"restart exit {exit_code}; {destructive_disabled_reason}, cannot escalate",
            [
                (
                    "ALERT",
                    {
                        "kind": "restart-failed-no-autorecover",
                        "exit_code": exit_code,
                        "disabled_reason": destructive_disabled_reason,
                    },
                )
            ],
        )
    if pull_cooldown_remaining_s > 0 and not force:
        return Decision(
            "noop",
            [],
            f"restart exit {exit_code}; peer-pull cool-down active",
            [
                (
                    "COOLDOWN",
                    {
                        "suppressed": pull_mode,
                        "lock": "divergence_recovery_lock",
                        "remaining_s": pull_cooldown_remaining_s,
                        "trigger_was": "restart_failed",
                    },
                )
            ],
        )
    return Decision(
        "peer-pull",
        _pull_argv(recovery_script, pull_mode, force),
        f"escalate after restart exit {exit_code}",
        [("ESCALATE", {"from": "restart", "to": pull_mode, "reason": f"restart exit code {exit_code}"})],
    )


# ── Forensic helpers used only by the loop ──────────────────────────────
def _trailing_equal(history) -> int:
    """How many trailing entries equal the last one (i.e. how stuck we are)."""
    if not history:
        return 0
    last = history[-1]
    c = 0
    for h in reversed(history):
        if h == last:
            c += 1
        else:
            break
    return c


def _emit_peer(p: dict) -> None:
    if p.get("reachable") and "err" not in p:
        ah = p.get("app_hash") or ""
        emit(
            "PEER",
            ip=p["ip"],
            reachable=True,
            h=p.get("height", 0),
            app_hash=(ah[:16] + "..." if ah else ""),
            catching_up=p.get("catching_up"),
            rtt_ms=p.get("rtt_ms"),
        )
    else:
        emit("PEER", ip=p["ip"], reachable=bool(p.get("reachable")), err=p.get("err", ""), rtt_ms=p.get("rtt_ms"))


def _invoke(argv: list[str], reason: str | None = None) -> int | None:
    """Run a recovery subprocess WITHOUT piping its output, so recover.sh's
    progress streams live to Supervisor's capture. The full step-by-step trail lives
    in recover.sh's own daily log (child_log), cross-referenced here by pid."""
    child_log = f"{LOGS_DIR}/deploy/divergence_recovery-{datetime.now(timezone.utc):%Y-%m-%d}.log"
    env = os.environ.copy()
    if reason:
        # recover.sh stamps RECOVERY_REASON into the pre-wipe forensic snapshot
        # manifest, so a captured diverged DB is always traceable back to the
        # watchdog trigger that decided to wipe it.
        env["RECOVERY_REASON"] = f"watchdog:{reason}"
        # Page a human that the node crashed/diverged and recovery is starting.
        # Deduped by ALERT_REPEAT_SECONDS so multi-attempt incidents (peer-pull
        # retries) page once, not once per attempt.
        global _last_external_notify
        if time.time() - _last_external_notify >= ALERT_REPEAT_SECONDS:
            _last_external_notify = time.time()
            notify_external("node recovery dispatched", f"reason={reason} mode={RECOVERY_MODE}")
    try:
        # stdin from /dev/null: the watchdog is supervised, so an inherited
        # TTY stdin would let recovery's background ssh take SIGTTIN and stop
        # (state T), which is unkillable by SIGTERM and wedges recovery forever.
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        emit("CRASH", where="invoke_spawn", argv=json.dumps(argv), err=repr(e))
        return None
    emit("INVOKE", phase="start", argv=json.dumps(argv), pid=proc.pid, child_log=child_log)
    t0 = time.time()
    code = proc.wait()
    emit("INVOKE", phase="end", pid=proc.pid, exit_code=code, duration_s=int(time.time() - t0))
    return code


_last_external_notify = 0.0


def notify_external(title: str, text: str) -> None:
    """Best-effort external push to ALERT_WEBHOOK_URL (no-op if unset). Sends a
    provider-agnostic {"text": ...} JSON body. NEVER raises: a short timeout and
    a blanket except keep a flaky/unreachable webhook from stalling the loop."""
    if not ALERT_WEBHOOK_URL:
        return
    body = json.dumps({"text": f"[mirage:{NODE_LABEL}] {title}\n{text}"}).encode()
    req = urllib.request.Request(
        ALERT_WEBHOOK_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=ALERT_WEBHOOK_TIMEOUT) as r:
            emit("ALERT", kind="webhook-sent", status=getattr(r, "status", 0))
    except Exception as e:  # noqa: BLE001 — notification must never break the watchdog
        emit("ALERT", kind="webhook-failed", err=repr(e))


def _loud_alert(trigger: str, reason: str) -> None:
    """Human-friendly multi-line alert block, deduped by the caller. The
    structured [ALERT] line is emitted separately every poll for the grep
    trail; this block is the eyeball-grabbing version."""
    log("============================================================")
    log("ALERT: watchdog recovery needed (see [TRIGGER]/[DISPATCH]/[ALERT] lines).")
    log(f"  trigger: {trigger}  reason: {reason}")
    log("  Investigate: mirage-status   (Supervisor programs: node, watchdog)")
    log(f"  Dry-run:     docker exec -it mirage bash {RECOVERY_SCRIPT} {RECOVERY_MODE} --dry-run")
    log(f"  Recover:     docker exec -it mirage bash {RECOVERY_SCRIPT} {RECOVERY_MODE} --auto")
    log("  Runbook:     docs/troubleshooting/divergence-recovery.md")
    log("============================================================")
    notify_external("watchdog ALERT — recovery needed", f"trigger={trigger} reason={reason}")


def _alert_once(trigger: str, reason: str) -> None:
    """Emit the loud block at most once per ALERT_REPEAT_SECONDS, using the
    dedicated ALERT_LOCK (NEVER the destructive cool-down LOCK — 2026-06-12)."""
    age = marker_age_s(ALERT_LOCK)
    if age is None or age >= ALERT_REPEAT_SECONDS:
        _loud_alert(trigger, reason)
        try:
            ALERT_LOCK.parent.mkdir(parents=True, exist_ok=True)
            ALERT_LOCK.touch()
        except OSError:
            pass
    else:
        emit("ALERT", kind="loud-suppressed", trigger=trigger, re_alert_in_s=int(ALERT_REPEAT_SECONDS - age))


def _disk_alert_once(disk: int) -> None:
    """Warn when the NODE_HOME filesystem crosses DISK_ALERT_PCT.

    ALERT-ONLY, deliberately: this never prunes, deletes or recovers anything.
    Disk pressure is a capacity decision for a human, and automating deletion
    under pressure is actively dangerous here — mass IAVL delete passes are the
    machinery behind the prune-hole crashes and the lockstep stall, and PebbleDB
    needs free headroom to compact, so bulk deletes can spike usage before they
    reclaim it. Firing that at 90% full is the worst possible moment.

    Deduped on its OWN marker: reusing ALERT_LOCK would let a disk warning
    suppress a genuine divergence alert (the 2026-06-12 shared-lock lesson).
    """
    if disk < DISK_ALERT_PCT:
        return
    age = marker_age_s(DISK_ALERT_LOCK)
    if age is not None and age < DISK_ALERT_REPEAT_SECONDS:
        emit("DISK", kind="warn-suppressed", used_pct=disk, re_alert_in_s=int(DISK_ALERT_REPEAT_SECONDS - age))
        return
    log("============================================================")
    log(f"WARNING: disk {disk}% used on {NODE_HOME} (threshold {DISK_ALERT_PCT}%).")
    log("  Capacity warning, NOT a divergence. Nothing was deleted.")
    log("  Triage:  du -sh /root/.mirage/* /var/lib/docker /var/log | sort -rh")
    log("  Usual suspects are logs and journald, not chain state (application.db")
    log("  is tens of MB once pruning has caught up). Do NOT reach for more")
    log("  aggressive pruning; see docs/troubleshooting/divergence-recovery.md.")
    log("============================================================")
    emit("DISK", kind="warn", used_pct=disk, threshold_pct=DISK_ALERT_PCT)
    notify_external(
        "disk pressure warning",
        f"{disk}% used on {NODE_HOME} (threshold {DISK_ALERT_PCT}%); nothing deleted, capacity check needed",
    )
    try:
        DISK_ALERT_LOCK.parent.mkdir(parents=True, exist_ok=True)
        DISK_ALERT_LOCK.touch()
    except OSError:
        pass


def _lag_alert_once(local_h: int, peer_max: int, lag: int, polls: int) -> None:
    """Warn when the node trails healthy peers while STILL COMMITTING blocks.

    ALERT-ONLY, deliberately. This is the slow-but-alive case: the node is not
    wedged and not diverged, it is losing a race, and it closes the gap by itself
    once the pressure lifts. Restarting it would replay the WAL on the very disk
    that is already the bottleneck, turning a five-minute lag into a real outage.
    Recovery stays reserved for a FROZEN height (signal 2) — which this is not,
    and which is exactly why this case had no detector before 2026-08-06.

    Own dedup marker: sharing ALERT_LOCK would let a lag warning suppress a
    genuine divergence alert (the 2026-06-12 shared-lock lesson).
    """
    age = marker_age_s(LAG_ALERT_LOCK)
    if age is not None and age < LAG_ALERT_REPEAT_SECONDS:
        emit("LAG", kind="warn-suppressed", lag=lag, re_alert_in_s=int(LAG_ALERT_REPEAT_SECONDS - age))
        return
    log("============================================================")
    log(f"WARNING: {lag} blocks behind peers (local={local_h} peer_max={peer_max}).")
    log(f"  Behind for {polls} consecutive polls but STILL ADVANCING, so this is")
    log("  neither a stall nor a divergence: no recovery was dispatched, and none")
    log("  should be forced. The node re-converges on its own.")
    log("  It is NOT harmless, though: while the head is stale the chain rejects")
    log("  relayed writes ('envelope_timestamp in future') and the backend answers")
    log("  503 node_catching_up, so users see posts and votes fail.")
    log("  Triage host disk latency first — [IO] and [POLL] io_await_ms in this")
    log("  log, then `iostat -x 5`. On 2026-08-06 the droplet's disk went from 3ms")
    log("  to 281ms average service time and the node fell 21 blocks behind.")
    log("============================================================")
    emit("LAG", kind="warn", local_h=local_h, peer_max=peer_max, lag=lag, polls=polls, threshold=LAG_ALERT_BLOCKS)
    notify_external(
        "node trailing peers",
        f"{lag} blocks behind peers (local={local_h} peer_max={peer_max}) for {polls} polls; "
        "still advancing so no recovery dispatched — writes are failing, check host disk latency",
    )
    try:
        LAG_ALERT_LOCK.parent.mkdir(parents=True, exist_ok=True)
        LAG_ALERT_LOCK.touch()
    except OSError:
        pass


def _io_alert_once(await_ms: int, busy_pct: int, polls: int) -> None:
    """Warn when host disk latency is high enough to threaten block commits.

    ALERT-ONLY: nothing the watchdog can do to a managed volume makes it faster,
    and every recovery action it owns writes MORE to that disk. This exists to
    name the root cause in the same breath as its symptoms, because from inside
    CometBFT a degraded volume looks like a mystery: /status keeps reporting
    catching_up=false while blocks quietly take 20s instead of 3.6s.
    """
    age = marker_age_s(IO_ALERT_LOCK)
    if age is not None and age < IO_ALERT_REPEAT_SECONDS:
        emit("IO", kind="warn-suppressed", await_ms=await_ms, re_alert_in_s=int(IO_ALERT_REPEAT_SECONDS - age))
        return
    log("============================================================")
    log(f"WARNING: host disk await {await_ms}ms (threshold {IO_AWAIT_ALERT_MS}ms), device busy {busy_pct}%.")
    log(f"  Sustained for {polls} consecutive polls. Consensus is fsync-bound, so")
    log("  this stalls block commits, Postgres checkpoints and the indexer at once.")
    log("  Check whether the cause is US or the VOLUME:  iostat -x 5")
    log("    IOPS up + latency up   -> our workload (compaction, snapshot, vacuum)")
    log("    IOPS flat/down + latency up -> the volume degraded; a provider issue")
    log("  2026-08-06 was the second kind: 33 -> 13 IOPS while await went 12 ->")
    log("  281ms. Nothing was deleted or restarted, and it self-healed in ~13 min.")
    log("============================================================")
    emit("IO", kind="warn", await_ms=await_ms, busy_pct=busy_pct, polls=polls, threshold_ms=IO_AWAIT_ALERT_MS)
    notify_external(
        "host disk latency warning",
        f"disk await {await_ms}ms (threshold {IO_AWAIT_ALERT_MS}ms), busy {busy_pct}%, {polls} polls; "
        "block commits and Postgres are both fsync-bound on this volume",
    )
    try:
        IO_ALERT_LOCK.parent.mkdir(parents=True, exist_ok=True)
        IO_ALERT_LOCK.touch()
    except OSError:
        pass


# ── Core loop ───────────────────────────────────────────────────────────
def run(dry_run: bool) -> int:
    import signal

    start_ts = time.time()
    stats = {
        "polls": 0,
        "triggers": {"log_pattern": 0, "stall": 0, "process_dead": 0},
        "dispatches": {"restart": 0, "peer-pull": 0, "alert": 0},
    }

    def destructive_gate() -> tuple[bool, bool, str]:
        key_present = path_is_file(RECOVERY_KEY)
        ready = WATCHDOG_AUTORECOVER and (RECOVERY_MODE != "peer-pull" or key_present)
        reason = "WATCHDOG_AUTORECOVER off" if not WATCHDOG_AUTORECOVER else f"RECOVERY_KEY missing at {RECOVERY_KEY}"
        return key_present, ready, reason

    recovery_key_present, destructive_recovery_ready, destructive_disabled_reason = destructive_gate()

    # STARTUP: dump EVERY knob + config so a 4-month-old log is self-describing.
    try:
        WATCHDOG_LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    emit(
        "STARTUP",
        poll_seconds=POLL_SECONDS,
        detection_window_s=DETECTION_WINDOW,
        stall_blocks=STALL_BLOCKS,
        peer_ahead_threshold=PEER_AHEAD_THRESHOLD,
        dead_threshold=DEAD_THRESHOLD,
        dry_run=dry_run,
        autorecover=WATCHDOG_AUTORECOVER,
        recovery_mode=RECOVERY_MODE,
        recovery_script=str(RECOVERY_SCRIPT),
        recovery_script_sha256=file_sha256_short(RECOVERY_SCRIPT),
        recovery_key=str(RECOVERY_KEY),
        recovery_key_present=recovery_key_present,
        destructive_recovery_ready=destructive_recovery_ready,
        cooldown_s=COOLDOWN_SECONDS,
        restart_cooldown_s=RESTART_COOLDOWN_SECONDS,
        restart_escalate_after=RESTART_ESCALATE_AFTER,
        restart_escalate_window_s=RESTART_ESCALATE_WINDOW_SECONDS,
        restart_verify_s=RECOVERY_VERIFY_SECONDS_RESTART,
        lock=str(LOCK),
        lock_age_s=marker_age_s(LOCK),
        restart_lock=str(RESTART_LOCK),
        restart_lock_age_s=marker_age_s(RESTART_LOCK),
        alert_lock=str(ALERT_LOCK),
        alert_lock_age_s=marker_age_s(ALERT_LOCK),
        disk_alert_pct=DISK_ALERT_PCT,
        disk_alert_lock_age_s=marker_age_s(DISK_ALERT_LOCK),
        disable_marker=str(DISABLE_MARKER),
        disable_marker_present=DISABLE_MARKER.exists(),
        local_rpc=LOCAL_RPC,
        node_home=str(NODE_HOME),
        persistent_peers=",".join(get_persistent_peer_ips()) or "none",
        log_dir=str(WATCHDOG_LOG_DIR),
        log_retention_days=WATCHDOG_LOG_RETENTION_DAYS,
    )

    if not WATCHDOG_AUTORECOVER:
        emit(
            "STARTUP",
            mode="restart-only",
            note="destructive peer-pull DISABLED (WATCHDOG_AUTORECOVER!=true); restart still active",
        )
    elif RECOVERY_MODE == "peer-pull" and not recovery_key_present:
        # Do NOT exit here: that would also disable the non-destructive restart
        # path on the one host where destructive peer-pull is normally enabled.
        # Surface the broken destructive path loudly and keep restart-only alive.
        emit("ALERT", kind="destructive-autorecover-disabled", reason=destructive_disabled_reason)
        log("============================================================")
        log("ALERT: WATCHDOG_AUTORECOVER=true with RECOVERY_MODE=peer-pull,")
        log(f"  but the recovery key is missing: {RECOVERY_KEY}")
        log("  Destructive auto-recovery CANNOT work on this host until fixed. Either:")
        log("    - provision it:  ./scripts/recover.sh provision --cluster=... --peer=... --container-host=...")
        log("    - or set RECOVERY_MODE=state-sync / WATCHDOG_AUTORECOVER=false")
        log("  Restart-only recovery remains active.")
        log("============================================================")

    def _shutdown(signum, _frame):
        emit(
            "SHUTDOWN",
            reason=f"signal:{signum}",
            uptime_s=int(time.time() - start_ts),
            polls=stats["polls"],
            triggers=json.dumps(stats["triggers"]),
            dispatches=json.dumps(stats["dispatches"]),
        )
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)

    height_history: deque[int] = deque(maxlen=STALL_BLOCKS + 1)
    recent_restarts: deque[float] = deque()
    consecutive_unreachable = 0
    last_advance_h: int | None = None
    last_advance_ts = start_ts
    last_cleanup_date = datetime.now(timezone.utc).date()
    io_prev: tuple[int, int, int] | None = None
    io_prev_ts = start_ts
    io_slow_polls = 0
    lag_polls = 0

    def recent_restart_count() -> int:
        cutoff = time.time() - RESTART_ESCALATE_WINDOW_SECONDS
        while recent_restarts and recent_restarts[0] < cutoff:
            recent_restarts.popleft()
        return len(recent_restarts)

    while True:
        try:
            stats["polls"] += 1
            poll_no = stats["polls"]
            recovery_key_present, destructive_recovery_ready, destructive_disabled_reason = destructive_gate()

            # Daily forensic-log retention sweep (once per UTC day).
            today = datetime.now(timezone.utc).date()
            if today != last_cleanup_date:
                removed = cleanup_old_logs()
                emit("RETENTION", removed=removed, retention_days=WATCHDOG_LOG_RETENTION_DAYS)
                last_cleanup_date = today

            if DISABLE_MARKER.exists():
                emit("POLL", poll=poll_no, disabled=True, marker=str(DISABLE_MARKER))
                time.sleep(POLL_SECONDS)
                continue

            trigger: str | None = None
            local_h = 0
            local_app_hash: str | None = None
            peer_app_hashes: dict = {}

            pid = miraged_pid()
            rss = proc_rss_mb(pid)
            disk = disk_used_pct(NODE_HOME)
            if disk is not None:
                _disk_alert_once(disk)
            io_now = read_disk_counters()
            io = disk_pressure(io_prev, io_now, time.time() - io_prev_ts)
            io_prev, io_prev_ts = io_now, time.time()
            io_await = io_busy = None
            if io is not None:
                io_await, io_busy = io
                # An idle interval yields no reading at all (io is None), which
                # must not reset the counter — absence of requests is not proof
                # the volume recovered.
                io_slow_polls = io_slow_polls + 1 if io_await > IO_AWAIT_ALERT_MS else 0
                if io_slow_polls >= IO_ALERT_POLLS:
                    _io_alert_once(io_await, io_busy, io_slow_polls)
            step, rnd = read_priv_validator_step()

            local = get_status(LOCAL_RPC)
            if not local:
                consecutive_unreachable += 1
                emit(
                    "POLL",
                    poll=poll_no,
                    local_status="unreachable",
                    unreachable=f"{consecutive_unreachable}/{DEAD_THRESHOLD}",
                    miraged_pid=pid if pid else "none",
                    mem_rss_mb=rss if rss is not None else "n/a",
                    disk_used_pct=disk if disk is not None else "n/a",
                    io_await_ms=io_await if io_await is not None else "n/a",
                    io_busy_pct=io_busy if io_busy is not None else "n/a",
                )
                if consecutive_unreachable < DEAD_THRESHOLD:
                    time.sleep(POLL_SECONDS)
                    continue
                if pid:
                    emit(
                        "POLL", poll=poll_no, note="status unreachable but miraged process alive; treating as transient"
                    )
                    time.sleep(POLL_SECONDS)
                    continue
                peers = probe_peers()
                for p in peers:
                    _emit_peer(p)
                healthy, peer_max = healthy_summary(peers)
                emit(
                    "GATE",
                    watchdog_autorecover=WATCHDOG_AUTORECOVER,
                    destructive_recovery_ready=destructive_recovery_ready,
                    recovery_key_present=recovery_key_present,
                    pull_cooldown_s=cooldown_remaining_s(LOCK, COOLDOWN_SECONDS),
                    restart_cooldown_s=cooldown_remaining_s(RESTART_LOCK, RESTART_COOLDOWN_SECONDS),
                    disable_marker=DISABLE_MARKER.exists(),
                    dry_run=dry_run,
                    recent_restarts=recent_restart_count(),
                )
                trigger = TRIGGER_PROCESS_DEAD
                stats["triggers"]["process_dead"] += 1
                emit(
                    "TRIGGER",
                    type="process-dead",
                    unreachable_polls=consecutive_unreachable,
                    peers_healthy=healthy,
                    peer_max=peer_max,
                )
            else:
                consecutive_unreachable = 0
                try:
                    si = local["sync_info"]
                    local_h = int(si["latest_block_height"])
                    catching_up = bool(si["catching_up"])
                except (KeyError, ValueError):
                    emit("POLL", poll=poll_no, error="local /status missing sync_info")
                    time.sleep(POLL_SECONDS)
                    continue

                if last_advance_h is None or local_h != last_advance_h:
                    last_advance_h = local_h
                    last_advance_ts = time.time()
                last_advance_age = int(time.time() - last_advance_ts)

                if catching_up:
                    # A node doing genuine block-sync/state-sync also reports
                    # catching_up=True — but it ADVANCES. A diverged node (wrong
                    # AppHash) gets wedged: catching_up stays True, the height is
                    # FROZEN, and its CometBFT log spews "wrong Block.Header.AppHash"
                    # while healthy peers move on. The old code unconditionally
                    # logged "not a divergence" and never acted, so a real
                    # divergence hiding behind catching_up=True was invisible to
                    # recovery (2026-06-16 mirage.talk: stuck ~95 min until a
                    # manual peer-pull). Detect the stuck+diverged case here.
                    height_history.clear()
                    div_hit = None
                    healthy = peer_max = 0
                    stuck = last_advance_age >= CATCHUP_STALL_SECONDS
                    if stuck:
                        log_path = latest_log_file()
                        if log_path:
                            div_hit = log_window_has_pattern(
                                tail_recent(log_path), DIVERGENCE_PATTERNS, DETECTION_WINDOW
                            )
                        if div_hit:
                            peers = probe_peers()
                            for p in peers:
                                _emit_peer(p)
                            healthy, peer_max = healthy_summary(peers)
                    if is_catchup_divergence(last_advance_age, div_hit, healthy, peer_max, local_h):
                        # Frozen height + AppHash error + healthy peers ahead =
                        # divergence. Route through the log-pattern trigger, which
                        # decide_action sends to peer-pull (no restart can fix
                        # wrong state). Gating still applies in decide_action.
                        trigger = TRIGGER_LOG_PATTERN
                        stats["triggers"]["log_pattern"] += 1
                        emit(
                            "TRIGGER",
                            type="log_pattern",
                            pattern=div_hit,
                            via="catching_up_stall",
                            local_h=local_h,
                            last_advance_age_s=last_advance_age,
                            peers_healthy=healthy,
                            peer_max=peer_max,
                        )
                        emit(
                            "GATE",
                            watchdog_autorecover=WATCHDOG_AUTORECOVER,
                            destructive_recovery_ready=destructive_recovery_ready,
                            recovery_key_present=recovery_key_present,
                            pull_cooldown_s=cooldown_remaining_s(LOCK, COOLDOWN_SECONDS),
                            restart_cooldown_s=cooldown_remaining_s(RESTART_LOCK, RESTART_COOLDOWN_SECONDS),
                            disable_marker=DISABLE_MARKER.exists(),
                            dry_run=dry_run,
                            alert_lock_age_s=marker_age_s(ALERT_LOCK),
                            recent_restarts=recent_restart_count(),
                        )
                        # Fall through to the shared dispatch below (no continue).
                    else:
                        emit(
                            "POLL",
                            poll=poll_no,
                            local_h=local_h,
                            catching_up=True,
                            step=step if step is not None else "n/a",
                            round=rnd if rnd is not None else "n/a",
                            last_advance_h=last_advance_h,
                            last_advance_age_s=last_advance_age,
                            miraged_pid=pid if pid else "none",
                            mem_rss_mb=rss if rss is not None else "n/a",
                            disk_used_pct=disk if disk is not None else "n/a",
                            io_await_ms=io_await if io_await is not None else "n/a",
                            io_busy_pct=io_busy if io_busy is not None else "n/a",
                            note=(
                                "catching_up; stuck but no divergence signal"
                                if stuck
                                else "catching_up; not a divergence"
                            ),
                        )
                        time.sleep(POLL_SECONDS)
                        continue
                else:
                    height_history.append(local_h)
                    stall_n = _trailing_equal(height_history)
                    emit(
                        "POLL",
                        poll=poll_no,
                        local_h=local_h,
                        catching_up=False,
                        step=step if step is not None else "n/a",
                        round=rnd if rnd is not None else "n/a",
                        last_advance_h=last_advance_h,
                        last_advance_age_s=last_advance_age,
                        stall_count=f"{stall_n}/{STALL_BLOCKS}",
                        history=list(height_history),
                        miraged_pid=pid if pid else "none",
                        mem_rss_mb=rss if rss is not None else "n/a",
                        disk_used_pct=disk if disk is not None else "n/a",
                        io_await_ms=io_await if io_await is not None else "n/a",
                        io_busy_pct=io_busy if io_busy is not None else "n/a",
                    )

                    peers = probe_peers()
                    for p in peers:
                        _emit_peer(p)
                    healthy, peer_max = healthy_summary(peers)

                    # Behind the network but still advancing — invisible to every
                    # trigger below, all of which need a frozen height.
                    lag = peer_max - local_h if healthy >= 2 and peer_max > 0 else 0
                    lag_polls = lag_polls + 1 if lag > LAG_ALERT_BLOCKS else 0
                    if lag_warning_due(lag_polls, stall_n):
                        _lag_alert_once(local_h, peer_max, lag, lag_polls)
                    emit(
                        "GATE",
                        watchdog_autorecover=WATCHDOG_AUTORECOVER,
                        destructive_recovery_ready=destructive_recovery_ready,
                        recovery_key_present=recovery_key_present,
                        pull_cooldown_s=cooldown_remaining_s(LOCK, COOLDOWN_SECONDS),
                        restart_cooldown_s=cooldown_remaining_s(RESTART_LOCK, RESTART_COOLDOWN_SECONDS),
                        disable_marker=DISABLE_MARKER.exists(),
                        dry_run=dry_run,
                        alert_lock_age_s=marker_age_s(ALERT_LOCK),
                        recent_restarts=recent_restart_count(),
                    )

                    # Signal 1: log-pattern divergence.
                    log_path = latest_log_file()
                    if log_path:
                        tail = tail_recent(log_path)
                        hit = log_window_has_pattern(tail, DIVERGENCE_PATTERNS, DETECTION_WINDOW)
                        if hit:
                            trigger = TRIGGER_LOG_PATTERN
                            stats["triggers"]["log_pattern"] += 1
                            emit("TRIGGER", type="log_pattern", pattern=hit, log=log_path.name, local_h=local_h)

                    # Signal 2: stall vs peers.
                    if (
                        trigger is None
                        and len(height_history) == height_history.maxlen
                        and len(set(height_history)) == 1
                        and healthy >= 2
                        and peer_max > local_h + PEER_AHEAD_THRESHOLD
                    ):
                        trigger = TRIGGER_STALL
                        stats["triggers"]["stall"] += 1
                        emit(
                            "TRIGGER",
                            type="stall",
                            local_h=local_h,
                            stall_polls=f"{STALL_BLOCKS}/{STALL_BLOCKS}",
                            peer_max=peer_max,
                            peers_healthy=healthy,
                            lag=peer_max - local_h,
                            last_advance_age_s=last_advance_age,
                        )
                        # PRECHECK: app_hash agreement AT the stuck height decides
                        # restart (state OK) vs peer-pull (state diverged).
                        local_app_hash, peer_app_hashes = local_peer_app_hash_at(local_h, peers)
                        match = bool(
                            local_app_hash
                            and peer_app_hashes
                            and all(h == local_app_hash for h in peer_app_hashes.values())
                        )
                        emit(
                            "PRECHECK",
                            kind="app_hash_at_local_h",
                            height=local_h,
                            local=(local_app_hash[:16] + "..." if local_app_hash else "unknown"),
                            peer_hashes="{" + ",".join(f"{ip}:{h[:12]}..." for ip, h in peer_app_hashes.items()) + "}",
                            match=match,
                            peer_count=len(peer_app_hashes),
                        )

            if trigger is None:
                time.sleep(POLL_SECONDS)
                continue

            upgrade_halt = False
            halt_kind = "upgrade halt"
            halt_log = latest_log_file()
            if halt_log:
                halt_text = tail_recent(halt_log)
                if log_has_upgrade_halt(halt_text):
                    upgrade_halt = True
                elif log_has_consensus_fatal_halt(halt_text):
                    upgrade_halt = True
                    halt_kind = "consensus-fatal halt"
            if upgrade_halt:
                emit("GATE", upgrade_halt=True, halt_kind=halt_kind, log=halt_log.name if halt_log else "")

            # ── Pure dispatch ───────────────────────────────────────────
            decision = decide_action(
                trigger=trigger,
                local_h=local_h,
                local_app_hash=local_app_hash,
                peer_app_hashes=peer_app_hashes,
                autorecover=destructive_recovery_ready,
                restart_cooldown_remaining_s=cooldown_remaining_s(RESTART_LOCK, RESTART_COOLDOWN_SECONDS),
                pull_cooldown_remaining_s=cooldown_remaining_s(LOCK, COOLDOWN_SECONDS),
                recent_restart_count=recent_restart_count(),
                dry_run=dry_run,
                destructive_disabled_reason=destructive_disabled_reason,
                upgrade_halt=upgrade_halt,
                halt_kind=halt_kind,
            )
            emit(
                "DISPATCH",
                action=decision.action,
                reason=decision.reason,
                argv=json.dumps(decision.argv) if decision.argv else "[]",
            )
            for tag, kv in decision.emits:
                emit(tag, **kv)

            if decision.action == "alert":
                stats["dispatches"]["alert"] += 1
                _alert_once(trigger, decision.reason)
                time.sleep(POLL_SECONDS)
                continue

            if decision.action == "noop":
                # Cool-down / dry-run: nothing to run, keep history armed.
                time.sleep(POLL_SECONDS)
                continue

            # action is restart or peer-pull: execute.
            code = _invoke(decision.argv, reason=decision.reason)
            stats["dispatches"][decision.action] = stats["dispatches"].get(decision.action, 0) + 1
            if decision.action == "restart":
                recent_restarts.append(time.time())

            post = get_status(LOCAL_RPC)
            new_h = None
            if post:
                try:
                    new_h = int(post["sync_info"]["latest_block_height"])
                except (KeyError, ValueError):
                    new_h = None
            emit(
                "POSTCHECK",
                action=decision.action,
                exit_code=code if code is not None else "spawn_error",
                new_height=new_h if new_h is not None else "unknown",
                verified=(code == 0),
            )

            # Escalate a failed restart to peer-pull (gated). process-dead forces
            # past the destructive cool-down because the node is fully down.
            if decision.action == "restart" and code is not None and code != 0:
                esc = decide_escalation_after_restart(
                    exit_code=code,
                    autorecover=destructive_recovery_ready,
                    pull_cooldown_remaining_s=cooldown_remaining_s(LOCK, COOLDOWN_SECONDS),
                    force=(trigger == TRIGGER_PROCESS_DEAD and not upgrade_halt),
                    destructive_disabled_reason=destructive_disabled_reason,
                    upgrade_halt=upgrade_halt,
                    halt_kind=halt_kind,
                )
                emit("DISPATCH", action=esc.action, reason=esc.reason, argv=json.dumps(esc.argv) if esc.argv else "[]")
                for tag, kv in esc.emits:
                    emit(tag, **kv)
                if esc.action == "peer-pull" and not dry_run:
                    code2 = _invoke(esc.argv, reason=esc.reason)
                    stats["dispatches"]["peer-pull"] += 1
                    post2 = get_status(LOCAL_RPC)
                    nh2 = None
                    if post2:
                        try:
                            nh2 = int(post2["sync_info"]["latest_block_height"])
                        except (KeyError, ValueError):
                            nh2 = None
                    emit(
                        "POSTCHECK",
                        action="peer-pull",
                        exit_code=code2 if code2 is not None else "spawn_error",
                        new_height=nh2 if nh2 is not None else "unknown",
                        verified=(code2 == 0),
                    )
                elif esc.action == "alert":
                    _alert_once("restart_failed", esc.reason)

            # After acting, reset detection and back off a few cycles so the
            # node has time to come back before we re-evaluate.
            height_history.clear()
            time.sleep(POLL_SECONDS * 5)

        except KeyboardInterrupt:
            emit(
                "SHUTDOWN",
                reason="SIGINT",
                uptime_s=int(time.time() - start_ts),
                polls=stats["polls"],
                triggers=json.dumps(stats["triggers"]),
                dispatches=json.dumps(stats["dispatches"]),
            )
            return 0
        except Exception as e:  # noqa: BLE001 — defensive top-level guard
            emit("CRASH", type=type(e).__name__, msg=str(e), traceback=traceback.format_exc().replace("\n", " | "))
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
