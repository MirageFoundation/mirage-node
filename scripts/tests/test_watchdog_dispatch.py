"""Unit tests for the pure dispatch core of divergence_watchdog.py.

These target decide_action() and decide_escalation_after_restart(), which are
deliberately pure: every side-effecting input (cool-down remainders, recent
restart count, the autorecover gate) is passed in, so no filesystem or clock
mocking is needed. Run from the repo root:

    python -m pytest scripts/tests/

The scenarios encode the 2026-06-14 incident lessons:
  - a stall whose app_hash matches peers is a runtime hang -> restart (cheap,
    non-destructive), never a DB-wiping peer-pull;
  - a stall whose app_hash disagrees is real divergence -> peer-pull (gated);
  - repeated restarts within the window escalate to peer-pull;
  - cool-downs suppress action.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import divergence_watchdog as wd  # noqa: E402

SCRIPT = str(wd.RECOVERY_SCRIPT)
PULL = wd.RECOVERY_MODE  # "peer-pull"
HASH_A = "0994F6AAD7D8AF75D7107643DA1645708A754FB3B8704128A55CF7825466832E"
HASH_B = "DEADBEEFD7D8AF75D7107643DA1645708A754FB3B8704128A55CF7825466832E"


def _decide(**overrides):
    """decide_action with safe, inert defaults; override per test."""
    kwargs = dict(
        trigger=wd.TRIGGER_STALL,
        local_h=5_329_009,
        local_app_hash=HASH_A,
        peer_app_hashes={"192.0.2.2": HASH_A, "192.0.2.3": HASH_A},
        autorecover=True,
        restart_cooldown_remaining_s=0,
        pull_cooldown_remaining_s=0,
        recent_restart_count=0,
        dry_run=False,
    )
    kwargs.update(overrides)
    return wd.decide_action(**kwargs)


def test_stall_with_matching_app_hash_invokes_restart():
    d = _decide()
    assert d.action == "restart"
    assert d.argv == ["bash", SCRIPT, "restart", "--auto"]


def test_stall_with_mismatching_app_hash_routes_to_peer_pull_when_authorized():
    d = _decide(peer_app_hashes={"192.0.2.2": HASH_A, "192.0.2.3": HASH_B})
    assert d.action == "peer-pull"
    assert d.argv == ["bash", SCRIPT, PULL, "--auto"]


def test_stall_with_mismatching_app_hash_alerts_when_not_authorized():
    d = _decide(
        peer_app_hashes={"192.0.2.2": HASH_A, "192.0.2.3": HASH_B},
        autorecover=False,
    )
    assert d.action == "alert"
    assert d.argv == []
    assert any(tag == "ALERT" for tag, _ in d.emits)


def test_destructive_disabled_reason_is_reported():
    d = _decide(
        peer_app_hashes={"192.0.2.2": HASH_A, "192.0.2.3": HASH_B},
        autorecover=False,
        destructive_disabled_reason="RECOVERY_KEY missing at /root/.mirage/.ssh/recovery_id",
    )
    assert d.action == "alert"
    assert "RECOVERY_KEY missing" in d.reason
    assert d.emits[0][1]["disabled_reason"].startswith("RECOVERY_KEY missing")


def test_log_pattern_routes_to_peer_pull():
    d = _decide(trigger=wd.TRIGGER_LOG_PATTERN)
    assert d.action == "peer-pull"
    assert d.argv == ["bash", SCRIPT, PULL, "--auto"]


def test_process_dead_restarts_with_force():
    # process-dead must force past the restart cool-down (node is fully down).
    d = _decide(
        trigger=wd.TRIGGER_PROCESS_DEAD, restart_cooldown_remaining_s=600, local_app_hash=None, peer_app_hashes={}
    )
    assert d.action == "restart"
    assert d.argv == ["bash", SCRIPT, "restart", "--auto", "--force"]


def test_recurrence_threshold_escalates_directly_to_peer_pull():
    d = _decide(recent_restart_count=wd.RESTART_ESCALATE_AFTER)
    assert d.action == "peer-pull"
    assert d.argv == ["bash", SCRIPT, PULL, "--auto"]
    assert any(tag == "ESCALATE" for tag, _ in d.emits)


def test_restart_cooldown_suppresses_action():
    d = _decide(restart_cooldown_remaining_s=600)
    assert d.action == "noop"
    assert d.argv == []
    assert any(tag == "COOLDOWN" for tag, _ in d.emits)


def test_dry_run_stall_match_is_noop_but_reports_restart_argv():
    d = _decide(dry_run=True)
    assert d.action == "noop"
    # argv still computed so the DISPATCH line shows what WOULD run.
    assert d.argv == ["bash", SCRIPT, "restart", "--auto"]


def test_restart_exit_5_escalates_to_peer_pull_when_authorized():
    d = wd.decide_escalation_after_restart(
        exit_code=5,
        autorecover=True,
        pull_cooldown_remaining_s=0,
    )
    assert d.action == "peer-pull"
    assert d.argv == ["bash", SCRIPT, PULL, "--auto"]
    assert any(tag == "ESCALATE" for tag, _ in d.emits)


def test_restart_exit_5_no_escalation_when_alert_only():
    d = wd.decide_escalation_after_restart(
        exit_code=5,
        autorecover=False,
        pull_cooldown_remaining_s=0,
    )
    assert d.action == "alert"
    assert d.argv == []
    assert any(tag == "ALERT" for tag, _ in d.emits)


def test_restart_exit_5_reports_destructive_disabled_reason():
    d = wd.decide_escalation_after_restart(
        exit_code=5,
        autorecover=False,
        pull_cooldown_remaining_s=0,
        destructive_disabled_reason="RECOVERY_KEY missing at /root/.mirage/.ssh/recovery_id",
    )
    assert d.action == "alert"
    assert "RECOVERY_KEY missing" in d.reason
    assert d.emits[0][1]["disabled_reason"].startswith("RECOVERY_KEY missing")


def test_restart_exit_5_pull_cooldown_suppresses_escalation():
    d = wd.decide_escalation_after_restart(
        exit_code=5,
        autorecover=True,
        pull_cooldown_remaining_s=3600,
    )
    assert d.action == "noop"
    assert any(tag == "COOLDOWN" for tag, _ in d.emits)


def test_restart_exit_0_is_noop():
    d = wd.decide_escalation_after_restart(
        exit_code=0,
        autorecover=True,
        pull_cooldown_remaining_s=0,
    )
    assert d.action == "noop"
    assert d.argv == []


def test_apphash_line_is_detected_as_divergence():
    # The real 2026-06-16 mirage.talk divergence line must match. Use a current
    # CometBFT-style 12h timestamp so the line falls inside the detection window
    # regardless of when the test runs.
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%I:%M%p").lstrip("0")
    text = (
        f"{ts} ERR Error in validation "
        'err="wrong Block.Header.AppHash.  Expected C6ABD68C, got 21C470FF" module=blocksync'
    )
    assert wd.log_window_has_pattern(text, wd.DIVERGENCE_PATTERNS, 300) == "wrong Block.Header.AppHash"


# ── catching_up divergence detection (2026-06-16 mirage.talk blind spot) ──
def _catchup(**overrides):
    kwargs = dict(
        last_advance_age_s=wd.CATCHUP_STALL_SECONDS,
        div_hit="wrong Block.Header.AppHash",
        healthy_peers=3,
        peer_max_height=5_378_200,
        local_h=5_378_001,
    )
    kwargs.update(overrides)
    return wd.is_catchup_divergence(**kwargs)


def test_catchup_stuck_with_apphash_and_peers_ahead_is_divergence():
    # Exactly the 2026-06-16 incident: frozen height + AppHash error + peers ahead.
    assert _catchup() is True


def test_catchup_advancing_node_is_not_divergence():
    # A genuine block-sync advances, so last_advance_age stays small.
    assert _catchup(last_advance_age_s=5) is False


def test_catchup_no_log_pattern_is_not_divergence():
    # Frozen + peers ahead but no AppHash/consensus-failure line => don't wipe DBs.
    assert _catchup(div_hit=None) is False


def test_catchup_needs_two_healthy_peers():
    assert _catchup(healthy_peers=1) is False


def test_catchup_requires_peers_strictly_ahead():
    assert _catchup(peer_max_height=5_378_001) is False


def test_catchup_divergence_routes_to_peer_pull():
    # When detected, the loop fires TRIGGER_LOG_PATTERN, which must peer-pull.
    d = _decide(trigger=wd.TRIGGER_LOG_PATTERN, local_app_hash=None, peer_app_hashes={})
    assert d.action == "peer-pull"
    assert d.argv == ["bash", SCRIPT, PULL, "--auto"]


def test_upgrade_halt_with_escaped_quotes_is_not_divergence():
    text = 'ERR CONSENSUS FAILURE!!! err="failed; error UPGRADE \\"v1.27.0\\" NEEDED at height: 5: "'
    assert wd.log_window_has_pattern(text, wd.DIVERGENCE_PATTERNS, 300) is None


def test_upgrade_halt_with_plain_quotes_is_not_divergence():
    text = 'ERR CONSENSUS FAILURE!!! err="failed; error UPGRADE "v1.27.0" NEEDED at height: 5: "'
    assert wd.log_window_has_pattern(text, wd.DIVERGENCE_PATTERNS, 300) is None
