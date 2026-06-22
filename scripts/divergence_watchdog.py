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

Designed to run inside the mirage container, in its own tmux window, started
by deploy/entrypoint.sh.

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
Every poll writes dense, tagged, greppable lines to BOTH stdout (for the tmux
pane) AND a durable daily file /root/.mirage/logs/watchdog/watchdog-YYYY-MM-DD.log
(90-day retention), so any incident is reconstructable months later. Tags:
STARTUP, POLL, PEER, GATE, TRIGGER, PRECHECK, DISPATCH, INVOKE, POSTCHECK,
COOLDOWN, ESCALATE, ALERT, CRASH, SHUTDOWN. One-liner to reconstruct every
interesting event:
  grep -E '\\[(TRIGGER|DISPATCH|INVOKE|POSTCHECK|ESCALATE|ALERT|CRASH)\\]' \\
    /root/.mirage/logs/watchdog/watchdog-*.log
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
)

# A "CONSENSUS FAILURE!!!" line that is actually the cosmos-sdk upgrade halt
# looks like:
#   ERR CONSENSUS FAILURE!!! err="failed to apply block; error UPGRADE \"v1.26.0\" NEEDED at height: 4895581: " module=consensus
# (the upgrade module returns the error verbatim from
# x/upgrade.Keeper.PreBlocker when it has no handler registered for plan.Name).
# This is operator-fixable (swap binaries), NEVER recoverable by wiping the
# chain DBs. Treat it as non-divergence.
UPGRADE_HALT_RE = re.compile(r'UPGRADE\s+\\?"[^"\\]+\\?"\s+NEEDED\s+at\s+height:')


# ── Logging ─────────────────────────────────────────────────────────────
def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def current_log_file() -> Path:
    """Today's UTC daily forensic log file. Recomputed on every write so the
    daily roll happens automatically when the date flips — no cronolog, no
    external rotation."""
    return WATCHDOG_LOG_DIR / f"watchdog-{datetime.now(timezone.utc):%Y-%m-%d}.log"


def _write_line(line: str) -> None:
    """Dual-write: stdout (tmux pane / human eyeballing) AND the durable daily
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
) -> Decision:
    """Map a fired trigger to a concrete action. PURE: every piece of
    side-effecting state (cool-down remainders, recent restart count, gate) is
    passed in, so tests need no filesystem or clock mocking.

    Ladder:
      log_pattern        -> peer-pull (gated)
      stall + ah match   -> restart (ungated), unless recurrence threshold hit
      stall + ah mismatch-> peer-pull (gated)
      process_dead       -> restart (ungated, force past restart cool-down)
    """
    if trigger is None:
        return Decision("noop", [], "no trigger")

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
) -> Decision:
    """Called when a `restart` action returned non-zero (5 = chain did not
    advance; other = error). PURE. Decides whether to escalate to peer-pull."""
    if exit_code == 0:
        return Decision("noop", [], "restart succeeded")
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
    progress streams live to the tmux pane. The full step-by-step trail lives
    in recover.sh's own daily log (child_log), cross-referenced here by pid."""
    child_log = f"{LOGS_DIR}/deploy/divergence_recovery-{datetime.now(timezone.utc):%Y-%m-%d}.log"
    env = os.environ.copy()
    if reason:
        # recover.sh stamps RECOVERY_REASON into the pre-wipe forensic snapshot
        # manifest, so a captured diverged DB is always traceable back to the
        # watchdog trigger that decided to wipe it.
        env["RECOVERY_REASON"] = f"watchdog:{reason}"
    try:
        # stdin from /dev/null: the watchdog runs in a tmux pane, so an inherited
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


def _loud_alert(trigger: str, reason: str) -> None:
    """Human-friendly multi-line alert block, deduped by the caller. The
    structured [ALERT] line is emitted separately every poll for the grep
    trail; this block is the eyeball-grabbing version."""
    log("============================================================")
    log("ALERT: watchdog recovery needed (see [TRIGGER]/[DISPATCH]/[ALERT] lines).")
    log(f"  trigger: {trigger}  reason: {reason}")
    log("  Investigate: tmux attach -t mirage   (windows 'node', 'watchdog')")
    log(f"  Dry-run:     docker exec -it mirage bash {RECOVERY_SCRIPT} {RECOVERY_MODE} --dry-run")
    log(f"  Recover:     docker exec -it mirage bash {RECOVERY_SCRIPT} {RECOVERY_MODE} --auto")
    log("  Runbook:     docs/troubleshooting/divergence-recovery.md")
    log("============================================================")


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
                    )

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
                    force=(trigger == TRIGGER_PROCESS_DEAD),
                    destructive_disabled_reason=destructive_disabled_reason,
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
