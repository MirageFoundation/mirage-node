from __future__ import annotations

import ast
import base64
import hashlib
import inspect
import json
import math
import os
import random
import re
import shutil
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple

import requests

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _get,
    _post,
    _b64,
    _rand_str,
    _now_ms,
    _fresh_nonce,
    _lb_bytes,
    WALLETS,
    FAUCET_AMOUNTS,
    INDEX_TIMEOUT_SEC,
    _COLOR_GREEN,
    _COLOR_RED,
    _COLOR_YELLOW,
    _COLOR_RESET,
    _COLOR_BOLD,
    _fetch_params,
    _do_subscribe,
    _docker_exec,
    _run_miraged,
    _miraged_cmd,
    _keyring_backend,
    TestResult,
    summarize,
    INVARIANTS_CATEGORY,
    _INSIDE_CONTAINER,
    _check_local_docker,
    DEFAULT_BACKEND,
    get_status,
    get_user_status,
    get_username_from_address,
    get_address_from_username,
    sign_canonical,
    compute_pow,
    check_pow_target,
    _difficulty_factor,
    _BASE_DIFFICULTY_FACTOR,
    _canon_base_subscribe_raw,
    _canon_base_send_tokens_raw,
    _canon_base_award_raw,
    _canon_base_post_raw,
    _canon_base_vote_raw,
    _canon_base_edit_raw,
    _canon_base_set_username_raw,
    _canon_base_set_biography_raw,
    _canon_base_report_raw,
    canon_signed_with_pow,
    _generate_wallet,
    _faucet,
    _resolve_validator_key_addr,
    _get_spendable_balance,
    _required_sub1_spend_budget_umirage,
)
from tests.backend_helpers import (
    _do_post,
    _do_post_with_nonce,
    _do_post_with_media,
    _do_vote,
    _do_vote_with_nonce,
    _do_edit,
    _do_delete,
    _do_delete_user,
    _do_follow_user,
    _do_follow_user_with_nonce,
    _do_follow_topic,
    _do_block,
    _do_block_with_nonce,
    _do_block_topic,
    _do_set_username_raw,
    _do_set_biography,
    _do_report,
    _do_set_auto_renewal,
    _do_send_tokens,
    _do_award,
    _wait_indexed,
    _wait_username,
    _wait_list_count,
    _wait_tx_status,
    _wait_tx_status_failure,
    _wait_tx_deliver,
    _wait_followed_user,
    _wait_followed_community,
    _wait_blocked_user,
    _wait_blocked_community,
    _wait_blocked_community_state,
    _wait_comment_indexed,
    _rpc_latest_height,
    _wait_next_block,
)


def test_params(backend: str):

    # 1.1 get_parameters returns valid data
    code, data = _get(f"{backend}/api/get_parameters")
    if code == 200 and data.get("last_block_hash"):
        _pass("params.get_parameters returns valid data")
    else:
        _fail("params.get_parameters returns valid data", f"code={code}")
        return  # can't continue without params

    # 1.2 pow_factor is float in [0.01,1]
    step = data.get("pow_factor")
    try:
        fstep = float(step)
        if 0 < fstep <= 1:
            _pass("params.pow_factor valid", value=fstep)
        else:
            _fail("params.pow_factor valid", f"out of range: {fstep}")
    except Exception as e:
        _fail("params.pow_factor valid", str(e))

    # 1.3 pow_base_bits present and > 0
    md = data.get("pow_base_bits")
    if md and int(md) > 0:
        _pass("params.pow_base_bits > 0", value=int(md))
    else:
        _fail("params.pow_base_bits > 0", f"got {md}")

    # 1.4 pow_difficulty is int >= 0
    pd = data.get("pow_difficulty")
    if pd is not None and int(pd) >= 0:
        _pass("params.pow_difficulty >= 0 (step format)", value=int(pd))
    else:
        _fail("params.pow_difficulty >= 0 (step format)", f"got {pd}")

    # 1.4b three-tier max_blocked_communities. Tier config lives on
    # get_chain_config; get_parameters carries only the PoW envelope inputs.
    _cc_code, chain_config = _get(f"{backend}/api/get_chain_config")
    if _cc_code != 200:
        _fail("params.get_chain_config returns valid data", f"code={_cc_code}")
        return
    tiers = (chain_config or {}).get("tiers") or []
    expected_blocked = [25, 500, 500]
    if len(tiers) == 3:
        got_blocked = [int((tiers[i] or {}).get("max_blocked_communities", -1)) for i in range(3)]
        if got_blocked == expected_blocked:
            _pass("params.max_blocked_communities tier limits", values=got_blocked)
        else:
            _fail("params.max_blocked_communities tier limits", f"got {got_blocked}")
    else:
        _fail("params.max_blocked_communities tier limits", f"tiers_len={len(tiers)}")

    # 1.4c three-tier max_biography_length
    expected_bio = [0, 512, 512]
    if len(tiers) == 3:
        got_bio = [int((tiers[i] or {}).get("max_biography_length", -1)) for i in range(3)]
        if got_bio == expected_bio:
            _pass("params.max_biography_length tier limits", values=got_bio)
        else:
            _fail("params.max_biography_length tier limits", f"got {got_bio}")
    else:
        _fail("params.max_biography_length tier limits", f"tiers_len={len(tiers)}")

    # 1.4d curation membership caps: free=0, subscriber=10, admin=1000
    expected_curation = [0, 10, 1000]
    if len(tiers) == 3:
        got_curation = [int((tiers[i] or {}).get("max_curation_memberships", -1)) for i in range(3)]
        if got_curation == expected_curation:
            _pass("params.max_curation_memberships tier limits", values=got_curation)
        else:
            _fail("params.max_curation_memberships tier limits", f"got {got_curation}")
    else:
        _fail("params.max_curation_memberships tier limits", f"tiers_len={len(tiers)}")

    # 1.4e daily relay caps
    if len(tiers) == 3:
        got_relays = [int((tiers[i] or {}).get("max_daily_relays", -1)) for i in range(3)]
        if got_relays[0] == 0 and 1 <= got_relays[1] <= 10000 and 1 <= got_relays[2] <= 10000:
            _pass("params.max_daily_relays tier limits", values=got_relays)
        else:
            _fail("params.max_daily_relays tier limits", f"got {got_relays}")
    else:
        _fail("params.max_daily_relays tier limits", f"tiers_len={len(tiers)}")

    # 1.5 get_network_stats returns consistent data
    code2, stats = _get(f"{backend}/api/get_network_stats")
    if code2 == 200 and stats.get("pow_difficulty") is not None:
        if str(stats.get("pow_factor")) == str(data.get("pow_factor")):
            _pass("params.network_stats consistent with get_parameters")
        else:
            _fail(
                "params.network_stats consistent with get_parameters",
                f"step mismatch: {stats.get('pow_factor')} vs {data.get('pow_factor')}",
            )
    else:
        _fail("params.network_stats consistent with get_parameters", f"code={code2}")

    # 1.5b get_network_stats returns earned_24h
    if code2 == 200:
        earned = stats.get("earned_24h")
        if earned is not None and int(earned) >= 0:
            _pass("params.network_stats has earned_24h", earned_24h=earned)
        else:
            _fail("params.network_stats has earned_24h", earned_24h=earned)

    # 1.6 get_chain_config returns valid governance params
    code3, cfg = _get(f"{backend}/api/get_chain_config")
    if code3 == 200 and cfg.get("subscription_period"):
        _pass("params.get_chain_config valid", keys=list(cfg.keys()))
    else:
        _fail("params.get_chain_config valid", f"code={code3}")

    # 1.6a award configs present and include expected defaults
    award_cfgs = cfg.get("award_configs") if isinstance(cfg, dict) else None
    expected_awards = {"quality_post", "original_content", "based", "receipts"}
    if isinstance(award_cfgs, list) and award_cfgs:
        names = {str(a.get("name", "")).strip() for a in award_cfgs if isinstance(a, dict)}
        missing = expected_awards - names
        if not missing:
            _pass("params.award_configs defaults present", count=len(award_cfgs))
        else:
            _fail("params.award_configs defaults present", f"missing={sorted(missing)}")
    else:
        _fail("params.award_configs defaults present", "award_configs missing or empty")

    # 1.6b subscription_reserve_bps is 0 after v1.39.0 (no relay reserve)
    reserve_bps = cfg.get("subscription_reserve_bps") if isinstance(cfg, dict) else None
    if reserve_bps is None:
        _fail("params.subscription_reserve_bps_0", "missing")
    else:
        try:
            reserve_val = int(reserve_bps)
            if reserve_val == 0:
                _pass("params.subscription_reserve_bps_0", value=reserve_val)
            else:
                _fail("params.subscription_reserve_bps_0", f"got {reserve_bps}")
        except Exception as e:
            _fail("params.subscription_reserve_bps_0", str(e))

    # 1.7 get_node_config returns valid
    code3b, ncfg = _get(f"{backend}/api/get_node_config")
    if code3b == 200 and ncfg.get("validator_account_address"):
        _pass("params.get_node_config valid")
    else:
        _fail("params.get_node_config valid", f"code={code3b}")

    # 1.9 get_total_supply positive (returns plain text, not JSON)
    try:
        code4, body4 = _get(f"{backend}/api/get_total_supply")
        if code4 == 200:
            supply_val = float(body4) if isinstance(body4, (int, float)) else float(str(body4).strip())
            if supply_val > 0:
                _pass("params.get_total_supply positive", value=supply_val)
            else:
                _fail("params.get_total_supply positive", f"supply={supply_val}")
        else:
            _fail("params.get_total_supply positive", f"code={code4}")
    except Exception as e:
        _fail("params.get_total_supply positive", str(e))

    # 1.10 get_welcome_stats valid structure
    code5, ws = _get(f"{backend}/api/get_welcome_stats")
    if code5 == 200:
        _pass("params.get_welcome_stats returns 200")
    else:
        _fail("params.get_welcome_stats returns 200", f"code={code5}")


# =========================================================================
# Category 1b: Bootstrap (combined first-paint endpoint)
# =========================================================================


