from __future__ import annotations

"""Community, curation, and creator HTTP reads/writes."""

import re

from flask import Blueprint, jsonify, request

from error_utils import api_error_code
from logging_utils import log_event, next_request_id
from db import connect_db
from params import expect_params
from curation import MODE_RAW, get_default_team, resolve_lens

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


def _valid_slug(slug: str) -> bool:
    params = expect_params()
    minimum = int(params["min_topic_size"])
    maximum = int(params["max_topic_size"])
    return minimum <= len(slug) <= maximum and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", slug) is not None


def _team_summary(team: dict | None) -> dict | None:
    if team is None:
        return None
    return {
        "team_id": str(team["team_id"]),
        "name": team["name"],
        "subscriber_count": str(team["subscriber_count"]),
    }


@communities_bp.route("/api/communities")
def list_communities():
    rid = next_request_id()
    q = (request.args.get("query") or "").strip().lower()
    joined_by = (request.args.get("joined_by") or "").strip().lower()
    cursor = (request.args.get("cursor") or "").strip().lower()
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
                    SELECT LOWER(TRIM(community)) AS community
                    FROM posts
                    WHERE protocol_version=1
                      AND COALESCE(target,'')=''
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
                     AND p.protocol_version=1
                     AND COALESCE(p.target,'')=''
                     AND p.deleted=FALSE
                    WHERE (%s='' OR c.community LIKE %s)
                      AND (%s='' OR c.community>%s)
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
                ORDER BY community
                LIMIT %s
                """,
                (
                    joined_by,
                    joined_by,
                    q,
                    q + "%",
                    cursor,
                    cursor,
                    joined_by,
                    joined_by,
                    curated,
                    curated,
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
        next_cursor = items[-1]["community"] if has_more and items else None
        log_event(rid, "[community] list.ok", count=len(items), joined_by=joined_by, curated=curated)
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
                    COUNT(*) FILTER (WHERE protocol_version=1 AND deleted=FALSE),
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
            "stored_team_id": (
                str(resolved["stored_team_id"]) if resolved.get("stored_team_id") is not None else None
            ),
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


@communities_bp.route("/api/communities/<slug>/teams")
def community_teams(slug: str):
    rid = next_request_id()
    slug = (slug or "").strip().lower()
    if not _valid_slug(slug):
        return api_error_code("community_invalid", 400)
    include_deleted = str(request.args.get("include_deleted") or "").lower() == "true"
    try:
        with connect_db() as conn:
            cur = conn.cursor()
            sql = """
                SELECT t.team_id, t.owner, t.name, t.description, t.policy,
                       t.subscriber_only, t.subscriber_count, t.deleted_height,
                       COUNT(m.curator) AS member_count
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
        items = [
            {
                "team_id": str(r[0]),
                "owner": r[1],
                "name": r[2],
                "description": r[3],
                "policy": r[4],
                "subscriber_only": bool(r[5]),
                "subscriber_count": str(r[6]),
                "deleted": r[7] is not None,
                "member_count": int(r[8]),
            }
            for r in rows
        ]
        return jsonify({"items": items, "next_cursor": None, "has_more": False})
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
                SELECT owner, name, description, policy, subscriber_only,
                       subscriber_count, created_height, created_order, deleted_height
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
                "policy": row[3],
                "subscriber_only": bool(row[4]),
                "subscriber_count": str(row[5]),
                "created_height": int(row[6]),
                "created_order": str(row[7]),
                "deleted": row[8] is not None,
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
    if not viewer:
        return api_error_code("missing_viewer", 400)
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
                    SELECT invitee, inviter, status, created_height, resolved_height
                    FROM curation_team_invitations
                    WHERE community=%s AND team_id=%s
                    ORDER BY created_height DESC, invitee
                    """,
                    (slug, team_id),
                )
            else:
                cur.execute(
                    """
                    SELECT invitee, inviter, status, created_height, resolved_height
                    FROM curation_team_invitations
                    WHERE community=%s AND team_id=%s AND LOWER(invitee)=%s
                    ORDER BY created_height DESC
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
                }
                for row in cur.fetchall()
            ]
        return jsonify({"items": invitations})
    except Exception as e:
        log_event(rid, "communities.invitations.err", error=str(e))
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
