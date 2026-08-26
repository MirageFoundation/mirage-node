from __future__ import annotations

"""Community, curation, and creator HTTP reads/writes."""

from flask import Blueprint, jsonify, request

from error_utils import api_error_code
from logging_utils import log_event, next_request_id
from db import connect_db

communities_bp = Blueprint("communities", __name__)


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


@communities_bp.route("/api/communities")
def list_communities():
    rid = next_request_id()
    q = (request.args.get("query") or "").strip().lower()
    joined_by = (request.args.get("joined_by") or "").strip().lower()
    limit = _limit()
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            if joined_by:
                cur.execute(
                    """
                    SELECT c.community, c.title, c.description, c.current_founder, c.current_default_team_id
                    FROM community_curation_preferences p
                    JOIN communities c ON c.community = p.community
                    WHERE LOWER(p.owner) = %s
                    ORDER BY c.community
                    LIMIT %s
                    """,
                    (joined_by, limit + 1),
                )
            elif q:
                cur.execute(
                    """
                    SELECT community, title, description, current_founder, current_default_team_id
                    FROM communities
                    WHERE community LIKE %s OR LOWER(title) LIKE %s
                    ORDER BY community
                    LIMIT %s
                    """,
                    (q + "%", "%" + q + "%", limit + 1),
                )
            else:
                cur.execute(
                    """
                    SELECT community, title, description, current_founder, current_default_team_id
                    FROM communities
                    ORDER BY created_order DESC
                    LIMIT %s
                    """,
                    (limit + 1,),
                )
            rows = cur.fetchall() or []
        items = [
            {
                "community": r[0],
                "title": r[1],
                "description": r[2],
                "current_founder": r[3],
                "current_default_team_id": str(r[4]) if r[4] is not None else None,
            }
            for r in rows[:limit]
        ]
        return jsonify({"items": items, "next_cursor": None, "has_more": len(rows) > limit})
    except Exception as e:
        log_event(rid, "communities.list.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>")
def community_detail(slug: str):
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    viewer = (request.args.get("viewer") or "").strip().lower()
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT community, original_founder, current_founder, title, description,
                       original_team_id, current_default_team_id, default_count, created_height
                FROM communities WHERE community = %s
                """,
                (slug,),
            )
            row = cur.fetchone()
            claimed = row is not None
            pref = None
            if viewer:
                cur.execute(
                    """
                    SELECT mode, pinned_team_id FROM community_curation_preferences
                    WHERE LOWER(owner)=%s AND community=%s
                    """,
                    (viewer, slug),
                )
                pref = cur.fetchone()
            cur.execute(
                "SELECT COUNT(*) FROM posts WHERE community=%s AND protocol_version=0 AND COALESCE(target,'')=''",
                (slug,),
            )
            legacy_count = int((cur.fetchone() or [0])[0] or 0)
        if not claimed:
            return jsonify({
                "community": slug,
                "claimed": False,
                "read_only": True,
                "legacy_archive_count": legacy_count,
            })
        stored_mode = int(pref[0]) if pref else None
        stored_team = str(pref[1]) if pref and pref[1] is not None else None
        return jsonify({
            "community": row[0],
            "claimed": True,
            "read_only": False,
            "original_founder": row[1],
            "current_founder": row[2],
            "title": row[3],
            "description": row[4],
            "original_team_id": str(row[5]),
            "current_default_team_id": str(row[6]) if row[6] is not None else None,
            "default_count": str(row[7]),
            "created_height": row[8],
            "legacy_archive_count": legacy_count,
            "viewer_joined": pref is not None,
            "stored_mode": stored_mode,
            "stored_team_id": stored_team,
        })
    except Exception as e:
        log_event(rid, "communities.detail.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/communities/<slug>/teams")
def community_teams(slug: str):
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    include_deleted = str(request.args.get("include_deleted") or "").lower() == "true"
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            sql = """
                SELECT team_id, owner, name, bio, policy, is_original, subscriber_only, supporter_count, deleted_height
                FROM curation_teams WHERE community=%s
            """
            if not include_deleted:
                sql += " AND deleted_height IS NULL"
            sql += " ORDER BY created_order LIMIT 100"
            cur.execute(sql, (slug,))
            rows = cur.fetchall() or []
        items = [
            {
                "team_id": str(r[0]),
                "owner": r[1],
                "name": r[2],
                "bio": r[3],
                "policy": r[4],
                "is_original": bool(r[5]),
                "subscriber_only": bool(r[6]),
                "supporter_count": str(r[7]),
                "deleted": r[8] is not None,
            }
            for r in rows
        ]
        return jsonify({"items": items, "next_cursor": None, "has_more": False})
    except Exception as e:
        log_event(rid, "communities.teams.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)


@communities_bp.route("/api/creator/earnings")
def creator_earnings():
    rid = next_request_id()
    creator = (request.args.get("creator") or "").strip()
    if not creator:
        return api_error_code("missing_creator", 400)
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT epoch_id, earned, claimed, claim_deadline_epoch, claimed_height
                FROM creator_accruals WHERE LOWER(creator)=LOWER(%s)
                ORDER BY epoch_id DESC LIMIT 50
                """,
                (creator,),
            )
            rows = cur.fetchall() or []
        items = [
            {
                "epoch_id": r[0],
                "earned": str(r[1]),
                "claimed": str(r[2]),
                "claim_deadline_epoch": r[3],
                "claimed_height": r[4],
            }
            for r in rows
        ]
        return jsonify({"items": items, "next_cursor": None, "has_more": False})
    except Exception as e:
        log_event(rid, "creator.earnings.err", error=str(e))
        return api_error_code("indexer_unavailable", 503)
