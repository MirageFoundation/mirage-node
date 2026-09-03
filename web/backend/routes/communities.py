from __future__ import annotations

"""Community, curation, and creator HTTP reads/writes."""

import re
import time

from flask import Blueprint, jsonify, request

from error_utils import api_error_code
from logging_utils import log_event, next_request_id
from db import connect_db
from params import expect_params, expect_creator_schedule
from curation import MODE_RAW, get_default_team, resolve_lens

communities_bp = Blueprint("communities", __name__)
CURATOR_READ_ACTION = "curator_read"


def _limit() -> int:
    try:
        n = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        n = 25
    if n < 1:
        n = 25
    if n > 100:
        n = 100
    return n


def _valid_slug(slug: str) -> bool:
    params = expect_params()
    minimum = int(params["min_community_size"])
    maximum = int(params["max_community_size"])
    return minimum <= len(slug) <= maximum and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", slug) is not None


def _team_summary(team: dict | None) -> dict | None:
    if team is None:
        return None
    return {
        "team_id": str(team["team_id"]),
        "name": team["name"],
        "subscriber_count": str(team["subscriber_count"]),
    }


def _parse_list_cursor(raw: str):
    """Return ((post_count, community), None) or (None, error_response). Empty is (None, None)."""
    if not raw:
        return None, None
    if ":" not in raw:
        return None, api_error_code("invalid_cursor", 400)
    count_str, community = raw.split(":", 1)
    try:
        post_count = int(count_str)
    except (TypeError, ValueError):
        return None, api_error_code("invalid_cursor", 400)
    if post_count < 0 or not community:
        return None, api_error_code("invalid_cursor", 400)
    return (post_count, community), None


def _parse_hidden_list_paging():
    """Return ((offset, limit), None) or (None, error_response)."""
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        return None, api_error_code("invalid_offset", 400)
    if offset < 0:
        return None, api_error_code("invalid_offset", 400)
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        return None, api_error_code("invalid_limit", 400)
    if limit < 1 or limit > 50:
        return None, api_error_code("invalid_limit", 400)
    return (offset, limit), None


def _viewer_is_team_curator(cur, slug: str, team_id: int, viewer: str) -> bool:
    cur.execute(
        """
        SELECT 1 FROM curation_team_curators
        WHERE community=%s AND team_id=%s AND LOWER(curator)=%s
        LIMIT 1
        """,
        (slug, team_id, viewer),
    )
    return cur.fetchone() is not None


def _require_curator_read(viewer: str):
    from routes.core import _require_signed_read

    data = request.args.to_dict(flat=True)
    return _require_signed_read(data, CURATOR_READ_ACTION, viewer)


def _parse_creator_paging():
    try:
        limit = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        return None, api_error_code("invalid_creator_limit", 400)
    if limit < 1 or limit > 100:
        return None, api_error_code("invalid_creator_limit", 400)
    claimable_raw = (request.args.get("claimable_only") or "false").strip().lower()
    if claimable_raw not in ("true", "false"):
        return None, api_error_code("invalid_input", 400)
    claimable_only = claimable_raw == "true"
    default_sort = "claim_deadline_asc" if claimable_only else "epoch_desc"
    sort = (request.args.get("sort") or default_sort).strip().lower()
    if sort not in ("claim_deadline_asc", "epoch_desc"):
        return None, api_error_code("invalid_input", 400)
    if claimable_only and sort != "claim_deadline_asc":
        return None, api_error_code("invalid_input", 400)
    if not claimable_only and sort != "epoch_desc":
        return None, api_error_code("invalid_input", 400)
    cursor = (request.args.get("cursor") or "").strip().lower()
    parsed_cursor = None
    if cursor:
        try:
            if sort == "claim_deadline_asc":
                deadline, epoch_id = cursor.split(":", 1)
                parsed_cursor = (int(deadline), int(epoch_id))
            else:
                parsed_cursor = int(cursor)
        except (TypeError, ValueError):
            return None, api_error_code("invalid_creator_cursor", 400)
        values = parsed_cursor if isinstance(parsed_cursor, tuple) else (parsed_cursor,)
        if any(value < 0 for value in values):
            return None, api_error_code("invalid_creator_cursor", 400)
    return (limit, claimable_only, sort, parsed_cursor), None