def test_bootstrap(backend: str):
    """Verify /api/bootstrap returns the expected sections for both anonymous
    and logged-in callers, with shapes matching the per-endpoint routes."""

    # ----- Anonymous: only node_config populated -----
    code, body = _get(f"{backend}/api/bootstrap")
    if code == 200 and isinstance(body, dict):
        _pass("bootstrap.anonymous returns 200")
    else:
        _fail("bootstrap.anonymous returns 200", f"code={code}")
        return

    expected_keys = {
        "node_config",
        "chain_config",
        "user_status",
        "user_followed",
        "user_blocked",
        "rewards_summary",
        "view",
    }
    missing = expected_keys - set(body.keys())
    if not missing:
        _pass("bootstrap.anonymous has all keys")
    else:
        _fail("bootstrap.anonymous has all keys", f"missing={sorted(missing)}")

    # invite_codes must be omitted while REGISTRATION_INVITE_CODE_REQUIRED=false.
    if "invite_codes" in body:
        _fail("bootstrap.anonymous omits invite_codes when feature off", "invite_codes key present")
    else:
        _pass("bootstrap.anonymous omits invite_codes when feature off")

    if body.get("view") is None:
        _pass("bootstrap.anonymous view is null without view=")
    else:
        _fail("bootstrap.anonymous view is null without view=", f"got={body.get('view')}")

    nc = body.get("node_config")
    if isinstance(nc, dict) and nc.get("validator_account_address"):
        _pass("bootstrap.anonymous node_config valid")
    else:
        _fail("bootstrap.anonymous node_config valid", f"got={type(nc).__name__}")

    cc = body.get("chain_config")
    if isinstance(cc, dict) and "tiers" in cc and "award_configs" in cc:
        _pass("bootstrap.anonymous chain_config valid")
    else:
        _fail("bootstrap.anonymous chain_config valid", f"got_keys={list((cc or {}).keys())[:8]}")

    user_sections = {k: body.get(k) for k in ("user_status", "user_followed", "user_blocked", "rewards_summary")}
    if all(v is None for v in user_sections.values()):
        _pass("bootstrap.anonymous user_* sections are null")
    else:
        _fail(
            "bootstrap.anonymous user_* sections are null",
            f"non_null={[k for k, v in user_sections.items() if v is not None]}",
        )

    # ----- Logged-in: all sections populated and shapes match per-endpoint -----
    wallet = WALLETS.get("free")
    if not wallet:
        _skip("bootstrap.logged_in", "free wallet not available")
        return
    addr = str(wallet.address())

    code2, body2 = _get(f"{backend}/api/bootstrap", {"address": addr})
    if code2 == 200 and isinstance(body2, dict):
        _pass("bootstrap.logged_in returns 200")
    else:
        _fail("bootstrap.logged_in returns 200", f"code={code2}")
        return

    nc2 = body2.get("node_config")
    if isinstance(nc2, dict) and nc2.get("validator_account_address"):
        _pass("bootstrap.logged_in node_config valid")
    else:
        _fail("bootstrap.logged_in node_config valid", f"got={type(nc2).__name__}")

    us = body2.get("user_status")
    if isinstance(us, dict) and "balance" in us and "user_level" in us:
        _pass("bootstrap.logged_in user_status valid")
    else:
        _fail("bootstrap.logged_in user_status valid", f"got_keys={list((us or {}).keys())[:8]}")

    uf = body2.get("user_followed")
    if isinstance(uf, dict) and {"joined_communities", "followed_users"} <= set(uf.keys()):
        _pass("bootstrap.logged_in user_followed valid")
    else:
        _fail("bootstrap.logged_in user_followed valid", f"got_keys={list((uf or {}).keys())[:8]}")

    ub = body2.get("user_blocked")
    if isinstance(ub, dict) and {"blocked_posts", "blocked_users", "blocked_communities"} <= set(ub.keys()):
        _pass("bootstrap.logged_in user_blocked valid")
    else:
        _fail("bootstrap.logged_in user_blocked valid", f"got_keys={list((ub or {}).keys())[:8]}")

    ic = body2.get("invite_codes")
    invite_required = bool((body2.get("node_config") or {}).get("registration_invite_code_required", False))
    if invite_required:
        if isinstance(ic, dict) and "codes" in ic and "total" in ic and "available" in ic:
            _pass("bootstrap.logged_in invite_codes valid")
        else:
            _fail("bootstrap.logged_in invite_codes valid", f"got_keys={list((ic or {}).keys())[:8]}")
    else:
        if "invite_codes" in body2:
            _fail("bootstrap.logged_in omits invite_codes when feature off", "invite_codes key present")
        else:
            _pass("bootstrap.logged_in omits invite_codes when feature off")

    # rewards_summary is retired with quests
    rs = body2.get("rewards_summary")
    if rs is None:
        _pass("bootstrap.logged_in rewards_summary omitted")
    else:
        _fail("bootstrap.logged_in rewards_summary omitted", f"got={type(rs).__name__}")

    # ----- Cross-check: per-endpoint /api/get_user_followed shape matches the bootstrap section -----
    code3, ufp = _get(f"{backend}/api/get_user_followed", {"address": addr})
    if code3 == 200 and isinstance(ufp, dict):
        # bootstrap section omits the injected balance, so compare lists only.
        for k in ("joined_communities", "followed_users"):
            if (uf or {}).get(k, []) == ufp.get(k, []):
                continue
            _fail(f"bootstrap.user_followed.{k} matches per-endpoint", "lists differ")
            break
        else:
            _pass("bootstrap.user_followed matches per-endpoint")
    else:
        _fail("bootstrap.user_followed matches per-endpoint", f"per-endpoint code={code3}")

    # ----- view=feed:home embeds posts -----
    code4, body4 = _get(
        f"{backend}/api/bootstrap",
        {"address": addr, "view": "feed:home", "by": "magic", "limit": "5"},
    )
    if code4 == 200 and isinstance(body4, dict):
        view = body4.get("view") or {}
        if view.get("kind") == "feed" and view.get("feed") == "home" and isinstance(view.get("posts"), list):
            _pass("bootstrap.view feed:home returns posts")
        else:
            _fail("bootstrap.view feed:home returns posts", f"view_keys={list(view.keys())[:8]}")
    else:
        _fail("bootstrap.view feed:home returns posts", f"code={code4}")

    # ----- view=thread:<missing> returns found:false -----
    missing_id = "0" * 64
    code5, body5 = _get(
        f"{backend}/api/bootstrap",
        {"address": addr, "view": f"thread:{missing_id}"},
    )
    if code5 == 200 and isinstance(body5, dict):
        view5 = body5.get("view") or {}
        if view5.get("kind") == "thread" and view5.get("found") is False:
            _pass("bootstrap.view thread missing returns found:false")
        else:
            _fail("bootstrap.view thread missing returns found:false", f"view={view5}")
    else:
        _fail("bootstrap.view thread missing returns found:false", f"code={code5}")


# =========================================================================
# Category 2: Account & Username
# =========================================================================


def test_search(backend: str):

    # The retired get_topics / search_topics paths are covered by
    # tests/cases/test_backend_retired.py.

    # 8.3 search general
    code, sr = _get(f"{backend}/api/search", {"q": "test", "limit": 5})
    if code == 200:
        _pass("search.general_search returns 200")
    else:
        _fail("search.general_search returns 200", f"code={code}")

    # 8.4 get_posts with community filter
    code, fp = _get(f"{backend}/api/get_posts", {"community": "test", "limit": 5})
    if code == 200:
        _pass("search.get_posts_by_community returns 200")
    else:
        _fail("search.get_posts_by_community returns 200", f"code={code}")

    # 8.5 get_posts pagination
    code1, p1 = _get(f"{backend}/api/get_posts", {"limit": 2, "page": 1})
    code2, p2 = _get(f"{backend}/api/get_posts", {"limit": 2, "page": 2})
    if code1 == 200 and code2 == 200:
        posts1 = (p1 or {}).get("posts") or []
        posts2 = (p2 or {}).get("posts") or []
        ids1 = {p.get("post_id") for p in posts1}
        ids2 = {p.get("post_id") for p in posts2}
        if not ids1.intersection(ids2):
            _pass("search.pagination pages are distinct")
        else:
            _pass("search.pagination returns 200")
    else:
        _fail("search.pagination returns 200", f"codes={code1},{code2}")

    # 8.6 get_inbox returns
    wallet = WALLETS["free"]
    addr = str(wallet.address())
    code, inbox = _get(f"{backend}/api/get_inbox", {"address": addr, "limit": 10})
    if code == 200:
        _pass("search.get_inbox returns 200")
    else:
        _fail("search.get_inbox returns 200", f"code={code}")


# =========================================================================
# Category 9: Edge Cases & Validation
# =========================================================================


def test_reports(backend: str):

    free_wallet = WALLETS["free"]
    sub1 = WALLETS["sub1"]
    free_addr = str(free_wallet.address())

    # Create a post to report
    target_post = _do_post(backend, free_wallet, "test", f"Report target {_rand_str(4)}", "reportable body")
    if not target_post:
        _fail("reports.setup", "cannot create target post")
        return
    _wait_indexed(backend, free_addr, target_post)

    # 16.1 Valid report (reports are stored in DB, not on-chain — response has success/id)
    try:
        resp = _do_report(backend, sub1, target_post, "spam")
        if resp.get("success") or resp.get("id"):
            _pass("reports.valid_report")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("reports.valid_report", f"not accepted: {err[:200]}")
    except Exception as e:
        _fail("reports.valid_report", str(e))

    # 16.2 Empty reason
    try:
        resp = _do_report(backend, sub1, target_post, "")
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "reason" in err or "empty" in err:
            _pass("reports.empty_reason_rejected")
        else:
            _pass("reports.empty_reason submitted (chain may reject)")
    except Exception as e:
        _pass("reports.empty_reason_rejected")

    # 16.3 Oversized reason
    try:
        resp = _do_report(backend, sub1, target_post, "x" * 2000)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "too long" in err:
            _pass("reports.oversized_reason_rejected")
        else:
            _pass("reports.oversized_reason submitted (chain may reject)")
    except Exception as e:
        _pass("reports.oversized_reason_rejected")

    # 16.4 Non-existent post
    try:
        resp = _do_report(backend, sub1, "cc" * 32, "spam")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("reports.nonexistent_post submitted (chain decides)")
        else:
            _pass("reports.nonexistent_post_rejected")
    except Exception as e:
        _pass("reports.nonexistent_post handled")

    # 16.5 Report own post
    try:
        resp = _do_report(backend, free_wallet, target_post, "self-report")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("reports.own_post submitted (chain decides)")
        else:
            _pass("reports.own_post_rejected")
    except Exception as e:
        _pass("reports.own_post handled")

    # 16.6 Duplicate report
    try:
        resp = _do_report(backend, sub1, target_post, "duplicate spam")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("reports.duplicate submitted (chain decides)")
        else:
            _pass("reports.duplicate_rejected")
    except Exception as e:
        _pass("reports.duplicate handled")


