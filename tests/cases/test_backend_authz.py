"""Authorization tests.

The suite already covers cross-user *writes* and input validation heavily. This
module covers the authorization surface instead: who may call a route at all,
who may read another user's private data, and whether the money path is
authenticated. See docs/security/backend/review-2026-08-05.md (C-2, H-1, H-2).
"""

from __future__ import annotations

import ast
import os
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
)

# Authorization classes.
#
# PUBLIC          no identity required; the data is public either way
# ENVELOPE        relay endpoint - the chain verifies the signed envelope, the
#                 backend only forwards (see H-3: the backend is not the
#                 enforcement boundary for chain writes)
# SIGNED_IDENTITY the backend itself must verify a signature binding the caller
#                 to the address whose private data it serves or mutates
# SIGNED_ADMIN    signature plus an admin level check
# DEBUG_ONLY      must not be reachable in production
PUBLIC = "PUBLIC"
ENVELOPE = "ENVELOPE"
SIGNED_IDENTITY = "SIGNED_IDENTITY"
SIGNED_ADMIN = "SIGNED_ADMIN"
DEBUG_ONLY = "DEBUG_ONLY"

# Intended policy for every registered route. A new route must be added here
# deliberately, which is the point: this table is the control that makes an
# unauthenticated route a test failure rather than a review finding.
ROUTE_POLICY: Dict[str, str] = {
    # --- Public chain / node data -------------------------------------------
    "/api/get_address_from_username": PUBLIC,
    "/api/get_agents": PUBLIC,
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
    "/api/get_topics": PUBLIC,
    "/api/get_total_supply": PUBLIC,
    "/api/get_tx_status": PUBLIC,
    "/api/get_user_followed": PUBLIC,
    "/api/get_user_posts": PUBLIC,
    "/api/get_user_status": PUBLIC,
    "/api/get_username_from_address": PUBLIC,
    "/api/get_users": PUBLIC,
    "/api/get_welcome_stats": PUBLIC,
    "/api/search": PUBLIC,
    "/api/search_topics": PUBLIC,
    "/api/search_username": PUBLIC,
    "/api/stats/visitor_attribution": PUBLIC,
    "/api/stream_proxy/<video_uid>": PUBLIC,
    "/api/stream_proxy/<video_uid>/<path:path>": PUBLIC,
    "/api/upload_media": PUBLIC,
    "/api/validate_invite_code": PUBLIC,
    # --- User-private reads (H-2) -------------------------------------------
    "/api/bootstrap": SIGNED_IDENTITY,
    "/api/get_blocked_users": SIGNED_IDENTITY,
    "/api/get_inbox": SIGNED_IDENTITY,
    "/api/get_invite_codes": SIGNED_IDENTITY,
    "/api/get_preferences": SIGNED_IDENTITY,
    "/api/get_user_blocked": SIGNED_IDENTITY,
    "/api/referrals/precheck": SIGNED_IDENTITY,
    "/api/referrals/summary": SIGNED_IDENTITY,
    # --- User-private state and the money path (C-2) ------------------------
    "/api/rewards/achievements": SIGNED_IDENTITY,
    "/api/rewards/claim": SIGNED_IDENTITY,
    "/api/rewards/summary": SIGNED_IDENTITY,
    "/api/mark_inbox_viewed": SIGNED_IDENTITY,
    "/api/seen_posts": SIGNED_IDENTITY,
    "/api/referrals/precheck_opt_in": SIGNED_IDENTITY,
    "/api/core/register_push_token": SIGNED_IDENTITY,
    "/api/core/unregister_push_token": SIGNED_IDENTITY,
    # --- Admin (H-1) --------------------------------------------------------
    "/api/admin/rewards/suspend": SIGNED_ADMIN,
    "/api/admin/rewards/unsuspend": SIGNED_ADMIN,
    "/api/admin/stats/aggregate": SIGNED_ADMIN,
    "/api/admin/stats/export": SIGNED_ADMIN,
    "/api/core/resolve_report": SIGNED_ADMIN,
    "/api/get_reports": SIGNED_ADMIN,
    "/api/get_stats": SIGNED_ADMIN,
    # --- Debug (M-1) --------------------------------------------------------
    "/api/rewards/debug": DEBUG_ONLY,
    "/api/rewards/debug/complete": DEBUG_ONLY,
    "/api/rewards/debug/reset": DEBUG_ONLY,
    "/api/rewards/debug/set_completed": DEBUG_ONLY,
    # --- Relay endpoints: chain verifies the envelope -----------------------
    "/api/core/annotate": ENVELOPE,
    "/api/core/award": ENVELOPE,
    "/api/core/block_post": ENVELOPE,
    "/api/core/block_topic": ENVELOPE,
    "/api/core/block_user": ENVELOPE,
    "/api/core/delete_post": ENVELOPE,
    "/api/core/delete_user": ENVELOPE,
    "/api/core/disable_agent": ENVELOPE,
    "/api/core/edit": ENVELOPE,
    "/api/core/enable_agent": ENVELOPE,
    "/api/core/follow_topic": ENVELOPE,
    "/api/core/follow_user": ENVELOPE,
    "/api/core/post": ENVELOPE,
    "/api/core/report": ENVELOPE,
    "/api/core/send_tokens": ENVELOPE,
    "/api/core/set_agents": ENVELOPE,
    "/api/core/set_auto_renewal": ENVELOPE,
    "/api/core/set_biography": ENVELOPE,
    "/api/core/set_username": ENVELOPE,
    "/api/core/subscribe": ENVELOPE,
    "/api/core/unblock_post": ENVELOPE,
    "/api/core/unblock_topic": ENVELOPE,
    "/api/core/unblock_user": ENVELOPE,
    "/api/core/unfollow_topic": ENVELOPE,
    "/api/core/unfollow_user": ENVELOPE,
    "/api/core/vote": ENVELOPE,
}

