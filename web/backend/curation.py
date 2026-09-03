"""Indexer-backed curation lens resolution and content filtering."""

from __future__ import annotations

import logging
from collections.abc import Mapping
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
    stored_mode: int | None,
    stored_team_id: int | None,
    default_team_id: int | None,
    team_hidden_post: bool,
    team_hidden_author: bool,
    team_subscriber_only: bool,
    lock_windows: list[tuple[int, int | None]],
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
    # Following the author does not survive the ban. A follow carve-out here kept
    # the banned user visible to everyone who followed them — including the
    # curator who issued the ban, since curators follow the people they curate —
    # which makes the control useless to the person holding it. Raw is the
    # deliberate escape hatch: a viewer who wants the ban ignored switches lens.
    if team_hidden_author:
        return _result(False, True, "team_hidden_author", effective_mode, effective_team)
    if team_subscriber_only and not was_subscriber_at_creation:
        return _result(False, True, "subscriber_only", effective_mode, effective_team)
    if post_sequence is not None and _inside_lock_window(post_sequence, lock_windows):
        return _result(False, True, "thread_locked", effective_mode, effective_team)
    return _result(True, False, "ok", effective_mode, effective_team)


def _lock_windows(lock_sequence, lock_windows) -> list[tuple[int, int | None]]:
    """Build the window list for one thread out of its ``curation_locks`` row.

    ``lock_windows`` holds the stretches a past unlock closed, and
    ``lock_sequence`` the start of the one still open, so the open window is
    appended with no end. A thread that was never locked has no row at all,
    which arrives here as two Nones.
    """
    windows: list[tuple[int, int | None]] = []
    for window in lock_windows or ():
        if len(window) != 2:
            raise RuntimeError(f"curation_locks.lock_windows holds a malformed window: {window!r}")
        windows.append((int(window[0]), int(window[1])))
    if lock_sequence is not None:
        windows.append((int(lock_sequence), None))
    return windows


def _inside_lock_window(post_sequence: int, lock_windows) -> bool:
    """Report whether this post was written while the thread was locked.

    A window is the half-open sequence range ``(start, end]``, and ``end`` of
    None is a lock that is still open. Windows closed by a past unlock stay in
    the list forever: a curator unlocking a thread reopens it for new replies,
    it does not publish the ones written while it was shut.
    """
    for start, end in lock_windows or ():
        if post_sequence > int(start) and (end is None or post_sequence <= int(end)):
            return True
    return False


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


