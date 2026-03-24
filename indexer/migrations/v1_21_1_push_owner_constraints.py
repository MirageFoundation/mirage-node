"""
Add lowercase owner constraints to push tables.
"""

MIGRATION_KEY = "v1.21.1_push_owner_constraints"


def run(db, chain, logger):
    return "skipped: table moved to backend DB"
