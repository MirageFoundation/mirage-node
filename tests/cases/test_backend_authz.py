"""Authorization tests.

The suite already covers cross-user *writes* and input validation heavily. This
module covers the authorization surface instead: who may call a route at all,
who may read another user's private data, and whether the money path is
authenticated. See docs/security/2026-08-05/backend-review.md (C-2, H-1, H-2).
"""

from __future__ import annotations

import ast
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Set, Tuple

import requests

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _get,
    _post,
    _generate_wallet,
    _b64,
    _fresh_nonce,
    _now_ms,
)

# Authorization classes.
#
# PUBLIC          no identity required; the data is public either way
# ENVELOPE        relay endpoint - the chain verifies the signed envelope, the
#                 backend only forwards (see H-3: the backend is not the
#                 enforcement boundary for chain writes)
# SIGNED_READ     signature binding the caller to the address; no nonce row
#                 (must not land _guard_push_request on a read path)
# SIGNED_IDENTITY signature plus the push-nonce replay guard (writes)
# SIGNED_ADMIN    signature plus an admin level check
PUBLIC = "PUBLIC"
ENVELOPE = "ENVELOPE"
SIGNED_READ = "SIGNED_READ"
SIGNED_IDENTITY = "SIGNED_IDENTITY"
SIGNED_ADMIN = "SIGNED_ADMIN"

# Intended policy for every registered route. A new route must be added here
# deliberately, which is the point: this table is the control that makes an
# unauthenticated route a test failure rather than a review finding.
ROUTE_POLICY: Dict[str, str] = {
    # --- Public chain / node data -------------------------------------------
    "/api/get_address_from_username": PUBLIC,
    "/api/get_chain_config": PUBLIC,
    "/api/get_circulating_supply": PUBLIC,
    "/api/get_circulation_stats": PUBLIC,
    "/api/get_comment_context": PUBLIC,
    "/api/get_comments": PUBLIC,
    "/api/get_network_stats": PUBLIC,
    "/api/get_node_config": PUBLIC,
    "/api/get_parameters": PUBLIC,
    "/api/get_peers": PUBLIC,
    "/api/get_posts": PUBLIC,
    "/api/get_profile": PUBLIC,
    "/api/get_recent_content": PUBLIC,
    "/api/get_root_post_id": PUBLIC,
    "/api/get_similar_users": PUBLIC,
    "/api/get_supply_history": PUBLIC,
    "/api/get_total_supply": PUBLIC,
    "/api/get_tx_status": PUBLIC,
    "/api/get_user_followed": PUBLIC,
    "/api/get_user_posts": PUBLIC,
    "/api/get_user_status": PUBLIC,
    "/api/get_username_from_address": PUBLIC,
    "/api/get_users": PUBLIC,
    "/api/get_welcome_stats": PUBLIC,
    "/api/search": PUBLIC,
    "/api/search_username": PUBLIC,
    "/api/stats/visitor_attribution": PUBLIC,
    "/api/stream_proxy/<video_uid>": PUBLIC,
    "/api/stream_proxy/<video_uid>/<path:path>": PUBLIC,
    "/api/upload_media": PUBLIC,
    # --- Deliberately public (H-2 reclassification) -------------------------
    # Chain-derived / indexer-backed reads: anyone with a public node can
    # recompute the same data, so gating the convenience endpoint is theater.
    "/api/bootstrap": PUBLIC,  # cold-start; invite_codes section omitted when feature off
    "/api/get_blocked_users": PUBLIC,  # indexer DB (chain-derived)
    "/api/get_inbox": PUBLIC,  # reply content is on chain
    "/api/get_preferences": PUBLIC,  # indexer DB (chain-derived)
    "/api/get_user_blocked": PUBLIC,  # indexer DB (chain-derived)
    # --- Authenticated writes / identity-bound state ------------------------
    "/api/mark_inbox_viewed": SIGNED_IDENTITY,
    "/api/seen_posts": SIGNED_IDENTITY,
    "/api/core/register_push_token": SIGNED_IDENTITY,
    "/api/core/unregister_push_token": SIGNED_IDENTITY,
    # --- Admin (H-1) --------------------------------------------------------
    "/api/admin/stats/aggregate": SIGNED_ADMIN,
    "/api/admin/stats/export": SIGNED_ADMIN,
    "/api/core/resolve_report": SIGNED_ADMIN,
    "/api/get_reports": SIGNED_ADMIN,  # signed read + level; no nonce row
    "/api/get_stats": SIGNED_ADMIN,
    # --- Relay endpoints: chain verifies the envelope -----------------------
    "/api/core/annotate": ENVELOPE,
    "/api/core/award": ENVELOPE,
    "/api/core/block_post": ENVELOPE,
    "/api/core/block_user": ENVELOPE,
    "/api/core/delete_post": ENVELOPE,
    "/api/core/delete_user": ENVELOPE,
    "/api/core/edit": ENVELOPE,
    "/api/core/follow_user": ENVELOPE,
    "/api/core/join_community": ENVELOPE,
    "/api/core/leave_community": ENVELOPE,
    "/api/core/block_community": ENVELOPE,
    "/api/core/unblock_community": ENVELOPE,
    "/api/core/create_curation_team": ENVELOPE,
    "/api/core/set_curation_preference": ENVELOPE,
    "/api/core/set_curation_team_profile": ENVELOPE,
    "/api/core/invite_curator": ENVELOPE,
    "/api/core/revoke_curator_invite": ENVELOPE,
    "/api/core/accept_curator_invite": ENVELOPE,
    "/api/core/decline_curator_invite": ENVELOPE,
    "/api/core/leave_curation_team": ENVELOPE,
    "/api/core/remove_curator": ENVELOPE,
    "/api/core/transfer_curation_team": ENVELOPE,
    "/api/core/delete_curation_team": ENVELOPE,
    "/api/core/set_curation_post_hidden": ENVELOPE,
    "/api/core/set_curation_user_hidden": ENVELOPE,
    "/api/core/set_curation_thread_locked": ENVELOPE,
    "/api/core/set_curation_subscriber_only": ENVELOPE,
    "/api/core/claim_creator_rewards": ENVELOPE,
    "/api/communities": PUBLIC,
    "/api/communities/<slug>": PUBLIC,
    "/api/communities/<slug>/teams": PUBLIC,
    # Team rosters and pending curator invitations are chain state: anyone can
    # read the same rows off a public node with Query/CurationTeamMembers and
    # Query/PendingCuratorInvitations, so gating the convenience route is theater.
    "/api/communities/<slug>/teams/<int:team_id>": PUBLIC,
    "/api/communities/<slug>/teams/<int:team_id>/invitations": PUBLIC,
    "/api/communities/<slug>/teams/<int:team_id>/moderation": PUBLIC,
    "/api/communities/<slug>/teams/<int:team_id>/hidden-users": PUBLIC,
    "/api/creator/earnings": PUBLIC,
    "/api/core/post": ENVELOPE,
    "/api/core/report": ENVELOPE,
    "/api/core/send_tokens": ENVELOPE,
    "/api/core/set_auto_renewal": ENVELOPE,
    "/api/core/set_biography": ENVELOPE,
    "/api/core/set_username": ENVELOPE,
    "/api/core/subscribe": ENVELOPE,
    "/api/core/unblock_post": ENVELOPE,
    "/api/core/unblock_user": ENVELOPE,
    "/api/core/unfollow_user": ENVELOPE,
    "/api/core/vote": ENVELOPE,
    # --- Retired in v1.39.0: 410 on every method ----------------------------
}