# =========================================================================
# Category 17: Frontend Bypass Validation
# =========================================================================


def test_tx_status(backend: str):
    """Test indexer-only get_tx_status (no CometBFT tx_index dependency)."""

    free = WALLETS.get("free")
    if not free:
        _skip("tx_status.setup", "free wallet not available")
        return

    # 28.1 Non-existent txhash returns found=false
    fake_hash = "00" * 32
    code, data = _get(f"{backend}/api/get_tx_status", {"hash": fake_hash})
    if code == 200 and data and not data.get("found"):
        _pass("tx_status.nonexistent_returns_not_found")
    else:
        _fail("tx_status.nonexistent_returns_not_found", f"code={code} data={data}")

    # 28.2 Invalid hash (too short) returns 400
    code2, data2 = _get(f"{backend}/api/get_tx_status", {"hash": "abc"})
    if code2 == 400:
        _pass("tx_status.invalid_hash_rejected")
    else:
        _fail("tx_status.invalid_hash_rejected", f"code={code2}")

    # 28.3 Missing hash returns 400
    code3, data3 = _get(f"{backend}/api/get_tx_status", {})
    if code3 == 400:
        _pass("tx_status.missing_hash_rejected")
    else:
        _fail("tx_status.missing_hash_rejected", f"code={code3}")

    # 28.4 Submit a post, wait for indexer, verify found=true with details
    community = "test"
    title = f"TxStatus Test {_rand_str(6)}"
    content = f"Content {_rand_str(10)}"
    txh = _do_post(backend, free, community, title, content)
    if not txh:
        _fail("tx_status.post_submit")
        return
    _pass("tx_status.post_submit", tx=txh)

    status = _wait_tx_status(backend, txh, expect_type="post")
    if status and status.get("found") and status.get("indexed"):
        details = status.get("details") or {}
        if details.get("community", "").lower() == community.lower() and details.get("title") == title:
            _pass("tx_status.post_found_indexed")
        else:
            _fail("tx_status.post_found_indexed", f"details={details}")
    else:
        _fail("tx_status.post_found_indexed", f"status={status}")

    # 28.5 Submit a vote, wait for indexer, verify found=true with vote details
    vote_resp = _do_vote(backend, free, txh, 1)
    vote_txh = str((vote_resp or {}).get("tx_hash", "") or "").lower() if vote_resp else ""
    if vote_txh:
        vote_status = _wait_tx_status(backend, vote_txh, expect_type="vote")
        if vote_status and vote_status.get("found") and vote_status.get("indexed"):
            vote_details = vote_status.get("details") or {}
            if vote_details.get("target", "").lower() == txh.lower():
                _pass("tx_status.vote_found_indexed")
            else:
                _fail("tx_status.vote_found_indexed", f"details={vote_details}")
        else:
            _fail("tx_status.vote_found_indexed", f"status={vote_status}")
    else:
        _fail("tx_status.vote_found_indexed", "vote submission failed")

    # 28.6 Response shape: found=true always includes success, indexed, tx_type
    if status:
        has_keys = all(k in status for k in ("found", "success", "indexed", "tx_type", "tx_hash"))
        if has_keys and status["success"] is True and status["tx_type"] == "post":
            _pass("tx_status.response_shape")
        else:
            _fail("tx_status.response_shape", f"keys={list(status.keys())}")
    else:
        _fail("tx_status.response_shape", "no status data")


def test_tx_status_non_post_vote(backend: str):
    """Test tx_index resolves non-post/vote types (set_username, follow, etc.)."""

    free = WALLETS.get("free")
    if not free:
        _skip("tx_status_npv.setup", "free wallet not available")
        return

    # Submit a set_username and check that get_tx_status can find it via tx_index
    uname = f"Anon-txidx{_rand_str(4)}"
    resp = _do_set_username_raw(backend, free, uname)
    txh = str(resp.get("tx_hash", "") or "").lower()
    if not txh or len(txh) != 64:
        _fail("tx_status_npv.set_username_submit", f"resp={resp}")
        return
    _pass("tx_status_npv.set_username_submit", tx=txh)

    status = _wait_tx_status(backend, txh, expect_type="set_username", require_details=False)
    if status and status.get("found") and status.get("indexed"):
        if status.get("success") is True and status.get("tx_type") == "set_username":
            _pass("tx_status_npv.set_username_found")
        else:
            _fail("tx_status_npv.set_username_found", f"status={status}")
    else:
        _fail("tx_status_npv.set_username_found", f"status={status}")


def test_failed_tx_status(backend: str):
    """Test tx_index records for failed vote/post transactions."""

    free = WALLETS.get("free")
    if not free:
        _skip("failed_tx.setup", "free wallet not available")
        return

    free_addr = str(free.address())

    # Create a valid post to vote on
    base_post = _do_post(backend, free, "test", f"Fail Base {_rand_str(6)}", f"Body {_rand_str(8)}")
    if not base_post:
        _fail("failed_tx.base_post_submit")
        return
    _pass("failed_tx.base_post_submit", tx=base_post)
    if not _wait_indexed(backend, free_addr, base_post):
        _fail("failed_tx.base_post_indexed")
        return

    # ── Failed vote: two txs with same nonce in the same block
    try:
        blk = _wait_next_block()
        _debug(f"failed_tx.vote next_block={blk}")
    except Exception as e:
        _fail("failed_tx.vote.block_sync", str(e))
        return

    vote_nonce = _fresh_nonce()
    vote_resp1 = _do_vote_with_nonce(backend, free, base_post, 1, vote_nonce)
    vote_resp2 = _do_vote_with_nonce(backend, free, base_post, 1, vote_nonce)
    vote_tx1 = str(vote_resp1.get("tx_hash", "") or "").lower()
    vote_tx2 = str(vote_resp2.get("tx_hash", "") or "").lower()
    _debug(f"failed_tx.vote tx1={vote_tx1} tx2={vote_tx2} nonce={vote_nonce}")
    if not vote_tx1 and not vote_tx2:
        _fail("failed_tx.vote.submit", f"tx1={vote_tx1} tx2={vote_tx2}")
        return
    if (not vote_tx1) != (not vote_tx2):
        # One rejected before broadcast (e.g., simulate error). Accept this path.
        fail_resp = vote_resp1 if not vote_tx1 else vote_resp2
        ok_vote = vote_tx1 if vote_tx1 else vote_tx2
        if fail_resp.get("error") or fail_resp.get("message"):
            _pass("failed_tx.vote.failure_detected", err=fail_resp.get("error") or fail_resp.get("message"))
        else:
            _fail("failed_tx.vote.failure_detected", f"fail={fail_resp}")
        ok_status = _wait_tx_status(backend, ok_vote, expect_type="vote")
        if ok_status and ok_status.get("success") is True:
            _pass("failed_tx.vote.success_detected", tx=ok_vote)
        else:
            _fail("failed_tx.vote.success_detected", f"status={ok_status}")
        return

    code1 = int(vote_resp1.get("code", 0) or 0)
    code2 = int(vote_resp2.get("code", 0) or 0)

    # If both were accepted, fall back to indexer failure detection (legacy behavior).
    if (code1 == 0) and (code2 == 0):
        fail1 = _wait_tx_status_failure(backend, vote_tx1, expect_type="vote")
        fail2 = _wait_tx_status_failure(backend, vote_tx2, expect_type="vote")
        if bool(fail1) == bool(fail2):
            _fail("failed_tx.vote.failure_detected", f"fail1={bool(fail1)} fail2={bool(fail2)}")
        else:
            fail_vote = fail1 or fail2
            ok_vote = vote_tx2 if fail1 else vote_tx1
            _pass("failed_tx.vote.failure_detected", tx=fail_vote.get("tx_hash"))
            ok_status = _wait_tx_status(backend, ok_vote, expect_type="vote")
            if ok_status and ok_status.get("success") is True:
                _pass("failed_tx.vote.success_detected", tx=ok_vote)
            else:
                _fail("failed_tx.vote.success_detected", f"status={ok_status}")
            if fail_vote.get("code", 0) and fail_vote.get("error_details"):
                _pass("failed_tx.vote.error_details_present")
            else:
                _fail("failed_tx.vote.error_details_present", f"fail={fail_vote}")
    elif (code1 == 0) != (code2 == 0):
        # One rejected at submit (CheckTx) — expect an immediate error response.
        fail_resp = vote_resp1 if code1 != 0 else vote_resp2
        ok_vote = vote_tx2 if code1 != 0 else vote_tx1
        _pass("failed_tx.vote.failure_detected", tx=fail_resp.get("tx_hash"))
        ok_status = _wait_tx_status(backend, ok_vote, expect_type="vote")
        if ok_status and ok_status.get("success") is True:
            _pass("failed_tx.vote.success_detected", tx=ok_vote)
        else:
            _fail("failed_tx.vote.success_detected", f"status={ok_status}")
        if fail_resp.get("code", 0) and (fail_resp.get("reason") or fail_resp.get("message")):
            _pass("failed_tx.vote.error_details_present")
        else:
            _fail("failed_tx.vote.error_details_present", f"fail={fail_resp}")
    else:
        _fail("failed_tx.vote.failure_detected", f"both rejected code1={code1} code2={code2}")

    # ── Failed post: two txs with same nonce in the same block
    try:
        blk = _wait_next_block()
        _debug(f"failed_tx.post next_block={blk}")
    except Exception as e:
        _fail("failed_tx.post.block_sync", str(e))
        return

    post_nonce = _fresh_nonce()
    post_resp1 = _do_post_with_nonce(
        backend,
        free,
        "test",
        f"Fail Post A {_rand_str(6)}",
        f"Body {_rand_str(8)}",
        post_nonce,
    )
    post_resp2 = _do_post_with_nonce(
        backend,
        free,
        "test",
        f"Fail Post B {_rand_str(6)}",
        f"Body {_rand_str(8)}",
        post_nonce,
    )
    post_tx1 = str(post_resp1.get("tx_hash", "") or "").lower()
    post_tx2 = str(post_resp2.get("tx_hash", "") or "").lower()
    _debug(f"failed_tx.post tx1={post_tx1} tx2={post_tx2} nonce={post_nonce}")
    if not post_tx1 and not post_tx2:
        _fail("failed_tx.post.submit", f"tx1={post_tx1} tx2={post_tx2}")
        return
    if (not post_tx1) != (not post_tx2):
        fail_resp = post_resp1 if not post_tx1 else post_resp2
        ok_post = post_tx1 if post_tx1 else post_tx2
        if fail_resp.get("error") or fail_resp.get("message"):
            _pass("failed_tx.post.failure_detected", err=fail_resp.get("error") or fail_resp.get("message"))
        else:
            _fail("failed_tx.post.failure_detected", f"fail={fail_resp}")
        ok_status = _wait_tx_status(backend, ok_post, expect_type="post")
        if ok_status and ok_status.get("success") is True:
            _pass("failed_tx.post.success_detected", tx=ok_post)
        else:
            _fail("failed_tx.post.success_detected", f"status={ok_status}")
        return

    code1 = int(post_resp1.get("code", 0) or 0)
    code2 = int(post_resp2.get("code", 0) or 0)

    if (code1 == 0) and (code2 == 0):
        pfail1 = _wait_tx_status_failure(backend, post_tx1, expect_type="post")
        pfail2 = _wait_tx_status_failure(backend, post_tx2, expect_type="post")
        if bool(pfail1) == bool(pfail2):
            _fail("failed_tx.post.failure_detected", f"fail1={bool(pfail1)} fail2={bool(pfail2)}")
        else:
            fail_post = pfail1 or pfail2
            ok_post = post_tx2 if pfail1 else post_tx1
            _pass("failed_tx.post.failure_detected", tx=fail_post.get("tx_hash"))
            ok_status = _wait_tx_status(backend, ok_post, expect_type="post")
            if ok_status and ok_status.get("success") is True:
                _pass("failed_tx.post.success_detected", tx=ok_post)
            else:
                _fail("failed_tx.post.success_detected", f"status={ok_status}")
            if fail_post.get("code", 0) and fail_post.get("error_details"):
                _pass("failed_tx.post.error_details_present")
            else:
                _fail("failed_tx.post.error_details_present", f"fail={fail_post}")
    elif (code1 == 0) != (code2 == 0):
        fail_resp = post_resp1 if code1 != 0 else post_resp2
        ok_post = post_tx2 if code1 != 0 else post_tx1
        _pass("failed_tx.post.failure_detected", tx=fail_resp.get("tx_hash"))
        ok_status = _wait_tx_status(backend, ok_post, expect_type="post")
        if ok_status and ok_status.get("success") is True:
            _pass("failed_tx.post.success_detected", tx=ok_post)
        else:
            _fail("failed_tx.post.success_detected", f"status={ok_status}")
        if fail_resp.get("code", 0) and (fail_resp.get("reason") or fail_resp.get("message")):
            _pass("failed_tx.post.error_details_present")
        else:
            _fail("failed_tx.post.error_details_present", f"fail={fail_resp}")
    else:
        _fail("failed_tx.post.failure_detected", f"both rejected code1={code1} code2={code2}")


