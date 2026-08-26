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
from cosmpy.crypto.keypairs import PrivateKey
from cosmpy.aerial.wallet import LocalWallet

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
    _feed_has_post,
    _feed_missing_post,
)
from tests.cases.test_backend_accounts import _ensure_subscriber


def test_agents(backend: str):
    """Agent enablement was removed in v1.39.0."""
    for path, label in (
        ("/api/core/enable_agent", "enable_agent"),
        ("/api/core/disable_agent", "disable_agent"),
        ("/api/core/set_agents", "set_agents"),
    ):
        code, _ = _post(f"{backend}{path}", {})
        if code == 410:
            _pass(f"agents.{label}_gone")
        else:
            _fail(f"agents.{label}_gone", f"code={code}")
    code, _ = _get(f"{backend}/api/get_agents")
    if code == 410:
        _pass("agents.get_agents_gone")
    else:
        _fail("agents.get_agents_gone", f"code={code}")
    return

    sub1 = WALLETS["sub1"]
    sub2 = WALLETS["sub2"]
    free_wallet = WALLETS["free"]
    sub1_addr = str(sub1.address())
    sub2_addr = str(sub2.address())
    free_addr = str(free_wallet.address())

    # 13.1 Enable agent (sub1 enables sub2 as agent)
    try:
        resp = _do_enable_agent(backend, sub1, sub2_addr, enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.enable_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.enable_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.enable_happy_path", str(e))

    time.sleep(3)

    # 13.2 Disable agent
    try:
        resp = _do_enable_agent(backend, sub1, sub2_addr, enable=False, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.disable_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.disable_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.disable_happy_path", str(e))

    # 13.3 Enable non-existent address
    fake_addr = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    try:
        resp = _do_enable_agent(backend, sub1, fake_addr, enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.enable_nonexistent submitted (chain decides)")
        else:
            _pass("agents.enable_nonexistent_rejected")
    except Exception as e:
        _pass("agents.enable_nonexistent handled")

    # 13.4 Self-enable as agent
    try:
        resp = _do_enable_agent(backend, sub1, sub1_addr, enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if txh:
            _fail("agents.self_enable_rejected", "tx accepted but should reject self-enable")
        elif "yourself" in err or "self" in err:
            _pass("agents.self_enable_rejected")
        else:
            _fail("agents.self_enable_rejected", f"unexpected error: {err[:200]}")
    except Exception as e:
        _fail("agents.self_enable_rejected", str(e))

    # 13.5 Invalid agent address format
    try:
        resp = _do_enable_agent(backend, sub1, "invalid_address", enable=True, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("agents.invalid_address_rejected")
        else:
            _pass("agents.invalid_address submitted (chain may reject)")
    except Exception as e:
        _pass("agents.invalid_address_rejected")

    # 13.6 Free user enables agent with PoW
    try:
        resp = _do_enable_agent(backend, free_wallet, sub2_addr, enable=True, skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.free_user_enable")
        else:
            _pass("agents.free_user_enable submitted")
    except Exception as e:
        _fail("agents.free_user_enable", str(e))

    time.sleep(3)

    # 13.7 SetAgents: atomically set agent list (subscriber)
    agent_a = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    agent_b = str(LocalWallet(PrivateKey(), prefix="mirage").address())
    try:
        resp = _do_set_agents(backend, sub1, [agent_a, agent_b], skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.set_agents_happy_path")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.set_agents_happy_path", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.set_agents_happy_path", str(e))

    _wait_list_count(backend, sub1_addr, "enabled_agents", 2)

    # 13.7b Verify order in get_user_followed
    code_followed, followed = _get(f"{backend}/api/get_user_followed", {"address": sub1_addr})
    if code_followed == 200:
        got_order = [str(a).lower() for a in (followed or {}).get("enabled_agents") or []]
        expected = [agent_a.lower(), agent_b.lower()]
        if got_order[:2] == expected:
            _pass("agents.set_agents_order_reflected")
        else:
            _fail("agents.set_agents_order_reflected", f"got={got_order[:4]}")
    else:
        _fail("agents.set_agents_order_reflected", f"code={code_followed}")

    # 13.7c Invalid payload type for agents
    code_bad, bad_resp = _post(f"{backend}/api/core/set_agents", {"agents": "not-an-array"})
    err = str((bad_resp or {}).get("error", "")).lower()
    if code_bad == 400 and "array" in err:
        _pass("agents.set_agents_invalid_payload")
    else:
        _fail("agents.set_agents_invalid_payload", f"code={code_bad} err={err[:120]}")

    # 13.7d Invalid agent address
    try:
        resp = _do_set_agents(backend, sub1, ["invalid_address"], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "invalid" in err:
            _pass("agents.set_agents_invalid_address")
        elif resp.get("tx_hash"):
            _pass("agents.set_agents_invalid_address submitted (chain may reject)")
        else:
            _pass("agents.set_agents_invalid_address handled")
    except Exception as e:
        _pass("agents.set_agents_invalid_address handled")

    # 13.8 SetAgents: clear all agents
    try:
        resp = _do_set_agents(backend, sub1, [], skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.set_agents_clear")
        else:
            err = str(resp.get("error", "")).lower()
            _fail("agents.set_agents_clear", f"no tx_hash: {err[:200]}")
    except Exception as e:
        _fail("agents.set_agents_clear", str(e))

    deadline = time.perf_counter() + INDEX_TIMEOUT_SEC
    cleared = False
    while time.perf_counter() < deadline:
        time.sleep(2)
        code_followed, followed = _get(f"{backend}/api/get_user_followed", {"address": sub1_addr})
        if code_followed == 200:
            got_order = [str(a).lower() for a in (followed or {}).get("enabled_agents") or []]
            if not got_order:
                cleared = True
                break
    if cleared:
        _pass("agents.set_agents_clear_reflected")
    elif code_followed != 200:
        _fail("agents.set_agents_clear_reflected", f"code={code_followed}")
    else:
        _fail("agents.set_agents_clear_reflected", f"count={len(got_order)}")

    # 13.9 SetAgents: reject duplicate agent addresses
    try:
        resp = _do_set_agents(backend, sub1, [agent_a, agent_a], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "duplicate" in err:
            _pass("agents.set_agents_duplicate_rejected")
        elif resp.get("tx_hash"):
            _pass("agents.set_agents_duplicate (chain may reject)")
        else:
            _pass("agents.set_agents_duplicate handled")
    except Exception as e:
        _pass("agents.set_agents_duplicate handled")

    # 13.9b SetAgents: reject self-as-agent
    try:
        resp = _do_set_agents(backend, sub1, [sub1_addr], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "yourself" in err:
            _pass("agents.set_agents_self_rejected")
        elif resp.get("tx_hash"):
            _fail("agents.set_agents_self_rejected", "tx accepted but should reject self-as-agent")
        else:
            _fail("agents.set_agents_self_rejected", f"unexpected: {err[:120]}")
    except Exception as e:
        _fail("agents.set_agents_self_rejected", str(e))

    # 13.9c SetAgents: reject self mixed with valid agents
    try:
        resp = _do_set_agents(backend, sub1, [agent_a, sub1_addr], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "yourself" in err:
            _pass("agents.set_agents_self_mixed_rejected")
        elif resp.get("tx_hash"):
            _fail("agents.set_agents_self_mixed_rejected", "tx accepted but should reject self-as-agent")
        else:
            _fail("agents.set_agents_self_mixed_rejected", f"unexpected: {err[:120]}")
    except Exception as e:
        _fail("agents.set_agents_self_mixed_rejected", str(e))

    # 13.10 SetAgents: free user with PoW
    try:
        resp = _do_set_agents(backend, free_wallet, [agent_a], skip_pow=False)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("agents.set_agents_free_pow")
        else:
            _pass("agents.set_agents_free_pow submitted")
    except Exception as e:
        _fail("agents.set_agents_free_pow", str(e))

    # 13.10b Free user without PoW should fail
    try:
        resp = _do_set_agents(backend, free_wallet, [agent_a], skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if "insufficient pow" in err:
            _pass("agents.set_agents_free_no_pow_rejected")
        elif resp.get("tx_hash"):
            _pass("agents.set_agents_free_no_pow submitted (chain may reject)")
        else:
            _pass("agents.set_agents_free_no_pow handled")
    except Exception as e:
        _pass("agents.set_agents_free_no_pow handled")


# =========================================================================
# Category 14: Media Attachments
# =========================================================================


def test_agent_behavior(backend: str):
    """Agent block propagation was removed in v1.39.0."""
    code, _ = _post(f"{backend}/api/core/enable_agent", {})
    if code == 410:
        _pass("agent_behavior.gone")
    else:
        _fail("agent_behavior.gone", f"code={code}")
    return

    agent = WALLETS["agent1"]
    user = WALLETS["sub1"]
    victim = WALLETS["sub2"]
    agent_addr = str(agent.address())
    user_addr = str(user.address())
    victim_addr = str(victim.address())

    # Ensure subscriber wallets are still active (subscription may have expired)
    for w, wname, lvl in [(agent, "agent1", 10), (user, "sub1", 1), (victim, "sub2", 1)]:
        if not _ensure_subscriber(backend, w, wname, lvl):
            _fail("agent_behavior.setup_levels", f"{wname} not at level {lvl}")
            return

    # ----- Setup: create test content -----

    topic_a = f"agenttest{_rand_str(6)}"
    topic_b = f"agentblk{_rand_str(6)}"

    # Post by victim in topic_a (will be individually blocked by agent)
    blocked_post = _do_post(
        backend, victim, topic_a, "Blocked Post", "This post should be hidden by the agent.", skip_pow=True
    )
    if not blocked_post:
        _fail("agent_behavior.setup_blocked_post", "could not create post")
        return
    if not _wait_indexed(backend, victim_addr, blocked_post):
        _fail("agent_behavior.setup_blocked_post_indexed", "not indexed")
        return

    # Post by victim in topic_b (topic will be blocked by agent)
    topic_post = _do_post(backend, victim, topic_b, "Topic Post", "This post is in a blocked topic.", skip_pow=True)
    if not topic_post:
        _fail("agent_behavior.setup_topic_post", "could not create post")
        return
    if not _wait_indexed(backend, victim_addr, topic_post):
        _fail("agent_behavior.setup_topic_post_indexed", "not indexed")
        return

    # Post by victim in topic_a (control — should remain visible)
    control_post = _do_post(
        backend, victim, topic_a, "Control Post", "This post should always be visible.", skip_pow=True
    )
    if not control_post:
        _fail("agent_behavior.setup_control_post", "could not create post")
        return
    if not _wait_indexed(backend, victim_addr, control_post):
        _fail("agent_behavior.setup_control_post_indexed", "not indexed")
        return

    # Another user's post (author will be blocked by agent)
    agent2 = WALLETS["agent2"]
    agent2_addr = str(agent2.address())
    author_post = _do_post(
        backend, agent2, topic_a, "Author Post", "Post from a user the agent will block.", skip_pow=True
    )
    if not author_post:
        _fail("agent_behavior.setup_author_post", "could not create post")
        return
    if not _wait_indexed(backend, agent2_addr, author_post):
        _fail("agent_behavior.setup_author_post_indexed", "not indexed")
        return

    _pass("agent_behavior.setup_content_created")

    # ----- 25.1 Baseline: user sees all posts before enabling agent -----

    if _feed_has_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.baseline_sees_blocked_post")
    else:
        _fail("agent_behavior.baseline_sees_blocked_post", "not in feed")

    if _feed_has_post(backend, user_addr, topic_post):
        _pass("agent_behavior.baseline_sees_topic_post")
    else:
        _fail("agent_behavior.baseline_sees_topic_post", "not in feed")

    if _feed_has_post(backend, user_addr, author_post):
        _pass("agent_behavior.baseline_sees_author_post")
    else:
        _fail("agent_behavior.baseline_sees_author_post", "not in feed")

    # ----- 25.2 Agent blocks: post, topic, user -----

    resp = _do_block(backend, agent, blocked_post, "post", skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.agent_blocks_post")
    else:
        _fail("agent_behavior.agent_blocks_post", f"resp={resp}")
        return

    resp = _do_block_topic(backend, agent, topic_b, skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.agent_blocks_topic")
    else:
        _fail("agent_behavior.agent_blocks_topic", f"resp={resp}")
        return

    resp = _do_block(backend, agent, agent2_addr, "user", skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.agent_blocks_user")
    else:
        _fail("agent_behavior.agent_blocks_user", f"resp={resp}")
        return

    time.sleep(4)

    # ----- 25.3 User still sees everything (agent not enabled yet) -----

    if _feed_has_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.pre_enable_sees_blocked_post")
    else:
        _fail("agent_behavior.pre_enable_sees_blocked_post", "not in feed")

    if _feed_has_post(backend, user_addr, topic_post):
        _pass("agent_behavior.pre_enable_sees_topic_post")
    else:
        _fail("agent_behavior.pre_enable_sees_topic_post", "not in feed")

    if _feed_has_post(backend, user_addr, author_post):
        _pass("agent_behavior.pre_enable_sees_author_post")
    else:
        _fail("agent_behavior.pre_enable_sees_author_post", "not in feed")

    # ----- 25.4 User enables agent -----

    resp = _do_enable_agent(backend, user, agent_addr, skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.user_enables_agent")
    else:
        _fail("agent_behavior.user_enables_agent", f"resp={resp}")
        return

    time.sleep(5)

    # ----- 25.5 Blocked post hidden from user's feed -----

    if _feed_missing_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.blocked_post_hidden")
    else:
        _fail("agent_behavior.blocked_post_hidden", "post still visible after enabling agent")

    # ----- 25.6 Topic-blocked post hidden from user's feed -----

    if _feed_missing_post(backend, user_addr, topic_post):
        _pass("agent_behavior.blocked_topic_post_hidden")
    else:
        _fail("agent_behavior.blocked_topic_post_hidden", "topic post still visible after enabling agent")

    # ----- 25.7 User-blocked author's post hidden from user's feed -----

    if _feed_missing_post(backend, user_addr, author_post):
        _pass("agent_behavior.blocked_user_post_hidden")
    else:
        _fail("agent_behavior.blocked_user_post_hidden", "author post still visible after enabling agent")

    # ----- 25.8 Control post still visible -----

    if _feed_has_post(backend, user_addr, control_post):
        _pass("agent_behavior.control_post_still_visible")
    else:
        _fail("agent_behavior.control_post_still_visible", "control post disappeared")

    # ----- 25.9 Disable agent — blocked content reappears -----

    resp = _do_enable_agent(backend, user, agent_addr, enable=False, skip_pow=True)
    txh = str(resp.get("tx_hash", "")).lower()
    if txh:
        _pass("agent_behavior.user_disables_agent")
    else:
        _fail("agent_behavior.user_disables_agent", f"resp={resp}")
        return

    time.sleep(5)

    if _feed_has_post(backend, user_addr, blocked_post):
        _pass("agent_behavior.post_reappears_after_disable")
    else:
        _fail("agent_behavior.post_reappears_after_disable", "still hidden")

    if _feed_has_post(backend, user_addr, topic_post):
        _pass("agent_behavior.topic_post_reappears_after_disable")
    else:
        _fail("agent_behavior.topic_post_reappears_after_disable", "still hidden")

    if _feed_has_post(backend, user_addr, author_post):
        _pass("agent_behavior.author_post_reappears_after_disable")
    else:
        _fail("agent_behavior.author_post_reappears_after_disable", "still hidden")

    # Clean up agent1's blocks so they don't leak into subsequent tests
    # (e.g. annotate test enables agent1 for a viewer — stale blocks would
    # propagate and viewer-filter unrelated posts).
    _do_block(backend, agent, blocked_post, "post", block=False, skip_pow=True)
    _do_block_topic(backend, agent, topic_b, block=False, skip_pow=True)
    _do_block(backend, agent, agent2_addr, "user", block=False, skip_pow=True)
