"""Unit tests for the disk-pressure warning in divergence_watchdog.py.

The disk warning exists because the watchdog already samples disk every poll but
never acted on it, so a slow squeeze would only surface at 100%. Two properties
matter more than the threshold arithmetic:

  - it is ALERT-ONLY. It must never prune, delete or dispatch recovery. Automating
    deletion under disk pressure is dangerous here: bulk IAVL delete passes are the
    machinery behind the prune-hole crashes, and PebbleDB needs free headroom to
    compact, so deletes can spike usage before reclaiming.
  - it dedupes on its OWN marker. Reusing ALERT_LOCK would let a disk warning
    suppress a genuine divergence alert, and touching the destructive LOCK would
    lock operators out of recovery — the 2026-06-12 shared-lock lesson.

Run from the repo root:

    python -m pytest scripts/tests/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import divergence_watchdog as wd  # noqa: E402


def _arm(monkeypatch, tmp_path, threshold=80, repeat_s=21600):
    """Point every marker at tmp_path and capture outbound notifications."""
    sent = []
    monkeypatch.setattr(wd, "DISK_ALERT_PCT", threshold)
    monkeypatch.setattr(wd, "DISK_ALERT_REPEAT_SECONDS", repeat_s)
    monkeypatch.setattr(wd, "DISK_ALERT_LOCK", tmp_path / ".disk_alert_lock")
    monkeypatch.setattr(wd, "ALERT_LOCK", tmp_path / ".divergence_alert_lock")
    monkeypatch.setattr(wd, "LOCK", tmp_path / ".divergence_recovery_lock")
    monkeypatch.setattr(wd, "RESTART_LOCK", tmp_path / ".restart_recovery_lock")
    monkeypatch.setattr(wd, "notify_external", lambda title, text: sent.append((title, text)))
    return sent


def test_below_threshold_is_silent(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path)
    wd._disk_alert_once(79)
    assert sent == []
    assert not wd.DISK_ALERT_LOCK.exists()


def test_at_threshold_warns_and_notifies(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path)
    wd._disk_alert_once(80)
    assert len(sent) == 1
    title, text = sent[0]
    assert "disk" in title.lower()
    assert "80" in text
    assert wd.DISK_ALERT_LOCK.exists(), "must record its own dedup marker"


def test_repeat_is_suppressed_within_window(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path)
    wd._disk_alert_once(91)
    wd._disk_alert_once(92)
    wd._disk_alert_once(93)
    assert len(sent) == 1, "disk fills over days; must not page every poll"


def test_re_alerts_once_window_elapses(monkeypatch, tmp_path):
    sent = _arm(monkeypatch, tmp_path, repeat_s=0)
    wd._disk_alert_once(85)
    wd._disk_alert_once(85)
    assert len(sent) == 2


def test_never_touches_the_recovery_or_divergence_locks(monkeypatch, tmp_path):
    """The 2026-06-12 lesson: a warning path must not write another path's lock.

    Touching LOCK would put recovery on a 6h cool-down (locking operators out
    mid-incident); touching ALERT_LOCK would silence a real divergence alert.
    """
    _arm(monkeypatch, tmp_path)
    wd._disk_alert_once(99)
    assert wd.DISK_ALERT_LOCK.exists()
    assert not wd.LOCK.exists(), "must not put destructive recovery on cool-down"
    assert not wd.ALERT_LOCK.exists(), "must not suppress divergence alerts"
    assert not wd.RESTART_LOCK.exists(), "must not put restart recovery on cool-down"


def test_alert_only_never_dispatches_recovery(monkeypatch, tmp_path):
    """A full disk is a capacity decision, never grounds for automated action."""
    _arm(monkeypatch, tmp_path)
    invoked = []
    monkeypatch.setattr(wd, "_invoke", lambda *a, **k: invoked.append(a))
    wd._disk_alert_once(100)
    assert invoked == [], "disk pressure must never trigger recovery"
