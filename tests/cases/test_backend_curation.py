"""v1.39.0 curator-team backend + indexer coverage."""

from __future__ import annotations

import time

from tests.common import (
    INDEX_TIMEOUT_SEC,
    WALLETS,
    _debug,
    _fail,
    _get,
    _pass,
    _rand_str,
)
from tests.backend_helpers import (
    _do_accept_curator_invite,
    _do_create_curation_team,
    _do_decline_curator_invite,
    _do_delete_curation_team,
    _do_follow_topic,
    _do_invite_curator,
    _do_leave_curation_team,
    _do_post,
    _do_remove_curator,
    _do_revoke_curator_invite,
    _do_set_curation_post_hidden,
    _do_set_curation_post_tag,
    _do_set_curation_preference,
    _do_set_curation_subscriber_only,
    _do_set_curation_tag,
    _do_set_curation_thread_locked,
    _do_set_curation_user_hidden,
    _do_transfer_curation_team,
    _wait_curation_team,
    _wait_indexed,
    _wait_team_member,
    _wait_team_owner,
    _wait_tx_status,
)


def _tx_ok(resp: dict) -> str:
    if not isinstance(resp, dict):
        return ""
    if resp.get("error") or int(resp.get("code", 0) or 0) != 0:
        return ""
    return str(resp.get("tx_hash") or "").lower()


def _feed_ids(feed: dict | None) -> set[str]:
    ids: set[str] = set()
    for post in (feed or {}).get("posts") or []:
        for key in ("post_id", "tx_hash", "hash"):
            value = str(post.get(key) or "").lower()
            if value:
                ids.add(value)
    return ids


def _community_feed(
    backend: str,
    address: str,
    slug: str,
    *,
    lens: str,
    team_id: int | None = None,
) -> tuple[int, dict]:
    params = {
        "address": address,
        "community": slug,
        "lens": lens,
        "scope": "current",
        "by": "newest",
        "page": 1,
        "limit": 25,
    }
    if team_id is not None:
        params["team_id"] = str(team_id)
    return _get(f"{backend}/api/get_posts", params)


