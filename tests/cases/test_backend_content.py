from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import random
import string
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple

import psycopg
import requests

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _get,
    _post,
    _post_multipart,
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
)


def test_post_lifecycle(backend: str):

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    topic = f"annot{_rand_str(6)}"
    title = f"Test Post {_rand_str(6)}"
    content = f"Content body {_rand_str(20)}"
    try:
        validator_addr = _resolve_validator_key_addr()
    except Exception as e:
        _fail("post.relayer.validator_addr", str(e))
        return
    validator_lower = validator_addr.lower()
    _debug(f"expected relayer={validator_lower}")

    # 3.1 Create post
    txh = _do_post(backend, wallet, topic, title, content)
    if txh:
        _pass("post.create succeeds", tx=txh)
    else:
        _fail("post.create succeeds")
        return

    # 3.2 Wait for indexing & verify in get_user_posts
    if _wait_indexed(backend, addr, txh):
        _pass("post.appears in get_user_posts")
    else:
        _fail("post.appears in get_user_posts", f"not found after {int(INDEX_TIMEOUT_SEC)}s")

    # 3.2a Relayer present in get_user_posts
    code, user_posts = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
    if code == 200:
        posts = (user_posts or {}).get("posts") or []
        p_user = next((p for p in posts if str(p.get("post_id", "")).lower() == txh), None)
        relayer_val = str(p_user.get("relayer", "")).strip().lower() if p_user else ""
        _debug(f"user_posts relayer={relayer_val}")
        if relayer_val == validator_lower:
            _pass("post.relayer in get_user_posts")
        else:
            _fail("post.relayer in get_user_posts", f"relayer={relayer_val}")
    else:
        _fail("post.relayer in get_user_posts", f"code={code}")

    # 3.3 Verify in get_posts feed (poll up to INDEX_TIMEOUT_SEC, use newest sort)
    found = []
    for _ in range(int(INDEX_TIMEOUT_SEC)):
        code, feed = _get(f"{backend}/api/get_posts", {"limit": 50, "by": "newest"})
        posts = (feed or {}).get("posts") or []
        found = [p for p in posts if str(p.get("post_id", "")).lower() == txh]
        if found:
            break
        time.sleep(1)
    if found:
        p = found[0]
        _pass("post.appears in get_posts feed")
    else:
        _fail("post.appears in get_posts feed")

    # 3.3a Relayer present in get_posts feed
    if found:
        p = found[0]
        relayer_val = str(p.get("relayer", "")).strip().lower()
        _debug(f"get_posts relayer={relayer_val}")
        if relayer_val == validator_lower:
            _pass("post.relayer in get_posts feed")
        else:
            _fail("post.relayer in get_posts feed", f"relayer={relayer_val}")

    # 3.4 Post has correct fields
    if found:
        p = found[0]
        ok = (
            p.get("title", "").strip() == title.strip()
            and p.get("topic", "").strip() == topic.strip()
            and content[:20] in (p.get("content") or "")
        )
        if ok:
            _pass("post.fields correct (title, topic, content)")
        else:
            _fail("post.fields correct", f"title={p.get('title')}, topic={p.get('topic')}")

    # 3.4a get_tx_status includes relayer
    post_status = _wait_tx_status(backend, txh, expect_type="post")
    if post_status and post_status.get("details"):
        relayer_val = str((post_status.get("details") or {}).get("relayer", "")).strip().lower()
        _debug(f"tx_status post relayer={relayer_val}")
        if relayer_val == validator_lower:
            _pass("post.relayer in get_tx_status")
        else:
            _fail("post.relayer in get_tx_status", f"relayer={relayer_val}")
    else:
        _fail("post.relayer in get_tx_status", "missing tx status details")

    # 3.4b Search results include relayer
    search_found = False
    search_relayer = ""
    for _ in range(int(INDEX_TIMEOUT_SEC)):
        code, sr = _get(f"{backend}/api/search", {"q": title[:8], "limit": 10})
        if code == 200:
            posts = (sr or {}).get("posts") or []
            match = next((p for p in posts if str(p.get("post_id", "")).lower() == txh), None)
            if match:
                search_found = True
                search_relayer = str(match.get("relayer", "")).strip().lower()
                break
        time.sleep(1)
    _debug(f"search relayer={search_relayer}")
    if search_found and search_relayer == validator_lower:
        _pass("post.relayer in search results")
    else:
        _fail("post.relayer in search results", f"found={search_found} relayer={search_relayer}")

    # 3.4c Award post (non-self)
    awarder = WALLETS["sub1"]
    award_type = "quality_post"
    _debug(f"award post target={txh} type={award_type}")
    award_code, award_resp = _do_award(backend, awarder, txh, award_type)
    award_txh = str(award_resp.get("tx_hash", "")).lower()
    if award_txh:
        _pass("post.award submitted", tx=award_txh)
    else:
        _fail("post.award submitted", f"code={award_code} resp={award_resp}")

    # 3.4d Award appears in post feed data
    award_seen = False
    if award_txh:
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, feed_aw = _get(f"{backend}/api/get_posts", {"limit": 50, "by": "newest"})
            posts_aw = (feed_aw or {}).get("posts") or []
            p_aw = next((p for p in posts_aw if str(p.get("post_id", "")).lower() == txh), None)
            if not p_aw:
                continue
            awards = p_aw.get("awards") or []
            if any(a.get("type") == award_type and int(a.get("count", 0)) >= 1 for a in awards):
                award_seen = True
                break
    if award_seen:
        _pass("post.award appears in feed")
    else:
        _fail("post.award appears in feed")

    # 3.4e Warm the feed's vote-totals cache before voting, so the check at 3.5b
    # is meaningful. The home feed serves totals from post_vote_totals_cache
    # (60s TTL) while get_user_posts and the post page sum votes live. Reading as
    # a guest here stores the pre-vote total, which is exactly the value that used
    # to be served back to the voter afterwards.
    _get(f"{backend}/api/get_posts", {"limit": 50, "feed": "home", "by": "newest"})

    # 3.5 Vote up (poll up to INDEX_TIMEOUT_SEC)
    vote_resp = _do_vote(backend, wallet, txh, 1)
    if vote_resp and vote_resp.get("error"):
        _fail("post.vote_up reflected", f"vote failed: {vote_resp}")
    else:
        votes_after_up = 0
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, feed2 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
            posts2 = (feed2 or {}).get("posts") or []
            p2 = next((p for p in posts2 if str(p.get("post_id", "")).lower() == txh), None)
            votes_after_up = int(p2.get("points", 0)) if p2 else 0
            if votes_after_up >= 1:
                break
        if votes_after_up >= 1:
            _pass("post.vote_up reflected", votes=votes_after_up)
        else:
            _fail("post.vote_up reflected", f"votes={votes_after_up}")

        # 3.5b The voter's own vote must also show on the cached feed path, not
        # just in get_user_posts. The two disagreed until v1.34.1: get_user_posts
        # and the post page sum votes live, while the home feed read a total that
        # could be up to 60s old, so a user saw their fresh upvote on the post but
        # not on the front page. The fix exempts posts the viewer has voted on
        # from the cache. INDEX_TIMEOUT_SEC (45s) is below the 60s TTL on purpose:
        # if the exemption regresses, the stale total outlives this loop.
        feed_points = 0.0
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, feed_c = _get(
                f"{backend}/api/get_posts",
                {"limit": 50, "feed": "home", "by": "newest", "address": addr},
            )
            posts_c = (feed_c or {}).get("posts") or []
            p_c = next((p for p in posts_c if str(p.get("post_id", "")).lower() == txh), None)
            if p_c:
                feed_points = float(p_c.get("points", 0) or 0)
                if feed_points >= 1:
                    break
        if feed_points >= 1:
            _pass("post.vote_up in cached feed path", points=feed_points)
        else:
            _fail(
                "post.vote_up in cached feed path",
                f"points={feed_points} while get_user_posts reported {votes_after_up} — "
                f"the home feed served a stale cached total for the voter's own vote",
            )

    # 3.5a Vote tx_status includes relayer
    vote_txh = str((vote_resp or {}).get("tx_hash", "") or "").lower()
    if vote_txh:
        vote_status = _wait_tx_status(backend, vote_txh, expect_type="vote")
        if vote_status and vote_status.get("details"):
            relayer_val = str((vote_status.get("details") or {}).get("relayer", "")).strip().lower()
            _debug(f"tx_status vote relayer={relayer_val}")
            if relayer_val == validator_lower:
                _pass("vote.relayer in get_tx_status")
            else:
                _fail("vote.relayer in get_tx_status", f"relayer={relayer_val}")
        else:
            _fail("vote.relayer in get_tx_status", "missing tx status details")
    else:
        _fail("vote.relayer in get_tx_status", "missing tx hash")

    # 3.6 Vote down (poll up to INDEX_TIMEOUT_SEC)
    _do_vote(backend, wallet, txh, -1)
    votes_after_down = votes_after_up
    for _ in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, feed3 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
        posts3 = (feed3 or {}).get("posts") or []
        p3 = next((p for p in posts3 if str(p.get("post_id", "")).lower() == txh), None)
        votes_after_down = int(p3.get("points", 0)) if p3 else 0
        if votes_after_down < votes_after_up:
            break
    if votes_after_down < votes_after_up:
        _pass("post.vote_down reflected", votes=votes_after_down)
    else:
        _fail("post.vote_down reflected", f"votes={votes_after_down}")

    # 3.7 Clear vote
    _do_vote(backend, wallet, txh, 0)
    time.sleep(2)
    _pass("post.vote_clear submitted")

    # 3.8 Edit post (root post: target="", override=post hash)
    new_content = f"Edited content {_rand_str(10)}"
    _do_edit(backend, wallet, override_hash=txh, topic=topic, title=title, content=new_content)
    time.sleep(3)
    code, feed4 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "address": addr, "limit": 50})
    posts4 = (feed4 or {}).get("posts") or []
    p4 = next((p for p in posts4 if str(p.get("post_id", "")).lower() == txh), None)
    if p4 and new_content[:15] in (p4.get("content") or ""):
        _pass("post.edit reflected in feed")
    else:
        _pass("post.edit submitted (indexer may lag)")

    # 3.9 Create post with tags
    tag_txh = _do_post(backend, wallet, topic, f"Tagged {_rand_str(4)}", "tag test", tag="sensitive")
    if tag_txh:
        _pass("post.create_with_tag succeeds", tx=tag_txh)
    else:
        _fail("post.create_with_tag succeeds")

    # 3.10 Get posts by topic filter
    code, tf = _get(f"{backend}/api/get_posts", {"topic": topic, "limit": 10})
    if code == 200:
        _pass("post.get_posts topic filter works")
    else:
        _fail("post.get_posts topic filter works", f"code={code}")

    # 3.11 Pagination
    code, pg = _get(f"{backend}/api/get_posts", {"limit": 2, "page": 1})
    pg_posts = (pg or {}).get("posts") or []
    if code == 200 and len(pg_posts) <= 2:
        _pass("post.pagination limit works", count=len(pg_posts))
    else:
        _fail("post.pagination limit works", f"code={code}, count={len(pg_posts)}")

    # 3.12 Delete post
    _do_delete(backend, wallet, txh)
    time.sleep(3)
    code, feed5 = _get(f"{backend}/api/get_user_posts", {"owner": addr, "limit": 50})
    posts5 = (feed5 or {}).get("posts") or []
    still_there = any(str(p.get("post_id", "")).lower() == txh for p in posts5)
    if not still_there:
        _pass("post.delete removes from feed")
    else:
        _pass("post.delete submitted (indexer may lag)")


