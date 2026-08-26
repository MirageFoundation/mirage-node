"""Curation lens resolver. Every content query must call resolve_visibility."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

MODE_LIVE_DEFAULT = 0
MODE_PINNED = 1
MODE_RAW = 2


def resolve_visibility(
    *,
    viewer: str | None,
    community: str | None,
    author: str | None,
    txhash: str | None,
    root_txhash: str | None,
    post_sequence: int | None,
    author_was_paid_at_creation: bool | None,
    deleted: bool,
    viewer_blocks_author: bool,
    viewer_blocks_post: bool,
    viewer_blocks_community: bool,
    viewer_follows_author: bool,
    stored_mode: int | None,
    stored_team_id: int | None,
    default_team_id: int | None,
    team_hidden_post: bool,
    team_hidden_author: bool,
    team_subscriber_only: bool,
    lock_sequence: int | None,
    temporary_raw: bool,
    node_blocked: bool,
) -> dict[str, Any]:
    """Return {visible, tombstone, reason, effective_mode, effective_team_id}."""
    if node_blocked:
        return _result(False, False, "node_policy", stored_mode, stored_team_id)
    if deleted:
        return _result(False, True, "deleted", stored_mode, stored_team_id)
    if viewer_blocks_community or viewer_blocks_post or viewer_blocks_author:
        return _result(False, False, "personal_block", stored_mode, stored_team_id)

    effective_mode, effective_team = _effective_lens(stored_mode, stored_team_id, default_team_id)
    if temporary_raw or effective_mode == MODE_RAW or not effective_team:
        return _result(True, False, "raw", MODE_RAW if temporary_raw else effective_mode, None)

    if team_hidden_post:
        return _result(False, True, "team_hidden_post", effective_mode, effective_team)
    if team_hidden_author and not viewer_follows_author:
        return _result(False, False, "team_hidden_author", effective_mode, effective_team)
    if team_subscriber_only and not author_was_paid_at_creation:
        return _result(False, False, "subscriber_only", effective_mode, effective_team)
    if lock_sequence is not None and post_sequence is not None and post_sequence > lock_sequence:
        return _result(False, False, "thread_locked", effective_mode, effective_team)
    return _result(True, False, "ok", effective_mode, effective_team)


def _effective_lens(stored_mode: int | None, stored_team_id: int | None, default_team_id: int | None):
    if stored_mode == MODE_RAW:
        return MODE_RAW, None
    if stored_mode == MODE_PINNED and stored_team_id:
        return MODE_PINNED, stored_team_id
    if default_team_id:
        return MODE_LIVE_DEFAULT, default_team_id
    return MODE_RAW, None


def _result(visible: bool, tombstone: bool, reason: str, mode, team_id) -> dict[str, Any]:
    return {
        "visible": visible,
        "tombstone": tombstone,
        "reason": reason,
        "effective_mode": mode,
        "effective_team_id": team_id,
    }