def get_default_team(cur, community: str, viewer: str | None = None) -> dict[str, Any] | None:
    """Return the best live team that has not banned this viewer."""
    address = str(viewer or "").strip().lower()
    if address == "guest":
        address = ""
    cur.execute(
        """
        SELECT t.team_id, t.owner, t.name, t.description, t.subscriber_only,
               t.subscriber_count, t.created_height, t.created_order, t.tag
        FROM curation_teams t
        WHERE t.community=%s AND t.deleted_height IS NULL
          AND (
              %s = ''
              OR NOT EXISTS (
                  SELECT 1
                  FROM curation_hidden_users h
                  WHERE h.community=t.community
                    AND h.team_id=t.team_id
                    AND LOWER(h.target_user)=%s
              )
          )
        ORDER BY t.subscriber_count DESC, t.created_order ASC, t.team_id ASC
        LIMIT 1
        """,
        (community, address, address),
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

    address = str(viewer or "").strip().lower()
    if address == "guest":
        address = ""
    default_team = get_default_team(cur, community, address)
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
        banned = False
        if address:
            cur.execute(
                """
                SELECT 1 FROM curation_hidden_users
                WHERE community=%s AND team_id=%s AND LOWER(target_user)=%s
                """,
                (community, int(requested_team_id), address),
            )
            banned = cur.fetchone() is not None
        if banned:
            result = {
                "requested_lens": lens,
                "effective_mode": MODE_PINNED if default_team else MODE_RAW,
                "effective_team_id": default_team["team_id"] if default_team else None,
            }
        else:
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
        if address:
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
                SELECT 1 FROM curation_teams t
                WHERE t.community=%s AND t.team_id=%s AND t.deleted_height IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM curation_hidden_users h
                      WHERE h.community=t.community
                        AND h.team_id=t.team_id
                        AND LOWER(h.target_user)=%s
                  )
                """,
                (community, stored_team_id, address),
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


def _requested_lens_for(
    community: str,
    requested_lens: str,
    requested_team_id: int | None,
    community_lenses: Mapping[str, tuple[str, int | None]] | None,
) -> tuple[str, int | None]:
    if not community_lenses:
        return requested_lens, requested_team_id
    override = community_lenses.get(community)
    if override is None:
        return requested_lens, requested_team_id
    lens, team_id = override
    log.debug("[lens] community override community=%s lens=%s team=%s", community, lens, team_id)
    return lens, team_id


def _load_post_tag_overrides(
    cur,
    lookups: list[tuple[str, int, str]],
) -> dict[tuple[str, int, str], str]:
    """Return {(community, team_id, post_id): tag} for the given triples."""
    if not lookups:
        return {}
    communities = [row[0] for row in lookups]
    team_ids = [row[1] for row in lookups]
    post_ids = [row[2] for row in lookups]
    cur.execute(
        """
        SELECT LOWER(community), team_id, LOWER(target_txhash), tag
        FROM curation_post_tags
        WHERE (community, team_id, LOWER(target_txhash)) IN (
            SELECT c, t, h
            FROM unnest(%s::text[], %s::int[], %s::text[]) AS x(c, t, h)
        )
        """,
        (communities, team_ids, post_ids),
    )
    return {
        (str(row[0]).lower(), int(row[1]), str(row[2]).lower()): str(row[3] or "")
        for row in cur.fetchall()
    }


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

    Each post needs a ``community`` (community slug) and a ``post_id``. When
    filter_posts has already stamped ``post["lens"]`` that team is reused;
    otherwise the lens is resolved here. Always run this before any
    allowed-tags filtering, which must see the effective value.
    """
    if not posts:
        return
    address = str(viewer or "").strip().lower()
    default_teams: dict[str, dict[str, Any] | None] = {}
    lens_teams: dict[str, int | None] = {}
    planned: list[tuple[dict, str, str, int | None]] = []
    override_lookups: list[tuple[str, int, str]] = []
    for post in posts:
        community = str(post.get("community") or "").strip().lower()
        post_id = str(post.get("post_id") or "").strip().lower()
        if not community or not post_id:
            continue
        if community not in default_teams:
            default_teams[community] = get_default_team(cur, community)

        stamped_lens = post.get("lens") or {}
        stamped = stamped_lens.get("effective_team_id")
        if stamped is not None:
            lens_team_id = int(stamped)
        elif stamped_lens:
            lens_team_id = None
        else:
            if community not in lens_teams:
                lens_teams[community] = resolve_lens(
                    cur,
                    viewer=address,
                    community=community,
                    requested_lens=requested_lens,
                    requested_team_id=requested_team_id,
                )["effective_team_id"]
            lens_team_id = lens_teams[community]
        planned.append((post, community, post_id, lens_team_id))
        if lens_team_id is not None:
            override_lookups.append((community, int(lens_team_id), post_id))

    overrides = _load_post_tag_overrides(cur, override_lookups)
    for post, community, post_id, lens_team_id in planned:
        default_team = default_teams[community]
        row = (
            overrides.get((community, int(lens_team_id), post_id))
            if lens_team_id is not None
            else None
        )
        community_tag = default_team["tag"] if default_team else ""
        if row is not None:
            effective = row
        elif community_tag:
            effective = community_tag
        else:
            continue
        if effective != post.get("tag", ""):
            log.debug(
                "[tag] override post=%s community=%s team=%s author_tag=%s effective=%s",
                post_id[:12],
                community,
                lens_team_id,
                post.get("tag", ""),
                effective,
            )
        post["tag"] = effective