def _target_page(cur, creator: str, epoch_id: int, limit: int, cursor: str = "") -> tuple[list[dict], str | None, bool]:
    cursor_amount = None
    cursor_txhash = ""
    if cursor:
        try:
            amount_raw, cursor_txhash = cursor.split(":", 1)
            cursor_amount = int(amount_raw)
        except (TypeError, ValueError):
            raise ValueError("invalid target cursor")
        if cursor_amount < 0 or not cursor_txhash:
            raise ValueError("invalid target cursor")
    cur.execute(
        """
        SELECT t.target_txhash, t.amount, t.upvote_units, t.direct_reply_units,
               p.title, p.content, p.community, p.target, p.deleted
        FROM creator_target_earnings t
        LEFT JOIN posts p ON p.txhash = t.target_txhash
        WHERE LOWER(t.creator)=LOWER(%s) AND t.epoch_id=%s
          AND (
            %s::NUMERIC IS NULL
            OR t.amount < %s
            OR (t.amount = %s AND LOWER(t.target_txhash) > %s)
          )
        ORDER BY t.amount DESC, LOWER(t.target_txhash) ASC
        LIMIT %s
        """,
        (creator, epoch_id, cursor_amount, cursor_amount, cursor_amount, cursor_txhash, limit + 1),
    )
    rows = cur.fetchall() or []
    has_more = len(rows) > limit
    items = []
    for row in rows[:limit]:
        deleted = bool(row[8])
        content = (row[5] or "").strip()
        items.append(
            {
                "txhash": row[0],
                "amount": str(row[1]),
                "upvote_units": int(row[2]),
                "direct_reply_units": int(row[3]),
                "title": None if deleted else (row[4] or None),
                "excerpt": None if deleted else (content[:120] or None),
                "community": row[6],
                "is_comment": row[7] is not None,
                "deleted": deleted,
            }
        )
    next_cursor = f"{items[-1]['amount']}:{items[-1]['txhash'].lower()}" if has_more and items else None
    return items, next_cursor, has_more


