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
    FILL_GAS_LIMIT,
    _build_msg_accept_curator_invite,
    _build_msg_create_curation_team,
    _build_msg_delete_curation_team,
    _build_msg_invite_curator,
    _build_msg_join_community,
    _build_msg_leave_curation_team,
    _build_msg_remove_curator,
    _build_msg_set_curation_post_tag,
    _build_msg_set_curation_preference,
    _build_msg_set_curation_subscriber_only,
    _build_msg_set_curation_team_profile,
    _build_msg_set_curation_thread_locked,
    _build_msg_transfer_curation_team,
    _check_deliver_accept,
    _check_deliver_reject,
    _gen_nonce,
    _get_chain_params,
    _get_pow_params,
    _submit_tx,
)
import tests.blockchain_helpers as _bh


def test_curation_chain(backend: str) -> None:
    """Create gates plus team-profile validation at exact and invalid boundaries."""
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
    msg = _build_msg_create_curation_team(sub, lb, 0, ts, slug, team_name, description, pow_val=0, nonce=_gen_nonce())
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

    # Both profile fields are governed rune limits, and policy is retired.
    params = _get_chain_params()
    max_name = int(params.get("max_curation_team_name_length") or 0)
    max_desc = int(params.get("max_curation_team_description_length") or 0)
    if max_name <= 0 or max_desc <= 0:
        _fail("curation.profile_limit_params", f"max_name={max_name} max_desc={max_desc}")
        return
    _pass("curation.profile_limit_params", max_name=max_name, max_desc=max_desc)
    if "max_curation_team_policy_length" in params:
        _fail("curation.policy_param_retired", "max_curation_team_policy_length still present")
    else:
        _pass("curation.policy_param_retired")

    invalid_profiles = (
        ("blank_name", "   ", ""),
        ("oversize_name", "n" * (max_name + 1), ""),
        ("invalid_name_characters", "Bad!", ""),
        ("blank_description", "BlankDescription", "   "),
        ("oversize_description", "LongDescription", "x" * (max_desc + 1)),
    )
    for label, invalid_name, invalid_description in invalid_profiles:
        ccode, dcode, dlog = _submit_curation(
            backend,
            sub,
            _build_msg_create_curation_team,
            "/mirage.core.v1.MsgCreateCurationTeam",
            f"c{_rand_str(8)}",
            invalid_name,
            invalid_description,
        )
        _check_deliver_reject(f"curation.{label}_rejected", ccode, dcode, dlog)

    boundary_slug = f"c{_rand_str(8)}"
    exact_name = "N" * max_name
    exact_description = "🙂" * max_desc
    ccode, dcode, dlog = _submit_curation(
        backend,
        sub,
        _build_msg_create_curation_team,
        "/mirage.core.v1.MsgCreateCurationTeam",
        boundary_slug,
        exact_name,
        exact_description,
    )
    _check_deliver_accept("curation.exact_profile_limits_accepted", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        sub,
        _build_msg_set_curation_team_profile,
        "/mirage.core.v1.MsgSetCurationTeamProfile",
        boundary_slug,
        1,
        exact_name,
        "x" * max_desc,
    )
    _check_deliver_accept("curation.exact_update_limits_accepted", ccode, dcode, dlog)

    for label, invalid_name, invalid_description in (
        ("update_invalid_name", "Bad!", ""),
        ("update_blank_description", exact_name, "   "),
        ("update_oversize_description", exact_name, "x" * (max_desc + 1)),
    ):
        ccode, dcode, dlog = _submit_curation(
            backend,
            sub,
            _build_msg_set_curation_team_profile,
            "/mirage.core.v1.MsgSetCurationTeamProfile",
            boundary_slug,
            1,
            invalid_name,
            invalid_description,
        )
        _check_deliver_reject(f"curation.{label}_rejected", ccode, dcode, dlog)

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


def _submit_curation(backend: str, wallet, builder, type_url: str, *args, **kwargs):
    """Build, sign and deliver one curation message, returning the tx codes.

    Subscribers are relay-exempt, so difficulty and pow stay zero; the point of
    these checks is the handler's authorization, not the ante.
    """
    addr = str(wallet.address())
    lb, _, _, _ = _get_pow_params(backend, addr)
    msg = builder(wallet, lb, 0, _now_ms(), *args, pow_val=0, nonce=_gen_nonce(), **kwargs)
    _, ccode, _, dcode, dlog = _submit_tx(
        [(msg, type_url)],
        FILL_GAS_LIMIT,
        _bh._VALIDATOR_ADDR or "",
        wallet.public_key().public_key_bytes,
        wait_deliver=True,
    )
    return ccode, dcode, dlog