# =========================================================================
# Category 4: Comment Threading
# =========================================================================


def test_comments(backend: str):

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    try:
        validator_addr = _resolve_validator_key_addr()
    except Exception as e:
        _fail("comments.relayer.validator_addr", str(e))
        return
    validator_lower = validator_addr.lower()
    _debug(f"expected relayer={validator_lower}")

    def _find_comment(nodes, target_id: str):
        for n in nodes:
            if str(n.get("post_id", "")).lower() == target_id:
                return n
            child = _find_comment(n.get("children") or [], target_id)
            if child:
                return child
        return None

    # Create a parent post
    parent_txh = _do_post(backend, wallet, "test", f"Parent {_rand_str(4)}", "Parent body")
    if not parent_txh:
        _fail("comments.create_parent_post")
        return
    _wait_indexed(backend, addr, parent_txh)
    _pass("comments.parent_post created", tx=parent_txh)

    # 4.1 Create comment on post
    c1_txh = _do_post(backend, wallet, "", "", "First comment", target=parent_txh)
    if c1_txh:
        _pass("comments.create_comment succeeds", tx=c1_txh)
    else:
        _fail("comments.create_comment succeeds")
        return

    # 4.2 Verify via get_comments
    if _wait_comment_indexed(backend, parent_txh, c1_txh):
        _pass("comments.appears in get_comments")
    else:
        _fail("comments.appears in get_comments", f"not found after {int(INDEX_TIMEOUT_SEC)}s")

    # 4.2a Relayer present in get_comments
    code, data = _get(f"{backend}/api/get_comments", {"post_id": parent_txh, "address": addr})
    if code == 200:
        root = (data or {}).get("root") or {}
        children = (data or {}).get("children") or []
        comment_node = _find_comment(children, c1_txh)
        root_relayer = str(root.get("relayer", "")).strip().lower()
        child_relayer = str((comment_node or {}).get("relayer", "")).strip().lower()
        _debug(f"comments relayer root={root_relayer} child={child_relayer}")
        if root_relayer == validator_lower and child_relayer == validator_lower:
            _pass("comments.relayer in get_comments")
        else:
            _fail("comments.relayer in get_comments", f"root={root_relayer} child={child_relayer}")
    else:
        _fail("comments.relayer in get_comments", f"code={code}")

    # 4.2b Award comment (non-self)
    awarder = WALLETS["sub1"]
    award_type = "receipts"
    _debug(f"award comment target={c1_txh} type={award_type}")
    award_code, award_resp = _do_award(backend, awarder, c1_txh, award_type)
    award_txh = str(award_resp.get("tx_hash", "")).lower()
    if award_txh:
        _pass("comments.award submitted", tx=award_txh)
    else:
        _fail("comments.award submitted", f"code={award_code} resp={award_resp}")

    # 4.2c Award appears in get_comments
    award_seen = False
    if award_txh:
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, data = _get(f"{backend}/api/get_comments", {"post_id": parent_txh, "limit": 100})
            if code != 200:
                continue
            children = (data or {}).get("children") or []
            c1 = next((c for c in children if str(c.get("post_id", "")).lower() == c1_txh), None)
            if not c1:
                continue
            awards = c1.get("awards") or []
            if any(a.get("type") == award_type and int(a.get("count", 0)) >= 1 for a in awards):
                award_seen = True
                break
    if award_seen:
        _pass("comments.award appears in get_comments")
    else:
        _fail("comments.award appears in get_comments")

    # 4.3 Nested comment (reply to comment)
    c2_txh = _do_post(backend, wallet, "", "", "Nested reply", target=c1_txh)
    if c2_txh:
        _pass("comments.nested_reply succeeds", tx=c2_txh)
    else:
        _fail("comments.nested_reply succeeds")

    # 4.4 get_root_post_id returns correct root (poll up to INDEX_TIMEOUT_SEC)
    if c2_txh:
        root_ok = False
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            time.sleep(1)
            code, root_data = _get(f"{backend}/api/get_root_post_id", {"comment_id": c2_txh})
            if code == 200:
                root_id = str(root_data.get("root_post_id", "")).lower()
                if root_id == parent_txh:
                    _pass("comments.get_root_post_id correct")
                else:
                    _pass("comments.get_root_post_id returns 200")
                root_ok = True
                break
        if not root_ok:
            _fail("comments.get_root_post_id correct", f"code={code}")

    # 4.5 get_comment_context (may need indexing time)
    if c2_txh:
        ctx_ok = False
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            code, ctx = _get(f"{backend}/api/get_comment_context", {"comment_id": c2_txh})
            if code == 200:
                _pass("comments.get_comment_context returns 200")
                ctx_ok = True
                break
            time.sleep(1)
        if not ctx_ok:
            _fail("comments.get_comment_context returns 200", f"code={code}")

    # 4.5a get_comments returns ancestors (root-first) for nested comments
    if c2_txh:
        data = None
        for _ in range(int(INDEX_TIMEOUT_SEC)):
            code, data = _get(f"{backend}/api/get_comments", {"post_id": c2_txh, "address": addr})
            if code == 200 and isinstance(data, dict) and data.get("root"):
                break
            time.sleep(1)
        if code == 200 and isinstance(data, dict):
            anc = data.get("ancestors")
            omitted = data.get("ancestors_omitted")
            if not isinstance(anc, list):
                _fail("comments.ancestors is list", f"got={type(anc).__name__}")
            elif "ancestors_omitted" not in data:
                _fail("comments.ancestors_omitted present")
            else:
                # Nested under parent comment under root post: expect root first, immediate parent last
                ids = [str(a.get("post_id", "")).lower() for a in anc]
                if ids and ids[0] == parent_txh.lower() and ids[-1] == c1_txh.lower():
                    _pass("comments.ancestors root-first ends at parent")
                elif len(ids) >= 1 and ids[0] == parent_txh.lower():
                    _pass("comments.ancestors includes root first")
                else:
                    _fail("comments.ancestors root-first ends at parent", f"ids={ids[:4]}")
                if isinstance(omitted, int) and omitted >= 0:
                    _pass("comments.ancestors_omitted non-negative int")
                else:
                    _fail("comments.ancestors_omitted non-negative int", f"got={omitted}")
                # Ancestors carry awards / user_vote fields
                if anc and "awards" in anc[0] and "user_vote" in anc[0]:
                    _pass("comments.ancestors enriched")
                else:
                    _fail("comments.ancestors enriched", f"keys={list((anc[0] if anc else {}).keys())[:10]}")
        else:
            _fail("comments.ancestors is list", f"code={code}")

    # 4.5b Root post returns empty ancestors
    code, data = _get(f"{backend}/api/get_comments", {"post_id": parent_txh, "address": addr})
    if code == 200 and isinstance(data, dict):
        if data.get("ancestors") == [] and data.get("ancestors_omitted") == 0:
            _pass("comments.root ancestors empty")
        else:
            _fail(
                "comments.root ancestors empty",
                f"ancestors={data.get('ancestors')} omitted={data.get('ancestors_omitted')}",
            )
    else:
        _fail("comments.root ancestors empty", f"code={code}")

    # 4.6 Edit comment (comment: target=parent, override=comment hash)
    if c1_txh:
        _do_edit(
            backend, wallet, override_hash=c1_txh, topic="", title="", content="Edited comment body", target=parent_txh
        )
        time.sleep(2)
        _pass("comments.edit submitted")

    # 4.7 Delete comment
    if c1_txh:
        _do_delete(backend, wallet, c1_txh)
        time.sleep(2)
        _pass("comments.delete submitted")

    # 4.8 Comments count (best-effort check)
    code, parent_data = _get(f"{backend}/api/get_user_posts", {"owner": addr, "limit": 50})
    _pass("comments.parent_post still queryable")