@communities_bp.route("/api/communities")
def list_communities():
    rid = next_request_id()
    q = (request.args.get("query") or "").strip().lower()
    joined_by = (request.args.get("joined_by") or "").strip().lower()
    cursor_raw = (request.args.get("cursor") or "").strip().lower()
    cursor_pair, cursor_err = _parse_list_cursor(cursor_raw)
    if cursor_err is not None:
        return cursor_err
    skip_cursor = cursor_pair is None
    cursor_count = 0 if skip_cursor else cursor_pair[0]
    cursor_community = "" if skip_cursor else cursor_pair[1]
    curated_raw = (request.args.get("curated") or "").strip().lower()
    if curated_raw not in ("", "true", "false"):
        return api_error_code("invalid_curated", 400)
    curated = None if not curated_raw else curated_raw == "true"
    limit = _limit()
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                WITH candidates AS (
                    -- Every protocol, not just 1: the pre-upgrade archive is served
                    -- in the default scope, so a community with only old posts is a
                    -- real community and has to be discoverable like any other.
                    SELECT LOWER(TRIM(community)) AS community
                    FROM posts
                    WHERE COALESCE(target,'')=''
                      AND community IS NOT NULL
                      AND community<>''
                    UNION
                    SELECT community
                    FROM curation_teams
                    WHERE deleted_height IS NULL
                    UNION
                    SELECT community
                    FROM community_curation_preferences
                    WHERE %s<>'' AND LOWER(owner)=%s
                ),
                aggregates AS (
                    SELECT c.community,
                           COUNT(DISTINCT t.team_id) AS live_team_count,
                           COUNT(DISTINCT p.txhash) AS post_count
                    FROM candidates c
                    LEFT JOIN curation_teams t
                      ON t.community=c.community AND t.deleted_height IS NULL
                    LEFT JOIN posts p
                      ON LOWER(p.community)=c.community
                     AND COALESCE(p.target,'')=''
                     AND p.deleted=FALSE
                    WHERE (%s='' OR c.community LIKE %s)
                      AND (
                        %s=''
                        OR EXISTS(
                            SELECT 1 FROM community_curation_preferences joined
                            WHERE LOWER(joined.owner)=%s AND joined.community=c.community
                        )
                      )
                    GROUP BY c.community
                )
                SELECT community, live_team_count, post_count
                FROM aggregates
                WHERE (%s::BOOLEAN IS NULL OR (live_team_count>0)=%s)
                  AND (%s OR post_count < %s OR (post_count = %s AND community > %s))
                ORDER BY post_count DESC, community ASC
                LIMIT %s
                """,
                (
                    joined_by,
                    joined_by,
                    q,
                    q + "%",
                    joined_by,
                    joined_by,
                    curated,
                    curated,
                    skip_cursor,
                    cursor_count,
                    cursor_count,
                    cursor_community,
                    limit + 1,
                ),
            )
            rows = cur.fetchall() or []
            items = []
            for community, live_team_count, post_count in rows[:limit]:
                default_team = get_default_team(cur, community)
                items.append(
                    {
                        "community": community,
                        "curated": int(live_team_count) > 0,
                        "live_team_count": int(live_team_count),
                        "post_count": int(post_count),
                        "default_team": _team_summary(default_team),
                    }
                )
        has_more = len(rows) > limit
        next_cursor = (
            f"{items[-1]['post_count']}:{items[-1]['community']}" if has_more and items else None
        )
        log_event(
            rid,
            "[community] list.ok",
            count=len(items),
            joined_by=joined_by,
            curated=curated,
            sort="post_count_desc",
            first=items[0]["community"] if items else None,
            first_posts=items[0]["post_count"] if items else None,
        )
        return jsonify({"items": items, "next_cursor": next_cursor, "has_more": has_more})
    except Exception as e:
        log_event(rid, "communities.list.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>")
def community_detail(slug: str):
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    viewer = (request.args.get("viewer") or "").strip().lower()
    if not _valid_slug(slug):
        return api_error_code("community_invalid", 400)
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT
                    COUNT(DISTINCT team_id) FILTER (WHERE deleted_height IS NULL),
                    COUNT(DISTINCT team_id) FILTER (WHERE deleted_height IS NOT NULL)
                FROM curation_teams
                WHERE community=%s
                """,
                (slug,),
            )
            team_counts = cur.fetchone()
            cur.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE deleted=FALSE),
                    COUNT(*) FILTER (WHERE protocol_version=0)
                FROM posts
                WHERE LOWER(community)=%s AND COALESCE(target,'')=''
                """,
                (slug,),
            )
            post_count, legacy_count = cur.fetchone()
            resolved = resolve_lens(cur, viewer=viewer, community=slug)
            live_team_count = int(team_counts[0] or 0)
            default_team = resolved["default_team"]
        response = {
            "community": slug,
            "curated": live_team_count > 0,
            "live_team_count": live_team_count,
            "deleted_team_count": int(team_counts[1] or 0),
            "post_count": int(post_count or 0),
            "legacy_archive_count": int(legacy_count or 0),
            "viewer_joined": resolved.get("stored_mode") is not None,
            "stored_mode": resolved.get("stored_mode"),
            "stored_team_id": (str(resolved["stored_team_id"]) if resolved.get("stored_team_id") is not None else None),
            "effective_mode": int(resolved["effective_mode"]),
            "effective_team_id": (
                str(resolved["effective_team_id"]) if resolved["effective_team_id"] is not None else None
            ),
            "default_team": _team_summary(default_team),
        }
        if live_team_count == 0:
            response["effective_mode"] = MODE_RAW
            response["effective_team_id"] = None
        log_event(rid, "[community] detail.ok", community=slug, curated=response["curated"])
        return jsonify(response)
    except Exception as e:
        log_event(rid, "communities.detail.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/curators/<address>/communities")
def curator_communities(address: str):
    """Communities where this address is an accepted curator on a live team."""
    rid = next_request_id()
    viewer = (address or "").strip().lower()
    if not re.fullmatch(r"mirage1[0-9a-z]{38}", viewer):
        return api_error_code("user_must_be_mirage1", 400)
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT DISTINCT ON (m.community) m.community, m.team_id, t.name
                FROM curation_team_curators m
                JOIN curation_teams t
                  ON t.community=m.community AND t.team_id=m.team_id
                WHERE LOWER(m.curator)=%s
                  AND t.deleted_height IS NULL
                ORDER BY m.community, m.team_id
                """,
                (viewer,),
            )
            memberships = []
            communities = []
            for community, team_id, name in (cur.fetchall() or []):
                if not community:
                    continue
                slug = str(community).lower()
                communities.append(slug)
                memberships.append(
                    {
                        "community": slug,
                        "team_id": int(team_id),
                        "name": str(name or "").strip(),
                    }
                )
        log_event(
            rid,
            "[community] curator_communities",
            viewer=viewer[:12],
            count=len(communities),
        )
        return jsonify({"communities": communities, "memberships": memberships})
    except Exception as e:
        log_event(rid, "communities.curator_communities.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/curators/<address>/invitations")
