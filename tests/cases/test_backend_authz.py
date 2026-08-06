"""Authorization tests.

The suite already covers cross-user *writes* and input validation heavily. This
module covers the authorization surface instead: who may call a route at all,
who may read another user's private data, and whether the money path is
authenticated. See docs/security/backend/review-2026-08-05.md (C-2, H-1, H-2).
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
# DISABLED        feature gated off; handler must 404 while the flag is false
# DEBUG_ONLY      must not be reachable in production
PUBLIC = "PUBLIC"
ENVELOPE = "ENVELOPE"
SIGNED_READ = "SIGNED_READ"
SIGNED_IDENTITY = "SIGNED_IDENTITY"
SIGNED_ADMIN = "SIGNED_ADMIN"
DISABLED = "DISABLED"
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
    # --- Deliberately public (H-2 reclassification) -------------------------
    # Chain-derived / indexer-backed reads: anyone with a public node can
    # recompute the same data, so gating the convenience endpoint is theater.
    "/api/bootstrap": PUBLIC,  # cold-start; invite_codes section omitted when feature off
    "/api/get_blocked_users": PUBLIC,  # indexer DB (chain-derived)
    "/api/get_inbox": PUBLIC,  # reply content is on chain
    "/api/get_preferences": PUBLIC,  # indexer DB (chain-derived)
    "/api/get_user_blocked": PUBLIC,  # indexer DB (chain-derived)
    "/api/referrals/precheck": PUBLIC,  # pre-signup; takes username, no identity yet
    # Backend-owned but not credentials and not actions. Deliberate disclosure.
    "/api/referrals/summary": PUBLIC,
    "/api/rewards/achievements": PUBLIC,
    "/api/rewards/summary": PUBLIC,
    # --- Invite codes (feature-gated) ---------------------------------------
    # REGISTRATION_INVITE_CODE_REQUIRED=false fleet-wide: both 404. When the
    # flag is true, get_invite_codes requires SIGNED_READ (bearer credentials);
    # validate_invite_code stays callable for pre-signup visitors (no owner
    # disclosure). Classified DISABLED so the parity test does not require
    # live auth markers while the feature is off.
    "/api/get_invite_codes": DISABLED,
    "/api/validate_invite_code": DISABLED,
    # --- Authenticated writes / identity-bound state ------------------------
    "/api/rewards/claim": SIGNED_IDENTITY,  # multiplier applied at claim time
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
    "/api/get_reports": SIGNED_ADMIN,  # signed read + level; no nonce row
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
# Values may be a single marker string or a set (for shared helpers that
# encapsulate multiple checks and live in another module, so the transitive
# same-file walk cannot see into them).
_AUTH_CALLS = {
    "_verify_signature": "sig",
    "_guard_push_request": "guard",
    "_verify_admin_stats_request": "admin",
    "get_user_level": "level",
    "_parse_envelope_nonce": "nonce",
    "verify_envelope": "envelope",
    # Cross-module helpers in routes.core — markers declared here because the
    # inventory walk only resolves callees defined in the same route file.
    "_require_signed_request": {"sig", "guard"},
    "_require_signed_read": {"sig"},
}

# What each class requires of the detected marker set.
_REQUIRED: Dict[str, Set[str]] = {
    PUBLIC: set(),
    DISABLED: set(),
    DEBUG_ONLY: set(),
    ENVELOPE: {"nonce"},
    SIGNED_READ: {"sig"},
    SIGNED_IDENTITY: {"sig", "guard"},
    # get_reports is a signed read (no guard); write admins also carry guard via
    # _require_signed_request. level is required of all.
    SIGNED_ADMIN: {"sig", "level"},
}

_ROUTE_FILES = ("public.py", "core.py", "quests.py")


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

    /api/rewards/claim takes `owner` from the request body. After the grace
    period it requires a signature; during LEGACY_UNSIGNED_UNTIL an unsigned
    claim is still served (logged). Concurrent claims must not double-pay.
    """
    from datetime import datetime, timezone

    from cosmpy.aerial.wallet import LocalWallet
    from cosmpy.crypto.keypairs import PrivateKey
    from shared.client import sign_canonical

    # Read LEGACY_UNSIGNED_UNTIL from settings.py so the live probe stays in
    # sync with the backend default without importing web/backend (wrong cwd).
    settings_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
        "settings.py",
    )
    settings_src = open(settings_path, encoding="utf-8").read()
    m = re.search(
        r'LEGACY_UNSIGNED_UNTIL\s*=\s*os\.environ\.get\(\s*"LEGACY_UNSIGNED_UNTIL"\s*,\s*"([^"]+)"\s*\)',
        settings_src,
    )
    if not m:
        _fail("reward_claim.grace_period_wired", "LEGACY_UNSIGNED_UNTIL default not found in settings.py")
        return
    grace_until = os.environ.get("LEGACY_UNSIGNED_UNTIL", m.group(1)).strip() or m.group(1)
    cutoff = datetime.strptime(grace_until, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    in_grace = datetime.now(tz=timezone.utc) < cutoff

    victim_wallet = LocalWallet(PrivateKey(), prefix="mirage")
    victim = str(victim_wallet.address()).lower()
    other_wallet = LocalWallet(PrivateKey(), prefix="mirage")

    def _sign_claim(wallet: LocalWallet, owner: str) -> dict:
        ts = _now_ms()
        nonce = _fresh_nonce()
        payload = f"rewards_claim:{owner.lower()}:{ts}:{nonce}"
        sig = sign_canonical(wallet, payload.encode("utf-8"))
        return {
            "pubkey": _b64(wallet.public_key().public_key_bytes),
            "signature": _b64(sig),
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "owner": owner,
        }

    # 1. Cross-address signature must be refused (always, grace period or not).
    forged = _sign_claim(other_wallet, victim)
    code, resp = _post(f"{backend}/api/rewards/claim", forged)
    if code in _UNAUTHENTICATED:
        _pass("reward_claim.cross_address_rejected", code=code)
    elif code == 503:
        _skip("reward_claim.cross_address_rejected", f"rewards not configured: {resp}")
    else:
        _fail(
            "reward_claim.cross_address_rejected",
            f"C-2: claim signed by a different address was processed (code={code}). resp={resp}",
        )

    # 1b. A correctly signed claim must clear the auth gate (even if there is
    #     nothing to pay — that returns success=false / no_rewards at 200).
    signed = _sign_claim(victim_wallet, victim)
    code, resp = _post(f"{backend}/api/rewards/claim", signed)
    if code == 200:
        _pass("reward_claim.signed_accepted", code=code, success=(resp or {}).get("success"))
    elif code == 503:
        # Pool not configured / payout path unavailable — auth still passed.
        _pass("reward_claim.signed_accepted", code=code, note="rewards unavailable after auth")
    elif code in _UNAUTHENTICATED:
        _fail(
            "reward_claim.signed_accepted",
            f"correctly signed claim was rejected as unauthenticated (code={code}). resp={resp}",
        )
    else:
        _fail("reward_claim.signed_accepted", f"unexpected code={code}: {resp}")

    # 2. Unsigned claim: behaviour depends on the grace-period date.
    code, resp = _post(f"{backend}/api/rewards/claim", {"owner": victim})
    if in_grace:
        if code in _UNAUTHENTICATED:
            _fail(
                "reward_claim.unsigned_during_grace",
                f"LEGACY_UNSIGNED_UNTIL={grace_until} but unsigned got {code}: {resp}",
            )
        elif code in (200, 503):
            _pass("reward_claim.unsigned_during_grace", code=code, until=grace_until)
        else:
            _fail("reward_claim.unsigned_during_grace", f"unexpected code={code}: {resp}")
    else:
        if code in _UNAUTHENTICATED:
            _pass("reward_claim.unsigned_after_grace", code=code, until=grace_until)
        elif code == 503:
            _skip("reward_claim.unsigned_after_grace", f"rewards not configured: {resp}")
        else:
            _fail(
                "reward_claim.unsigned_after_grace",
                f"C-2: unsigned claim after grace period was processed (code={code}). resp={resp}",
            )

    # 3. Source guard: the claim handler must reference the self-expiring window.
    quests_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
        "routes",
        "quests.py",
    )
    quests_src = open(quests_path, encoding="utf-8").read()
    if "legacy_unsigned_claim_allowed" in quests_src and "authz.legacy_unsigned" in quests_src:
        _pass("reward_claim.grace_period_wired")
    else:
        _fail(
            "reward_claim.grace_period_wired",
            "claim handler missing legacy_unsigned_claim_allowed / authz.legacy_unsigned logging",
        )

    # 4. Double-pay race under the advisory lock. Concurrent claims stay
    #    unsigned so the race is measured independently of the signing gate.
    if not in_grace:
        _skip("reward_claim.no_double_pay", "grace period closed; concurrent unsigned probe not applicable")
        return

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
            f"pending rows; the claim must be taken atomically under a per-owner advisory lock. "
            f"tx_hashes={[b.get('tx_hash') for _c, b in paid]}",
        )


