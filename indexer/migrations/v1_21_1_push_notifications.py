"""
Create push_tokens, push_budget, and push_receipts tables for Expo push notifications.

push_tokens: stores Expo push tokens per user (multiple devices allowed).
push_budget: per-user notification budget (max 3, resets on mark_inbox_viewed).
push_receipts: Expo ticket IDs for opportunistic receipt checking.
"""

MIGRATION_KEY = "v1.21.1_push_notifications"


def run(db, chain, logger):
    return "skipped: table moved to backend DB"