# Markers the static scan looks for, mapped to the capability they prove.
# Values may be a single marker string or a set (for shared helpers that
# encapsulate multiple checks and live in another module, so the transitive
# same-file walk cannot see into them).
_AUTH_CALLS = {
    "_verify_signature": "sig",
    "_guard_push_request": "guard",
    "_verify_admin_stats_request": "admin",
    "get_user_level": "level",
    "_parse_envelope_nonce": "nonce",
    "_parse_relay_envelope": "nonce",
    "verify_envelope": "envelope",
    # Cross-module helpers in routes.core — markers declared here because the
    # inventory walk only resolves callees defined in the same route file.
    "_require_signed_request": {"sig", "guard"},
    "_require_signed_read": {"sig"},
}

# What each class requires of the detected marker set.
_REQUIRED: Dict[str, Set[str]] = {
    PUBLIC: set(),
    ENVELOPE: {"nonce"},
    SIGNED_READ: {"sig"},
    SIGNED_IDENTITY: {"sig", "guard"},
    # get_reports is a signed read (no guard); write admins also carry guard via
    # _require_signed_request. level is required of all.
    SIGNED_ADMIN: {"sig", "level"},
}

_ROUTE_FILES = ("public.py", "core.py", "communities.py")


def _markers_of(fn: ast.FunctionDef) -> Set[str]:
    out = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            name = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
            if name in _AUTH_CALLS:
                marker = _AUTH_CALLS[name]
                if isinstance(marker, str):
                    out.add(marker)
                else:
                    out |= set(marker)
    return out


def _called_names(fn: ast.FunctionDef) -> Set[str]:
    out = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            name = getattr(sub.func, "id", None)
            if name:
                out.add(name)
    return out