def curator_invitations(address: str):
    """Pending curator-team invites for this address. Signed viewer must match."""
    rid = next_request_id()
    target = (address or "").strip().lower()
    if not re.fullmatch(r"mirage1[0-9a-z]{38}", target):
        return api_error_code("user_must_be_mirage1", 400)
    viewer = (request.args.get("viewer") or "").strip().lower()
    signed_viewer, auth_err = _require_curator_read(viewer)
    if auth_err is not None:
        return auth_err
    if signed_viewer != target:
        return api_error_code("forbidden", 403)
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT i.community, i.team_id, t.name, i.inviter, inv.username, i.created_height
                FROM curation_team_invitations i
                JOIN curation_teams t
                  ON t.community=i.community AND t.team_id=i.team_id
                LEFT JOIN profiles inv ON LOWER(inv.owner)=LOWER(i.inviter)
                WHERE LOWER(i.invitee)=%s
                  AND i.status=0
                  AND t.deleted_height IS NULL
                ORDER BY i.created_height DESC, i.community, i.team_id
                LIMIT 20
                """,
                (target,),
            )
            items = []
            for community, team_id, name, inviter, inviter_username, created_height in (cur.fetchall() or []):
                if not community:
                    continue
                items.append(
                    {
                        "community": str(community).lower(),
                        "team_id": int(team_id),
                        "name": str(name or "").strip(),
                        "inviter": str(inviter or "").lower(),
                        "inviter_username": inviter_username or None,
                        "created_height": int(created_height),
                    }
                )
        log_event(
            rid,
            "[community] curator_invitations",
            viewer=target[:12],
            count=len(items),
        )
        return jsonify({"items": items})
    except Exception as e:
        log_event(rid, "communities.curator_invitations.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>/teams")
def community_teams(slug: str):
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    if not _valid_slug(slug):
        return api_error_code("community_invalid", 400)
    include_deleted = str(request.args.get("include_deleted") or "").lower() == "true"
    viewer = (request.args.get("viewer") or "").strip().lower()
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            sql = """
                SELECT t.team_id, t.owner, t.name, t.description,
                       t.subscriber_only, t.subscriber_count, t.deleted_height,
                       COUNT(m.curator) AS member_count, t.tag
                FROM curation_teams t
                LEFT JOIN curation_team_curators m
                  ON m.community=t.community AND m.team_id=t.team_id
                WHERE t.community=%s
            """
            if not include_deleted:
                sql += " AND t.deleted_height IS NULL"
            sql += """
                GROUP BY t.community, t.team_id
                ORDER BY t.created_order, t.team_id
                LIMIT 100
            """
            cur.execute(sql, (slug,))
            rows = cur.fetchall() or []
            viewer_team_ids: list[str] = []
            if viewer:
                cur.execute(
                    """
                    SELECT team_id
                    FROM curation_team_curators
                    WHERE community=%s AND LOWER(curator)=%s
                    ORDER BY team_id
                    """,
                    (slug, viewer),
                )
                viewer_team_ids = [str(r[0]) for r in cur.fetchall()]
                log_event(
                    rid,
                    "[community] teams.viewer_membership",
                    community=slug,
                    viewer=viewer[:12],
                    team_ids=viewer_team_ids,
                )
        items = [
            {
                "team_id": str(r[0]),
                "owner": r[1],
                "name": r[2],
                "description": r[3],
                "subscriber_only": bool(r[4]),
                "subscriber_count": str(r[5]),
                "deleted": r[6] is not None,
                "member_count": int(r[7]),
                "tag": str(r[8] or ""),
            }
            for r in rows
        ]
        return jsonify(
            {
                "items": items,
                "viewer_team_ids": viewer_team_ids,
                "next_cursor": None,
                "has_more": False,
            }
        )
    except Exception as e:
        log_event(rid, "communities.teams.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>/teams/<int:team_id>")
def community_team_detail(slug: str, team_id: int):
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    if not _valid_slug(slug) or team_id <= 0:
        return api_error_code("community_invalid", 400)
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT owner, name, description, subscriber_only,
                       subscriber_count, created_height, created_order, deleted_height, tag
                FROM curation_teams
                WHERE community=%s AND team_id=%s
                """,
                (slug, team_id),
            )
            row = cur.fetchone()
            if not row:
                return api_error_code("curation_team_not_found", 404)
            cur.execute(
                """
                SELECT m.curator, m.accepted_order, m.joined_height,
                       p.username, p.effective_paid
                FROM curation_team_curators m
                LEFT JOIN profiles p ON LOWER(p.owner)=LOWER(m.curator)
                WHERE m.community=%s AND m.team_id=%s
                ORDER BY m.accepted_order, m.curator
                """,
                (slug, team_id),
            )
            members = [
                {
                    "address": member[0],
                    "accepted_order": str(member[1]),
                    "joined_height": int(member[2]),
                    "username": member[3] or None,
                    "effective_paid": bool(member[4]),
                }
                for member in cur.fetchall()
            ]
        return jsonify(
            {
                "community": slug,
                "team_id": str(team_id),
                "owner": row[0],
                "name": row[1],
                "description": row[2],
                "subscriber_only": bool(row[3]),
                "subscriber_count": str(row[4]),
                "created_height": int(row[5]),
                "created_order": str(row[6]),
                "deleted": row[7] is not None,
                "tag": str(row[8] or ""),
                "members": members,
            }
        )
    except Exception as e:
        log_event(rid, "communities.team_detail.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>/teams/<int:team_id>/invitations")
