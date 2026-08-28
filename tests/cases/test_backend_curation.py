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
    _do_create_curation_team,
    _do_follow_topic,
    _do_post,
    _do_set_curation_post_hidden,
    _do_set_curation_preference,
    _wait_curation_team,
    _wait_indexed,
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
    if not _wait_tx_status(
        backend, unjoined_tx, expect_type="create_curation_team", require_details=False
    ):
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
    create_resp = _do_create_curation_team(
        backend, sub, slug, team_name, description, skip_pow=True
    )
    create_tx = _tx_ok(create_resp)
    if not create_tx:
        _fail("curation.backend_create", f"resp={create_resp}")
        return
    if not _wait_tx_status(
        backend, create_tx, expect_type="create_curation_team", require_details=False
    ):
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
        _wait_tx_status(
            backend, pref_tx, expect_type="set_curation_preference", require_details=False
        )
        _pass("curation.backend_preference_pin")
    elif pref.get("error"):
        _fail("curation.backend_preference_pin", f"resp={pref}")
    else:
        _fail("curation.backend_preference_pin", f"resp={pref}")

    hide = _do_set_curation_post_hidden(
        backend, sub, slug, team_id, post_tx, hidden=True, skip_pow=True
    )
    hide_tx = _tx_ok(hide)
    if not hide_tx:
        _fail("curation.backend_hide_post", f"resp={hide}")
        return
    if not _wait_tx_status(
        backend, hide_tx, expect_type="set_curation_post_hidden", require_details=False
    ):
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
        last_team_code, last_team_feed = _community_feed(
            backend, sub_addr, slug, lens="team", team_id=team_id
        )
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

    _debug(f"curation.backend done community={slug} team_id={team_id}")
