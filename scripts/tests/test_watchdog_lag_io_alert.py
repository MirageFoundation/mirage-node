"""Unit tests for the trailing-peers (LAG) and disk-latency (IO) warnings.

Both exist because of the 2026-08-06 mirage.talk incident, where the droplet's
volume degraded (33 -> 13 IOPS while average service time went 12ms -> 281ms) and
the node fell ~21 blocks behind the network for five minutes. Nothing alerted:
the stall trigger needs a FROZEN height and this node kept committing blocks, and
CometBFT reported catching_up=false throughout. Meanwhile every relayed write was
rejected by the ante handler for a stale block time, so users saw failed posts.

The properties that matter:

  - both are ALERT-ONLY. A node that is merely slow re-converges by itself, and
    every recovery action the watchdog owns writes MORE to the disk that is
    already the bottleneck. Recovery stays reserved for a frozen height.
  - both dedupe on their OWN marker. Reusing ALERT_LOCK would let a warning
    suppress a genuine divergence alert, and touching LOCK would lock operators
    out of recovery — the 2026-06-12 shared-lock lesson.
  - the lag warning stands down once the stall trigger owns the incident, so one
    event never produces two competing alert streams.
  - the thresholds stay quiet on a healthy node. A noisy alert is a disabled one.

Run from the repo root:

    python -m pytest scripts/tests/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import divergence_watchdog as wd  # noqa: E402

# The incident minute, as measured: 13 IOPS for 60s at 281ms each, device busy 48s.
INCIDENT = (780, 780 * 281, 48000)
# A normal minute on the same host: 33 IOPS at 3ms, device busy 2.5% of the time.
HEALTHY = (1980, 1980 * 3, 1500)


def _arm(monkeypatch, tmp_path, repeat_s=1800):
    """Point every marker at tmp_path and capture outbound notifications."""
    sent = []
    monkeypatch.setattr(wd, "LAG_ALERT_REPEAT_SECONDS", repeat_s)
    monkeypatch.setattr(wd, "IO_ALERT_REPEAT_SECONDS", repeat_s)
    monkeypatch.setattr(wd, "LAG_ALERT_LOCK", tmp_path / ".lag_alert_lock")
    monkeypatch.setattr(wd, "IO_ALERT_LOCK", tmp_path / ".io_alert_lock")
    monkeypatch.setattr(wd, "DISK_ALERT_LOCK", tmp_path / ".disk_alert_lock")
    monkeypatch.setattr(wd, "ALERT_LOCK", tmp_path / ".divergence_alert_lock")
    monkeypatch.setattr(wd, "LOCK", tmp_path / ".divergence_recovery_lock")
    monkeypatch.setattr(wd, "RESTART_LOCK", tmp_path / ".restart_recovery_lock")
    monkeypatch.setattr(wd, "notify_external", lambda title, text: sent.append((title, text)))
    return sent


# ── disk sampling math ──────────────────────────────────────────────────
def test_disk_pressure_reproduces_the_incident():
    assert wd.disk_pressure((0, 0, 0), INCIDENT, 60.0) == (281, 80)


def test_disk_pressure_on_a_normal_minute():
    assert wd.disk_pressure((0, 0, 0), HEALTHY, 60.0) == (3, 2)


def test_default_threshold_separates_the_two():
    """The whole point: quiet at 3ms, loud at 281ms, with room on both sides."""
    healthy_await = wd.disk_pressure((0, 0, 0), HEALTHY, 60.0)[0]
    incident_await = wd.disk_pressure((0, 0, 0), INCIDENT, 60.0)[0]
    assert healthy_await < wd.IO_AWAIT_ALERT_MS < incident_await


def test_disk_pressure_needs_two_samples():
    assert wd.disk_pressure(None, HEALTHY, 60.0) is None
    assert wd.disk_pressure(HEALTHY, None, 60.0) is None
    assert wd.disk_pressure((0, 0, 0), HEALTHY, 0.0) is None


def test_idle_interval_is_not_a_latency_reading():
    """An average over zero completed requests would divide by zero, and an idle
    disk must never be reported as fast OR slow."""
    assert wd.disk_pressure((5, 5, 5), (5, 9, 9), 60.0) is None


def test_counter_reset_is_discarded():
    """/proc/diskstats counters restart at boot; a negative delta is not a reading."""
    assert wd.disk_pressure((99, 99, 99), (1, 1, 1), 60.0) is None


def test_only_whole_disks_are_counted():
    """Summing a partition with its parent would double-count every request."""
    assert wd._WHOLE_DISK_RE.match("vda")
    assert wd._WHOLE_DISK_RE.match("nvme0n1")
    assert not wd._WHOLE_DISK_RE.match("vda1")
    assert not wd._WHOLE_DISK_RE.match("nvme0n1p1")
    assert not wd._WHOLE_DISK_RE.match("loop0")
    assert not wd._WHOLE_DISK_RE.match("dm-0")


def test_read_disk_counters_returns_monotonic_totals():
    first = wd.read_disk_counters()
    assert first is not None and len(first) == 3
    second = wd.read_disk_counters()
    assert all(b >= a for a, b in zip(first, second))


# ── when the lag warning is due ─────────────────────────────────────────
def test_single_poll_behind_is_not_enough():
    """One poll can straddle a block; the local read and the peer probe are
    seconds apart, so a small gap is normal."""
    assert not wd.lag_warning_due(1, stall_n=1)
    assert not wd.lag_warning_due(wd.LAG_ALERT_POLLS - 1, stall_n=1)


def test_sustained_lag_while_advancing_warns():
    assert wd.lag_warning_due(wd.LAG_ALERT_POLLS, stall_n=1)
    assert wd.lag_warning_due(wd.LAG_ALERT_POLLS + 10, stall_n=3)


def test_stands_down_once_the_stall_trigger_owns_it():
    """A frozen height is a stall: that path dispatches recovery and alerts on its
    own, and two alert streams for one event is how operators learn to ignore
    alerts."""
    assert not wd.lag_warning_due(20, stall_n=wd.STALL_BLOCKS)
    assert not wd.lag_warning_due(20, stall_n=wd.STALL_BLOCKS + 5)


# ── the LAG warning itself ──────────────────────────────────────────────
def test_lag_warns_and_notifies(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path)
    wd._lag_alert_once(local_h=6629858, peer_max=6629879, lag=21, polls=3)
    assert len(sent) == 1
    title, text = sent[0]
    assert "peers" in title.lower()
    assert "21 blocks behind" in text
    assert "no recovery dispatched" in text, "must say it did NOT act"
    assert wd.LAG_ALERT_LOCK.exists(), "must record its own dedup marker"


def test_lag_repeat_is_suppressed_within_window(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path)
    for _ in range(5):
        wd._lag_alert_once(1, 2, 21, 3)
    assert len(sent) == 1, "a five-minute lag must not page every poll"


def test_lag_re_alerts_once_window_elapses(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path, repeat_s=0)
    wd._lag_alert_once(1, 2, 21, 3)
    wd._lag_alert_once(1, 2, 21, 4)
    assert len(sent) == 2


def test_lag_never_touches_another_paths_lock(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path)
    wd._lag_alert_once(1, 2, 99, 9)
    assert wd.LAG_ALERT_LOCK.exists()
    assert not wd.LOCK.exists(), "must not put destructive recovery on cool-down"
    assert not wd.ALERT_LOCK.exists(), "must not suppress divergence alerts"
    assert not wd.RESTART_LOCK.exists(), "must not put restart recovery on cool-down"
    assert not wd.DISK_ALERT_LOCK.exists()


def test_lag_never_dispatches_recovery(monkeypatch, tmp_path):
    """Restarting a node that is merely slow replays the WAL on the disk that is
    already the bottleneck — a five-minute lag becomes a real outage."""
    _arm(monkeypatch, tmp_path)
    invoked = []
    monkeypatch.setattr(wd, "_invoke", lambda *a, **k: invoked.append(a))
    wd._lag_alert_once(1, 2, 500, 60)
    assert invoked == []


# ── the IO warning itself ───────────────────────────────────────────────
def test_io_warns_and_notifies(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path)
    wd._io_alert_once(await_ms=281, busy_pct=80, polls=2)
    assert len(sent) == 1
    title, text = sent[0]
    assert "disk" in title.lower()
    assert "281ms" in text
    assert wd.IO_ALERT_LOCK.exists(), "must record its own dedup marker"


def test_io_repeat_is_suppressed_within_window(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path)
    for await_ms in (150, 200, 281, 400):
        wd._io_alert_once(await_ms, 80, 2)
    assert len(sent) == 1


def test_io_never_touches_another_paths_lock(monkeypatch, tmp_path):
    _arm(monkeypatch, tmp_path)
    wd._io_alert_once(281, 80, 2)
    assert wd.IO_ALERT_LOCK.exists()
    assert not wd.LOCK.exists()
    assert not wd.ALERT_LOCK.exists()
    assert not wd.RESTART_LOCK.exists()
    assert not wd.LAG_ALERT_LOCK.exists()


def test_io_never_dispatches_recovery(monkeypatch, tmp_path):
    """Nothing the watchdog can do to a managed volume makes it faster."""
    _arm(monkeypatch, tmp_path)
    invoked = []
    monkeypatch.setattr(wd, "_invoke", lambda *a, **k: invoked.append(a))
    wd._io_alert_once(2000, 100, 30)
    assert invoked == []