def community_team_invitations(slug: str, team_id: int):
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    viewer = (request.args.get("viewer") or "").strip().lower()
    signed_viewer, auth_err = _require_curator_read(viewer)
    if auth_err is not None:
        return auth_err
    viewer = signed_viewer
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT owner FROM curation_teams WHERE community=%s AND team_id=%s",
                (slug, team_id),
            )
            row = cur.fetchone()
            if not row:
                return api_error_code("curation_team_not_found", 404)
            owner = str(row[0]).lower()
            if viewer == owner:
                cur.execute(
                    """
                    SELECT i.invitee, i.inviter, i.status, i.created_height, i.resolved_height,
                           p.username
                    FROM curation_team_invitations i
                    LEFT JOIN profiles p ON LOWER(p.owner)=LOWER(i.invitee)
                    WHERE i.community=%s AND i.team_id=%s
                    ORDER BY i.created_height DESC, i.invitee
                    """,
                    (slug, team_id),
                )
            else:
                cur.execute(
                    """
                    SELECT i.invitee, i.inviter, i.status, i.created_height, i.resolved_height,
                           p.username
                    FROM curation_team_invitations i
                    LEFT JOIN profiles p ON LOWER(p.owner)=LOWER(i.invitee)
                    WHERE i.community=%s AND i.team_id=%s AND LOWER(i.invitee)=%s
                    ORDER BY i.created_height DESC
                    """,
                    (slug, team_id, viewer),
                )
            invitations = [
                {
                    "invitee": row[0],
                    "inviter": row[1],
                    "status": int(row[2]),
                    "created_height": int(row[3]),
                    "resolved_height": int(row[4]) if row[4] is not None else None,
                    "username": row[5] or None,
                }
                for row in cur.fetchall()
            ]
        return jsonify({"items": invitations})
    except Exception as e:
        log_event(rid, "communities.invitations.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


# The curate menu needs this state for every post a curator can see, so asking
# one post at a time made opening a menu cost a round trip. The batch form below
# answers a whole feed page in one signed call.
#
# Capped at one feed page, which is also what a GET can carry: each id is 64
# hex characters, so a larger batch builds a query string the proxy rejects with
# a bodyless 400 before Flask sees it. The cap has to stay at or under the feed
# limit for that reason, not merely to bound the query.
MODERATION_BATCH_CAP = 50


def _parse_moderation_post_ids(raw: str):
    """Split and validate the batch ``post_ids`` parameter."""
    post_ids: list[str] = []
    seen: set[str] = set()
    for chunk in raw.split(","):
        candidate = chunk.strip().lower()
        if not candidate:
            continue
        if len(candidate) != 64 or any(char not in "0123456789abcdef" for char in candidate):
            return None, api_error_code("invalid_post_id", 400)
        if candidate in seen:
            continue
        seen.add(candidate)
        post_ids.append(candidate)
    if not post_ids:
        return None, api_error_code("missing_post_id", 400)
    if len(post_ids) > MODERATION_BATCH_CAP:
        return None, api_error_code("too_many_post_ids", 400)
    return post_ids, None


@communities_bp.route("/api/communities/<slug>/teams/<int:team_id>/moderation")
def community_team_moderation(slug: str, team_id: int):
    """Return this team's hide/lock state for one post — curator viewers only."""
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    viewer = (request.args.get("viewer") or "").strip().lower()
    post_id = (request.args.get("post_id") or "").strip().lower()
    author = (request.args.get("author") or "").strip().lower()
    root = (request.args.get("root") or "").strip().lower()
    if not _valid_slug(slug) or team_id <= 0:
        return api_error_code("community_invalid", 400)
    signed_viewer, auth_err = _require_curator_read(viewer)
    if auth_err is not None:
        return auth_err
    viewer = signed_viewer
    batch_raw = (request.args.get("post_ids") or "").strip()
    if batch_raw:
        post_ids, parse_err = _parse_moderation_post_ids(batch_raw)
        if parse_err is not None:
            return parse_err
        try:
            with connect_db() as conn:
                cur = conn.cursor()
                if not _viewer_is_team_curator(cur, slug, team_id, viewer):
                    return api_error_code("forbidden", 403)
                # Author and root come from the posts table rather than the
                # client: the caller has no business asserting whose post this
                # is, and the root is what the lock is keyed on.
                cur.execute(
                    """
                    WITH meta AS (
                        SELECT LOWER(p.txhash) AS post_id,
                               LOWER(p.owner) AS author,
                               LOWER(COALESCE(p.root_txhash, p.root_post_id, p.txhash)) AS root
                        FROM posts p
                        WHERE LOWER(p.txhash)=ANY(%s)
                    )
                    SELECT
                        m.post_id,
                        EXISTS(
                            SELECT 1 FROM curation_hidden_posts
                            WHERE community=%s AND team_id=%s AND LOWER(target_txhash)=m.post_id
                        ),
                        EXISTS(
                            SELECT 1 FROM curation_hidden_users
                            WHERE community=%s AND team_id=%s AND LOWER(target_user)=m.author
                        ),
                        EXISTS(
                            SELECT 1 FROM curation_locks
                            WHERE community=%s AND team_id=%s AND LOWER(root_txhash)=m.root
                              AND lock_sequence IS NOT NULL
                        ),
                        (
                            SELECT tag FROM curation_post_tags
                            WHERE community=%s AND team_id=%s AND LOWER(target_txhash)=m.post_id
                        )
                    FROM meta m
                    """,
                    (
                        post_ids,
                        slug,
                        team_id,
                        slug,
                        team_id,
                        slug,
                        team_id,
                        slug,
                        team_id,
                    ),
                )
                rows = cur.fetchall() or []
            items = [
                {
                    "post_id": str(row[0]).lower(),
                    "post_hidden": bool(row[1]),
                    "user_hidden": bool(row[2]),
                    "thread_locked": bool(row[3]),
                    # null means this team has no opinion; "" means the curator
                    # explicitly marked the post untagged.
                    "post_tag": row[4],
                }
                for row in rows
            ]
            log_event(
                rid,
                "[community] teams.moderation.batch",
                community=slug,
                team_id=team_id,
                viewer=viewer[:12],
                requested=len(post_ids),
                count=len(items),
                # A requested post with no row is a post the indexer has not
                # seen; the caller asks for it individually rather than being
                # handed a guess.
                missing=len(post_ids) - len(items),
            )
            return jsonify(
                {
                    "community": slug,
                    "team_id": str(team_id),
                    "items": items,
                }
            )
        except Exception as e:
            log_event(rid, "communities.moderation.batch.err", error=str(e))
            return api_error_code("indexer_unavailable", 503)
    if not post_id:
        return api_error_code("missing_post_id", 400)
    if not author:
        return api_error_code("missing_author", 400)
    if not root:
        root = post_id
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT 1 FROM curation_team_curators
                WHERE community=%s AND team_id=%s AND LOWER(curator)=%s
                LIMIT 1
                """,
                (slug, team_id, viewer),
            )
            if not cur.fetchone():
                return api_error_code("forbidden", 403)
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
                    EXISTS(
                        SELECT 1 FROM curation_locks
                        WHERE community=%s AND team_id=%s AND LOWER(root_txhash)=%s
                          AND lock_sequence IS NOT NULL
                    ),
                    (
                        SELECT tag FROM curation_post_tags
                        WHERE community=%s AND team_id=%s AND LOWER(target_txhash)=%s
                    )
                """,
                (
                    slug,
                    team_id,
                    post_id,
                    slug,
                    team_id,
                    author,
                    slug,
                    team_id,
                    root,
                    slug,
                    team_id,
                    post_id,
                ),
            )
            post_hidden, user_hidden, thread_locked, post_tag = cur.fetchone()
        log_event(
            rid,
            "[community] teams.moderation",
            community=slug,
            team_id=team_id,
            viewer=viewer[:12],
            post_id=post_id[:12],
            post_hidden=bool(post_hidden),
            user_hidden=bool(user_hidden),
            thread_locked=bool(thread_locked),
            post_tag=post_tag,
        )
        return jsonify(
            {
                "community": slug,
                "team_id": str(team_id),
                "post_id": post_id,
                "author": author,
                "root": root,
                "post_hidden": bool(post_hidden),
                "user_hidden": bool(user_hidden),
                "thread_locked": bool(thread_locked),
                # null means this team has no opinion; "" means the curator
                # explicitly marked the post untagged.
                "post_tag": post_tag,
            }
        )
    except Exception as e:
        log_event(rid, "communities.moderation.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>/teams/<int:team_id>/hidden-users")