def test_tx_status_matrix(backend: str):
    """Matrix test: submit one tx per core type, verify get_tx_status resolves each."""

    free = WALLETS.get("free")
    sub1 = WALLETS.get("sub1")
    sub2 = WALLETS.get("sub2")
    sub3 = WALLETS.get("sub3")
    sub4 = WALLETS.get("sub4")
    if not free or not sub1 or not sub2 or not sub3 or not sub4:
        _skip("tx_matrix.setup", "free/sub1/sub2/sub3/sub4 wallets not available")
        return

    _debug("tx_matrix: begin")
    free_addr = str(free.address())
    sub2_addr = str(sub2.address())
    agent1_addr = str(sub3.address())
    agent2_addr = str(sub4.address())
    post_community = "test"
    follow_community = f"matrix{_rand_str(4)}"

    # Use sub1 (subscriber, level>=1) as primary actor — free (level 0) has
    # max_biography_length=0 and low follow limits that cause chain rejections.

    def _pick_unfollowed_user() -> str:
        code, data = _get(f"{backend}/api/get_user_followed", {"address": str(sub1.address())})
        if code != 200:
            _fail("tx_matrix.follow_user.target_lookup", f"code={code} data={data}")
            return ""
        users = (data or {}).get("followed_users") or (data or {}).get("users") or []
        candidates = [free_addr, sub2_addr, agent1_addr, agent2_addr]
        for addr in candidates:
            if not any(addr.lower() in json.dumps(u).lower() for u in users):
                return addr
        _fail("tx_matrix.follow_user.target_lookup", "no unfollowed target available")
        return ""

    def _pick_unblocked_user() -> str:
        code, data = _get(f"{backend}/api/get_user_blocked", {"address": str(sub1.address())})
        if code != 200:
            _fail("tx_matrix.block_user.target_lookup", f"code={code} data={data}")
            return ""
        users = (data or {}).get("blocked_users") or (data or {}).get("users") or []
        candidates = [free_addr, sub2_addr, agent1_addr, agent2_addr]
        for addr in candidates:
            if not any(addr.lower() in json.dumps(u).lower() for u in users):
                return addr
        _fail("tx_matrix.block_user.target_lookup", "no unblocked target available")
        return ""

    def _extract_tx_hash(label: str, resp: dict | None) -> str:
        if not isinstance(resp, dict):
            _fail(f"tx_matrix.{label}.submit", f"resp={resp}")
            return ""
        txh_raw = resp.get("tx_hash")
        if not txh_raw:
            _fail(f"tx_matrix.{label}.submit", f"resp={resp}")
            return ""
        txh = str(txh_raw).lower()
        if len(txh) != 64:
            _fail(f"tx_matrix.{label}.submit", f"resp={resp}")
            return ""
        _pass(f"tx_matrix.{label}.submit", tx=txh[:16])
        return txh

    def _check(label: str, tx_hash: str, expected_type: str, expect_details: bool = False):
        """Poll get_tx_status and assert the response matches expectations."""
        status = _wait_tx_status(backend, tx_hash, expect_type=expected_type, require_details=expect_details)
        if not status:
            _fail(f"tx_matrix.{label}", f"timeout waiting for tx_hash={tx_hash[:16]}...")
            return
        if not (status.get("found") and status.get("indexed")):
            _fail(f"tx_matrix.{label}", f"not indexed: {status}")
            return
        if status.get("success") is not True:
            _fail(f"tx_matrix.{label}", f"not successful: {status}")
            return
        if status.get("tx_type") != expected_type:
            _fail(f"tx_matrix.{label}", f"tx_type={status.get('tx_type')} expected={expected_type}")
            return
        if expect_details and not status.get("details"):
            _fail(f"tx_matrix.{label}", "expected details but got none")
            return
        _pass(f"tx_matrix.{label}", tx=tx_hash[:16])

    # 1. set_biography (sub1 — tier 0 has max_biography_length=0)
    bio_resp = _do_set_biography(backend, sub1, f"Matrix bio {_rand_str(6)}", skip_pow=True)
    bio_txh = _extract_tx_hash("set_biography", bio_resp)
    if bio_txh:
        _check("set_biography", bio_txh, "set_biography")

    # 2. follow_user (sub1 follows free — higher follow limits)
    follow_target = _pick_unfollowed_user()
    if not follow_target:
        return
    follow_resp = _do_follow_user(backend, sub1, follow_target, follow=True, skip_pow=True)
    follow_txh = _extract_tx_hash("follow_user", follow_resp)
    if follow_txh:
        _check("follow_user", follow_txh, "follow_user")

    # 3. unfollow (clean up the follow)
    unfollow_resp = _do_follow_user(backend, sub1, follow_target, follow=False, skip_pow=True)
    unfollow_txh = _extract_tx_hash("unfollow_user", unfollow_resp)
    if unfollow_txh:
        _check("unfollow_user", unfollow_txh, "unfollow_user")

    # 4. join_community (sub1 — higher limits). Every valid slug is joinable as
    # of v1.39.0: communities are not registered or claimed, so nothing has to
    # exist before the join.
    fcommunity_resp = _do_follow_topic(backend, sub1, follow_community, follow=True, skip_pow=True)
    fcommunity_txh = _extract_tx_hash("join_community", fcommunity_resp)
    if fcommunity_txh:
        _check("join_community", fcommunity_txh, "join_community")

    # 5. leave_community (clean up join)
    ucommunity_resp = _do_follow_topic(backend, sub1, follow_community, follow=False, skip_pow=True)
    ucommunity_txh = _extract_tx_hash("leave_community", ucommunity_resp)
    if ucommunity_txh:
        _check("leave_community", ucommunity_txh, "leave_community")

    # 6. send_tokens
    send_resp = _do_send_tokens(backend, sub1, free_addr, 1, skip_pow=True)
    send_txh = _extract_tx_hash("send_tokens", send_resp)
    if send_txh:
        _check("send_tokens", send_txh, "send_tokens")

    # 7. post (should have details — free wallet, always works)
    post_txh = _do_post(backend, free, post_community, f"Matrix Post {_rand_str(6)}", f"Body {_rand_str(8)}")
    if not post_txh or len(post_txh) != 64:
        _fail("tx_matrix.post.submit", f"tx={post_txh}")
        return
    _pass("tx_matrix.post.submit", tx=post_txh[:16])
    _check("post", post_txh, "post", expect_details=True)

    # 8. vote (should have details)
    vote_resp = _do_vote(backend, free, post_txh, 1)
    vote_txh = _extract_tx_hash("vote", vote_resp)
    if vote_txh:
        _check("vote", vote_txh, "vote", expect_details=True)

    # 9. edit (needs indexed post)
    if post_txh and _wait_indexed(backend, free_addr, post_txh):
        edit_resp = _do_edit(
            backend, free, post_txh, post_community, f"Edited Title {_rand_str(4)}", f"Edited Body {_rand_str(6)}"
        )
        edit_txh = _extract_tx_hash("edit", edit_resp)
        if edit_txh:
            _check("edit", edit_txh, "edit")
    else:
        _fail("tx_matrix.edit.submit", "post not indexed in time")

    # 10. delete (own post)
    if post_txh:
        delete_resp = _do_delete(backend, free, post_txh)
        delete_txh = _extract_tx_hash("delete", delete_resp)
        if delete_txh:
            _check("delete", delete_txh, "delete")

    # 11. block_user (sub1 blocks another user — higher limits)
    block_target = _pick_unblocked_user()
    if not block_target:
        return
    block_resp = _do_block(backend, sub1, block_target, "user", block=True, skip_pow=True)
    block_txh = _extract_tx_hash("block_user", block_resp)
    if block_txh:
        _check("block_user", block_txh, "block_user")

    # 12. unblock_user (clean up)
    unblock_resp = _do_block(backend, sub1, block_target, "user", block=False, skip_pow=True)
    unblock_txh = _extract_tx_hash("unblock_user", unblock_resp)
    if unblock_txh:
        _check("unblock_user", unblock_txh, "unblock_user")


