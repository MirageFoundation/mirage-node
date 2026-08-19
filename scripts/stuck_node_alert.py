#!/usr/bin/env python3
"""
stuck_node_alert.py — minimal, INDEPENDENT liveness pager for a miraged node.

WHY THIS EXISTS (separate from divergence_watchdog.py)
------------------------------------------------------
The divergence watchdog only pages a human on a `catching_up=True` + frozen
node when it ALSO finds a divergence log pattern ("wrong Block.Header.AppHash",
"CONSENSUS FAILURE!!!"). The 2026-06-16 mirage.talk incident produced NO such
marker: the node sat `catching_up=True` with a frozen height for ~95 minutes,
emitting nothing the watchdog keys on, so nobody was paged until a human noticed
by chance. Worse, during a manual recovery the watchdog process is sometimes
deliberately frozen (`kill -STOP`) — a watchdog that is itself stopped can never
alert.

This script is the dead-man's-switch that closes both gaps. It is a tiny,
stdlib-only daemon that imports NOTHING from the watchdog (separate failure
domain) and runs as its own Supervisor program. Its single rule: a healthy validator
ALWAYS advances its height within seconds, so if the local height has not moved
for > STUCK_ALERT_SECONDS — or /status has been unreachable that long — page a
human. That is true regardless of `catching_up`, regardless of whether any
divergence pattern was logged, and regardless of whether the watchdog is alive.

It NEVER recovers anything (no restart, no peer-pull, no DB writes). It only
observes /status and POSTs to ALERT_WEBHOOK_URL. Recovery stays the watchdog's
job; this is pure detection/notification.

CONFIG (env)
------------
  LOCAL_RPC                 default http://127.0.0.1:26657
  ALERT_WEBHOOK_URL         provider-agnostic {"text": ...} webhook; unset = no-op
  ALERT_WEBHOOK_TIMEOUT     seconds, default 5
  NODE_LABEL / MONIKER      label in the alert (falls back to hostname)
  STUCK_ALERT_SECONDS       frozen/unreachable budget before paging, default 600
  STUCK_ALERT_POLL_SECONDS  poll cadence, default 60
  STUCK_ALERT_REPEAT_SECONDS  re-page cadence while still stuck, default 1800

FLAGS
-----
  --dry-run    log decisions but never POST (also via STUCK_ALERT_DRY_RUN=true)
  --selftest   validate config + send one test page, then exit
  --once       run a single poll and exit (no freeze timing; liveness ping only)
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

LOCAL_RPC = os.environ.get("LOCAL_RPC", "http://127.0.0.1:26657").rstrip("/")
ALERT_WEBHOOK_URL = os.environ.get("ALERT_WEBHOOK_URL", "").strip()
ALERT_WEBHOOK_TIMEOUT = float(os.environ.get("ALERT_WEBHOOK_TIMEOUT", "5"))
NODE_LABEL = os.environ.get("NODE_LABEL", "") or os.environ.get("MONIKER", "") or socket.gethostname()

STUCK_ALERT_SECONDS = int(os.environ.get("STUCK_ALERT_SECONDS", "600"))
POLL_SECONDS = int(os.environ.get("STUCK_ALERT_POLL_SECONDS", "60"))
REPEAT_SECONDS = int(os.environ.get("STUCK_ALERT_REPEAT_SECONDS", "1800"))

_running = True


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(tag: str, **kv) -> None:
    """One greppable line per event, mirroring the watchdog's [TAG] k=v style so
    both pagers reconstruct the same way from logs."""
    parts = " ".join(f"{k}={v}" for k, v in kv.items())
    print(f"{now()} [stuck-alert] [{tag}] {parts}", flush=True)


def get_status(timeout: float = 5.0):
    """Return the /status `result` dict, or None if unreachable/garbage. Mirrors
    divergence_watchdog.get_status (intentionally duplicated to stay independent)."""
    try:
        with urllib.request.urlopen(f"{LOCAL_RPC}/status", timeout=timeout) as r:
            return json.load(r)["result"]
    except (
        urllib.error.URLError,
        urllib.error.HTTPError,
        json.JSONDecodeError,
        TimeoutError,
        ConnectionError,
        OSError,
        KeyError,
    ):
        return None


def notify_external(title: str, text: str, dry_run: bool) -> None:
    """Best-effort page to ALERT_WEBHOOK_URL. Identical payload shape to the
    watchdog so alerts render the same. NEVER raises — a flaky webhook must not
    crash the only thing watching a silently-frozen node."""
    if not ALERT_WEBHOOK_URL:
        emit("ALERT", kind="webhook-skipped", reason="ALERT_WEBHOOK_URL unset", title=title)
        return
    if dry_run:
        emit("ALERT", kind="webhook-dry-run", title=title, text=text)
        return
    body = json.dumps({"text": f"[mirage:{NODE_LABEL}] {title}\n{text}"}).encode()
    req = urllib.request.Request(
        ALERT_WEBHOOK_URL, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=ALERT_WEBHOOK_TIMEOUT) as r:
            emit("ALERT", kind="webhook-sent", status=getattr(r, "status", 0), title=title)
    except Exception as e:  # noqa: BLE001 — notification must never break the pager
        emit("ALERT", kind="webhook-failed", err=repr(e), title=title)


def _install_signal_handlers() -> None:
    def _stop(signum, _frame):
        global _running
        _running = False
        emit("SHUTDOWN", signal=signum)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)


def poll_once(dry_run: bool) -> None:
    """Single liveness ping: log current height/catching_up, page if /status is
    down. Used by --once; cannot measure a freeze (no timing across polls)."""
    si = (get_status() or {}).get("sync_info")
    if not si:
        emit("POLL", reachable=False, note="/status unreachable")
        notify_external(
            "node UNREACHABLE (one-shot check)",
            f"/status at {LOCAL_RPC} did not respond",
            dry_run,
        )
        return
    emit(
        "POLL",
        reachable=True,
        height=si.get("latest_block_height"),
        catching_up=si.get("catching_up"),
    )


def run(dry_run: bool) -> int:
    _install_signal_handlers()
    emit(
        "STARTUP",
        rpc=LOCAL_RPC,
        label=NODE_LABEL,
        stuck_after_s=STUCK_ALERT_SECONDS,
        poll_s=POLL_SECONDS,
        repeat_s=REPEAT_SECONDS,
        webhook="set" if ALERT_WEBHOOK_URL else "unset",
        dry_run=dry_run,
    )
    if STUCK_ALERT_SECONDS <= POLL_SECONDS:
        emit("STARTUP", warn="STUCK_ALERT_SECONDS <= poll interval; alert may fire after one poll")

    last_height: int | None = None
    last_advance_ts = time.time()
    first_unreachable_ts: float | None = None
    last_page_ts: float | None = None  # set while in a paging (stuck) state
    alerting = False  # True once we have paged for the current stuck episode

    while _running:
        si = (get_status() or {}).get("sync_info")
        nowt = time.time()

        if not si:
            # RPC down. Treat sustained unreachability as a stuck condition too:
            # a crashed/hung node whose RPC never answers is exactly what must page.
            if first_unreachable_ts is None:
                first_unreachable_ts = nowt
            down_for = int(nowt - first_unreachable_ts)
            emit("POLL", reachable=False, down_for_s=down_for)
            if down_for >= STUCK_ALERT_SECONDS:
                if (last_page_ts is None) or (nowt - last_page_ts >= REPEAT_SECONDS):
                    notify_external(
                        "node UNREACHABLE — /status down",
                        f"{LOCAL_RPC}/status has been unreachable for {down_for}s "
                        f"(threshold {STUCK_ALERT_SECONDS}s). Node process may be dead/hung.",
                        dry_run,
                    )
                    last_page_ts = nowt
                    alerting = True
            _sleep(POLL_SECONDS)
            continue

        # Reachable again after an unreachable streak — clear that timer.
        first_unreachable_ts = None

        try:
            height = int(si["latest_block_height"])
        except (KeyError, ValueError, TypeError):
            emit("POLL", reachable=True, note="missing/garbage latest_block_height")
            _sleep(POLL_SECONDS)
            continue
        catching_up = bool(si.get("catching_up", False))

        if last_height is None or height != last_height:
            # Progress. If we were paging, announce recovery exactly once.
            if alerting:
                notify_external(
                    "node RECOVERED — height advancing again",
                    f"height now {height} (catching_up={catching_up}).",
                    dry_run,
                )
                alerting = False
                last_page_ts = None
            last_height = height
            last_advance_ts = nowt

        frozen_for = int(nowt - last_advance_ts)
        emit(
            "POLL",
            reachable=True,
            height=height,
            catching_up=catching_up,
            frozen_for_s=frozen_for,
            stuck_after_s=STUCK_ALERT_SECONDS,
        )

        if frozen_for >= STUCK_ALERT_SECONDS:
            if (last_page_ts is None) or (nowt - last_page_ts >= REPEAT_SECONDS):
                notify_external(
                    "node STUCK — height frozen",
                    f"height {height} has not advanced for {frozen_for}s "
                    f"(threshold {STUCK_ALERT_SECONDS}s, catching_up={catching_up}). "
                    f"No automatic divergence marker required — paging anyway.",
                    dry_run,
                )
                last_page_ts = nowt
                alerting = True

        _sleep(POLL_SECONDS)

    emit("SHUTDOWN", note="loop exited cleanly")
    return 0


def _sleep(seconds: int) -> None:
    """Sleep in 1s slices so SIGTERM/SIGINT stops the daemon promptly."""
    end = time.time() + seconds
    while _running and time.time() < end:
        time.sleep(min(1.0, end - time.time()))


def main() -> int:
    ap = argparse.ArgumentParser(description="Independent liveness pager for a miraged node.")
    ap.add_argument("--dry-run", action="store_true", help="log decisions; never POST the webhook")
    ap.add_argument("--selftest", action="store_true", help="validate config, send one test page, exit")
    ap.add_argument("--once", action="store_true", help="single poll then exit (liveness ping only)")
    args = ap.parse_args()

    dry_run = args.dry_run or os.environ.get("STUCK_ALERT_DRY_RUN", "").lower() in {"1", "true", "yes"}

    if args.selftest:
        emit(
            "SELFTEST",
            rpc=LOCAL_RPC,
            label=NODE_LABEL,
            webhook="set" if ALERT_WEBHOOK_URL else "unset",
            stuck_after_s=STUCK_ALERT_SECONDS,
            dry_run=dry_run,
        )
        notify_external("stuck-node alert SELFTEST", "configuration OK; this is a test page", dry_run)
        return 0

    if args.once:
        poll_once(dry_run)
        return 0

    return run(dry_run)


if __name__ == "__main__":
    sys.exit(main())