def community_team_hidden_users(slug: str, team_id: int):
    """Users this team currently hides — curator viewers only. Newest first."""
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    viewer = (request.args.get("viewer") or "").strip().lower()
    if not _valid_slug(slug) or team_id <= 0:
        return api_error_code("community_invalid", 400)
    signed_viewer, auth_err = _require_curator_read(viewer)
    if auth_err is not None:
        return auth_err
    viewer = signed_viewer
    paging, err = _parse_hidden_list_paging()
    if err is not None:
        return err
    offset, limit = paging
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            if not _viewer_is_team_curator(cur, slug, team_id, viewer):
                return api_error_code("forbidden", 403)
            cur.execute(
                """
                SELECT h.target_user, p.username
                FROM curation_hidden_users h
                LEFT JOIN profiles p ON LOWER(p.owner)=LOWER(h.target_user)
                WHERE h.community=%s AND h.team_id=%s
                ORDER BY h.updated_height DESC, h.target_user
                LIMIT %s OFFSET %s
                """,
                (slug, team_id, limit + 1, offset),
            )
            rows = cur.fetchall() or []
        has_more = len(rows) > limit
        items = [
            {
                "address": str(row[0]).lower(),
                "username": row[1] or None,
            }
            for row in rows[:limit]
        ]
        log_event(
            rid,
            "[community] teams.hidden_users",
            community=slug,
            team_id=team_id,
            viewer=viewer[:12],
            offset=offset,
            limit=limit,
            count=len(items),
            has_more=has_more,
        )
        return jsonify(
            {
                "community": slug,
                "team_id": str(team_id),
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                "items": items,
            }
        )
    except Exception as e:
        log_event(rid, "communities.hidden_users.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>/teams/<int:team_id>/hidden-posts")