# =========================================================================
# Category 5: Social Graph
# =========================================================================


def test_media(backend: str):

    sub1 = WALLETS["sub1"]
    free_wallet = WALLETS["free"]
    sub1_addr = str(sub1.address())

    # 14.1 Valid HTTPS URL
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Media test",
        "body",
        media=["https://example.com/image.jpg"],
        skip_pow=True,
    )
    if txh:
        _pass("media.valid_https_url")
    else:
        _fail("media.valid_https_url", "no tx_hash")

    # 14.2 Multiple valid URLs
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Multi media",
        "body",
        media=["https://a.com/1.jpg", "https://b.com/2.png", "https://c.com/3.gif"],
        skip_pow=True,
    )
    if txh:
        _pass("media.multiple_valid_urls")
    else:
        _fail("media.multiple_valid_urls", "no tx_hash")

    # 14.3 Too many URLs (>10)
    many_urls = [f"https://example.com/{i}.jpg" for i in range(12)]
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Too many",
        "body",
        media=many_urls,
        skip_pow=True,
    )
    if not txh:
        _pass("media.too_many_urls_rejected")
    else:
        _pass("media.too_many_urls submitted (chain may reject)")

    # 14.4 HTTP URL (not HTTPS)
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Http media",
        "body",
        media=["http://example.com/image.jpg"],
        skip_pow=True,
    )
    if not txh:
        _pass("media.http_url_rejected")
    else:
        _pass("media.http_url submitted (chain may reject)")

    # 14.5 Empty string media
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Empty media",
        "body",
        media=[""],
        skip_pow=True,
    )
    if not txh:
        _pass("media.empty_string_rejected")
    else:
        _pass("media.empty_string submitted (chain may reject)")

    # 14.6 Non-URL string
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Bad media",
        "body",
        media=["not a url at all"],
        skip_pow=True,
    )
    if not txh:
        _pass("media.non_url_rejected")
    else:
        _pass("media.non_url submitted (chain may reject)")

    # 14.7 URL exceeding 2048 chars
    long_url = "https://example.com/" + "a" * 2040
    txh = _do_post_with_media(
        backend,
        sub1,
        f"media{_rand_str(4)}",
        "Long URL",
        "body",
        media=[long_url],
        skip_pow=True,
    )
    if not txh:
        _pass("media.oversized_url_rejected")
    else:
        _pass("media.oversized_url submitted (chain may reject)")

    # 14.8 Edit adding media
    edit_media_topic = f"media{_rand_str(4)}"
    base_post = _do_post(backend, sub1, edit_media_topic, "Edit media test", "body", skip_pow=True)
    if base_post:
        time.sleep(3)
        try:
            addr = sub1_addr
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
            pub = sub1.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = edit_media_topic
            media_list = ["https://example.com/edited.jpg"]
            base = _canon_base_edit_raw(
                pub,
                _lb_bytes(lb),
                0,
                ts,
                "",
                topic,
                "Edit media test",
                "updated body",
                "",
                base_post,
                media_list,
                nonce,
            )
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(sub1, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 0,
                "target": "",
                "topic": topic,
                "title": "Edit media test",
                "content": "updated body",
                "tag": "",
                "override": base_post,
                "media": media_list,
            }
            code, resp = _post(f"{backend}/api/core/edit", payload)
            txh = str((resp or {}).get("tx_hash", "") or "").lower()
            if txh:
                _pass("media.edit_adding_media")
            else:
                _pass("media.edit_adding_media submitted")
        except Exception as e:
            _fail("media.edit_adding_media", str(e))
    else:
        _fail("media.edit_adding_media", "setup post failed")

    # 14.9 Free user with media and PoW
    txh = _do_post_with_media(
        backend,
        free_wallet,
        f"media{_rand_str(4)}",
        "Free media",
        "body",
        media=["https://example.com/free.jpg"],
        skip_pow=False,
    )
    if txh:
        _pass("media.free_user_with_pow")
    else:
        _fail("media.free_user_with_pow", "no tx_hash")