# Reads that were overstated as H-2 private. Kept here as a documentation
# assertion: they must remain PUBLIC (or DISABLED) so a future change that
# re-gates them as SIGNED_IDENTITY without a real secret to protect fails the
# parity test's intent rather than silently "fixing" a theater gate.
_PUBLIC_BY_DESIGN = (
    ("get_inbox", "/api/get_inbox", "address"),
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
    """H-2 reclassification: chain-derived / deliberate-disclosure reads stay public.

    Invite-code endpoints are DISABLED (404) while the feature flag is false.
    """
    victim = str(_generate_wallet().address())

    for name, path, key in _PUBLIC_BY_DESIGN:
        # referrals/precheck takes a username, not an address — use a dummy.
        params = {"username": "nobody"} if name == "referrals_precheck" else {key: victim}
        code, resp = _get(f"{backend}{path}", params=params)
        if code == 200:
            _pass(f"cross_user_read.{name}_public", code=code)
        elif code == 503:
            _skip(f"cross_user_read.{name}_public", f"unavailable: {resp}")
        else:
            _fail(
                f"cross_user_read.{name}_public",
                f"expected public read (200), got {code}: {resp}",
            )

    # Invite codes: feature off → 404 (not a private-data leak, not served).
    code, resp = _get(f"{backend}/api/get_invite_codes", params={"address": victim})
    if code == 404:
        _pass("cross_user_read.get_invite_codes_disabled", code=code)
    else:
        _fail(
            "cross_user_read.get_invite_codes_disabled",
            f"invite codes must 404 while REGISTRATION_INVITE_CODE_REQUIRED=false; got {code}: {resp}",
        )

    code, resp = _post(f"{backend}/api/validate_invite_code", {"code": "ABCD-EFGH"})
    if code == 404:
        _pass("cross_user_read.validate_invite_code_disabled", code=code)
    else:
        _fail(
            "cross_user_read.validate_invite_code_disabled",
            f"validate_invite_code must 404 while feature off; got {code}: {resp}",
        )