def community_team_hidden_posts(slug: str, team_id: int):
    """Posts this team currently hides — curator viewers only. Newest first."""
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    viewer = (request.args.get("viewer") or "").strip().lower()
    if not _valid_slug(slug) or team_id <= 0:
        return api_error_code("community_invalid", 400)
    signed_viewer, auth_err = _require_curator_read(viewer)
    if auth_err is not None:
        return auth_err
    viewer = signed_viewer
    paging, err = _parse_hidden_list_paging()
    if err is not None:
        return err
    offset, limit = paging
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            if not _viewer_is_team_curator(cur, slug, team_id, viewer):
                return api_error_code("forbidden", 403)
            cur.execute(
                """
                SELECT h.target_txhash, p.title
                FROM curation_hidden_posts h
                LEFT JOIN posts p ON LOWER(p.txhash)=LOWER(h.target_txhash)
                WHERE h.community=%s AND h.team_id=%s
                ORDER BY h.updated_height DESC, h.target_txhash
                LIMIT %s OFFSET %s
                """,
                (slug, team_id, limit + 1, offset),
            )
            rows = cur.fetchall() or []
        has_more = len(rows) > limit
        items = [
            {
                "post_id": str(row[0]).lower(),
                "title": row[1] if isinstance(row[1], str) and row[1].strip() else None,
            }
            for row in rows[:limit]
        ]
        log_event(
            rid,
            "[community] teams.hidden_posts",
            community=slug,
            team_id=team_id,
            viewer=viewer[:12],
            offset=offset,
            limit=limit,
            count=len(items),
            has_more=has_more,
        )
        return jsonify(
            {
                "community": slug,
                "team_id": str(team_id),
                "offset": offset,
                "limit": limit,
                "has_more": has_more,
                "items": items,
            }
        )
    except Exception as e:
        log_event(rid, "communities.hidden_posts.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/creator/earnings")