def test_curation_team_chain(backend: str) -> None:
    """Curator roster and moderation authorization at DeliverTx.

    Every message below carries its authorization in the handler rather than the
    ante, so CheckTx accepts them all and only the delivered result says whether
    the rule holds.
    """
    owner = WALLETS["sub1"]
    curator = WALLETS["sub2"]
    outsider = WALLETS["free"]
    owner_addr = str(owner.address())
    curator_addr = str(curator.address())
    outsider_addr = str(outsider.address())
    slug = f"c{_rand_str(8)}"
    root_hash = _rand_str(8).encode().hex().ljust(64, "0")
    post_hash = "ab" * 32

    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_create_curation_team,
        "/mirage.core.v1.MsgCreateCurationTeam",
        slug,
        "RosterTeam",
        "roster rules",
    )
    _check_deliver_accept("curation_team.chain_create", ccode, dcode, dlog)
    team_id = 1

    # Invitations are owner-only, and the invitee is not a member yet.
    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_invite_curator,
        "/mirage.core.v1.MsgInviteCurator",
        slug,
        team_id,
        curator_addr,
    )
    _check_deliver_reject("curation_team.chain_invite_non_owner_rejected", ccode, dcode, dlog)

    # A free wallet cannot be a curator, so it cannot be invited either.
    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_invite_curator,
        "/mirage.core.v1.MsgInviteCurator",
        slug,
        team_id,
        outsider_addr,
    )
    _check_deliver_reject("curation_team.chain_invite_free_rejected", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_invite_curator,
        "/mirage.core.v1.MsgInviteCurator",
        slug,
        team_id,
        curator_addr,
    )
    _check_deliver_accept("curation_team.chain_invite", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_accept_curator_invite,
        "/mirage.core.v1.MsgAcceptCuratorInvite",
        slug,
        team_id,
    )
    _check_deliver_accept("curation_team.chain_accept", ccode, dcode, dlog)

    # Accepting twice must fail: the invitation is consumed.
    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_accept_curator_invite,
        "/mirage.core.v1.MsgAcceptCuratorInvite",
        slug,
        team_id,
    )
    _check_deliver_reject("curation_team.chain_accept_twice_rejected", ccode, dcode, dlog)

    # Owner-only control refused for an accepted curator.
    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_set_curation_subscriber_only,
        "/mirage.core.v1.MsgSetCurationSubscriberOnly",
        slug,
        team_id,
        True,
    )
    _check_deliver_reject("curation_team.chain_subscriber_only_non_owner_rejected", ccode, dcode, dlog)

    # Any curator may lock a thread and tag a post.
    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_set_curation_thread_locked,
        "/mirage.core.v1.MsgSetCurationThreadLocked",
        slug,
        team_id,
        root_hash,
        True,
    )
    _check_deliver_accept("curation_team.chain_curator_locks_thread", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_set_curation_post_tag,
        "/mirage.core.v1.MsgSetCurationPostTag",
        slug,
        team_id,
        post_hash,
        "gore",
        True,
    )
    _check_deliver_reject("curation_team.chain_post_tag_clear_with_tag_rejected", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_set_curation_post_tag,
        "/mirage.core.v1.MsgSetCurationPostTag",
        slug,
        team_id,
        post_hash,
        "not-a-real-tag",
        False,
    )
    _check_deliver_reject("curation_team.chain_post_tag_unknown_rejected", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_set_curation_post_tag,
        "/mirage.core.v1.MsgSetCurationPostTag",
        slug,
        team_id,
        post_hash,
        "gore",
        False,
    )
    _check_deliver_accept("curation_team.chain_curator_sets_post_tag", ccode, dcode, dlog)

    # Roster changes.
    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_remove_curator,
        "/mirage.core.v1.MsgRemoveCurator",
        slug,
        team_id,
        owner_addr,
    )
    _check_deliver_reject("curation_team.chain_remove_non_owner_rejected", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_remove_curator,
        "/mirage.core.v1.MsgRemoveCurator",
        slug,
        team_id,
        owner_addr,
    )
    _check_deliver_reject("curation_team.chain_remove_self_rejected", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_transfer_curation_team,
        "/mirage.core.v1.MsgTransferCurationTeam",
        slug,
        team_id,
        outsider_addr,
    )
    _check_deliver_reject("curation_team.chain_transfer_to_ineligible_rejected", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_transfer_curation_team,
        "/mirage.core.v1.MsgTransferCurationTeam",
        slug,
        team_id,
        curator_addr,
    )
    _check_deliver_accept("curation_team.chain_transfer", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_leave_curation_team,
        "/mirage.core.v1.MsgLeaveCurationTeam",
        slug,
        team_id,
    )
    _check_deliver_reject("curation_team.chain_owner_leave_rejected", ccode, dcode, dlog)

    # The transferred-away old owner is an ordinary curator and may leave.
    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_leave_curation_team,
        "/mirage.core.v1.MsgLeaveCurationTeam",
        slug,
        team_id,
    )
    _check_deliver_accept("curation_team.chain_curator_leaves", ccode, dcode, dlog)

    # The departed curator is still a paid subscriber, so this rejection can
    # only come from the membership check rather than the ante or eligibility.
    ccode, dcode, dlog = _submit_curation(
        backend,
        owner,
        _build_msg_set_curation_thread_locked,
        "/mirage.core.v1.MsgSetCurationThreadLocked",
        slug,
        team_id,
        root_hash,
        False,
    )
    _check_deliver_reject("curation_team.chain_departed_curator_lock_rejected", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_delete_curation_team,
        "/mirage.core.v1.MsgDeleteCurationTeam",
        slug,
        team_id,
    )
    _check_deliver_accept("curation_team.chain_delete", ccode, dcode, dlog)

    ccode, dcode, dlog = _submit_curation(
        backend,
        curator,
        _build_msg_set_curation_subscriber_only,
        "/mirage.core.v1.MsgSetCurationSubscriberOnly",
        slug,
        team_id,
        True,
    )
    _check_deliver_reject("curation_team.chain_deleted_team_rejects_control", ccode, dcode, dlog)

    _debug(f"curation_team.chain done community={slug} team_id={team_id}")