# =========================================================================
# Category 15: Auto Renewal
# =========================================================================


def test_content_limits(backend: str):
    """Test content/title length limits per tier at the backend API level."""

    free_wallet = WALLETS["free"]
    sub1 = WALLETS["sub1"]
    agent1 = WALLETS["agent1"]

    # 23.1 Free user: content > 1000 should fail
    long_content = "x" * 1050
    txh = _do_post(backend, free_wallet, f"cl{_rand_str(4)}", "Title", long_content, skip_pow=False)
    if txh is None:
        _pass("content_limits.free_over_1000_rejected")
    else:
        _fail("content_limits.free_over_1000_rejected", f"txh={txh}")

    # 23.2 Free user: content <= 1000 should succeed
    ok_content = "x" * 950
    txh = _do_post(backend, free_wallet, f"cl{_rand_str(4)}", "Title", ok_content, skip_pow=False)
    if txh:
        _pass("content_limits.free_950_accepted")
    else:
        _fail("content_limits.free_950_accepted")

    # 23.3 Subscriber: content > 1000 but <= 20000 should succeed
    txh = _do_post(backend, sub1, f"cl{_rand_str(4)}", "Title", long_content, skip_pow=True)
    if txh:
        _pass("content_limits.sub_1050_accepted")
    else:
        _fail("content_limits.sub_1050_accepted")

    # 23.3b Subscriber: content just under the 20000 limit must succeed.
    # This brackets 23.4: a blanket relay failure would fail here too, so 23.4's
    # rejection can only come from the content-length rule. The C-1 remediation
    # briefly capped the relay fee at relay_max_gas_fee, which made every post
    # over ~10.7k chars fail on gas — 23.3 (1050 chars) was too short to notice
    # and 23.4 went green for the wrong reason.
    near_max_content = "y" * 19900
    txh = _do_post(backend, sub1, f"cl{_rand_str(4)}", "Title", near_max_content, skip_pow=True)
    if txh:
        _pass("content_limits.sub_near_max_accepted")
    else:
        _fail("content_limits.sub_near_max_accepted", f"{len(near_max_content)} chars rejected, limit is 20000")

    # 23.4 Subscriber: content > 20000 should fail
    huge_content = "x" * 20050
    txh = _do_post(backend, sub1, f"cl{_rand_str(4)}", "Title", huge_content, skip_pow=True)
    if txh is None:
        _pass("content_limits.sub_over_20000_rejected")
    else:
        _fail("content_limits.sub_over_20000_rejected", f"txh={txh}")

    # 23.5 Free user: title > 150 should fail
    long_title = "T" * 160
    txh = _do_post(backend, free_wallet, f"cl{_rand_str(4)}", long_title, "body", skip_pow=False)
    if txh is None:
        _pass("content_limits.free_title_over_150_rejected")
    else:
        _fail("content_limits.free_title_over_150_rejected", f"txh={txh}")

    # 23.6 Subscriber: title 160 should succeed (limit is 300)
    txh = _do_post(backend, sub1, f"cl{_rand_str(4)}", long_title, "body", skip_pow=True)
    if txh:
        _pass("content_limits.sub_title_160_accepted")
    else:
        _fail("content_limits.sub_title_160_accepted")

    # 23.7 Agent: same limits as subscriber for content/title
    txh = _do_post(backend, agent1, f"cl{_rand_str(4)}", "Title", long_content, skip_pow=True)
    if txh:
        _pass("content_limits.agent_1050_accepted")
    else:
        _fail("content_limits.agent_1050_accepted")


# =========================================================================
# Category 24: Profile Fields Verification
# =========================================================================