# Markers the static scan looks for, mapped to the capability they prove.
_AUTH_CALLS = {
    "_verify_signature": "sig",
    "_guard_push_request": "guard",
    "_verify_admin_stats_request": "admin",
    "get_user_level": "level",
    "_parse_envelope_nonce": "nonce",
    "verify_envelope": "envelope",
}

# What each class requires of the detected marker set.
_REQUIRED: Dict[str, Set[str]] = {
    PUBLIC: set(),
    DEBUG_ONLY: set(),
    ENVELOPE: {"nonce"},
    SIGNED_IDENTITY: {"sig", "guard"},
    SIGNED_ADMIN: {"sig", "level"},
}

_ROUTE_FILES = ("public.py", "core.py", "quests.py")


def _markers_of(fn: ast.FunctionDef) -> Set[str]:
    out = set()
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Call):
            name = getattr(sub.func, "id", None) or getattr(sub.func, "attr", None)
            if name in _AUTH_CALLS:
                out.add(_AUTH_CALLS[name])
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
    """The four endpoints that derive authority from a client-supplied string."""
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
        (
            "rewards_suspend",
            lambda: _post(
                f"{backend}/api/admin/rewards/suspend",
                {"admin": victim, "target": victim, "duration_days": 1, "reason": "authz test"},
            ),
        ),
        (
            "rewards_unsuspend",
            lambda: _post(
                f"{backend}/api/admin/rewards/unsuspend",
                {"admin": victim, "target": victim},
            ),
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
    """C-2: the money path must be authenticated and must not pay twice.

    /api/rewards/claim takes `owner` from the request body with no signature,
    and the payout is broadcast before `claimed_at` is set, in a separate
    transaction, with no `WHERE claimed_at IS NULL` guard. So an unauthenticated
    caller can trigger someone's claim, and concurrent callers can be paid more
    than once for the same rows.
    """
    victim = str(_generate_wallet().address())

    # 1. Authentication. Triggering another account's claim must be refused for
    #    lack of proof, not merely produce an empty result.
    code, resp = _post(f"{backend}/api/rewards/claim", {"owner": victim})
    if code in _UNAUTHENTICATED:
        _pass("reward_claim.requires_signature", code=code)
    elif code == 503:
        _skip("reward_claim.requires_signature", f"rewards not configured on this node: {resp}")
    else:
        _fail(
            "reward_claim.requires_signature",
            f"C-2: an unsigned claim for a third party was processed (code={code}); the endpoint "
            f"must require a signature binding the caller to `owner`. resp={resp}",
        )

    # 2. Double-pay race. Needs a real pending reward, which the debug endpoint
    #    can create when it is reachable.
    code, summary = _get(f"{backend}/api/rewards/summary", params={"owner": victim})
    if code != 200 or not isinstance(summary, dict):
        _skip("reward_claim.no_double_pay", f"rewards summary unavailable: code={code}")
        return
    if summary.get("disabled"):
        _skip("reward_claim.no_double_pay", "quests disabled on this node")
        return

    quests = summary.get("daily_quests") or []
    if not quests:
        _skip("reward_claim.no_double_pay", "no daily quests to complete")
        return

    quest_id = quests[0].get("quest_id")
    code, resp = _post(f"{backend}/api/rewards/debug/complete", {"owner": victim, "quest_id": quest_id})
    if code != 200:
        _skip("reward_claim.no_double_pay", f"cannot seed a pending reward (debug complete -> {code})")
        return

    code, summary = _get(f"{backend}/api/rewards/summary", params={"owner": victim})
    pending = (summary or {}).get("pending_rewards") or []
    if not pending:
        _skip("reward_claim.no_double_pay", "no pending reward materialized")
        return
    _debug(f"reward_claim: seeded {len(pending)} pending reward(s) for {victim}")

    # Fire concurrent claims for the same rows. These go through requests
    # directly rather than _post: _post retries on 5xx, and a retried claim
    # would be a second claim, which is the very thing being measured.
    def claim(_i):
        r = requests.post(f"{backend}/api/rewards/claim", json={"owner": victim}, timeout=30)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(claim, range(4)))

    paid = [
        (code, body)
        for code, body in results
        if code == 200 and isinstance(body, dict) and body.get("success") is True and body.get("rewards")
    ]
    if len(paid) <= 1:
        _pass("reward_claim.no_double_pay", paid=len(paid), attempts=len(results))
    else:
        _fail(
            "reward_claim.no_double_pay",
            f"C-2: {len(paid)} of {len(results)} concurrent claims were each paid for the same "
            f"pending rows; the claim must be taken atomically "
            f"(UPDATE ... WHERE claimed_at IS NULL RETURNING) before any payout. "
            f"tx_hashes={[b.get('tx_hash') for _c, b in paid]}",
        )