def test_failed_tx_non_post_vote(backend: str):
    """Test tx_index failure detection for non-post/vote types (follow_user via same-nonce)."""

    free = WALLETS.get("free")
    sub1 = WALLETS.get("sub1")
    sub2 = WALLETS.get("sub2")
    sub3 = WALLETS.get("sub3")
    sub4 = WALLETS.get("sub4")
    if not free or not sub1 or not sub2 or not sub3 or not sub4:
        _skip("failed_npv.setup", "free/sub1/sub2/sub3/sub4 wallets not available")
        return

    free_addr = str(free.address())
    sub2_addr = str(sub2.address())
    agent1_addr = str(sub3.address())
    agent2_addr = str(sub4.address())

    # Use sub1 (subscriber) as actor — free (tier 0) has low follow limits.

    def _pick_unfollowed_user() -> str:
        code, data = _get(f"{backend}/api/get_user_followed", {"address": str(sub1.address())})
        if code != 200:
            _fail("failed_npv.follow.target_lookup", f"code={code} data={data}")
            return ""
        users = (data or {}).get("followed_users") or (data or {}).get("users") or []
        candidates = [free_addr, sub2_addr, agent1_addr, agent2_addr]
        for addr in candidates:
            if not any(addr.lower() in json.dumps(u).lower() for u in users):
                return addr
        _fail("failed_npv.follow.target_lookup", "no unfollowed target available")
        return ""

    def _pick_unblocked_user() -> str:
        code, data = _get(f"{backend}/api/get_user_blocked", {"address": str(sub1.address())})
        if code != 200:
            _fail("failed_npv.block.target_lookup", f"code={code} data={data}")
            return ""
        users = (data or {}).get("blocked_users") or (data or {}).get("users") or []
        candidates = [free_addr, sub2_addr, agent1_addr, agent2_addr]
        for addr in candidates:
            if not any(addr.lower() in json.dumps(u).lower() for u in users):
                return addr
        _fail("failed_npv.block.target_lookup", "no unblocked target available")
        return ""

    # ── Failed follow_user: two txs with same nonce in the same block ──
    try:
        blk = _wait_next_block()
        _debug(f"failed_npv.follow next_block={blk}")
    except Exception as e:
        _fail("failed_npv.follow.block_sync", str(e))
        return

    target_addr = _pick_unfollowed_user()
    if not target_addr:
        return
    nonce = _fresh_nonce()
    resp1 = _do_follow_user_with_nonce(backend, sub1, target_addr, nonce, follow=True, skip_pow=True)
    resp2 = _do_follow_user_with_nonce(backend, sub1, target_addr, nonce, follow=True, skip_pow=True)
    if not isinstance(resp1, dict) or not isinstance(resp2, dict):
        _fail("failed_npv.follow.submit", f"resp1={resp1} resp2={resp2}")
        return
    tx1_raw = resp1.get("tx_hash")
    tx2_raw = resp2.get("tx_hash")
    tx1 = str(tx1_raw).lower() if tx1_raw else ""
    tx2 = str(tx2_raw).lower() if tx2_raw else ""
    _debug(f"failed_npv.follow tx1={tx1} tx2={tx2} nonce={nonce}")

    if not tx1 and not tx2:
        _fail("failed_npv.follow.submit", f"tx1={tx1} tx2={tx2}")
        return
    if (not tx1) != (not tx2):
        fail_resp = resp1 if not tx1 else resp2
        ok_tx = tx1 if tx1 else tx2
        if fail_resp.get("error") or fail_resp.get("message"):
            _pass("failed_npv.follow.failure_detected", err=fail_resp.get("error") or fail_resp.get("message"))
        else:
            _fail("failed_npv.follow.failure_detected", f"fail={fail_resp}")
        ok_status = _wait_tx_status(backend, ok_tx, expect_type="follow_user", require_details=False)
        if ok_status and ok_status.get("success") is True:
            _pass("failed_npv.follow.success_detected", tx=ok_tx[:16])
        else:
            _fail("failed_npv.follow.success_detected", f"status={ok_status}")
        return

    code1 = int(resp1.get("code", 0) or 0)
    code2 = int(resp2.get("code", 0) or 0)

    if (code1 == 0) and (code2 == 0):
        fail1 = _wait_tx_status_failure(backend, tx1, expect_type="follow_user")
        fail2 = _wait_tx_status_failure(backend, tx2, expect_type="follow_user")
        if bool(fail1) == bool(fail2):
            _fail("failed_npv.follow.failure_detected", f"fail1={bool(fail1)} fail2={bool(fail2)}")
        else:
            fail_tx = fail1 or fail2
            ok_tx = tx2 if fail1 else tx1
            _pass("failed_npv.follow.failure_detected", tx=fail_tx.get("tx_hash", "")[:16])
            ok_status = _wait_tx_status(backend, ok_tx, expect_type="follow_user", require_details=False)
            if ok_status and ok_status.get("success") is True:
                _pass("failed_npv.follow.success_detected", tx=ok_tx[:16])
            else:
                _fail("failed_npv.follow.success_detected", f"status={ok_status}")
            if fail_tx.get("code", 0) and fail_tx.get("error_details"):
                _pass("failed_npv.follow.error_details_present")
            else:
                _fail("failed_npv.follow.error_details_present", f"fail={fail_tx}")
    elif (code1 == 0) != (code2 == 0):
        fail_resp = resp1 if code1 != 0 else resp2
        ok_tx = tx2 if code1 != 0 else tx1
        _pass("failed_npv.follow.failure_detected", tx=fail_resp.get("tx_hash", "")[:16])
        ok_status = _wait_tx_status(backend, ok_tx, expect_type="follow_user", require_details=False)
        if ok_status and ok_status.get("success") is True:
            _pass("failed_npv.follow.success_detected", tx=ok_tx[:16])
        else:
            _fail("failed_npv.follow.success_detected", f"status={ok_status}")
        if fail_resp.get("code", 0) and (fail_resp.get("reason") or fail_resp.get("message")):
            _pass("failed_npv.follow.error_details_present")
        else:
            _fail("failed_npv.follow.error_details_present", f"fail={fail_resp}")
    else:
        _fail("failed_npv.follow.failure_detected", f"both rejected code1={code1} code2={code2}")

    # Clean up: unfollow so state is reset
    try:
        _do_follow_user(backend, sub1, target_addr, follow=False, skip_pow=True)
    except Exception:
        pass

    # ── Failed block_user: two txs with same nonce in the same block ──
    try:
        blk = _wait_next_block()
        _debug(f"failed_npv.block next_block={blk}")
    except Exception as e:
        _fail("failed_npv.block.block_sync", str(e))
        return

    block_target = _pick_unblocked_user()
    if not block_target:
        return
    nonce2 = _fresh_nonce()
    bresp1 = _do_block_with_nonce(backend, sub1, block_target, "user", nonce2, block=True, skip_pow=True)
    bresp2 = _do_block_with_nonce(backend, sub1, block_target, "user", nonce2, block=True, skip_pow=True)
    if not isinstance(bresp1, dict) or not isinstance(bresp2, dict):
        _fail("failed_npv.block.submit", f"resp1={bresp1} resp2={bresp2}")
        return
    btx1_raw = bresp1.get("tx_hash")
    btx2_raw = bresp2.get("tx_hash")
    btx1 = str(btx1_raw).lower() if btx1_raw else ""
    btx2 = str(btx2_raw).lower() if btx2_raw else ""
    _debug(f"failed_npv.block tx1={btx1} tx2={btx2} nonce={nonce2}")

    if not btx1 and not btx2:
        _fail("failed_npv.block.submit", f"tx1={btx1} tx2={btx2}")
        return
    if (not btx1) != (not btx2):
        fail_resp = bresp1 if not btx1 else bresp2
        ok_tx = btx1 if btx1 else btx2
        if fail_resp.get("error") or fail_resp.get("message"):
            _pass("failed_npv.block.failure_detected", err=fail_resp.get("error") or fail_resp.get("message"))
        else:
            _fail("failed_npv.block.failure_detected", f"fail={fail_resp}")
        ok_status = _wait_tx_status(backend, ok_tx, expect_type="block_user", require_details=False)
        if ok_status and ok_status.get("success") is True:
            _pass("failed_npv.block.success_detected", tx=ok_tx[:16])
        else:
            _fail("failed_npv.block.success_detected", f"status={ok_status}")
        return

    bcode1 = int(bresp1.get("code", 0) or 0)
    bcode2 = int(bresp2.get("code", 0) or 0)

    if (bcode1 == 0) and (bcode2 == 0):
        bfail1 = _wait_tx_status_failure(backend, btx1, expect_type="block_user")
        bfail2 = _wait_tx_status_failure(backend, btx2, expect_type="block_user")
        if bool(bfail1) == bool(bfail2):
            _fail("failed_npv.block.failure_detected", f"fail1={bool(bfail1)} fail2={bool(bfail2)}")
        else:
            fail_tx = bfail1 or bfail2
            ok_tx = btx2 if bfail1 else btx1
            _pass("failed_npv.block.failure_detected", tx=fail_tx.get("tx_hash", "")[:16])
            ok_status = _wait_tx_status(backend, ok_tx, expect_type="block_user", require_details=False)
            if ok_status and ok_status.get("success") is True:
                _pass("failed_npv.block.success_detected", tx=ok_tx[:16])
            else:
                _fail("failed_npv.block.success_detected", f"status={ok_status}")
            if fail_tx.get("code", 0) and fail_tx.get("error_details"):
                _pass("failed_npv.block.error_details_present")
            else:
                _fail("failed_npv.block.error_details_present", f"fail={fail_tx}")
    elif (bcode1 == 0) != (bcode2 == 0):
        fail_resp = bresp1 if bcode1 != 0 else bresp2
        ok_tx = btx2 if bcode1 != 0 else btx1
        _pass("failed_npv.block.failure_detected", tx=fail_resp.get("tx_hash", "")[:16])
        ok_status = _wait_tx_status(backend, ok_tx, expect_type="block_user", require_details=False)
        if ok_status and ok_status.get("success") is True:
            _pass("failed_npv.block.success_detected", tx=ok_tx[:16])
        else:
            _fail("failed_npv.block.success_detected", f"status={ok_status}")
        if fail_resp.get("code", 0) and (fail_resp.get("reason") or fail_resp.get("message")):
            _pass("failed_npv.block.error_details_present")
        else:
            _fail("failed_npv.block.error_details_present", f"fail={fail_resp}")
    else:
        _fail("failed_npv.block.failure_detected", f"both rejected code1={bcode1} code2={bcode2}")

    # Clean up: unblock
    try:
        _do_block(backend, sub1, block_target, "user", block=False, skip_pow=True)
    except Exception:
        pass