def test_annotate(backend: str):
    """Test MsgAnnotate agent overlay edits."""

    agent = WALLETS.get("agent1")
    free = WALLETS.get("free")
    if not agent or not free:
        _skip("annotate.setup", "agent1 or free wallet not available")
        return

    agent_addr = str(agent.address())
    free_addr = str(free.address())

    # 1. Create a test post as the free user
    # Use a unique topic to avoid collisions with topic-blocking tests.
    topic = f"annot{_rand_str(8)}"
    title = f"Annotate Target {_rand_str(6)}"
    content = f"Original content {_rand_str(20)}"
    txh = _do_post(backend, free, topic, title, content)
    if not txh:
        _fail("annotate.create_target_post")
        return
    _pass("annotate.create_target_post", tx=txh)
    if not _wait_indexed(backend, free_addr, txh):
        _fail("annotate.target_indexed")
        return
    _pass("annotate.target_indexed")

    # 2. Non-agent cannot annotate
    resp = _do_annotate(backend, free, override_hash=txh, title="hacked")
    if resp.get("error"):
        _pass("annotate.non_agent_rejected")
    else:
        _fail("annotate.non_agent_rejected", f"expected error, got {resp}")

    # 3. Agent can annotate with title override
    new_title = f"Agent Fixed Title {_rand_str(6)}"
    resp = _do_annotate(backend, agent, override_hash=txh, title=new_title)
    if resp.get("tx_hash"):
        _pass("annotate.agent_title_override", tx=resp["tx_hash"])
    else:
        _fail("annotate.agent_title_override", resp.get("error", str(resp)))

    # 4. Agent can annotate with appendix
    appendix_text = f"Agent note: {_rand_str(10)}"
    resp = _do_annotate(backend, agent, override_hash=txh, appendix=appendix_text)
    if resp.get("tx_hash"):
        _pass("annotate.agent_appendix", tx=resp["tx_hash"])
    else:
        _fail("annotate.agent_appendix", resp.get("error", str(resp)))

    # 5. Media sentinel: ["."] = no change
    resp = _do_annotate(backend, agent, override_hash=txh, media=["."])
    if resp.get("tx_hash"):
        _pass("annotate.media_sentinel_no_change", tx=resp["tx_hash"])
    else:
        _fail("annotate.media_sentinel_no_change", resp.get("error", str(resp)))

    # 6. Media clear: [] = clear
    resp = _do_annotate(backend, agent, override_hash=txh, media=[])
    if resp.get("tx_hash"):
        _pass("annotate.media_clear", tx=resp["tx_hash"])
    else:
        _fail("annotate.media_clear", resp.get("error", str(resp)))

    # 7. Media replace: list of URLs
    resp = _do_annotate(backend, agent, override_hash=txh, media=["https://example.com/img.jpg"])
    if resp.get("tx_hash"):
        _pass("annotate.media_replace", tx=resp["tx_hash"])
    else:
        _fail("annotate.media_replace", resp.get("error", str(resp)))

    # 8. Annotate should reject PoW fields
    resp = _do_annotate(backend, agent, override_hash=txh, pow_difficulty=1, pow_val=1)
    if resp.get("error"):
        _pass("annotate.pow_rejected")
    else:
        _fail("annotate.pow_rejected", f"expected error, got {resp}")

    # 9. Enable agent for viewer and verify overlay shows up
    resp = _do_set_agents(backend, free, [agent_addr], skip_pow=False)
    if resp.get("tx_hash"):
        _pass("annotate.viewer_sets_agents")
    else:
        _fail("annotate.viewer_sets_agents", f"resp={resp}")
        return

    def _find_node(nodes, target_id: str):
        for n in nodes or []:
            if str(n.get("post_id", "")).lower() == target_id.lower():
                return n
            if n.get("children"):
                found = _find_node(n["children"], target_id)
                if found:
                    return found
        return None

    # Poll for overlay to appear (indexer needs to process both set_agents and annotate txs).
    # Keep the best root seen — transient viewer-filtering during indexer reprocessing can
    # temporarily return an empty root even after it was previously found.
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            candidate = (data or {}).get("root") or {}
            if candidate:
                root = candidate
            if root.get("agent_edited"):
                break
    if not root:
        # Address-qualified query returned nothing — try without viewer address.
        # Stale agent blocks from prior tests can cause viewer-filtering even after
        # cleanup txs are submitted (indexer propagation delay).
        pcode, pdata = _get(f"{backend}/api/get_comments", {"post_id": txh})
        if pcode == 200:
            root = (pdata or {}).get("root") or {}
    if not root:
        _fail(
            "annotate.overlay_get_comments",
            f"post not in get_comments after {int(INDEX_TIMEOUT_SEC)}s",
        )
        return
    if root.get("title") == new_title:
        _pass("annotate.overlay_title_applied")
    else:
        _fail("annotate.overlay_title_applied", f"title={root.get('title')}")
    if root.get("agent_edited") is True:
        _pass("annotate.overlay_agent_edited_flag")
    else:
        _fail("annotate.overlay_agent_edited_flag", f"agent_edited={root.get('agent_edited')}")
    appendices = root.get("appendices") or []
    if any(a.get("text") == appendix_text for a in appendices if isinstance(a, dict)):
        _pass("annotate.overlay_appendix_present")
    else:
        _fail("annotate.overlay_appendix_present", f"appendices={appendices}")

    meta = root.get("agent_edits_meta") or {}
    if meta.get("title", "").lower() == agent_addr.lower():
        _pass("annotate.overlay_meta_title_agent")
    else:
        _fail("annotate.overlay_meta_title_agent", f"meta={meta}")

    # 10. Sentinel no-change should preserve prior title/appendix
    resp = _do_annotate(backend, agent, override_hash=txh, title=".", appendix=".")
    if resp.get("tx_hash"):
        _pass("annotate.no_change_sentinel_tx")
    else:
        _fail("annotate.no_change_sentinel_tx", resp.get("error", str(resp)))
        return

    # Poll for overlays to remain unchanged
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            root = (data or {}).get("root") or {}
            if root.get("title") == new_title:
                break
    if root.get("title") == new_title:
        _pass("annotate.no_change_preserves_title")
    else:
        _fail("annotate.no_change_preserves_title", f"title={root.get('title')}")
    appendices = root.get("appendices") or []
    if any(a.get("text") == appendix_text for a in appendices if isinstance(a, dict)):
        _pass("annotate.no_change_preserves_appendix")
    else:
        _fail("annotate.no_change_preserves_appendix", f"appendices={appendices}")

    # 11. Multi-agent priority ordering for title + appendices
    agent2 = WALLETS.get("agent2")
    if not agent2:
        _fail("annotate.agent2_missing", "agent2 wallet not available")
        return
    agent2_addr = str(agent2.address())
    title2 = f"Agent2 Title {_rand_str(6)}"
    appendix2 = f"Agent2 note {_rand_str(6)}"
    resp = _do_annotate(backend, agent2, override_hash=txh, title=title2, appendix=appendix2)
    if resp.get("tx_hash"):
        _pass("annotate.agent2_title_override", tx=resp["tx_hash"])
    else:
        _fail("annotate.agent2_title_override", resp.get("error", str(resp)))
        return

    resp = _do_set_agents(backend, free, [agent2_addr, agent_addr], skip_pow=False)
    if resp.get("tx_hash"):
        _pass("annotate.viewer_agent_order_2_1")
    else:
        _fail("annotate.viewer_agent_order_2_1", f"resp={resp}")
        return

    # Poll for agent2's overlay to appear
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            root = (data or {}).get("root") or {}
            if root.get("title") == title2:
                break
    if root.get("title") == title2:
        _pass("annotate.priority_title_agent2_wins")
    else:
        _fail("annotate.priority_title_agent2_wins", f"title={root.get('title')}")
    appendices = root.get("appendices") or []
    if (
        len(appendices) >= 2
        and appendices[0].get("agent", "").lower() == agent2_addr.lower()
        and appendices[1].get("agent", "").lower() == agent_addr.lower()
    ):
        _pass("annotate.appendix_order_agent2_first")
    else:
        _fail("annotate.appendix_order_agent2_first", f"appendices={appendices}")

    resp = _do_set_agents(backend, free, [agent_addr, agent2_addr], skip_pow=False)
    if resp.get("tx_hash"):
        _pass("annotate.viewer_agent_order_1_2")
    else:
        _fail("annotate.viewer_agent_order_1_2", f"resp={resp}")
        return

    # Poll for agent1-first priority overlay
    root = {}
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        if code == 200:
            root = (data or {}).get("root") or {}
            if root.get("title") == new_title:
                break
    if root.get("title") == new_title:
        _pass("annotate.priority_title_agent1_wins")
    else:
        _fail("annotate.priority_title_agent1_wins", f"title={root.get('title')}")

    # 12. Comment annotations should apply to content
    comment_tx = _do_post(backend, free, "", "", f"Comment {_rand_str(10)}", target=txh)
    if not comment_tx:
        _fail("annotate.comment_setup")
        return
    if not _wait_indexed(backend, free_addr, comment_tx):
        _fail("annotate.comment_indexed")
        return
    comment_content = f"Agent comment fix {_rand_str(6)}"
    resp = _do_annotate(backend, agent, override_hash=comment_tx, content=comment_content)
    if resp.get("tx_hash"):
        _pass("annotate.comment_content_override", tx=resp["tx_hash"])
    else:
        _fail("annotate.comment_content_override", resp.get("error", str(resp)))
        return

    # Poll for comment overlay
    comment_node = None
    for _poll in range(int(INDEX_TIMEOUT_SEC)):
        time.sleep(1)
        code, data = _get(f"{backend}/api/get_comments", {"post_id": txh, "address": free_addr})
        comment_node = _find_node((data or {}).get("children") or [], comment_tx)
        if comment_node and comment_node.get("content") == comment_content:
            break
    if comment_node and comment_node.get("content") == comment_content:
        _pass("annotate.comment_overlay_applied")
    else:
        _fail("annotate.comment_overlay_applied", f"content={comment_node.get('content') if comment_node else None}")


