"""
Create push_nonces table for replay protection on push endpoints.
"""

MIGRATION_KEY = "v1.21.1_push_nonce_guard"


def run(db, chain, logger):
    return "skipped: table moved to backend DB"