def test_curation_backend(backend: str) -> None:
    """Create gates, team shape (no policy), hide + lens filter."""
    free = WALLETS["free"]
    sub = WALLETS["sub1"]
    sub_addr = str(sub.address()).lower()
    slug = f"c{_rand_str(8)}"

    # Free create rejected before broadcast when possible.
    free_resp = _do_create_curation_team(backend, free, slug, "FreeTeam", "nope", skip_pow=False)
    if free_resp.get("error_code") == "not_subscriber" or free_resp.get("error"):
        _pass("curation.backend_free_create_rejected")
    else:
        txh = _tx_ok(free_resp)
        if txh:
            status = _wait_tx_status(backend, txh, require_details=False)
            if status and status.get("success") is False:
                _pass("curation.backend_free_create_rejected")
            else:
                _fail("curation.backend_free_create_rejected", f"resp={free_resp} status={status}")
        else:
            _pass("curation.backend_free_create_rejected")

    # Paid create without joining first must succeed.
    lonely = f"c{_rand_str(8)}"
    unjoined = _do_create_curation_team(backend, sub, lonely, "Lonely", "no join", skip_pow=True)
    unjoined_tx = _tx_ok(unjoined)
    if not unjoined_tx:
        _fail("curation.backend_unjoined_create_allowed", f"resp={unjoined}")
        return
    if not _wait_tx_status(backend, unjoined_tx, expect_type="create_curation_team", require_details=False):
        _fail("curation.backend_unjoined_create_allowed", f"tx={unjoined_tx}")
        return
    _pass("curation.backend_unjoined_create_allowed")

    # Join is still required later for pinning a preference; create does not need it.
    join_resp = _do_follow_topic(backend, sub, slug, follow=True, skip_pow=True)
    if not isinstance(join_resp, dict):
        _fail("curation.backend_join", f"resp={join_resp}")
        return
    join_tx = str(join_resp.get("tx_hash") or "").lower()
    if join_resp.get("error") or int(join_resp.get("code", 0) or 0) != 0 or not join_tx:
        _fail("curation.backend_join", f"resp={join_resp}")
        return
    if not _wait_tx_status(backend, join_tx, expect_type="join_community", require_details=False):
        _fail("curation.backend_join_indexed", f"tx={join_tx}")
        return
    _pass("curation.backend_join")

    team_name = f"Lens{_rand_str(4)}"
    description = "Moderation lives in description: hide spam, keep adult content."
    create_resp = _do_create_curation_team(backend, sub, slug, team_name, description, skip_pow=True)
    create_tx = _tx_ok(create_resp)
    if not create_tx:
        _fail("curation.backend_create", f"resp={create_resp}")
        return
    if not _wait_tx_status(backend, create_tx, expect_type="create_curation_team", require_details=False):
        _fail("curation.backend_create_indexed", f"tx={create_tx}")
        return
    _pass("curation.backend_create")

    team = _wait_curation_team(backend, slug, owner=sub_addr, name=team_name)
    if not team:
        _fail("curation.backend_team_listed", "team not indexed")
        return
    if "policy" in team:
        _fail("curation.backend_team_no_policy", f"team={team}")
    else:
        _pass("curation.backend_team_no_policy")
    if team.get("description") != description:
        _fail("curation.backend_team_description", f"team={team}")
    else:
        _pass("curation.backend_team_description")

    team_id = int(team["team_id"])
    code, detail = _get(f"{backend}/api/communities/{slug}/teams/{team_id}")
    if code != 200 or not isinstance(detail, dict):
        _fail("curation.backend_team_detail", f"code={code} detail={detail}")
    elif "policy" in detail:
        _fail("curation.backend_team_detail_no_policy", f"detail={detail}")
    else:
        _pass("curation.backend_team_detail_no_policy")

    # Params: description limit present, policy length gone.
    code, params_body = _get(f"{backend}/api/get_parameters")
    params = (params_body or {}).get("params") or params_body or {}
    if not isinstance(params, dict):
        # some deployments nest differently
        params = params_body if isinstance(params_body, dict) else {}
    # Backend params endpoint shape varies; also try chain_params via community path.
    if "max_curation_team_policy_length" in params:
        _fail("curation.backend_policy_param_retired", "still present in get_parameters")
    else:
        _pass("curation.backend_policy_param_retired")

    # Post + hide under team lens; raw still shows it.
    post_tx = _do_post(backend, sub, slug, f"Hidden {_rand_str(4)}", "body", skip_pow=True)
    if not post_tx or not _wait_indexed(backend, sub_addr, post_tx):
        _fail("curation.backend_seed_post", f"tx={post_tx}")
        return
    _pass("curation.backend_seed_post")

    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    raw_visible = False
    last_raw_code = 0
    last_raw_feed: dict | None = None
    while time.perf_counter() < deadline:
        last_raw_code, last_raw_feed = _community_feed(backend, sub_addr, slug, lens="raw")
        raw_visible = last_raw_code == 200 and post_tx in _feed_ids(last_raw_feed)
        if raw_visible:
            break
        time.sleep(0.5)
    if not raw_visible:
        _debug(
            f"curation.raw_before_hide code={last_raw_code} "
            f"ids={sorted(_feed_ids(last_raw_feed))[:8]} err={(last_raw_feed or {}).get('error')}"
        )
        _fail("curation.backend_raw_lens_shows_post", f"post never appeared in raw lens ({post_tx})")
        return

    # Pin preference so effective/default can resolve to this team.
    pref = _do_set_curation_preference(backend, sub, slug, mode=1, pinned_team_id=team_id, skip_pow=True)
    pref_tx = _tx_ok(pref)
    if pref_tx:
        _wait_tx_status(backend, pref_tx, expect_type="set_curation_preference", require_details=False)
        _pass("curation.backend_preference_pin")
    elif pref.get("error"):
        _fail("curation.backend_preference_pin", f"resp={pref}")
    else:
        _fail("curation.backend_preference_pin", f"resp={pref}")

    hide = _do_set_curation_post_hidden(backend, sub, slug, team_id, post_tx, hidden=True, skip_pow=True)
    hide_tx = _tx_ok(hide)
    if not hide_tx:
        _fail("curation.backend_hide_post", f"resp={hide}")
        return
    if not _wait_tx_status(backend, hide_tx, expect_type="set_curation_post_hidden", require_details=False):
        _fail("curation.backend_hide_post_indexed", f"tx={hide_tx}")
        return
    _pass("curation.backend_hide_post")

    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    team_hidden = False
    raw_visible = False
    last_team_code = 0
    last_raw_code = 0
    last_team_feed: dict | None = None
    last_raw_feed: dict | None = None
    while time.perf_counter() < deadline:
        last_team_code, last_team_feed = _community_feed(backend, sub_addr, slug, lens="team", team_id=team_id)
        last_raw_code, last_raw_feed = _community_feed(backend, sub_addr, slug, lens="raw")
        team_hidden = last_team_code == 200 and post_tx not in _feed_ids(last_team_feed)
        raw_visible = last_raw_code == 200 and post_tx in _feed_ids(last_raw_feed)
        if team_hidden and raw_visible:
            break
        time.sleep(0.5)

    if team_hidden:
        _pass("curation.backend_team_lens_hides_post")
    else:
        _debug(
            f"curation.team_after_hide code={last_team_code} "
            f"ids={sorted(_feed_ids(last_team_feed))[:8]} err={(last_team_feed or {}).get('error')}"
        )
        _fail("curation.backend_team_lens_hides_post", f"post still in team lens ({post_tx})")
    if raw_visible:
        _pass("curation.backend_raw_lens_shows_post")
    else:
        _debug(
            f"curation.raw_after_hide code={last_raw_code} "
            f"ids={sorted(_feed_ids(last_raw_feed))[:8]} err={(last_raw_feed or {}).get('error')}"
        )
        _fail("curation.backend_raw_lens_shows_post", f"post missing from raw lens ({post_tx})")

    hidden_list_url = f"{backend}/api/communities/{slug}/teams/{team_id}/hidden-users"
    code, missing = _get(hidden_list_url)
    if code == 400 and isinstance(missing, dict) and missing.get("error_code") == "missing_viewer":
        _pass("curation.backend_hidden_users_requires_viewer")
    else:
        _fail("curation.backend_hidden_users_requires_viewer", f"code={code} body={missing}")

    free_addr = str(free.address()).lower()
    code, forbidden = _get(hidden_list_url, {"viewer": free_addr})
    if code == 403 and isinstance(forbidden, dict) and forbidden.get("error_code") == "forbidden":
        _pass("curation.backend_hidden_users_curator_only")
    else:
        _fail("curation.backend_hidden_users_curator_only", f"code={code} body={forbidden}")

    hide_user = _do_set_curation_user_hidden(backend, sub, slug, team_id, free_addr, hidden=True, skip_pow=True)
    hide_user_tx = _tx_ok(hide_user)
    if not hide_user_tx:
        _fail("curation.backend_hide_user", f"resp={hide_user}")
        return
    if not _wait_tx_status(backend, hide_user_tx, expect_type="set_curation_user_hidden", require_details=False):
        _fail("curation.backend_hide_user_indexed", f"tx={hide_user_tx}")
        return
    _pass("curation.backend_hide_user")

    listed = False
    last_list_code = 0
    last_list_body: dict | None = None
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        last_list_code, last_list_body = _get(hidden_list_url, {"viewer": sub_addr, "limit": 10, "offset": 0})
        addresses = {str(item.get("address") or "").lower() for item in ((last_list_body or {}).get("items") or [])}
        listed = (
            last_list_code == 200
            and free_addr in addresses
            and isinstance(last_list_body, dict)
            and last_list_body.get("has_more") is False
        )
        if listed:
            break
        time.sleep(0.5)
    if listed:
        _pass("curation.backend_hidden_users_lists_target")
    else:
        _fail(
            "curation.backend_hidden_users_lists_target",
            f"code={last_list_code} body={last_list_body}",
        )

    hidden_posts_url = f"{backend}/api/communities/{slug}/teams/{team_id}/hidden-posts"
    posts_listed = False
    last_posts_code = 0
    last_posts_body: dict | None = None
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        last_posts_code, last_posts_body = _get(hidden_posts_url, {"viewer": sub_addr, "limit": 10, "offset": 0})
        post_ids = {str(item.get("post_id") or "").lower() for item in ((last_posts_body or {}).get("items") or [])}
        posts_listed = last_posts_code == 200 and post_tx in post_ids
        if posts_listed:
            break
        time.sleep(0.5)
    if posts_listed:
        _pass("curation.backend_hidden_posts_lists_target")
    else:
        _fail(
            "curation.backend_hidden_posts_lists_target",
            f"code={last_posts_code} body={last_posts_body}",
        )

    code, bad_limit = _get(hidden_posts_url, {"viewer": sub_addr, "limit": 51})
    if code == 400 and isinstance(bad_limit, dict) and bad_limit.get("error_code") == "invalid_limit":
        _pass("curation.backend_hidden_posts_limit_cap")
    else:
        _fail("curation.backend_hidden_posts_limit_cap", f"code={code} body={bad_limit}")

    code, listed = _get(f"{backend}/api/communities", {"limit": 25})
    items = (listed or {}).get("items") if isinstance(listed, dict) else None
    if code != 200 or not isinstance(items, list):
        _fail("curation.communities_sorted_by_post_count", f"code={code} body={listed}")
    else:
        pairs = [(int(item["post_count"]), str(item["community"])) for item in items]
        expected = sorted(pairs, key=lambda row: (-row[0], row[1]))
        if pairs != expected:
            _fail("curation.communities_sorted_by_post_count", f"got={pairs[:8]}")
        else:
            _pass("curation.communities_sorted_by_post_count")
        if listed.get("has_more"):
            last = items[-1]
            want_cursor = f"{int(last['post_count'])}:{last['community']}"
            if listed.get("next_cursor") != want_cursor:
                _fail(
                    "curation.communities_post_count_cursor",
                    f"cursor={listed.get('next_cursor')} want={want_cursor}",
                )
            else:
                _pass("curation.communities_post_count_cursor")
    code, bad_cursor = _get(f"{backend}/api/communities", {"cursor": "not-a-cursor"})
    if code == 400 and isinstance(bad_cursor, dict) and bad_cursor.get("error_code") == "invalid_cursor":
        _pass("curation.communities_invalid_cursor")
    else:
        _fail("curation.communities_invalid_cursor", f"code={code} body={bad_cursor}")

    _debug(f"curation.backend done community={slug} team_id={team_id}")