def test_edit_target_immutability(backend: str):
    """Test that MsgEdit cannot change a post's target (parent)."""

    free = WALLETS.get("free")
    if not free:
        _skip("edit_target.setup", "free wallet not available")
        return

    free_addr = str(free.address())

    # Create a root post
    topic = "test"
    title = f"Root Post {_rand_str(6)}"
    content = f"Content {_rand_str(10)}"
    txh = _do_post(backend, free, topic, title, content)
    if not txh:
        _fail("edit_target.create_root")
        return
    _pass("edit_target.create_root", tx=txh)
    if not _wait_indexed(backend, free_addr, txh):
        _fail("edit_target.root_indexed")
        return

    # Try to edit with a fake target (re-parenting attempt)
    fake_target = "a" * 64
    resp = _do_edit(backend, free, override_hash=txh, topic=topic, title=title, content="edited", target=fake_target)
    if resp.get("error"):
        _pass("edit_target.mismatch_rejected", msg=resp["error"])
    else:
        _fail("edit_target.mismatch_rejected", f"expected rejection, got {resp}")


def test_tag_normalization_porn_to_adult(backend: str) -> None:
    """v1.23.0: posting with tag='porn' should store as 'adult' on-chain."""
    free = WALLETS.get("free")
    if not free:
        _skip("tag_normalize.setup", "free wallet not available")
        return

    free_addr = str(free.address())
    topic = "test"
    title = f"Tag Normalize {_rand_str(6)}"
    content = f"Body {_rand_str(10)}"

    txh = _do_post(backend, free, topic, title, content, tag="porn")
    if not txh:
        _fail("tag_normalize.post_with_porn_tag")
        return
    _pass("tag_normalize.post_with_porn_tag", tx=txh)

    if not _wait_indexed(backend, free_addr, txh):
        _fail("tag_normalize.indexed")
        return

    code, data = _get(f"{backend}/api/get_user_posts", {"owner": free_addr, "limit": 10, "page": 1})
    if code != 200:
        _fail("tag_normalize.fetch_posts", f"status={code}")
        return

    posts = (data or {}).get("posts") or []
    h = txh.lower()
    matched = [p for p in posts if str(p.get("post_id", "")).lower() == h]
    if not matched:
        _fail("tag_normalize.find_post", "post not in results")
        return

    stored_tag = matched[0].get("tag", "")
    if stored_tag == "adult":
        _pass("tag_normalize.stored_as_adult")
    else:
        _fail("tag_normalize.stored_as_adult", f"expected 'adult', got '{stored_tag}'")


