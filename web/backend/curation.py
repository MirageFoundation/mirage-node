"""Indexer-backed curation lens resolution and content filtering."""

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
    was_subscriber_at_creation: bool | None,
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
        return _result(False, True, "team_hidden_author", effective_mode, effective_team)
    if team_subscriber_only and not was_subscriber_at_creation:
        return _result(False, True, "subscriber_only", effective_mode, effective_team)
    if lock_sequence is not None and post_sequence is not None and post_sequence > lock_sequence:
        return _result(False, True, "thread_locked", effective_mode, effective_team)
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


def get_default_team(cur, community: str) -> dict[str, Any] | None:
    """Return this node's live default: paid subscribers, then oldest team."""
    cur.execute(
        """
        SELECT team_id, owner, name, description, subscriber_only,
               subscriber_count, created_height, created_order, tag
        FROM curation_teams
        WHERE community=%s AND deleted_height IS NULL
        ORDER BY subscriber_count DESC, created_order ASC, team_id ASC
        LIMIT 1
        """,
        (community,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "team_id": int(row[0]),
        "owner": row[1],
        "name": row[2],
        "description": row[3],
        "subscriber_only": bool(row[4]),
        "subscriber_count": int(row[5]),
        "created_height": int(row[6]),
        "created_order": int(row[7]),
        "tag": str(row[8] or ""),
    }


def resolve_lens(
    cur,
    *,
    viewer: str | None,
    community: str,
    requested_lens: str = "effective",
    requested_team_id: int | None = None,
) -> dict[str, Any]:
    """Resolve effective/default/team/raw against live indexer state."""
    lens = str(requested_lens or "effective").strip().lower()
    if lens not in ("effective", "default", "team", "raw"):
        raise ValueError("invalid lens")
    if lens == "team" and (requested_team_id is None or int(requested_team_id) <= 0):
        raise ValueError("team lens requires team_id")
    if lens != "team" and requested_team_id is not None:
        raise ValueError("team_id is only valid with team lens")

    default_team = get_default_team(cur, community)
    if lens == "raw":
        result = {"requested_lens": lens, "effective_mode": MODE_RAW, "effective_team_id": None}
    elif lens == "team":
        cur.execute(
            """
            SELECT 1 FROM curation_teams
            WHERE community=%s AND team_id=%s AND deleted_height IS NULL
            """,
            (community, int(requested_team_id)),
        )
        if not cur.fetchone():
            raise LookupError("curation team not found")
        result = {
            "requested_lens": lens,
            "effective_mode": MODE_PINNED,
            "effective_team_id": int(requested_team_id),
        }
    elif lens == "default":
        result = {
            "requested_lens": lens,
            "effective_mode": MODE_LIVE_DEFAULT if default_team else MODE_RAW,
            "effective_team_id": default_team["team_id"] if default_team else None,
        }
    else:
        stored_mode = None
        stored_team_id = None
        address = str(viewer or "").strip().lower()
        if address and address != "guest":
            cur.execute(
                """
                SELECT mode, pinned_team_id
                FROM community_curation_preferences
                WHERE LOWER(owner)=%s AND community=%s
                """,
                (address, community),
            )
            pref = cur.fetchone()
            if pref:
                stored_mode = int(pref[0])
                stored_team_id = int(pref[1]) if pref[1] is not None else None
        if stored_mode == MODE_RAW:
            effective_mode, effective_team_id = MODE_RAW, None
        elif stored_mode == MODE_PINNED and stored_team_id is not None:
            cur.execute(
                """
                SELECT 1 FROM curation_teams
                WHERE community=%s AND team_id=%s AND deleted_height IS NULL
                """,
                (community, stored_team_id),
            )
            if cur.fetchone():
                effective_mode, effective_team_id = MODE_PINNED, stored_team_id
            elif default_team:
                effective_mode, effective_team_id = MODE_LIVE_DEFAULT, default_team["team_id"]
            else:
                effective_mode, effective_team_id = MODE_RAW, None
        elif default_team:
            effective_mode, effective_team_id = MODE_LIVE_DEFAULT, default_team["team_id"]
        else:
            effective_mode, effective_team_id = MODE_RAW, None
        result = {
            "requested_lens": lens,
            "effective_mode": effective_mode,
            "effective_team_id": effective_team_id,
            "stored_mode": stored_mode,
            "stored_team_id": stored_team_id,
        }
    result["default_team"] = default_team
    log.debug(
        "[lens] resolve viewer=%s community=%s requested=%s effective_mode=%s team_id=%s",
        str(viewer or "")[:12],
        community,
        lens,
        result["effective_mode"],
        result["effective_team_id"],
    )
    return result


def resolve_effective_tags(
    cur,
    posts: list[dict],
    *,
    viewer: str | None = None,
    requested_lens: str = "effective",
    requested_team_id: int | None = None,
) -> None:
    """Rewrite each post's ``tag`` to the one this viewer's lens actually shows.

    Precedence is the lens team's per-post override, then the community's
    blanket tag, then the author's own tag. The community tag is deliberately
    not lens-scoped: it is a property of the community rather than of any one
    curator's view, so it is read from the default team and applies on the raw
    lens too. A per-post override of ``""`` is a curator asserting the post
    carries no tag, which is why an existing row wins even when it is empty.

    Each post needs a ``topic`` (community slug) and a ``post_id``. When
    filter_posts has already stamped ``post["lens"]`` that team is reused;
    otherwise the lens is resolved here. Always run this before any
    allowed-tags filtering, which must see the effective value.
    """
    if not posts:
        return
    address = str(viewer or "").strip().lower()
    default_teams: dict[str, dict[str, Any] | None] = {}
    lens_teams: dict[str, int | None] = {}
    for post in posts:
        community = str(post.get("topic") or "").strip().lower()
        post_id = str(post.get("post_id") or "").strip().lower()
        if not community or not post_id:
            continue
        if community not in default_teams:
            default_teams[community] = get_default_team(cur, community)
        default_team = default_teams[community]

        stamped = (post.get("lens") or {}).get("effective_team_id")
        if stamped is not None:
            team_id = int(stamped)
        else:
            if community not in lens_teams:
                lens_teams[community] = resolve_lens(
                    cur,
                    viewer=address,
                    community=community,
                    requested_lens=requested_lens,
                    requested_team_id=requested_team_id,
                )["effective_team_id"]
            team_id = lens_teams[community]
        # The raw lens has no team of its own, so per-post overrides fall back
        # to the default team's, which is where the community tag comes from.
        if team_id is None:
            if not default_team:
                continue
            team_id = default_team["team_id"]

        cur.execute(
            """
            SELECT tag FROM curation_post_tags
            WHERE community=%s AND team_id=%s AND LOWER(target_txhash)=%s
            """,
            (community, int(team_id), post_id),
        )
        row = cur.fetchone()
        community_tag = default_team["tag"] if default_team else ""
        if row is not None:
            effective = str(row[0] or "")
        elif community_tag:
            effective = community_tag
        else:
            continue
        if effective != post.get("tag", ""):
            log.debug(
                "[tag] override post=%s community=%s team=%s author_tag=%s effective=%s",
                post_id[:12],
                community,
                team_id,
                post.get("tag", ""),
                effective,
            )
        post["tag"] = effective


def filter_posts(
    cur,
    posts: list[dict],
    *,
    viewer: str | None,
    requested_lens: str,
    requested_team_id: int | None,
    scope: str,
    direct: bool = False,
) -> tuple[list[dict], list[dict]]:
    """Apply protocol scope and curator-team rules to serialized posts."""
    if scope not in ("current", "legacy"):
        raise ValueError("scope must be current or legacy")
    if not posts:
        return [], []
    ids = [str(post.get("post_id") or "").strip().lower() for post in posts]
    if any(len(post_id) != 64 for post_id in ids):
        raise RuntimeError("post response is missing a valid post_id")
    cur.execute(
        """
        SELECT LOWER(p.txhash), LOWER(p.owner), LOWER(COALESCE(p.community,'')),
               p.protocol_version, LOWER(COALESCE(p.root_txhash,p.root_post_id,p.txhash)),
               p.post_sequence, p.was_subscriber_at_creation
        FROM posts p
        WHERE LOWER(p.txhash)=ANY(%s)
        """,
        (ids,),
    )
    metadata = {
        row[0]: {
            "author": row[1],
            "community": row[2],
            "protocol_version": int(row[3]),
            "root_txhash": row[4],
            "post_sequence": int(row[5]) if row[5] is not None else None,
            "was_subscriber_at_creation": row[6],
        }
        for row in cur.fetchall()
    }
    if set(metadata) != set(ids):
        raise RuntimeError("post metadata query did not return every serialized post")

    wanted_protocol = 1 if scope == "current" else 0
    lenses: dict[str, dict[str, Any]] = {}
    visible: list[dict] = []
    tombstones: list[dict] = []
    address = str(viewer or "").strip().lower()
    for post, post_id in zip(posts, ids):
        meta = metadata[post_id]
        if meta["protocol_version"] != wanted_protocol:
            continue
        if scope == "legacy":
            visible.append(post)
            continue
        if meta["post_sequence"] is None or meta["was_subscriber_at_creation"] is None:
            raise RuntimeError(f"protocol-1 post is missing required curation metadata: {post_id}")
        community = meta["community"]
        if not community:
            raise RuntimeError(f"protocol-1 post is missing community: {post_id}")
        if community not in lenses:
            lenses[community] = resolve_lens(
                cur,
                viewer=address,
                community=community,
                requested_lens=requested_lens,
                requested_team_id=requested_team_id,
            )
        resolved = lenses[community]
        team_id = resolved["effective_team_id"]
        if team_id is None:
            post["lens"] = {
                "requested": requested_lens,
                "effective_mode": MODE_RAW,
                "effective_team_id": None,
            }
            visible.append(post)
            continue

        cur.execute(
            """
            SELECT
                EXISTS(
                    SELECT 1 FROM curation_hidden_posts
                    WHERE community=%s AND team_id=%s AND LOWER(target_txhash)=%s
                ),
                EXISTS(
                    SELECT 1 FROM curation_hidden_users
                    WHERE community=%s AND team_id=%s AND LOWER(target_user)=%s
                ),
                COALESCE((
                    SELECT subscriber_only FROM curation_teams
                    WHERE community=%s AND team_id=%s AND deleted_height IS NULL
                ), FALSE),
                (
                    SELECT lock_sequence FROM curation_locks
                    WHERE community=%s AND team_id=%s AND LOWER(root_txhash)=%s
                ),
                EXISTS(
                    SELECT 1 FROM followed_users
                    WHERE LOWER(owner)=%s AND LOWER(target)=%s
                )
            """,
            (
                community,
                team_id,
                post_id,
                community,
                team_id,
                meta["author"],
                community,
                team_id,
                community,
                team_id,
                meta["root_txhash"],
                address,
                meta["author"],
            ),
        )
        hidden_post, hidden_author, subscriber_only, lock_sequence, follows_author = cur.fetchone()
        visibility = resolve_visibility(
            viewer=address,
            community=community,
            author=meta["author"],
            txhash=post_id,
            root_txhash=meta["root_txhash"],
            post_sequence=meta["post_sequence"],
            was_subscriber_at_creation=bool(meta["was_subscriber_at_creation"]),
            deleted=False,
            viewer_blocks_author=False,
            viewer_blocks_post=False,
            viewer_blocks_community=False,
            viewer_follows_author=bool(follows_author),
            stored_mode=resolved["effective_mode"],
            stored_team_id=team_id,
            default_team_id=team_id,
            team_hidden_post=bool(hidden_post),
            team_hidden_author=bool(hidden_author),
            team_subscriber_only=bool(subscriber_only),
            lock_sequence=int(lock_sequence) if lock_sequence is not None else None,
            temporary_raw=False,
            node_blocked=False,
        )
        if visibility["reason"] == "subscriber_only":
            log.debug(
                "curation.subscriber_only hide post=%s community=%s team=%s was_subscriber=%s",
                post_id[:12],
                community,
                team_id,
                bool(meta["was_subscriber_at_creation"]),
            )
        post["lens"] = {
            "requested": requested_lens,
            "effective_mode": visibility["effective_mode"],
            "effective_team_id": visibility["effective_team_id"],
        }
        if visibility["visible"]:
            visible.append(post)
        elif direct and visibility["tombstone"]:
            tombstones.append(
                {
                    "post_id": post_id,
                    "tombstone": True,
                    "reason": visibility["reason"],
                    "raw_view": f"?scope=current&lens=raw",
                }
            )
    return visible, tombstones


def thread_locked_for_lens(cur, community: str, root_id: str, team_id: int | None) -> bool:
    """Report whether this lens's team has locked the thread rooted at ``root_id``.

    A lock is per team, so the raw lens (``team_id`` None) is never locked and
    two teams can disagree. This is only ever used to tell the client not to
    offer a reply it would immediately hide: the lock is a read filter, so a
    comment written anyway is still valid on chain and still visible on raw.
    """
    slug = str(community or "").strip().lower()
    root = str(root_id or "").strip().lower()
    if not slug or not root or team_id is None:
        return False
    cur.execute(
        """
        SELECT 1 FROM curation_locks
        WHERE community=%s AND team_id=%s AND LOWER(root_txhash)=%s
        """,
        (slug, int(team_id), root),
    )
    return cur.fetchone() is not None
