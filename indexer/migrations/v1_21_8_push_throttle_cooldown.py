"""
Add cooldown_until column to push_throttle for summary cooldown.
"""

MIGRATION_KEY = "v1.21.8_push_throttle_cooldown"


def run(db, chain, logger):
    return "skipped: table moved to backend DB"