def _route_inventory(backend_src: str) -> Dict[str, Tuple[str, Set[str]]]:
    """Map route path -> (handler, auth markers), resolving helper indirection.

    Several routes authenticate through a module-level helper (seen_posts via
    _verify_seen_signature, the admin stats routes via
    _verify_admin_stats_request), so markers are unioned transitively.
    """
    inventory: Dict[str, Tuple[str, Set[str]]] = {}
    for fname in _ROUTE_FILES:
        path = os.path.join(backend_src, "routes", fname)
        tree = ast.parse(open(path, encoding="utf-8").read())
        funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        direct = {name: _markers_of(fn) for name, fn in funcs.items()}
        calls = {name: _called_names(fn) for name, fn in funcs.items()}

        def resolve(name: str, depth: int = 3) -> Set[str]:
            out = set(direct.get(name, set()))
            if depth <= 0:
                return out
            for callee in calls.get(name, set()):
                if callee in funcs and callee != name:
                    out |= resolve(callee, depth - 1)
            return out

        for name, fn in funcs.items():
            for dec in fn.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                    continue
                if dec.func.attr != "route" or not dec.args:
                    continue
                if not isinstance(dec.args[0], ast.Constant):
                    continue
                inventory[dec.args[0].value] = (f"{fname}:{name}", resolve(name))
        # v1.39 registers many curation relay routes via _curation_team_route("path", ...),
        # which the decorator walk cannot see (path is a Name, not a Constant).
        for node in tree.body:
            if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                continue
            call = node.value
            if not isinstance(call.func, ast.Name) or call.func.id != "_curation_team_route":
                continue
            if not call.args or not isinstance(call.args[0], ast.Constant):
                continue
            path_value = call.args[0].value
            if not isinstance(path_value, str):
                continue
            handler_markers = set()
            if "_curation_team_route" in funcs:
                handler_markers = resolve("_curation_team_route")
            # Nested handler always parses a relay envelope.
            handler_markers |= {"nonce"}
            inventory[path_value] = (f"{fname}:_curation_team_route", handler_markers)
    return inventory


def test_route_authz_parity(backend):
    """Every route is classified, and its code satisfies its class.

    This is the structural control for H-1 and H-2: an unauthenticated route is
    a test failure rather than something a reviewer has to notice.
    """
    backend_src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
    )
    if not os.path.isdir(os.path.join(backend_src, "routes")):
        _skip("route_authz.inventory", "backend routes source not present")
        return

    inventory = _route_inventory(backend_src)

    # 1. Inventory parity. Any route added or removed without updating the
    #    policy table fails here, which is the drift guard.
    registered = set(inventory)
    declared = set(ROUTE_POLICY)
    undeclared = sorted(registered - declared)
    stale = sorted(declared - registered)
    if undeclared or stale:
        parts = []
        if undeclared:
            parts.append(f"{len(undeclared)} route(s) not in ROUTE_POLICY: {', '.join(undeclared[:5])}")
        if stale:
            parts.append(f"{len(stale)} stale entr(y/ies): {', '.join(stale[:5])}")
        _fail("route_authz.inventory", "; ".join(parts))
    else:
        _pass("route_authz.inventory", routes=len(registered))

    # 2. Policy compliance. A route classified SIGNED_IDENTITY or SIGNED_ADMIN
    #    must actually verify a signature.
    violations = []
    for path in sorted(registered & declared):
        handler, markers = inventory[path]
        want = _REQUIRED[ROUTE_POLICY[path]]
        missing = want - markers
        if missing:
            violations.append(f"{path} [{ROUTE_POLICY[path]}] {handler} missing={','.join(sorted(missing))}")

    if violations:
        _fail(
            "route_authz.policy",
            f"{len(violations)} route(s) below their declared class: " + " | ".join(violations[:8]),
        )
    else:
        _pass("route_authz.policy", checked=len(registered & declared))


# Statuses that mean "we refused because you did not prove who you are".
# A 403 is NOT in this set on purpose: 403 means the endpoint accepted the
# client-supplied address as the caller's identity and merely found the level
# too low, which is exactly the H-1 defect.
_UNAUTHENTICATED = (400, 401)


def _admin_probe(backend: str):
    """The endpoints that derive authority from a client-supplied string.

    The reward suspend/unsuspend probes were dropped with the reward endpoints
    themselves in v1.39.0; they now answer 410 and have no authority to leak.
    """
    victim = str(_generate_wallet().address())
    return [
        (
            "get_reports",
            lambda: _get(f"{backend}/api/get_reports", params={"address": victim, "limit": 1}),
        ),
        (
            "resolve_report",
            lambda: _post(f"{backend}/api/core/resolve_report", {"address": victim, "id": 1}),
        ),
    ]