# User-private reads, and the request key each one uses for identity. The suite
# already covers cross-user *writes* thoroughly; these are the reads.
_PRIVATE_READS = (
    ("get_inbox", "/api/get_inbox", "address"),
    ("get_invite_codes", "/api/get_invite_codes", "address"),
    ("get_preferences", "/api/get_preferences", "address"),
    ("get_blocked_users", "/api/get_blocked_users", "address"),
    ("get_user_blocked", "/api/get_user_blocked", "address"),
    ("referrals_summary", "/api/referrals/summary", "address"),
    ("referrals_precheck", "/api/referrals/precheck", "address"),
    ("rewards_summary", "/api/rewards/summary", "owner"),
    ("rewards_achievements", "/api/rewards/achievements", "owner"),
    ("bootstrap", "/api/bootstrap", "address"),
)


def test_cross_user_reads(backend):
    """H-2: an address in the query string is not proof of identity.

    Each of these endpoints serves data that belongs to one user - inbox,
    invite codes, preferences, block lists, referral earnings, reward balances -
    keyed on an `address` (or `owner`) parameter that anyone can set to anyone
    else's address. The read is the attack: no write is needed to harvest it.

    The test asserts the endpoint refuses a request carrying only an address. It
    does not assert on the body, because a fix might legitimately return an
    empty document rather than an error; what it must not do is serve the
    named user's private data to an unauthenticated caller.
    """
    victim = str(_generate_wallet().address())

    for name, path, key in _PRIVATE_READS:
        code, resp = _get(f"{backend}{path}", params={key: victim})
        if code in _UNAUTHENTICATED:
            _pass(f"cross_user_read.{name}_requires_signature", code=code)
        elif code == 200:
            _fail(
                f"cross_user_read.{name}_requires_signature",
                f"H-2: served {path} for an arbitrary {key} with no signature; a caller can read "
                f"any user's private data by naming them. keys={sorted(resp)[:8] if isinstance(resp, dict) else type(resp).__name__}",
            )
        else:
            _fail(
                f"cross_user_read.{name}_requires_signature",
                f"expected 400/401 for an unsigned read, got {code}: {resp}",
            )