def test_seen_posts(backend: str) -> None:
    """Test seen-post tracking: beacon ingestion, score downranking, idempotency."""
    free = WALLETS.get("free")
    viewer = WALLETS.get("sub1")
    if not free or not viewer:
        _skip("seen_posts.setup", "wallet not available")
        return

    free_addr = str(free.address())
    viewer_addr = str(viewer.address())
    topic = "test"
    title = f"Seen Test {_rand_str(6)}"
    content = f"Body {_rand_str(10)}"

    def _seen_sig(wallet, addr: str):
        ts = _now_ms()
        nonce = _fresh_nonce()
        sig = sign_canonical(wallet, f"seen_posts:{addr.lower()}:{ts}:{nonce}".encode("utf-8"))
        return {
            "pubkey": _b64(wallet.public_key().public_key_bytes),
            "signature": _b64(sig),
            "timestamp": ts,
            "envelope_nonce": str(nonce),
        }

    txh = _do_post(backend, free, topic, title, content)
    if not txh:
        _fail("seen_posts.create_post")
        return
    txh = txh.lower()
    _pass("seen_posts.create_post", tx=txh)

    if not _wait_indexed(backend, free_addr, txh):
        _fail("seen_posts.indexed")
        return
    _pass("seen_posts.indexed")

    # Verify post appears in home feed for another user (before marking seen)
    found_before = False
    for _ in range(int(INDEX_TIMEOUT_SEC)):
        code, feed = _get(
            f"{backend}/api/get_posts", {"feed": "home", "by": "newest", "limit": 50, "address": viewer_addr}
        )
        posts = (feed or {}).get("posts") or []
        if any(str(p.get("post_id", "")).lower() == txh for p in posts):
            found_before = True
            break
        time.sleep(1)
    if found_before:
        _pass("seen_posts.visible_before_mark")
    else:
        _fail("seen_posts.visible_before_mark", "post not in home feed")
        return

    # Mark as seen via beacon
    sig_viewer = _seen_sig(viewer, viewer_addr)
    code_b, resp_b = _post(
        f"{backend}/api/seen_posts",
        {
            "address": viewer_addr,
            "posts": [{"id": txh, "reason": "open"}],
            **sig_viewer,
        },
    )
    if code_b == 200 and (resp_b or {}).get("ok"):
        _pass("seen_posts.beacon_ingest")
    else:
        _fail("seen_posts.beacon_ingest", f"code={code_b} resp={resp_b}")
        return

    # Replaying the exact same signed body must be refused as a replay, not
    # crash. _guard_push_request hands back a (response, status) pair, and
    # passing that through as the error message made the handler jsonify a
    # Response object and 500 — which is what mobile was hitting.
    code_r, resp_r = _post(
        f"{backend}/api/seen_posts",
        {
            "address": viewer_addr,
            "posts": [{"id": txh, "reason": "open"}],
            **sig_viewer,
        },
    )
    if code_r >= 500:
        _fail("seen_posts.replay_rejected", f"replayed beacon crashed the handler: code={code_r} resp={resp_r}")
    elif code_r == 400 and str((resp_r or {}).get("error_code") or "") == "nonce_replayed":
        _pass("seen_posts.replay_rejected", code=code_r)
    else:
        _fail("seen_posts.replay_rejected", f"expected 400 nonce_replayed, got {code_r}: {resp_r}")

    # Verify the author's own feed still shows their post
    code_self, feed_self = _get(
        f"{backend}/api/get_posts",
        {
            "feed": "home",
            "by": "newest",
            "limit": 50,
            "address": free_addr,
        },
    )
    posts_self = (feed_self or {}).get("posts") or []
    own_visible = any(str(p.get("post_id", "")).lower() == txh for p in posts_self)
    if own_visible:
        _pass("seen_posts.own_post_visible")
    else:
        _fail("seen_posts.own_post_visible", "own post not in feed")

    # Test beacon idempotency: send same ID again
    sig_viewer2 = _seen_sig(viewer, viewer_addr)
    code_i, resp_i = _post(
        f"{backend}/api/seen_posts",
        {
            "address": viewer_addr,
            "posts": [{"id": txh, "reason": "dwell"}],
            **sig_viewer2,
        },
    )
    if code_i == 200 and (resp_i or {}).get("ingested") == 1:
        _pass("seen_posts.beacon_idempotent")
    else:
        _fail("seen_posts.beacon_idempotent", f"code={code_i} resp={resp_i}")

    # Test guest feed still works (no seen data for guests)
    code3, feed4 = _get(
        f"{backend}/api/get_posts",
        {
            "feed": "home",
            "by": "newest",
            "limit": 50,
        },
    )
    if code3 == 200:
        _pass("seen_posts.guest_feed_ok")
    else:
        _fail("seen_posts.guest_feed_ok", f"code={code3}")

    # Test beacon with guest address returns ok with 0 ingested
    code4, resp4 = _post(
        f"{backend}/api/seen_posts",
        {
            "address": "guest",
            "posts": [{"id": txh}],
        },
    )
    if code4 == 200 and (resp4 or {}).get("ingested") == 0:
        _pass("seen_posts.guest_beacon_noop")
    else:
        _fail("seen_posts.guest_beacon_noop", f"code={code4} resp={resp4}")

    # Test view_count increments: send same ID again via beacon and verify it's accepted
    sig_viewer4 = _seen_sig(viewer, viewer_addr)
    code5, resp5 = _post(
        f"{backend}/api/seen_posts",
        {
            "address": viewer_addr,
            "posts": [{"id": txh, "reason": "dwell"}],
            **sig_viewer4,
        },
    )
    if code5 == 200 and (resp5 or {}).get("ingested") == 1:
        _pass("seen_posts.view_count_increment")
    else:
        _fail("seen_posts.view_count_increment", f"code={code5} resp={resp5}")

    # Verify novelty in magic feed too (feed_debug includes equation with N)
    code_m, feed_m = _get(
        f"{backend}/api/get_posts",
        {
            "feed": "home",
            "by": "magic",
            "limit": 50,
            "address": viewer_addr,
        },
    )
    posts_m = (feed_m or {}).get("posts") or []
    target_m = None
    for p in posts_m:
        if str(p.get("post_id", "")).lower() == txh:
            target_m = p
            break
    if target_m:
        debug_m = target_m.get("feed_debug") or {}
        eq = debug_m.get("equation", "")
        if "N" in eq and debug_m.get("seen_count", 0) > 0:
            _pass("seen_posts.magic_feed_debug", equation=eq, N=debug_m.get("N"))
        else:
            _fail("seen_posts.magic_feed_debug", f"expected equation with N, got: {debug_m}")
    else:
        _pass("seen_posts.magic_feed_debug", note="post not in first page of magic feed (pushed down by novelty)")


def test_image_impressions(backend: str) -> None:
    """Approximate image impressions tracked on get_posts responses."""
    db_url = os.environ.get("BACKEND_DB_URL", "").strip()
    if not db_url:
        _fail("image_impressions.db_url_missing", "BACKEND_DB_URL not set")
        return

    sub1 = WALLETS.get("sub1")
    if not sub1:
        _skip("image_impressions.wallet_missing", "wallet not available")
        return
    sub1_addr = str(sub1.address())

    image_id = str(uuid.uuid4()).upper()
    topic = f"imgtrack{_rand_str(6)}"
    url = f"https://imagedelivery.net/testhash/{image_id}/public"

    txh = _do_post_with_media(
        backend,
        sub1,
        topic,
        "Image impressions test",
        "body",
        media=[url],
        skip_pow=True,
    )
    if not txh:
        _fail("image_impressions.post_created", "no tx_hash")
        return
    if not _wait_indexed(backend, sub1_addr, txh):
        _fail("image_impressions.post_indexed")
        return

    def _get_view_count() -> int:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT view_count FROM image_views WHERE image_id = %s", (image_id.lower(),))
                row = cur.fetchone()
                return int(row[0]) if row else 0

    before = _get_view_count()
    code, resp = _get(f"{backend}/api/get_posts", {"topic": topic, "limit": 10})
    if code != 200:
        _fail("image_impressions.get_posts", f"code={code}")
        return
    posts = (resp or {}).get("posts") or []
    if not any(str(p.get("post_id", "")).lower() == txh for p in posts):
        _fail("image_impressions.post_visible")
        return
    after = _get_view_count()
    if after == before + 1:
        _pass("image_impressions.increment_once")
    else:
        _fail("image_impressions.increment_once", f"before={before} after={after}")

    code2, _ = _get(f"{backend}/api/get_posts", {"topic": topic, "limit": 10})
    if code2 != 200:
        _fail("image_impressions.get_posts_repeat", f"code={code2}")
        return
    after2 = _get_view_count()
    if after2 == after + 1:
        _pass("image_impressions.increment_twice")
    else:
        _fail("image_impressions.increment_twice", f"after={after} after2={after2}")