def creator_earnings():
    rid = next_request_id()
    creator = (request.args.get("creator") or "").strip()
    if not creator:
        return api_error_code("missing_creator", 400)
    paging, paging_err = _parse_creator_paging()
    if paging_err is not None:
        return paging_err
    limit, claimable_only, sort, cursor = paging
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            conditions = ["LOWER(creator)=LOWER(%s)"]
            query_params: list = [creator]
            if claimable_only:
                conditions.extend(
                    [
                        "earned > claimed",
                        "claimed_height IS NULL",
                        "claim_deadline_unix IS NOT NULL",
                        "claim_deadline_unix >= %s",
                    ]
                )
                query_params.append(int(time.time()))
            if cursor is not None:
                if sort == "claim_deadline_asc":
                    conditions.append(
                        "(claim_deadline_unix > %s OR (claim_deadline_unix = %s AND epoch_id > %s))"
                    )
                    query_params.extend((cursor[0], cursor[0], cursor[1]))
                else:
                    conditions.append("epoch_id < %s")
                    query_params.append(cursor)
            order = (
                "claim_deadline_unix ASC, epoch_id ASC"
                if sort == "claim_deadline_asc"
                else "epoch_id DESC"
            )
            cur.execute(
                f"""
                SELECT epoch_id, earned, claimed, claim_deadline_unix,
                       start_unix, end_unix, claimed_height
                FROM creator_accruals
                WHERE {" AND ".join(conditions)}
                ORDER BY {order}
                LIMIT %s
                """,
                query_params + [limit + 1],
            )
            rows = cur.fetchall() or []
            has_more = len(rows) > limit
            rows = rows[:limit]
            posts_by_epoch = {}
            for row in rows:
                posts_by_epoch[row[0]] = _target_page(cur, creator, int(row[0]), 25)
        schedule = expect_creator_schedule()
        params = expect_params()
        creator_epoch_seconds = int(schedule["epoch_seconds"])
        # Times come from the epoch record, not from the live grid. Governance
        # can change creator_epoch_seconds, which renumbers epochs from that
        # point on, so an id settled under an earlier grid cannot be converted.
        items = [
            {
                "epoch_id": r[0],
                "earned": str(r[1]),
                "claimed": str(r[2]),
                "epoch_start_unix": r[4],
                "epoch_end_unix": r[5],
                "claim_deadline_unix": r[3],
                "claimed_height": r[6],
                "posts": posts_by_epoch[r[0]][0],
                "posts_next_cursor": posts_by_epoch[r[0]][1],
                "posts_has_more": posts_by_epoch[r[0]][2],
            }
            for r in rows
        ]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = (
                f"{last['claim_deadline_unix']}:{last['epoch_id']}"
                if sort == "claim_deadline_asc"
                else str(last["epoch_id"])
            )
        return jsonify(
            {
                "items": items,
                "creator_epoch_seconds": creator_epoch_seconds,
                "origin_epoch": int(schedule["origin_epoch"]),
                "origin_unix": int(schedule["origin_unix"]),
                "max_creator_claim_epochs": int(params["max_creator_claim_epochs"]),
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
        )
    except Exception as e:
        log_event(rid, "creator.earnings.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/creator/earnings/<int:epoch_id>/targets")
def creator_earning_targets(epoch_id: int):
    rid = next_request_id()
    creator = (request.args.get("creator") or "").strip()
    if not creator:
        return api_error_code("missing_creator", 400)
    try:
        limit = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        return api_error_code("invalid_creator_limit", 400)
    if epoch_id < 0 or limit < 1 or limit > 100:
        return api_error_code("invalid_creator_limit", 400)
    cursor = (request.args.get("cursor") or "").strip().lower()
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            items, next_cursor, has_more = _target_page(cur, creator, epoch_id, limit, cursor)
        return jsonify({"items": items, "next_cursor": next_cursor, "has_more": has_more})
    except ValueError:
        return api_error_code("invalid_creator_cursor", 400)
    except Exception as e:
        log_event(rid, "creator.targets.err", error=str(e), epoch_id=epoch_id)
        return api_error_code("indexer_unavailable", 503)