def _load_team_moderation(
    cur,
    pending: list[tuple[str, int, str, str, str]],
) -> tuple[
    set[tuple[str, int, str]],
    set[tuple[str, int, str]],
    dict[tuple[str, int], bool],
    dict[tuple[str, int, str], tuple[Any, Any]],
]:
    """Load hide/lock/subscriber-only state for many posts in a few queries.

    Home/bootstrap rank hundreds of candidates and then filter them. A per-post
    EXISTS round-trip made that filter the cold-load stall: one SQL per card,
    hundreds of times, before the first 15 posts could leave the backend.
    """
    hidden_posts: set[tuple[str, int, str]] = set()
    hidden_users: set[tuple[str, int, str]] = set()
    subscriber_only: dict[tuple[str, int], bool] = {}
    locks: dict[tuple[str, int, str], tuple[Any, Any]] = {}
    if not pending:
        return hidden_posts, hidden_users, subscriber_only, locks

    communities = [row[0] for row in pending]
    team_ids = [int(row[1]) for row in pending]
    post_ids = [row[2] for row in pending]
    authors = [row[3] for row in pending]
    cur.execute(
        """
        SELECT LOWER(community), team_id, LOWER(target_txhash)
        FROM curation_hidden_posts
        WHERE (community, team_id, LOWER(target_txhash)) IN (
            SELECT c, t, h FROM unnest(%s::text[], %s::int[], %s::text[]) AS x(c, t, h)
        )
        """,
        (communities, team_ids, post_ids),
    )
    hidden_posts = {(str(row[0]).lower(), int(row[1]), str(row[2]).lower()) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT LOWER(community), team_id, LOWER(target_user)
        FROM curation_hidden_users
        WHERE (community, team_id, LOWER(target_user)) IN (
            SELECT c, t, u FROM unnest(%s::text[], %s::int[], %s::text[]) AS x(c, t, u)
        )
        """,
        (communities, team_ids, authors),
    )
    hidden_users = {(str(row[0]).lower(), int(row[1]), str(row[2]).lower()) for row in cur.fetchall()}

    pair_communities: list[str] = []
    pair_team_ids: list[int] = []
    seen_pairs: set[tuple[str, int]] = set()
    for community, team_id, _post_id, _author, _root in pending:
        key = (community, int(team_id))
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        pair_communities.append(community)
        pair_team_ids.append(int(team_id))
    cur.execute(
        """
        SELECT LOWER(community), team_id, COALESCE(subscriber_only, FALSE)
        FROM curation_teams
        WHERE deleted_height IS NULL
          AND (community, team_id) IN (
              SELECT c, t FROM unnest(%s::text[], %s::int[]) AS x(c, t)
          )
        """,
        (pair_communities, pair_team_ids),
    )
    subscriber_only = {(str(row[0]).lower(), int(row[1])): bool(row[2]) for row in cur.fetchall()}

    root_communities: list[str] = []
    root_team_ids: list[int] = []
    root_hashes: list[str] = []
    seen_roots: set[tuple[str, int, str]] = set()
    for community, team_id, _post_id, _author, root in pending:
        key = (community, int(team_id), root)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        root_communities.append(community)
        root_team_ids.append(int(team_id))
        root_hashes.append(root)
    cur.execute(
        """
        SELECT LOWER(community), team_id, LOWER(root_txhash), lock_sequence, lock_windows
        FROM curation_locks
        WHERE (community, team_id, LOWER(root_txhash)) IN (
            SELECT c, t, r FROM unnest(%s::text[], %s::int[], %s::text[]) AS x(c, t, r)
        )
        """,
        (root_communities, root_team_ids, root_hashes),
    )
    locks = {
        (str(row[0]).lower(), int(row[1]), str(row[2]).lower()): (row[3], row[4])
        for row in cur.fetchall()
    }
    log.debug(
        "curation.moderation_batch posts=%d hidden_posts=%d hidden_users=%d teams=%d locks=%d",
        len(pending),
        len(hidden_posts),
        len(hidden_users),
        len(subscriber_only),
        len(locks),
    )
    return hidden_posts, hidden_users, subscriber_only, locks


def filter_posts(
    cur,
    posts: list[dict],
    *,
    viewer: str | None,
    requested_lens: str,
    requested_team_id: int | None,
    scope: str,
    direct: bool = False,
    community_lenses: Mapping[str, tuple[str, int | None]] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Apply protocol scope and curator-team rules to serialized posts.

    ``community_lenses`` overrides ``requested_lens`` for the communities it
    names. An aggregated feed carries posts from many communities, so one
    request-wide lens cannot express a viewer who reads one community
    uncensored and the rest through their curators.
    """
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

    lenses: dict[str, dict[str, Any]] = {}
    # Team moderation is loaded in one batched query, so posts that resolve to a
    # team cannot be decided in this first pass. Recording each verdict against
    # the post's input position and assembling the result at the end is what
    # keeps the output in the caller's order: appending as verdicts arrive put
    # every team-backed post behind every raw one, which silently reordered the
    # feed. A community gaining its first curation team was enough to drop its
    # posts from the front page — they were still returned, just at the back of
    # a list the caller slices to a page.
    kept: list[dict | None] = [None] * len(posts)
    tombstones: list[dict] = []
    pending: list[tuple[int, dict, str, dict[str, Any], dict[str, Any], str, int]] = []
    address = str(viewer or "").strip().lower()
    for index, (post, post_id) in enumerate(zip(posts, ids)):
        meta = metadata[post_id]
        post["protocol_version"] = meta["protocol_version"]
        if scope == "legacy":
            # The legacy scope is the protocol-0 archive and nothing else.
            if meta["protocol_version"] != 0:
                continue
            kept[index] = post
            continue
        # Protocol-0 posts are curated like any other. The chain never recorded a
        # post_sequence or a subscriber flag for them, but only two of the rules
        # below read those: resolve_visibility skips the thread-lock windows when
        # post_sequence is None, and treats an unknown subscriber flag as "not a
        # subscriber". Hiding a post, hiding a user and the community tag all key
        # on the txhash, the author and the community, which legacy posts have.
        # Exempting them from curation entirely would mean a curator could hide a
        # user and still see them in the feed, which is the whole point of the
        # control — and today essentially every post is protocol 0.
        if meta["protocol_version"] == 1 and (
            meta["post_sequence"] is None or meta["was_subscriber_at_creation"] is None
        ):
            raise RuntimeError(f"protocol-1 post is missing required curation metadata: {post_id}")
        community = meta["community"]
        if not community:
            if meta["protocol_version"] == 1:
                raise RuntimeError(f"protocol-1 post is missing community: {post_id}")
            # A legacy comment whose root is not in the database has no community
            # to resolve a team against, so there is no curation to apply.
            post["lens"] = {
                "requested": requested_lens,
                "effective_mode": MODE_RAW,
                "effective_team_id": None,
            }
            post["thread_locked"] = False
            kept[index] = post
            continue
        if community not in lenses:
            community_lens, community_team_id = _requested_lens_for(
                community,
                requested_lens,
                requested_team_id,
                community_lenses,
            )
            lenses[community] = resolve_lens(
                cur,
                viewer=address,
                community=community,
                requested_lens=community_lens,
                requested_team_id=community_team_id,
            )
        resolved = lenses[community]
        team_id = resolved["effective_team_id"]
        if team_id is None:
            post["lens"] = {
                "requested": resolved["requested_lens"],
                "effective_mode": MODE_RAW,
                "effective_team_id": None,
            }
            post["thread_locked"] = False
            kept[index] = post
            continue
        pending.append((index, post, post_id, meta, resolved, community, int(team_id)))

    hidden_posts, hidden_users, subscriber_only, locks = _load_team_moderation(
        cur,
        [
            (community, team_id, post_id, meta["author"], meta["root_txhash"])
            for _index, _post, post_id, meta, _resolved, community, team_id in pending
        ],
    )
    for index, post, post_id, meta, resolved, community, team_id in pending:
        lock_sequence, lock_windows = locks.get((community, team_id, meta["root_txhash"]), (None, None))
        windows = _lock_windows(lock_sequence, lock_windows)
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
            stored_mode=resolved["effective_mode"],
            stored_team_id=team_id,
            default_team_id=team_id,
            team_hidden_post=(community, team_id, post_id) in hidden_posts,
            team_hidden_author=(community, team_id, meta["author"]) in hidden_users,
            team_subscriber_only=bool(subscriber_only.get((community, team_id), False)),
            lock_windows=windows,
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
            "requested": resolved["requested_lens"],
            "effective_mode": visibility["effective_mode"],
            "effective_team_id": visibility["effective_team_id"],
        }
        # Roots of a locked thread stay in the feed; stamp the lock so the
        # card can show it. Replies after the lock are already dropped above.
        # This is the live lock only: a thread unlocked again is not locked now,
        # even though the replies from its closed windows stay hidden.
        post["thread_locked"] = lock_sequence is not None
        if post["thread_locked"]:
            log.debug(
                "[lock] feed stamp post=%s community=%s team=%s",
                post_id[:12],
                community,
                team_id,
            )
        if visibility["visible"]:
            kept[index] = post
        elif direct and visibility["tombstone"]:
            tombstones.append(
                {
                    "post_id": post_id,
                    "tombstone": True,
                    "reason": visibility["reason"],
                    "raw_view": f"?scope=current&lens=raw",
                }
            )
    return [post for post in kept if post is not None], tombstones


def thread_locked_for_lens(cur, community: str, root_id: str, team_id: int | None) -> bool:
    """Report whether this lens's team has locked the thread rooted at ``root_id``.

    A lock is per team, so the raw lens (``team_id`` None) is never locked and
    two teams can disagree. This is only ever used to tell the client not to
    offer a reply it would immediately hide: the lock is a read filter, so a
    comment written anyway is still valid on chain and still visible on raw.

    A row can outlive the lock that created it, because the windows a past
    unlock closed are kept there to keep hiding the replies written inside
    them. Only an open window means the thread is locked now.
    """
    slug = str(community or "").strip().lower()
    root = str(root_id or "").strip().lower()
    if not slug or not root or team_id is None:
        return False
    cur.execute(
        """
        SELECT 1 FROM curation_locks
        WHERE community=%s AND team_id=%s AND LOWER(root_txhash)=%s
          AND lock_sequence IS NOT NULL
        """,
        (slug, int(team_id), root),
    )
    return cur.fetchone() is not None