def test_admin_authz(backend):
    """H-1: an admin endpoint must not take the caller's identity on trust.

    Each of these four endpoints reads an address out of the request, looks that
    address's level up in the database, and acts if the level is >= 100. Nothing
    ties the request to the key that owns the address, so knowing an admin's
    public mirage1 address is enough to act as that admin.

    The discriminator is the status code. A signature-verifying endpoint answers
    an unsigned request with 400/401 (no proof of identity). Answering 403
    proves the address was accepted as the caller and only the level check
    stopped it, which is the vulnerability.
    """
    for name, call in _admin_probe(backend):
        code, resp = call()
        if code in _UNAUTHENTICATED:
            _pass(f"admin_authz.{name}_requires_signature", code=code)
        elif code == 403:
            _fail(
                f"admin_authz.{name}_requires_signature",
                f"H-1: got 403, so the client-supplied address was accepted as the caller's "
                f"identity and only the level check refused it; an unsigned request must be "
                f"rejected as unauthenticated. resp={resp}",
            )
        elif code == 200:
            _fail(
                f"admin_authz.{name}_requires_signature",
                f"H-1: unsigned request SUCCEEDED (200) - admin action performed with no proof "
                f"of identity. resp={resp}",
            )
        else:
            _fail(f"admin_authz.{name}_requires_signature", f"expected 400/401, got {code}: {resp}")


def test_reward_claim_authz(backend):
    """The whole quest/reward surface was removed in v1.39.0 and must answer 410.

    The claim endpoint moved tokens and the admin suspend/unsuspend pair moved a
    user's earning ability, so a route that quietly came back — or a proxy that
    answered for it — is worth catching. The reads are here too: they are what a
    stale client polls, and a 200 from any of them means the retired quest tables
    are being served from somewhere.
    """
    for name, call in (
        ("claim", lambda: _post(f"{backend}/api/rewards/claim", {"owner": "x"})),
        ("summary", lambda: _get(f"{backend}/api/rewards/summary", params={"address": "x"})),
        ("achievements", lambda: _get(f"{backend}/api/rewards/achievements", params={"address": "x"})),
        ("debug", lambda: _get(f"{backend}/api/rewards/debug", params={"address": "x"})),
        ("admin_suspend", lambda: _post(f"{backend}/api/admin/rewards/suspend", {"address": "x"})),
        ("admin_unsuspend", lambda: _post(f"{backend}/api/admin/rewards/unsuspend", {"address": "x"})),
    ):
        code, resp = call()
        if code == 410:
            _pass(f"reward_claim_authz.{name}_gone")
        else:
            _fail(f"reward_claim_authz.{name}_gone", f"expected 410, got {code}: {resp}")


# Reads that were overstated as H-2 private. Kept here as a documentation
# assertion: they must remain PUBLIC so a future change that
# re-gates them as SIGNED_IDENTITY without a real secret to protect fails the
# parity test's intent rather than silently "fixing" a theater gate.
_PUBLIC_BY_DESIGN = (
    ("get_inbox", "/api/get_inbox", "address"),
    ("get_preferences", "/api/get_preferences", "address"),
    ("get_blocked_users", "/api/get_blocked_users", "address"),
    ("get_user_blocked", "/api/get_user_blocked", "address"),
    ("bootstrap", "/api/bootstrap", "address"),
)


def test_cross_user_reads(backend):
    """H-2 reclassification: chain-derived / deliberate-disclosure reads stay public.

    Invite codes and referrals were retired in v1.39.0 and must answer 410.
    """
    victim = str(_generate_wallet().address())

    for name, path, key in _PUBLIC_BY_DESIGN:
        code, resp = _get(f"{backend}{path}", params={key: victim})
        if code == 200:
            _pass(f"cross_user_read.{name}_public", code=code)
        elif code == 503:
            _skip(f"cross_user_read.{name}_public", f"unavailable: {resp}")
        else:
            _fail(
                f"cross_user_read.{name}_public",
                f"expected public read (200), got {code}: {resp}",
            )

    # Invite codes were retired in v1.39.0.
    code, resp = _get(f"{backend}/api/get_invite_codes", params={"address": victim})
    if code == 410:
        _pass("cross_user_read.get_invite_codes_gone", code=code)
    else:
        _fail(
            "cross_user_read.get_invite_codes_gone",
            f"invite codes must 410 after v1.39.0; got {code}: {resp}",
        )

    code, resp = _post(f"{backend}/api/validate_invite_code", {"code": "ABCD-EFGH"})
    if code == 410:
        _pass("cross_user_read.validate_invite_code_gone", code=code)
    else:
        _fail(
            "cross_user_read.validate_invite_code_gone",
            f"validate_invite_code must 410 after v1.39.0; got {code}: {resp}",
        )