def _expect_accepted(name: str, backend: str, resp: dict) -> bool:
    """Assert a curation route reached the chain and its handler accepted it."""
    txh = _tx_ok(resp)
    if not txh:
        _fail(name, f"resp={resp}")
        return False
    status = _wait_tx_status(backend, txh, require_details=False)
    if not status:
        _fail(name, f"tx never resolved ({txh})")
        return False
    if status.get("success") is False:
        _fail(name, f"tx rejected: {status}")
        return False
    _pass(name)
    return True


def _expect_rejected(name: str, backend: str, resp: dict) -> bool:
    """Assert a curation route was refused, at the API or by the handler.

    Authorization for these messages lives in the handler, not the ante, so a
    CheckTx-level accept proves nothing — the rejection has to be confirmed at
    DeliverTx.
    """
    if not isinstance(resp, dict):
        _fail(name, f"resp={resp}")
        return False
    if resp.get("error") or resp.get("error_code"):
        _pass(name)
        return True
    txh = _tx_ok(resp)
    if not txh:
        _pass(name)
        return True
    status = _wait_tx_status(backend, txh, require_details=False)
    if status and status.get("success") is False:
        _pass(name)
        return True
    _fail(name, f"accepted when it should not have been: tx={txh} status={status}")
    return False


def _moderation(backend: str, slug: str, team_id: int, viewer: str, post_id: str, author: str) -> tuple[int, dict]:
    return _get(
        f"{backend}/api/communities/{slug}/teams/{team_id}/moderation",
        {"viewer": viewer, "post_id": post_id, "author": author, "root": post_id},
    )