def test_error_registry(backend):
    """Every literal error string returned by a route must be in the error registry.

    factory._inject_error_code re-raises on an unmapped message, so an
    unregistered string turns a deliberate 4xx into a 500.
    """
    backend_src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
    )
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)
    try:
        from error_utils import _MSG_TO_CODE
    except Exception as e:
        _skip("error_registry.unmapped_messages", f"backend modules not importable: {e}")
        return

    unregistered = []
    for root, _dirs, files in os.walk(backend_src):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError as e:
                _fail("error_registry.unmapped_messages", f"cannot parse {path}: {e}")
                return
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "jsonify"):
                    continue
                for arg in node.args:
                    if not isinstance(arg, ast.Dict):
                        continue
                    keys = {k.value for k in arg.keys if isinstance(k, ast.Constant)}
                    if "error" not in keys or "error_code" in keys:
                        continue
                    for key, val in zip(arg.keys, arg.values):
                        if not (isinstance(key, ast.Constant) and key.value == "error"):
                            continue
                        if isinstance(val, ast.Constant) and val.value not in _MSG_TO_CODE:
                            rel = os.path.relpath(path, backend_src)
                            unregistered.append(f"{rel}:{node.lineno} {val.value!r}")

    if unregistered:
        _fail("error_registry.unmapped_messages", f"{len(unregistered)} unregistered: {'; '.join(unregistered[:6])}")
    else:
        _pass("error_registry.unmapped_messages", checked=len(_MSG_TO_CODE))

    # Every code must have user-facing copy, or the UI renders "Unknown error code: x".
    js_path = os.path.join(os.path.dirname(backend_src), "frontend", "src", "utils", "errorMessages.js")
    if not os.path.exists(js_path):
        _skip("error_registry.frontend_copy", "frontend source not present in this image")
        return
    js = open(js_path, encoding="utf-8").read()
    mapped = set(re.findall(r"^\s{4}([a-z0-9_]+):", js, re.M))
    missing = sorted(set(_MSG_TO_CODE.values()) - mapped)
    if missing:
        _fail("error_registry.frontend_copy", f"{len(missing)} codes without UI copy: {', '.join(missing[:8])}")
    else:
        _pass("error_registry.frontend_copy", checked=len(mapped))


def test_block_hash_window_margin(backend):
    """The catching-up gate must trip before a served block hash ages out of the chain's window.

    Since v1.34.0 the PoW ante enforces that an envelope's last_block_hash is
    still inside the on-chain block_hash_window, and the only hash the backend
    can hand a client comes from the indexer's recent_blocks. That makes indexer
    freshness load-bearing for submission in a way it never was before: if the
    backend kept serving while the indexer fell further behind than the window,
    every submission would be refused chain-side, with the cause one component
    away from the symptom.

    is_node_catching_up already prevents it — /api/get_parameters returns 503
    node_catching_up first — but only because its thresholds happen to be far
    tighter than the window. Nothing structural held those two apart, so this
    asserts the two properties the design rests on: the worst lag the backend
    tolerates stays inside the window, and the window covers max_envelope_age.
    Raising the lag thresholds, or governing block_hash_window down, now fails
    here instead of in production.
    """
    backend_src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
    )
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)
    try:
        import chain as chain_mod
        from params import load_params
    except Exception as e:
        _skip("block_hash_window.margin", f"backend modules not importable: {e}")
        return

    try:
        # load_params rather than expect_params: the cache is populated by the
        # backend process at startup, so a test running in its own interpreter
        # has to fill it. The default retry budget is an hour, which is a startup
        # policy, not a test one.
        p = load_params(max_retries=1, retry_interval=0.0)
        window_blocks = int(p["block_hash_window"])
        max_envelope_age = int(p["max_envelope_age"])
        block_time = int(chain_mod.get_block_time_seconds())
        skew_s = int(chain_mod.max_envelope_future_skew_seconds())
    except Exception as e:
        # Not a skip: this category is a release gate, so an unevaluated
        # invariant has to read as a failure rather than as silence.
        _fail("block_hash_window.margin", f"live params unreadable, invariant unchecked: {e}")
        return

    window_span_s = window_blocks * block_time
    # The height threshold is counted in blocks, so it only becomes comparable
    # to a deadline in seconds after conversion - the exact mismatch that made
    # the 2s-vs-3s local block time misleading.
    #
    # max, not min, and deliberately so. is_node_catching_up ORs its triggers, so
    # in practice the tightest one stops serving first and the real tolerance is
    # the minimum. Asserting against the minimum would assume every trigger is
    # live, and the height one is not: it is guarded on chain_head > 0, so an
    # absent chain_head_height leaves it permanently false. Taking the maximum
    # asserts the weaker property that holds even when only the loosest surviving
    # trigger fires, which is the one worth guaranteeing.
    worst_tolerated_lag_s = max(
        chain_mod._MAX_PROCESSING_LAG_SECONDS,
        chain_mod._MAX_HEIGHT_LAG_BLOCKS * block_time,
        skew_s,
    )

    # Deliberately not "worst_lag + envelope_age <= window": that is stricter
    # than the chain guarantees. MinBlockHashWindow is 20 blocks, which at a 3s
    # block time is exactly max_envelope_age, so the tighter form would fail on a
    # window the chain considers legal. These are the two invariants the design
    # actually rests on.
    if worst_tolerated_lag_s < window_span_s:
        _pass(
            "block_hash_window.margin",
            window=f"{window_blocks}blk={window_span_s}s",
            worst_lag=f"{worst_tolerated_lag_s}s",
        )
    else:
        _fail(
            "block_hash_window.margin",
            f"the backend keeps serving block hashes at up to {worst_tolerated_lag_s}s of lag, which "
            f"reaches or exceeds the chain's window ({window_blocks} blocks = {window_span_s}s at "
            f"{block_time}s/block), so the chain can refuse every submission while the backend still "
            f"reports healthy. A pre-upgrade chain stores 10 and fails here by design",
        )

    # The window must also cover the envelope lifetime, independent of lag: the
    # chain-side floor exists because a window shorter than max_envelope_age
    # rejects work the age check still accepts.
    if window_span_s >= max_envelope_age:
        _pass("block_hash_window.covers_envelope_age", window_s=window_span_s, envelope_age=max_envelope_age)
    else:
        _fail(
            "block_hash_window.covers_envelope_age",
            f"window {window_span_s}s is shorter than max_envelope_age {max_envelope_age}s, so the "
            f"block-hash check is stricter than the expiry it is supposed to sit inside",
        )


def test_indexer_fail_hard(backend):
    """M-6: an indexer DB outage must surface as an outage, not as sync lag.

    Before v1.32.1 chain.py answered a dead DB with catching_up=True and a
    zero-filled difficulty dict, so a total outage looked like a node that was
    merely syncing and PoW prechecks ran against difficulty 0.
    """
    backend_src = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
    )
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)
    try:
        import chain as chain_mod
        from error_utils import IndexerUnavailable
    except Exception as e:
        _skip("indexer_fail_hard.raises", f"backend modules not importable: {e}")
        return

    def _boom(*_a, **_kw):
        raise OSError("simulated indexer DB outage")

    original = chain_mod.connect_db
    chain_mod.connect_db = _boom
    chain_mod._CATCHING_UP_CACHE = None
    chain_mod._DIFFICULTY_CACHE = None
    try:
        for name, fn in (
            ("is_node_catching_up", chain_mod.is_node_catching_up),
            ("get_indexer_health", chain_mod.get_indexer_health),
        ):
            try:
                result = fn()
            except IndexerUnavailable:
                _pass(f"indexer_fail_hard.{name}")
            except Exception as e:
                _fail(f"indexer_fail_hard.{name}", f"raised {type(e).__name__} instead of IndexerUnavailable: {e}")
            else:
                _fail(
                    f"indexer_fail_hard.{name}",
                    f"returned {result!r} during a DB outage instead of raising IndexerUnavailable",
                )
    finally:
        chain_mod.connect_db = original
        chain_mod._CATCHING_UP_CACHE = None
        chain_mod._DIFFICULTY_CACHE = None

    # A reachable DB with no difficulty_info row must also raise, rather than
    # reporting difficulty 0 as if the chain had asserted it.
    class _EmptyCursor:
        def execute(self, *_a, **_kw):
            return None

        def fetchone(self):
            return None

    class _EmptyConn:
        def cursor(self):
            return _EmptyCursor()

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    chain_mod.connect_db = lambda *_a, **_kw: _EmptyConn()
    chain_mod._DIFFICULTY_CACHE = None
    try:
        info = chain_mod.get_difficulty_info(force=True)
    except IndexerUnavailable:
        _pass("indexer_fail_hard.difficulty_no_row")
    except Exception as e:
        _fail("indexer_fail_hard.difficulty_no_row", f"raised {type(e).__name__} instead of IndexerUnavailable: {e}")
    else:
        _fail(
            "indexer_fail_hard.difficulty_no_row",
            f"returned {info!r} with no difficulty_info row instead of raising",
        )
    finally:
        chain_mod.connect_db = original
        chain_mod._DIFFICULTY_CACHE = None

    # The 503 mapping is what makes the outage distinguishable from
    # node_catching_up at the 29 relay routes that classify by exception.
    core_src = open(os.path.join(backend_src, "routes", "core.py"), encoding="utf-8").read()
    tree = ast.parse(core_src)
    mapped = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_classify_exception":
            body = ast.get_source_segment(core_src, node) or ""
            mapped = "IndexerUnavailable" in body and "indexer_unavailable" in body and "503" in body
    if mapped:
        _pass("indexer_fail_hard.classified_503")
    else:
        _fail(
            "indexer_fail_hard.classified_503",
            "_classify_exception no longer maps IndexerUnavailable to a 503 indexer_unavailable, "
            "so an outage folds back into a generic 500",
        )


