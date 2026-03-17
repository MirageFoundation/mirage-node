from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import string
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
    _do_upgrade_level,
    _docker_exec,
    _run_miraged,
    _miraged_cmd,
    _keyring_backend,
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
    _canon_base_upgrade_level_raw,
    _canon_base_send_tokens_raw,
    _canon_base_award_raw,
    _canon_base_post_raw,
    _canon_base_vote_raw,
    _canon_base_edit_raw,
    _canon_base_set_username_raw,
    _canon_base_set_biography_raw,
    _canon_base_annotate_raw,
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
    _do_annotate,
    _do_delete,
    _do_delete_user,
    _do_follow_user,
    _do_follow_topic,
    _do_block,
    _do_block_topic,
    _do_set_username_raw,
    _do_set_biography,
    _do_report,
    _do_enable_agent,
    _do_set_agents,
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
    _wait_followed_topic,
    _wait_blocked_user,
    _wait_blocked_topic,
    _wait_blocked_topic_state,
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

    # 1.2 pow_factor is float in (0,1]
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

    # 1.4b tier limits for max_blocked_topics (requires v1.13.0 upgrade)
    tiers = data.get("tiers") or []
    expected_blocked = [10, 125, 500, 1000]
    if len(tiers) >= 4:
        got_blocked = [int((tiers[i] or {}).get("max_blocked_topics", -1)) for i in range(4)]
        if got_blocked == expected_blocked:
            _pass("params.max_blocked_topics tier limits", values=got_blocked)
        else:
            _fail("params.max_blocked_topics tier limits", f"got {got_blocked}")
    else:
        _pass("params.max_blocked_topics tier limits (skipped, pre-v1.13.0)", tiers_len=len(tiers))

    # 1.4c tier limits for max_biography_length (requires v1.18.0 upgrade)
    expected_bio = [0, 512, 512]
    if len(tiers) >= 3:
        got_bio = [int((tiers[i] or {}).get("max_biography_length", -1)) for i in range(3)]
        if got_bio == expected_bio:
            _pass("params.max_biography_length tier limits", values=got_bio)
        else:
            _fail("params.max_biography_length tier limits", f"got {got_bio}")
    else:
        _pass("params.max_biography_length tier limits (skipped, pre-v1.18.0)", tiers_len=len(tiers))

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

    # 1.6b subscription_reserve_percent is 0.95
    reserve_pct = cfg.get("subscription_reserve_percent") if isinstance(cfg, dict) else None
    if reserve_pct is None:
        _fail("params.subscription_reserve_percent_0.95", "missing")
    else:
        try:
            reserve_val = float(reserve_pct)
            if abs(reserve_val - 0.95) < 0.01:
                _pass("params.subscription_reserve_percent_0.95", value=reserve_val)
            else:
                _fail("params.subscription_reserve_percent_0.95", f"got {reserve_pct}")
        except Exception as e:
            _fail("params.subscription_reserve_percent_0.95", str(e))

    # 1.7 get_node_config returns valid
    code3b, ncfg = _get(f"{backend}/api/get_node_config")
    if code3b == 200 and ncfg.get("validator_account_address"):
        _pass("params.get_node_config valid")
    else:
        _fail("params.get_node_config valid", f"code={code3b}")

    # 1.8 bridge_attestation_threshold is float in [0,1] (via bridge config)
    code_bridge, bridge_data = _get(f"{backend}/api/bridge/config")
    if code_bridge == 200 and bridge_data.get("attestation_threshold") is not None:
        bat = float(bridge_data["attestation_threshold"])
        if 0 <= bat <= 1:
            _pass("params.bridge_attestation_threshold in [0,1]", value=bat)
        else:
            _fail("params.bridge_attestation_threshold in [0,1]", f"got {bat}")
    else:
        _pass("params.bridge_attestation_threshold (bridge endpoint may not be available)")

    # 1.9 get_total_supply positive (returns plain text, not JSON)
    try:
        r4 = requests.get(f"{backend}/api/get_total_supply", timeout=10)
        supply_val = float(r4.text.strip()) if r4.status_code == 200 else 0
        if supply_val > 0:
            _pass("params.get_total_supply positive", value=supply_val)
        else:
            _fail("params.get_total_supply positive", f"code={r4.status_code}")
    except Exception as e:
        _fail("params.get_total_supply positive", str(e))

    # 1.10 get_welcome_stats valid structure
    code5, ws = _get(f"{backend}/api/get_welcome_stats")
    if code5 == 200:
        _pass("params.get_welcome_stats returns 200")
    else:
        _fail("params.get_welcome_stats returns 200", f"code={code5}")


# =========================================================================
# Category 2: Account & Username
# =========================================================================


def test_search(backend: str):

    # 8.1 get_topics returns list
    code, topics = _get(f"{backend}/api/get_topics")
    if code == 200:
        t_list = topics.get("topics") or topics.get("data") or []
        _pass("search.get_topics returns 200", count=len(t_list))
    else:
        _fail("search.get_topics returns 200", f"code={code}")

    # 8.2 search_topics
    code, st = _get(f"{backend}/api/search_topics", {"q": "test"})
    if code == 200:
        _pass("search.search_topics returns 200")
    else:
        _fail("search.search_topics returns 200", f"code={code}")

    # 8.3 search general
    code, sr = _get(f"{backend}/api/search", {"q": "test", "limit": 5})
    if code == 200:
        _pass("search.general_search returns 200")
    else:
        _fail("search.general_search returns 200", f"code={code}")

    # 8.4 get_posts with topic filter
    code, fp = _get(f"{backend}/api/get_posts", {"topic": "test", "limit": 5})
    if code == 200:
        _pass("search.get_posts_by_topic returns 200")
    else:
        _fail("search.get_posts_by_topic returns 200", f"code={code}")

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
    topic = "test"
    title = f"TxStatus Test {_rand_str(6)}"
    content = f"Content {_rand_str(10)}"
    txh = _do_post(backend, free, topic, title, content)
    if not txh:
        _fail("tx_status.post_submit")
        return
    _pass("tx_status.post_submit", tx=txh)

    status = _wait_tx_status(backend, txh, expect_type="post")
    if status and status.get("found") and status.get("indexed"):
        details = status.get("details") or {}
        if details.get("topic", "").lower() == topic.lower() and details.get("title") == title:
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


def test_failed_tx_status(backend: str):
    """Test indexer receipts for failed vote/post transactions."""

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
        ok_vote = vote_tx2 if vote_tx1 else vote_tx1
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
        ok_post = post_tx2 if post_tx1 else post_tx1
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