def _wait_moderation(
    backend: str,
    slug: str,
    team_id: int,
    viewer: str,
    post_id: str,
    author: str,
    field: str,
    expected,
) -> tuple[bool, dict | None]:
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    last: dict | None = None
    while time.perf_counter() < deadline:
        code, last = _moderation(backend, slug, team_id, viewer, post_id, author)
        if code == 200 and isinstance(last, dict) and last.get(field) == expected:
            return True, last
        time.sleep(0.5)
    return False, last


def test_curation_team_lifecycle(backend: str) -> None:
    """Invite, accept, moderate, transfer, remove and delete through the API.

    The team-scoped messages carry their authorization in the handler, so each
    negative case here has to be confirmed at DeliverTx rather than at the API.
    """
    owner_wallet = WALLETS["sub1"]
    curator_wallet = WALLETS["sub2"]
    owner_addr = str(owner_wallet.address()).lower()
    curator_addr = str(curator_wallet.address()).lower()
    slug = f"c{_rand_str(8)}"
    team_name = f"Life{_rand_str(4)}"

    create = _do_create_curation_team(backend, owner_wallet, slug, team_name, "lifecycle", skip_pow=True)
    if not _expect_accepted("curation_team.create", backend, create):
        return
    team = _wait_curation_team(backend, slug, owner=owner_addr, name=team_name)
    if not team:
        _fail("curation_team.create_indexed", "team not indexed")
        return
    team_id = int(team["team_id"])
    _pass("curation_team.create_indexed", team_id=team_id)

    invitations_url = f"{backend}/api/communities/{slug}/teams/{team_id}/invitations"
    code, missing = _get(invitations_url)
    if code == 400 and isinstance(missing, dict) and missing.get("error_code") == "missing_viewer":
        _pass("curation_team.invitations_requires_viewer")
    else:
        _fail("curation_team.invitations_requires_viewer", f"code={code} body={missing}")

    invite = _do_invite_curator(backend, owner_wallet, slug, team_id, curator_addr, skip_pow=True)
    if not _expect_accepted("curation_team.invite", backend, invite):
        return

    invited = False
    last_inv: dict | None = None
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        code, last_inv = _get(invitations_url, {"viewer": owner_addr})
        invitees = {str(item.get("invitee") or "").lower() for item in ((last_inv or {}).get("items") or [])}
        if code == 200 and curator_addr in invitees:
            invited = True
            break
        time.sleep(0.5)
    if invited:
        _pass("curation_team.invitation_listed_to_owner")
    else:
        _fail("curation_team.invitation_listed_to_owner", f"body={last_inv}")

    # Only the owner may revoke. The invitee revoking its own invitation would
    # otherwise be indistinguishable from declining it.
    _expect_rejected(
        "curation_team.revoke_non_owner_rejected",
        backend,
        _do_revoke_curator_invite(backend, curator_wallet, slug, team_id, curator_addr, skip_pow=True),
    )
    _expect_accepted(
        "curation_team.revoke",
        backend,
        _do_revoke_curator_invite(backend, owner_wallet, slug, team_id, curator_addr, skip_pow=True),
    )
    _expect_rejected(
        "curation_team.accept_after_revoke_rejected",
        backend,
        _do_accept_curator_invite(backend, curator_wallet, slug, team_id, skip_pow=True),
    )

    # Revoking must release the pending slot, so a re-invite is accepted.
    if not _expect_accepted(
        "curation_team.reinvite_after_revoke",
        backend,
        _do_invite_curator(backend, owner_wallet, slug, team_id, curator_addr, skip_pow=True),
    ):
        return
    _expect_accepted(
        "curation_team.decline",
        backend,
        _do_decline_curator_invite(backend, curator_wallet, slug, team_id, skip_pow=True),
    )
    if not _expect_accepted(
        "curation_team.reinvite_after_decline",
        backend,
        _do_invite_curator(backend, owner_wallet, slug, team_id, curator_addr, skip_pow=True),
    ):
        return
    if not _expect_accepted(
        "curation_team.accept",
        backend,
        _do_accept_curator_invite(backend, curator_wallet, slug, team_id, skip_pow=True),
    ):
        return
    if _wait_team_member(backend, slug, team_id, curator_addr):
        _pass("curation_team.roster_has_curator")
    else:
        _fail("curation_team.roster_has_curator", f"curator={curator_addr[:12]}")

    code, curated = _get(f"{backend}/api/curators/{curator_addr}/communities")
    if code == 200 and slug in [str(c).lower() for c in (curated or {}).get("communities") or []]:
        _pass("curation_team.curator_communities_lists_slug")
    else:
        _fail("curation_team.curator_communities_lists_slug", f"code={code} body={curated}")

    code, bad_addr = _get(f"{backend}/api/curators/not-an-address/communities")
    if code == 400 and isinstance(bad_addr, dict) and bad_addr.get("error_code") == "user_must_be_mirage1":
        _pass("curation_team.curator_communities_validates_address")
    else:
        _fail("curation_team.curator_communities_validates_address", f"code={code} body={bad_addr}")

    # Owner-only controls stay owner-only for an accepted curator.
    _expect_rejected(
        "curation_team.subscriber_only_non_owner_rejected",
        backend,
        _do_set_curation_subscriber_only(backend, curator_wallet, slug, team_id, enabled=True, skip_pow=True),
    )
    _expect_rejected(
        "curation_team.community_tag_non_owner_rejected",
        backend,
        _do_set_curation_tag(backend, curator_wallet, slug, team_id, "adult", skip_pow=True),
    )
    _expect_rejected(
        "curation_team.remove_curator_non_owner_rejected",
        backend,
        _do_remove_curator(backend, curator_wallet, slug, team_id, owner_addr, skip_pow=True),
    )
    _expect_rejected(
        "curation_team.delete_non_owner_rejected",
        backend,
        _do_delete_curation_team(backend, curator_wallet, slug, team_id, skip_pow=True),
    )
    _expect_accepted(
        "curation_team.subscriber_only_owner",
        backend,
        _do_set_curation_subscriber_only(backend, owner_wallet, slug, team_id, enabled=True, skip_pow=True),
    )
    subs_only = False
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    last_detail: dict | None = None
    while time.perf_counter() < deadline:
        code, last_detail = _get(f"{backend}/api/communities/{slug}/teams/{team_id}")
        if code == 200 and isinstance(last_detail, dict) and last_detail.get("subscriber_only") is True:
            subs_only = True
            break
        time.sleep(0.5)
    if subs_only:
        _pass("curation_team.subscriber_only_indexed")
    else:
        _fail("curation_team.subscriber_only_indexed", f"detail={last_detail}")
    _expect_accepted(
        "curation_team.subscriber_only_off",
        backend,
        _do_set_curation_subscriber_only(backend, owner_wallet, slug, team_id, enabled=False, skip_pow=True),
    )
    _expect_accepted(
        "curation_team.community_tag_owner",
        backend,
        _do_set_curation_tag(backend, owner_wallet, slug, team_id, "adult", skip_pow=True),
    )
    tagged = False
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    while time.perf_counter() < deadline:
        code, last_detail = _get(f"{backend}/api/communities/{slug}/teams/{team_id}")
        if code == 200 and isinstance(last_detail, dict) and last_detail.get("tag") == "adult":
            tagged = True
            break
        time.sleep(0.5)
    if tagged:
        _pass("curation_team.community_tag_indexed")
    else:
        _fail("curation_team.community_tag_indexed", f"detail={last_detail}")

    # A non-owner curator may still moderate, and the /moderation read is the
    # only way the UI learns the team's current decision for one post.
    post_tx = _do_post(backend, owner_wallet, slug, f"Mod {_rand_str(4)}", "body", skip_pow=True)
    if not post_tx or not _wait_indexed(backend, owner_addr, post_tx):
        _fail("curation_team.seed_post", f"tx={post_tx}")
        return
    _pass("curation_team.seed_post")

    code, forbidden = _moderation(backend, slug, team_id, str(WALLETS["free"].address()).lower(), post_tx, owner_addr)
    if code == 403 and isinstance(forbidden, dict) and forbidden.get("error_code") == "forbidden":
        _pass("curation_team.moderation_curator_only")
    else:
        _fail("curation_team.moderation_curator_only", f"code={code} body={forbidden}")

    code, no_post = _get(
        f"{backend}/api/communities/{slug}/teams/{team_id}/moderation",
        {"viewer": curator_addr, "author": owner_addr},
    )
    if code == 400 and isinstance(no_post, dict) and no_post.get("error_code") == "missing_post_id":
        _pass("curation_team.moderation_requires_post_id")
    else:
        _fail("curation_team.moderation_requires_post_id", f"code={code} body={no_post}")

    _expect_accepted(
        "curation_team.curator_hides_post",
        backend,
        _do_set_curation_post_hidden(backend, curator_wallet, slug, team_id, post_tx, hidden=True, skip_pow=True),
    )
    ok, body = _wait_moderation(backend, slug, team_id, curator_addr, post_tx, owner_addr, "post_hidden", True)
    if ok:
        _pass("curation_team.moderation_reports_post_hidden")
    else:
        _fail("curation_team.moderation_reports_post_hidden", f"body={body}")

    _expect_accepted(
        "curation_team.curator_locks_thread",
        backend,
        _do_set_curation_thread_locked(backend, curator_wallet, slug, team_id, post_tx, locked=True, skip_pow=True),
    )
    ok, body = _wait_moderation(backend, slug, team_id, curator_addr, post_tx, owner_addr, "thread_locked", True)
    if ok:
        _pass("curation_team.moderation_reports_thread_locked")
    else:
        _fail("curation_team.moderation_reports_thread_locked", f"body={body}")

    _expect_accepted(
        "curation_team.curator_unlocks_thread",
        backend,
        _do_set_curation_thread_locked(backend, curator_wallet, slug, team_id, post_tx, locked=False, skip_pow=True),
    )
    ok, body = _wait_moderation(backend, slug, team_id, curator_addr, post_tx, owner_addr, "thread_locked", False)
    if ok:
        _pass("curation_team.moderation_reports_thread_unlocked")
    else:
        _fail("curation_team.moderation_reports_thread_unlocked", f"body={body}")

    _expect_accepted(
        "curation_team.curator_sets_post_tag",
        backend,
        _do_set_curation_post_tag(backend, curator_wallet, slug, team_id, post_tx, tag="gore", skip_pow=True),
    )
    ok, body = _wait_moderation(backend, slug, team_id, curator_addr, post_tx, owner_addr, "post_tag", "gore")
    if ok:
        _pass("curation_team.moderation_reports_post_tag")
    else:
        _fail("curation_team.moderation_reports_post_tag", f"body={body}")

    # An empty tag is a decision; clearing withdraws it. /moderation reports the
    # first as "" and the second as null, and the tag precedence chain depends
    # on the difference.
    _expect_accepted(
        "curation_team.curator_sets_empty_post_tag",
        backend,
        _do_set_curation_post_tag(backend, curator_wallet, slug, team_id, post_tx, tag="", skip_pow=True),
    )
    ok, body = _wait_moderation(backend, slug, team_id, curator_addr, post_tx, owner_addr, "post_tag", "")
    if ok:
        _pass("curation_team.moderation_reports_empty_post_tag")
    else:
        _fail("curation_team.moderation_reports_empty_post_tag", f"body={body}")

    _expect_accepted(
        "curation_team.curator_clears_post_tag",
        backend,
        _do_set_curation_post_tag(backend, curator_wallet, slug, team_id, post_tx, clear=True, skip_pow=True),
    )
    ok, body = _wait_moderation(backend, slug, team_id, curator_addr, post_tx, owner_addr, "post_tag", None)
    if ok:
        _pass("curation_team.moderation_reports_cleared_post_tag")
    else:
        _fail("curation_team.moderation_reports_cleared_post_tag", f"body={body}")

    # An unwhitelisted tag never reaches the chain: this route validates before
    # broadcasting.
    bad_tag = _do_set_curation_post_tag(
        backend, curator_wallet, slug, team_id, post_tx, tag="not-a-real-tag", skip_pow=True
    )
    if isinstance(bad_tag, dict) and bad_tag.get("error_code") == "invalid_tag":
        _pass("curation_team.post_tag_rejects_unknown_tag")
    else:
        _fail("curation_team.post_tag_rejects_unknown_tag", f"resp={bad_tag}")

    # Transfer moves the owner-only powers; the old owner stays on the roster.
    _expect_accepted(
        "curation_team.transfer",
        backend,
        _do_transfer_curation_team(backend, owner_wallet, slug, team_id, curator_addr, skip_pow=True),
    )
    if _wait_team_owner(backend, slug, team_id, curator_addr):
        _pass("curation_team.transfer_indexed")
    else:
        _fail("curation_team.transfer_indexed", f"expected owner={curator_addr[:12]}")
    _expect_rejected(
        "curation_team.old_owner_loses_owner_powers",
        backend,
        _do_set_curation_subscriber_only(backend, owner_wallet, slug, team_id, enabled=True, skip_pow=True),
    )
    _expect_rejected(
        "curation_team.new_owner_cannot_leave",
        backend,
        _do_leave_curation_team(backend, curator_wallet, slug, team_id, skip_pow=True),
    )

    _expect_accepted(
        "curation_team.new_owner_removes_old_owner",
        backend,
        _do_remove_curator(backend, curator_wallet, slug, team_id, owner_addr, skip_pow=True),
    )
    if _wait_team_member(backend, slug, team_id, owner_addr, present=False):
        _pass("curation_team.removed_curator_off_roster")
    else:
        _fail("curation_team.removed_curator_off_roster", f"removed={owner_addr[:12]}")

    _expect_accepted(
        "curation_team.delete",
        backend,
        _do_delete_curation_team(backend, curator_wallet, slug, team_id, skip_pow=True),
    )
    gone = False
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    last_list: dict | None = None
    while time.perf_counter() < deadline:
        code, last_list = _get(f"{backend}/api/communities/{slug}/teams")
        if code == 200 and isinstance(last_list, dict):
            live = [str(item.get("team_id")) for item in (last_list.get("items") or [])]
            if str(team_id) not in live:
                gone = True
                break
        time.sleep(0.5)
    if gone:
        _pass("curation_team.delete_removes_from_live_list")
    else:
        _fail("curation_team.delete_removes_from_live_list", f"body={last_list}")

    _expect_rejected(
        "curation_team.deleted_team_rejects_moderation",
        backend,
        _do_set_curation_post_hidden(backend, curator_wallet, slug, team_id, post_tx, hidden=False, skip_pow=True),
    )
    _expect_rejected(
        "curation_team.deleted_team_rejects_invite",
        backend,
        _do_invite_curator(backend, curator_wallet, slug, team_id, owner_addr, skip_pow=True),
    )

    _debug(f"curation_team.lifecycle done community={slug} team_id={team_id}")


