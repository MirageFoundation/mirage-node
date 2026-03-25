"""
Replace push_budget (3-send budget reset on mark_inbox_viewed) with push_throttle
(5-per-30-minute sliding window with suppressed-event tracking for summary pushes).
"""

MIGRATION_KEY = "v1.21.8_push_throttle"


def run(db, chain, logger):
    return "skipped: table moved to backend DB"