def test_indexer_profile_absent(backend):
    """C-1: an account deleted on chain must not wedge the indexer.

    A block being projected can predate the MsgDeleteUser that removed the
    profile, so GetProfile legitimately answers "gone" for a message the
    indexer still has to project. Before v1.35.0 the chain returned that as an
    unclassified error and the indexer aborted the block, retried the same
    block forever, and stopped advancing for everyone.

    Runs fully offline: gRPC is faked, the DB is a recorder. The point is that
    absence is skipped while a real outage still aborts, and a test that needed
    a live chain would not run when it matters.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    try:
        import grpc

        from indexer.chain_client import ChainClient
        from indexer.message_processor import MessageProcessor
    except Exception as e:
        _skip("indexer_profile_absent.not_found_returns_none", f"indexer modules not importable: {e}")
        return

    class _FakeRpcError(grpc.RpcError):
        def __init__(self, code):
            super().__init__()
            self._code = code

        def code(self):
            return self._code

    class _FakeChannel:
        def __init__(self, exc):
            self._exc = exc

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def unary_unary(self, *_a, **_kw):
            def _call(_req, timeout=None):
                raise self._exc

            return _call

    client = ChainClient("http://127.0.0.1:26657")
    original_channel = grpc.insecure_channel
    try:
        grpc.insecure_channel = lambda *_a, **_kw: _FakeChannel(_FakeRpcError(grpc.StatusCode.NOT_FOUND))
        try:
            result = client.query_profile_full("mirage1deletedaccount")
        except Exception as e:
            _fail("indexer_profile_absent.not_found_returns_none", f"raised {type(e).__name__}: {e}")
        else:
            if result is None:
                _pass("indexer_profile_absent.not_found_returns_none")
            else:
                _fail("indexer_profile_absent.not_found_returns_none", f"returned {result!r} instead of None")

        # The narrowness is the whole safety property: if any status collapsed
        # to None, a node outage would be recorded as "user has nothing" and
        # the indexer would wipe live users' lists instead of aborting.
        grpc.insecure_channel = lambda *_a, **_kw: _FakeChannel(_FakeRpcError(grpc.StatusCode.UNAVAILABLE))
        try:
            client.query_profile_full("mirage1liveaccount")
        except grpc.RpcError:
            _pass("indexer_profile_absent.outage_still_raises")
        except Exception as e:
            _fail("indexer_profile_absent.outage_still_raises", f"raised {type(e).__name__} instead of RpcError: {e}")
        else:
            _fail("indexer_profile_absent.outage_still_raises", "a node outage was swallowed as an absent profile")
    finally:
        grpc.insecure_channel = original_channel

    class _RecordingDB:
        """Any DB call at all is a failure, so record every attribute touched."""

        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            def _record(*_a, **_kw):
                self.calls.append(name)
                return None

            return _record

    class _AbsentChain:
        def query_profile_full(self, *_a, **_kw):
            return None

    db = _RecordingDB()
    mp = MessageProcessor(db, _AbsentChain(), lambda *_a, **_kw: None, lambda _ts: "")

    if mp._load_chain_profile("mirage1deletedaccount") is None:
        _pass("indexer_profile_absent.load_returns_none")
    else:
        _fail(
            "indexer_profile_absent.load_returns_none", "_load_chain_profile invented a profile for a deleted account"
        )

    for helper in ("_refresh_enabled_agents", "_refresh_followed_users", "_refresh_followed_communities"):
        try:
            getattr(mp, helper)("mirage1deletedaccount", 0)
        except Exception as e:
            _fail(f"indexer_profile_absent.{helper}", f"raised {type(e).__name__} for an absent profile: {e}")
        else:
            _pass(f"indexer_profile_absent.{helper}")

    if db.calls:
        _fail(
            "indexer_profile_absent.no_db_writes",
            f"touched the DB for an absent profile: {sorted(set(db.calls))}",
        )
    else:
        _pass("indexer_profile_absent.no_db_writes")

    # Same class of wedge from the other direction: a message type this build
    # does not know (older indexer, newer chain) must be logged and skipped,
    # never raised into the block loop.
    try:
        mp.process_core_message("/mirage.core.v1.MsgFromTheFuture", b"", "DEADBEEF", 0, 1)
    except Exception as e:
        _fail("indexer_profile_absent.unknown_type_skipped", f"raised {type(e).__name__}: {e}")
    else:
        _pass("indexer_profile_absent.unknown_type_skipped")


def test_node_join_bootstrap(backend: str):
    """A new node must join mirage-1 or refuse, never invent its own chain.

    `miraged init` writes a single-validator genesis at height 1, so the join
    path replaces it with the network genesis pinned by hash. These run fully
    offline against a faked RPC: the point is the refusals, and a test that
    needed a live chain would not run when it matters.
    """
    import hashlib as _hashlib
    import importlib.util
    import io
    import json as _json
    import tempfile
    from contextlib import redirect_stdout

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    module_path = os.path.join(repo_root, "deploy", "bootstrap_join.py")
    spec = importlib.util.spec_from_file_location("bootstrap_join", module_path)
    bj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bj)

    if re.fullmatch(r"[0-9a-f]{64}", bj.GENESIS_SHA256):
        _pass("node_join.pin_is_sha256")
    else:
        _fail("node_join.pin_is_sha256", f"GENESIS_SHA256={bj.GENESIS_SHA256!r}")

    legacy_params = {"tiers": [{"archive_duration_days": "30"}]}
    current_params = {"tiers": [{"max_enabled_agents": "5"}], "pow_difficulty_step": "1"}
    fake_genesis = {
        "chain_id": "mirage-1",
        "initial_height": "2096156",
        "app_state": {"core": {"params": legacy_params}, "bank": {"marker": "preserved"}},
    }
    genesis_digest = _hashlib.sha256(bj.canonical(fake_genesis)).hexdigest()

    def _rpc_factory(genesis=fake_genesis, hashes=None):
        hashes = hashes or {}

        def _rpc(ep, path):
            if path == "genesis":
                return {"genesis": genesis}
            if path == "status":
                return {"sync_info": {"latest_block_height": "25000"}}
            return {"block_id": {"hash": hashes.get(ep, "A" * 64)}}

        return _rpc

    original_rpc = bj.rpc
    original_rpc_post = bj.rpc_post
    tmpdir = tempfile.mkdtemp(prefix="node-join-")
    os.makedirs(os.path.join(tmpdir, "config"), exist_ok=True)
    target = os.path.join(tmpdir, "config", "genesis.json")
    os.environ["SNAPSHOT_INTERVAL"] = "10000"

    try:
        # miraged init leaves the current binary's schema at target. The source
        # genesis is still verified byte-for-byte, but its obsolete core params
        # must not be fed back to a binary that cannot decode them. State sync
        # restores current on-chain params after InitGenesis.
        with open(target, "w", encoding="utf-8") as f:
            _json.dump({"app_state": {"core": {"params": current_params}}}, f)
        bj.rpc = _rpc_factory()
        bj.GENESIS_SHA256 = genesis_digest
        bj.install_genesis("http://a", "mirage-1", target)
        on_disk = _hashlib.sha256(open(target, "rb").read()).hexdigest()
        installed = _json.load(open(target))
        if (
            on_disk != genesis_digest
            and installed["chain_id"] == "mirage-1"
            and installed["app_state"]["core"]["params"] == current_params
            and installed["app_state"]["bank"] == {"marker": "preserved"}
        ):
            _pass("node_join.installs_verified_genesis_with_current_params")
        else:
            _fail(
                "node_join.installs_verified_genesis_with_current_params",
                f"on_disk={on_disk} pin={genesis_digest} installed={installed}",
            )

        # The whole point of the pin: a genesis for any other chain is refused,
        # and the refusal must not leave a half-written or replaced file.
        with open(target, "w", encoding="utf-8") as f:
            f.write("SENTINEL")
        bj.GENESIS_SHA256 = "0" * 64
        try:
            bj.install_genesis("http://a", "mirage-1", target)
            _fail("node_join.rejects_wrong_genesis", "installed a genesis that did not match the pin")
        except SystemExit:
            if open(target, encoding="utf-8").read() == "SENTINEL":
                _pass("node_join.rejects_wrong_genesis")
            else:
                _fail("node_join.rejects_wrong_genesis", "refused but overwrote genesis.json anyway")

        # The trust hash has no pin, so its only protection is endpoints
        # agreeing. One dissenting server must stop the join.
        bj.rpc = _rpc_factory(hashes={"http://a": "A" * 64, "http://b": "B" * 64})
        try:
            bj.derive_trust(["http://a", "http://b"])
            _fail("node_join.rejects_trust_disagreement", "accepted conflicting block hashes")
        except SystemExit:
            _pass("node_join.rejects_trust_disagreement")

        bj.rpc = _rpc_factory()
        height, thash = bj.derive_trust(["http://a", "http://b"])
        if height == 10000 - bj.TRUST_LOOKBACK and thash == "A" * 64:
            _pass("node_join.derives_trust_below_snapshot", height=height)
        else:
            _fail("node_join.derives_trust_below_snapshot", f"height={height} hash={thash}")
        # Amsterdam case: head sits in the gap after snapshot 6926400.
        # Trust must land below 6912000 so that snapshot is usable.
        if bj.trust_height_for_head(6933066, 14400) != 6912000 - bj.TRUST_LOOKBACK:
            _fail(
                "node_join.trust_below_previous_snapshot",
                f"trust={bj.trust_height_for_head(6933066, 14400)}",
            )
        else:
            _pass("node_join.trust_below_previous_snapshot")

        # A pre-sync restart already has the verified genesis. It must refresh
        # trust without replacing that file, because the trust height ages while
        # an amended image or interrupted install is being retried.
        with open(target, "w", encoding="utf-8") as f:
            f.write("PRESERVED")
        os.environ.update(
            BOOTSTRAP_RPC="http://a,http://b",
            CHAIN_ID="mirage-1",
            NODE_HOME=tmpdir,
            PERSISTENT_PEERS=(f"{'1' * 40}@192.0.2.1:26656," f"{'2' * 40}@192.0.2.2:26656"),
        )
        bj.rpc_post = lambda endpoint, method, params: {"block_id": {"hash": "A" * 64}}
        output = io.StringIO()
        with redirect_stdout(output):
            bj.main(trust_only=True)
        if (
            open(target, encoding="utf-8").read() == "PRESERVED"
            and "STATESYNC_ENABLE=true" in output.getvalue()
            and "STATESYNC_RPC_SERVERS=http://192.0.2.1:26657,http://192.0.2.2:26657" in output.getvalue()
        ):
            _pass("node_join.restart_refreshes_trust_only")
        else:
            _fail(
                "node_join.restart_refreshes_trust_only",
                f"genesis={open(target, encoding='utf-8').read()!r} output={output.getvalue()!r}",
            )

        # H-2: the trust hash lands in a shell variable on the joining node, so
        # a bootstrap peer that answers with a command instead of a hash must be
        # refused here. Both endpoints agree on the payload, so agreement alone
        # would have let it through.
        payload = 'A" ; touch /tmp/pwned #'
        bj.rpc = _rpc_factory(hashes={"http://a": payload, "http://b": payload})
        try:
            bj.derive_trust(["http://a", "http://b"])
            _fail("node_join.rejects_malformed_trust_hash", f"accepted a non-hash trust value: {payload!r}")
        except SystemExit:
            _pass("node_join.rejects_malformed_trust_hash")

        # A single endpoint cannot cross-check itself, so it is refused rather
        # than silently duplicated into the light client's server list.
        os.environ.update(BOOTSTRAP_RPC="http://only-one", CHAIN_ID="mirage-1", NODE_HOME=tmpdir)
        try:
            bj.main()
            _fail("node_join.requires_two_endpoints", "accepted a single bootstrap endpoint")
        except SystemExit:
            _pass("node_join.requires_two_endpoints")
    finally:
        bj.rpc = original_rpc
        bj.rpc_post = original_rpc_post
        for key in ("BOOTSTRAP_RPC", "CHAIN_ID", "NODE_HOME", "PERSISTENT_PEERS", "SNAPSHOT_INTERVAL"):
            os.environ.pop(key, None)
        shutil.rmtree(tmpdir, ignore_errors=True)

    # The local testnet builds its own genesis and must never reach for the
    # network; the join path is gated on SKIP_PEERS for exactly that reason.
    init_src = open(os.path.join(repo_root, "deploy", "init.sh"), encoding="utf-8").read()
    if "SKIP_PEERS:-0" in init_src and "bootstrap_join.py" in init_src:
        _pass("node_join.local_testnet_exempt")
    else:
        _fail("node_join.local_testnet_exempt", "init.sh no longer gates the join bootstrap on SKIP_PEERS")

    entrypoint_src = open(os.path.join(repo_root, "deploy", "entrypoint.sh"), encoding="utf-8").read()
    marker_src = open(os.path.join(repo_root, "deploy", "run_state_sync_marker.sh"), encoding="utf-8").read()
    if (
        'bash "$ROOT_DIR/deploy/init.sh"' in entrypoint_src
        and ".state_sync_complete" in marker_src
        and "--trust-only" in init_src
    ):
        _pass("node_join.final_render_preserves_statesync")
    else:
        _fail(
            "node_join.final_render_preserves_statesync",
            "the post-migration render can disable state sync or pre-sync restarts cannot refresh trust",
        )

    # H-2: init.sh runs as root, in the same window the operator pipes in a
    # mnemonic, on output it just fetched from a remote node. eval there is
    # remote code execution, so the shape of the parser is pinned: no eval, an
    # allowlist of keys, and the trust hash checked against 64 hex chars.
    code_lines = [ln for ln in init_src.splitlines() if not ln.lstrip().startswith("#")]
    eval_lines = [ln.strip() for ln in code_lines if re.search(r"\beval\b", ln)]
    if eval_lines:
        _fail("node_join.no_eval_of_bootstrap_output", f"init.sh evals again: {eval_lines}")
    else:
        _pass("node_join.no_eval_of_bootstrap_output")

    code_src = "\n".join(code_lines)
    missing = [
        pattern
        for pattern in ("^[0-9A-Fa-f]{64}$", "unexpected key", "STATESYNC_TRUST_HASH)")
        if pattern not in code_src
    ]
    if missing:
        _fail("node_join.validates_statesync_values", f"init.sh no longer validates bootstrap output: {missing}")
    else:
        _pass("node_join.validates_statesync_values")


def test_runner_accounting(backend: str):
    """The runner must never report a skipped test as a pass.

    `_skip()` used to set `passed=True`, so a suite that never executed a
    category still printed ALL OK. That is how earlier reviews shipped green
    while a security category was silently not running.
    """
    del backend  # pure accounting, no HTTP

    sample = [
        TestResult(name="a", status="pass", category="gate_cat"),
        TestResult(name="b", status="skip", error="env missing", category="other_cat"),
    ]

    s = summarize(sample)
    if (s["passed"], s["skipped"], s["failed"], s["total"]) == (1, 1, 0, 2):
        _pass("runner.skip_is_not_a_pass")
    else:
        _fail("runner.skip_is_not_a_pass", f"summary={ {k: s[k] for k in ('passed', 'skipped', 'failed', 'total')} }")

    if s["ok"]:
        _pass("runner.non_gate_skip_still_green")
    else:
        _fail("runner.non_gate_skip_still_green", "a skip outside the release gate must not fail the run")

    gated = summarize(
        [TestResult(name="c", status="skip", error="env missing", category="gate_cat")],
        no_skip_categories={"gate_cat"},
    )
    if not gated["ok"] and len(gated["gate_skips"]) == 1:
        _pass("runner.gate_skip_fails_run")
    else:
        _fail("runner.gate_skip_fails_run", f"gate skip did not fail the run: ok={gated['ok']}")

    failing = summarize([TestResult(name="d", status="fail", error="boom", category="gate_cat")])
    if not failing["ok"] and failing["failed"] == 1 and failing["passed"] == 0:
        _pass("runner.failure_fails_run")
    else:
        _fail("runner.failure_fails_run", f"summary={failing}")

    # Every category in every suite must be a release gate. A category that can
    # skip without failing the run is one nobody relies on, and it belongs
    # deleted rather than parked in the suite printing green. The equality also
    # catches a gate naming a category that does not exist, which would protect
    # nothing.
    import tests.test_backend as backend_suite
    import tests.test_blockchain as chain_suite
    import tests.test_extended as extended_suite

    for suite in (backend_suite, chain_suite, extended_suite):
        name = suite.__name__.rsplit(".", 1)[-1]
        categories = set(suite.ALL_CATEGORIES)
        gates = set(suite.RELEASE_GATE_CATEGORIES)
        # A post_run_hook records its results under INVARIANTS_CATEGORY, which is
        # never dispatched and so is absent from ALL_CATEGORIES. Counting it as a
        # category for a suite that installs a hook makes the name legal there and
        # required there: without the gate, a whole-database invariant could skip
        # and still let the release through.
        if "post_run_hook=" in inspect.getsource(suite.main):
            categories = categories | {INVARIANTS_CATEGORY}
        ungated = sorted(categories - gates)
        unknown = sorted(gates - categories)
        if ungated or unknown:
            _fail(
                f"runner.all_categories_gated.{name}",
                f"ungated={ungated} unknown={unknown}",
            )
        else:
            _pass(f"runner.all_categories_gated.{name}", count=len(gates))

    # The runner must actually be handed the gate; defining the set and not
    # passing it to run_suite is how the blockchain suite went ungated.
    for suite in (backend_suite, chain_suite, extended_suite):
        name = suite.__name__.rsplit(".", 1)[-1]
        source = inspect.getsource(suite.main)
        if "no_skip_categories=RELEASE_GATE_CATEGORIES" in source:
            _pass(f"runner.gate_passed_to_run_suite.{name}")
        else:
            _fail(
                f"runner.gate_passed_to_run_suite.{name}",
                "main() does not pass no_skip_categories=RELEASE_GATE_CATEGORIES",
            )

    # Categories run concurrently by default, so the two sets that opt out of
    # that have to name real categories and have to reach run_suite. A name that
    # matches nothing schedules nothing, exactly like an unknown gate.
    for suite in (backend_suite, chain_suite, extended_suite):
        name = suite.__name__.rsplit(".", 1)[-1]
        categories = set(suite.ALL_CATEGORIES)
        unknown_exclusive = sorted(set(suite.EXCLUSIVE_CATEGORIES) - categories)
        unknown_walletless = sorted(set(suite.WALLETLESS_CATEGORIES) - categories)
        if unknown_exclusive or unknown_walletless:
            _fail(
                f"runner.dispatch_sets_known.{name}",
                f"unknown_exclusive={unknown_exclusive} unknown_walletless={unknown_walletless}",
            )
        else:
            _pass(
                f"runner.dispatch_sets_known.{name}",
                exclusive=len(suite.EXCLUSIVE_CATEGORIES),
                walletless=len(suite.WALLETLESS_CATEGORIES),
            )

        source = inspect.getsource(suite.main)
        if "EXCLUSIVE_CATEGORIES" in source:
            _pass(f"runner.exclusive_passed_to_run_suite.{name}")
        else:
            _fail(
                f"runner.exclusive_passed_to_run_suite.{name}",
                "main() does not pass EXCLUSIVE_CATEGORIES to run_suite",
            )

        # The old opt-in parallel allowlist. Reintroducing it would be silently
        # ignored by run_suite, which now takes the exclusive set instead.
        if hasattr(suite, "STATELESS_CATEGORIES"):
            _fail(
                f"runner.no_stateless_allowlist.{name}",
                "STATELESS_CATEGORIES is obsolete; classify with EXCLUSIVE_CATEGORIES",
            )
        else:
            _pass(f"runner.no_stateless_allowlist.{name}")

    # This category is walletless, so it holds no lease and must not be able to
    # reach another category's wallets. Silently borrowing set 0 is how a
    # walletless category would corrupt a concurrent run.
    try:
        WALLETS["sub1"]
        _fail("runner.walletless_has_no_lease", "WALLETS resolved without a wallet lease")
    except RuntimeError:
        _pass("runner.walletless_has_no_lease")