def _thread_ids(
    backend: str,
    root: str,
    *,
    address: str,
    lens: str,
    team_id: int | None = None,
) -> tuple[int, set[str], dict]:
    """Return the post ids the thread tree serves for one lens."""
    params = {"post_id": root, "address": address, "lens": lens, "scope": "current"}
    if team_id is not None:
        params["team_id"] = str(team_id)
    code, body = _get(f"{backend}/api/get_comments", params)
    ids: set[str] = set()

    def walk(nodes) -> None:
        for node in nodes or []:
            post_id = str(node.get("post_id") or "").lower()
            if post_id:
                ids.add(post_id)
            walk(node.get("children"))

    if code == 200 and isinstance(body, dict):
        walk(body.get("children"))
    return code, ids, body if isinstance(body, dict) else {}


def _wait_thread_ids(
    backend: str,
    root: str,
    *,
    address: str,
    lens: str,
    team_id: int | None,
    expect_present: set[str],
    expect_absent: set[str],
) -> tuple[bool, set[str], dict]:
    """Poll one lens's thread until it serves exactly the wanted replies."""
    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    ids: set[str] = set()
    body: dict = {}
    while time.perf_counter() < deadline:
        code, ids, body = _thread_ids(backend, root, address=address, lens=lens, team_id=team_id)
        if code == 200 and expect_present <= ids and not (expect_absent & ids):
            return True, ids, body
        time.sleep(0.5)
    return False, ids, body