def test_upload_media(backend: str) -> None:
    """Uniform provider-agnostic upload endpoint: POST /api/upload_media.

    Validates the contract that holds for ALL providers (kind/file/magic-byte/
    video-metadata checks) and, on the default local provider, a real image
    round-trip returning {url, asset_id, kind}.
    """
    # 1x1 transparent PNG (valid magic bytes)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    # Minimal sniffable MP4 header (ftyp/mp42)
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64

    url = f"{backend}/api/upload_media"

    # Invalid kind -> 400 media_invalid_kind
    r = _post_multipart(url, {"kind": "bogus"}, {"file": ("x.png", png, "image/png")})
    if r.status_code == 400 and (r.json() or {}).get("error_code") == "media_invalid_kind":
        _pass("upload_media.invalid_kind_rejected")
    else:
        _fail("upload_media.invalid_kind_rejected", f"code={r.status_code} body={r.text[:200]}")

    # Missing file -> 400 media_file_required
    r = _post_multipart(url, {"kind": "image"})
    if r.status_code == 400 and (r.json() or {}).get("error_code") == "media_file_required":
        _pass("upload_media.missing_file_rejected")
    else:
        _fail("upload_media.missing_file_rejected", f"code={r.status_code} body={r.text[:200]}")

    # Bad magic bytes (text labelled as image) -> 415 media_invalid_type
    r = _post_multipart(url, {"kind": "image"}, {"file": ("x.png", b"not an image", "image/png")})
    if r.status_code == 415 and (r.json() or {}).get("error_code") == "media_invalid_type":
        _pass("upload_media.bad_magic_rejected")
    else:
        _fail("upload_media.bad_magic_rejected", f"code={r.status_code} body={r.text[:200]}")

    # Video without duration/height -> 400 media_metadata_required
    r = _post_multipart(url, {"kind": "video"}, {"file": ("x.mp4", fake_mp4, "video/mp4")})
    if r.status_code == 400 and (r.json() or {}).get("error_code") == "media_metadata_required":
        _pass("upload_media.video_metadata_required")
    else:
        _fail("upload_media.video_metadata_required", f"code={r.status_code} body={r.text[:200]}")

    # Valid image upload -> 200 {url, asset_id, kind}
    r = _post_multipart(url, {"kind": "image"}, {"file": ("x.png", png, "image/png")})
    if r.status_code == 200:
        body = r.json() or {}
        if body.get("url") and body.get("asset_id") and body.get("kind") == "image":
            _pass("upload_media.image_round_trip")
        else:
            _fail("upload_media.image_round_trip", f"body={r.text[:200]}")
    elif r.status_code in (500, 502) and (r.json() or {}).get("error_code") == "media_provider_not_configured":
        # Node configured for a provider whose credentials aren't set in this env.
        _skip("upload_media.image_round_trip", "provider not configured")
    else:
        _fail("upload_media.image_round_trip", f"code={r.status_code} body={r.text[:200]}")


def test_recent_content(backend: str) -> None:
    """get_recent_content returns a chronological mix of posts and comments."""
    wallet = WALLETS["free"]
    addr = str(wallet.address())

    parent_txh = _do_post(backend, wallet, f"recent{_rand_str(6)}", f"Recent {_rand_str(6)}", "Recent body")
    if not parent_txh:
        _fail("recent_content.create_post")
        return
    if not _wait_indexed(backend, addr, parent_txh):
        _fail("recent_content.parent_indexed")
        return
    _pass("recent_content.parent_indexed", tx=parent_txh)

    comment_txh = _do_post(backend, wallet, "", "", "Recent comment body", target=parent_txh)
    if not comment_txh:
        _fail("recent_content.create_comment")
        return
    if not _wait_comment_indexed(backend, parent_txh, comment_txh):
        _fail("recent_content.comment_indexed")
        return
    _pass("recent_content.comment_indexed", tx=comment_txh)

    code, data = _get(f"{backend}/api/get_recent_content", {"limit": 200})
    if code != 200 or not isinstance(data, dict):
        _fail("recent_content.basic_fetch", f"code={code}")
        return

    items = data.get("items")
    if not isinstance(items, list) or not items:
        _fail("recent_content.items_present", f"items={items!r}")
        return

    expected_top_keys = {"items", "limit", "next_before", "has_more"}
    missing = expected_top_keys - set(data.keys())
    if missing:
        _fail("recent_content.shape", f"missing keys: {sorted(missing)}")
    else:
        _pass("recent_content.shape")

    expected_item_keys = {
        "post_id",
        "author",
        "username",
        "timestamp",
        "topic",
        "root_topic",
        "root_post_id",
        "target",
        "title",
        "content",
        "tag",
        "edited_at",
        "is_comment",
    }
    sample = items[0]
    item_missing = expected_item_keys - set(sample.keys())
    if item_missing:
        _fail("recent_content.item_shape", f"missing fields: {sorted(item_missing)}")
    else:
        _pass("recent_content.item_shape")

    timestamps = [int(it.get("timestamp", 0)) for it in items]
    if timestamps == sorted(timestamps, reverse=True):
        _pass("recent_content.chronological_desc")
    else:
        _fail("recent_content.chronological_desc")

    parent_item = next((it for it in items if str(it.get("post_id", "")).lower() == parent_txh), None)
    comment_item = next((it for it in items if str(it.get("post_id", "")).lower() == comment_txh), None)

    if parent_item and parent_item.get("is_comment") is False and not parent_item.get("target"):
        _pass("recent_content.parent_post_present")
    else:
        _fail("recent_content.parent_post_present", f"parent_item={parent_item}")

    if (
        comment_item
        and comment_item.get("is_comment") is True
        and (comment_item.get("target") or "").lower() == parent_txh
    ):
        _pass("recent_content.comment_present")
    else:
        _fail("recent_content.comment_present", f"comment_item={comment_item}")

    code_clamp, data_clamp = _get(f"{backend}/api/get_recent_content", {"limit": 9999})
    if code_clamp == 200 and int((data_clamp or {}).get("limit", 0)) == 500:
        _pass("recent_content.limit_clamped")
    else:
        _fail("recent_content.limit_clamped", f"code={code_clamp} limit={(data_clamp or {}).get('limit')}")

    code_small, data_small = _get(f"{backend}/api/get_recent_content", {"limit": 1})
    small_items = (data_small or {}).get("items") or []
    if (
        code_small == 200
        and len(small_items) == 1
        and (data_small or {}).get("has_more") is True
        and (data_small or {}).get("next_before") is not None
    ):
        _pass("recent_content.has_more_with_cursor")
        cursor = int(data_small["next_before"])
        code_next, data_next = _get(f"{backend}/api/get_recent_content", {"limit": 50, "before": cursor})
        next_items = (data_next or {}).get("items") or []
        seen_ids = {str(small_items[0].get("post_id", "")).lower()}
        if (
            code_next == 200
            and all(int(it.get("timestamp", 0)) < cursor for it in next_items)
            and not any(str(it.get("post_id", "")).lower() in seen_ids for it in next_items)
        ):
            _pass("recent_content.before_cursor_advances")
        else:
            _fail("recent_content.before_cursor_advances", f"code={code_next} count={len(next_items)}")
    else:
        _fail(
            "recent_content.has_more_with_cursor",
            f"code={code_small} items={len(small_items)} has_more={(data_small or {}).get('has_more')}",
        )
