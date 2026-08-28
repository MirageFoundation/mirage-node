"""v1.39.0 curator-team chain coverage (direct DeliverTx)."""

from __future__ import annotations

from tests.common import (
    WALLETS,
    _debug,
    _fail,
    _now_ms,
    _pass,
    _rand_str,
)
from tests.blockchain_helpers import (
    DEFAULT_GAS_LIMIT,
    FILL_GAS_LIMIT,
    _build_msg_create_curation_team,
    _build_msg_join_community,
    _build_msg_set_curation_preference,
    _check_deliver_accept,
    _check_deliver_reject,
    _gen_nonce,
    _get_chain_params,
    _get_pow_params,
    _submit_tx,
)
import tests.blockchain_helpers as _bh


def test_curation_chain(backend: str) -> None:
    """Paid+joined create, free/unjoined reject, description limit, no policy field."""
    fee_payer = _bh._VALIDATOR_ADDR or ""
    free = WALLETS["free"]
    free_addr = str(free.address())
    free_pub = free.public_key().public_key_bytes
    sub = WALLETS["sub1"]
    sub_addr = str(sub.address())
    sub_pub = sub.public_key().public_key_bytes
    slug = f"c{_rand_str(8)}"

    # Free wallet: create team must reject (active subscriber required).
    lb, _, _, _ = _get_pow_params(backend, free_addr)
    ts = _now_ms()
    msg = _build_msg_create_curation_team(
        free, lb, 0, ts, slug, "FreeTeam", "should fail", pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgCreateCurationTeam")],
        FILL_GAS_LIMIT,
        fee_payer,
        free_pub,
        wait_deliver=True,
    )
    _check_deliver_reject("curation.free_create_rejected", ccode, dcode, dlog)

    # Paid but not joined: create still succeeds.
    unjoined_slug = f"c{_rand_str(8)}"
    lb, _, _, _ = _get_pow_params(backend, sub_addr)
    ts = _now_ms()
    msg = _build_msg_create_curation_team(
        sub, lb, 0, ts, unjoined_slug, "Lonely", "no join", pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgCreateCurationTeam")],
        FILL_GAS_LIMIT,
        fee_payer,
        sub_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("curation.unjoined_create_allowed", ccode, dcode, dlog)

    # Paid + joined: create succeeds. Description may include moderation guidance.
    lb, _, _, _ = _get_pow_params(backend, sub_addr)
    ts = _now_ms()
    msg = _build_msg_join_community(sub, lb, 0, ts, slug, pow_val=0, nonce=_gen_nonce())
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgJoinCommunity")],
        FILL_GAS_LIMIT,
        fee_payer,
        sub_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("curation.sub_join_community", ccode, dcode, dlog)

    team_name = f"Lens{_rand_str(4)}"
    description = "Hide spam; keep adult content; no brigading."
    lb, _, _, _ = _get_pow_params(backend, sub_addr)
    ts = _now_ms()
    msg = _build_msg_create_curation_team(
        sub, lb, 0, ts, slug, team_name, description, pow_val=0, nonce=_gen_nonce()
    )
    # MsgCreateCurationTeam must not expose a policy attribute on the wire type.
    if hasattr(msg, "policy"):
        _fail("curation.msg_has_no_policy_field", "MsgCreateCurationTeam still has policy")
    else:
        _pass("curation.msg_has_no_policy_field")

    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgCreateCurationTeam")],
        FILL_GAS_LIMIT,
        fee_payer,
        sub_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("curation.paid_joined_create_accepted", ccode, dcode, dlog)

    # Description over max_curation_team_description_length is rejected.
    params = _get_chain_params()
    max_desc = int(params.get("max_curation_team_description_length") or 0)
    if max_desc <= 0:
        _fail("curation.description_limit_param", f"max_desc={max_desc}")
    else:
        _pass("curation.description_limit_param", max_desc=max_desc)
        if "max_curation_team_policy_length" in params:
            _fail(
                "curation.policy_param_retired",
                "max_curation_team_policy_length still present",
            )
        else:
            _pass("curation.policy_param_retired")

        over = "x" * (max_desc + 1)
        over_slug = f"c{_rand_str(8)}"
        lb, _, _, _ = _get_pow_params(backend, sub_addr)
        ts = _now_ms()
        msg = _build_msg_join_community(sub, lb, 0, ts, over_slug, pow_val=0, nonce=_gen_nonce())
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgJoinCommunity")],
            FILL_GAS_LIMIT,
            fee_payer,
            sub_pub,
            wait_deliver=True,
        )
        if ccode != 0 or dcode != 0:
            # already a curator elsewhere in this slug path; use a fresh subscriber wallet path
            _debug(f"curation.oversize join unexpected reject: {dlog}")
        # Second create on a new community by same user after join
        lb, _, _, _ = _get_pow_params(backend, sub_addr)
        ts = _now_ms()
        # leave previous community not required — one team per community only
        # join new slug if not already (deliver may have failed if already joined)
        msg = _build_msg_join_community(sub, lb, 0, ts, over_slug, pow_val=0, nonce=_gen_nonce())
        _submit_tx(
            [(msg, "/mirage.core.v1.MsgJoinCommunity")],
            FILL_GAS_LIMIT,
            fee_payer,
            sub_pub,
            wait_deliver=True,
        )
        lb, _, _, _ = _get_pow_params(backend, sub_addr)
        ts = _now_ms()
        msg = _build_msg_create_curation_team(
            sub, lb, 0, ts, over_slug, "TooLong", over, pow_val=0, nonce=_gen_nonce()
        )
        _, ccode, _, dcode, dlog = _submit_tx(
            [(msg, "/mirage.core.v1.MsgCreateCurationTeam")],
            max(FILL_GAS_LIMIT, DEFAULT_GAS_LIMIT * 2),
            fee_payer,
            sub_pub,
            wait_deliver=True,
        )
        _check_deliver_reject("curation.oversize_description_rejected", ccode, dcode, dlog)

    # Preference pin still works as an explicit on-chain write (UI viewing is local).
    lb, _, _, _ = _get_pow_params(backend, sub_addr)
    ts = _now_ms()
    msg = _build_msg_set_curation_preference(
        sub, lb, 0, ts, slug, mode=1, pinned_team_id=1, pow_val=0, nonce=_gen_nonce()
    )
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, "/mirage.core.v1.MsgSetCurationPreference")],
        FILL_GAS_LIMIT,
        fee_payer,
        sub_pub,
        wait_deliver=True,
    )
    _check_deliver_accept("curation.preference_pin_accepted", ccode, dcode, dlog)