def _reply(backend: str, wallet, root: str, text: str) -> str:
    """Post a reply to `root` and wait for the indexer; returns the tx hash."""
    tx = _do_post(backend, wallet, "", "", text, target=root, skip_pow=True)
    if not tx or not _wait_indexed(backend, str(wallet.address()).lower(), tx):
        return ""
    return tx.lower()


def test_curation_thread_lock_windows(backend: str) -> None:
    """A lock is a timed cut-off, and unlocking does not republish what it hid.

    A curator can lock and unlock the same thread repeatedly. Each locked
    stretch is a window in global post-sequence space, and the replies written
    inside one stay hidden on that team's lens forever: unlocking reopens the
    thread for new replies rather than publishing the ones it refused. The chain
    keeps only the cut-off of the window that is open right now, so this walks
    the whole lock/reply/unlock/reply cycle to prove the indexer carries the
    closed windows on its own.

    None of it is a write gate. Every reply here is accepted on chain and every
    one of them stays visible on raw, which is the lens that shows what the
    network actually holds.
    """
    owner_wallet = WALLETS["sub1"]
    owner_addr = str(owner_wallet.address()).lower()
    slug = f"c{_rand_str(8)}"
    team_name = f"Lock{_rand_str(4)}"

    if not _expect_accepted(
        "curation_lock.create_team",
        backend,
        _do_create_curation_team(backend, owner_wallet, slug, team_name, "lock windows", skip_pow=True),
    ):
        return
    team = _wait_curation_team(backend, slug, owner=owner_addr, name=team_name)
    if not team:
        _fail("curation_lock.team_indexed", "team not indexed")
        return
    team_id = int(team["team_id"])
    _pass("curation_lock.team_indexed", team_id=team_id)

    root = _do_post(backend, owner_wallet, slug, f"Lock {_rand_str(4)}", "root", skip_pow=True)
    if not root or not _wait_indexed(backend, owner_addr, root):
        _fail("curation_lock.root_indexed", f"tx={root}")
        return
    root = root.lower()
    _pass("curation_lock.root_indexed")

    def set_locked(label: str, locked: bool) -> bool:
        return _expect_accepted(
            f"curation_lock.{label}",
            backend,
            _do_set_curation_thread_locked(backend, owner_wallet, slug, team_id, root, locked=locked, skip_pow=True),
        )

    open_reply = _reply(backend, owner_wallet, root, "before any lock")
    if not open_reply:
        _fail("curation_lock.open_reply_indexed", "reply never indexed")
        return
    _pass("curation_lock.open_reply_indexed")

    if not set_locked("lock_first", True):
        return
    locked_reply = _reply(backend, owner_wallet, root, "written while locked")
    if not locked_reply:
        _fail("curation_lock.locked_reply_indexed", "reply never indexed")
        return
    _pass("curation_lock.locked_reply_indexed")

    ok, ids, body = _wait_thread_ids(
        backend,
        root,
        address=owner_addr,
        lens="team",
        team_id=team_id,
        expect_present={open_reply},
        expect_absent={locked_reply},
    )
    if ok and (body.get("root") or {}).get("thread_locked") is True:
        _pass("curation_lock.locked_reply_hidden_on_team_lens")
    else:
        _fail(
            "curation_lock.locked_reply_hidden_on_team_lens",
            f"ids={sorted(i[:12] for i in ids)} thread_locked={(body.get('root') or {}).get('thread_locked')}",
        )

    ok, ids, body = _wait_thread_ids(
        backend,
        root,
        address=owner_addr,
        lens="default",
        team_id=None,
        expect_present={open_reply},
        expect_absent={locked_reply},
    )
    if ok and (body.get("root") or {}).get("thread_locked") is True:
        _pass("curation_lock.locked_reply_hidden_on_default_lens")
    else:
        _fail(
            "curation_lock.locked_reply_hidden_on_default_lens",
            f"ids={sorted(i[:12] for i in ids)} thread_locked={(body.get('root') or {}).get('thread_locked')}",
        )

    # Re-locking must not move the cut-off forward: that would republish every
    # reply written since the thread was originally locked.
    if not set_locked("lock_again", True):
        return
    ok, ids, _ = _wait_thread_ids(
        backend,
        root,
        address=owner_addr,
        lens="team",
        team_id=team_id,
        expect_present={open_reply},
        expect_absent={locked_reply},
    )
    if ok:
        _pass("curation_lock.redundant_lock_keeps_cutoff")
    else:
        _fail("curation_lock.redundant_lock_keeps_cutoff", f"ids={sorted(i[:12] for i in ids)}")

    if not set_locked("unlock_first", False):
        return
    reopened_reply = _reply(backend, owner_wallet, root, "after the unlock")
    if not reopened_reply:
        _fail("curation_lock.reopened_reply_indexed", "reply never indexed")
        return
    _pass("curation_lock.reopened_reply_indexed")

    # The point of the whole feature: the closed window outlives the unlock.
    ok, ids, body = _wait_thread_ids(
        backend,
        root,
        address=owner_addr,
        lens="team",
        team_id=team_id,
        expect_present={open_reply, reopened_reply},
        expect_absent={locked_reply},
    )
    if ok and (body.get("root") or {}).get("thread_locked") is False:
        _pass("curation_lock.closed_window_survives_unlock")
    else:
        _fail(
            "curation_lock.closed_window_survives_unlock",
            f"ids={sorted(i[:12] for i in ids)} thread_locked={(body.get('root') or {}).get('thread_locked')}",
        )

    # A second lock opens a second window and leaves the first one alone.
    if not set_locked("lock_second", True):
        return
    second_locked_reply = _reply(backend, owner_wallet, root, "written during the second lock")
    if not second_locked_reply:
        _fail("curation_lock.second_locked_reply_indexed", "reply never indexed")
        return
    _pass("curation_lock.second_locked_reply_indexed")

    if not set_locked("unlock_second", False):
        return
    ok, ids, _ = _wait_thread_ids(
        backend,
        root,
        address=owner_addr,
        lens="team",
        team_id=team_id,
        expect_present={open_reply, reopened_reply},
        expect_absent={locked_reply, second_locked_reply},
    )
    if ok:
        _pass("curation_lock.both_windows_stay_hidden")
    else:
        _fail("curation_lock.both_windows_stay_hidden", f"ids={sorted(i[:12] for i in ids)}")

    # Raw is the uncensored lens: a lock is a curation filter, not a write gate,
    # so everything written during either window is still there.
    ok, ids, body = _wait_thread_ids(
        backend,
        root,
        address=owner_addr,
        lens="raw",
        team_id=None,
        expect_present={open_reply, locked_reply, reopened_reply, second_locked_reply},
        expect_absent=set(),
    )
    if ok and (body.get("root") or {}).get("thread_locked") is False:
        _pass("curation_lock.raw_lens_keeps_every_reply")
    else:
        _fail(
            "curation_lock.raw_lens_keeps_every_reply",
            f"ids={sorted(i[:12] for i in ids)} thread_locked={(body.get('root') or {}).get('thread_locked')}",
        )

    _debug(f"curation_lock.windows done community={slug} team_id={team_id} root={root[:12]}")
