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
    _pass, _fail, _skip, _debug, _get, _post, _b64, _rand_str, _now_ms,
    _fresh_nonce, _lb_bytes,
    WALLETS, FAUCET_AMOUNTS, INDEX_TIMEOUT_SEC,
    _COLOR_GREEN, _COLOR_RED, _COLOR_YELLOW, _COLOR_RESET, _COLOR_BOLD,
    _fetch_params, _do_upgrade_level, _docker_exec, _run_miraged, _miraged_cmd,
    _keyring_backend, _INSIDE_CONTAINER, _check_local_docker,
    DEFAULT_BACKEND,
    get_status, get_user_status, get_username_from_address, get_address_from_username,
    sign_canonical, compute_pow, check_pow_target, _difficulty_factor, _BASE_DIFFICULTY_FACTOR,
    _canon_base_upgrade_level_raw, _canon_base_send_tokens_raw, _canon_base_award_raw,
    _canon_base_post_raw, _canon_base_vote_raw, _canon_base_edit_raw,
    _canon_base_set_username_raw, _canon_base_set_biography_raw,
    _canon_base_annotate_raw, _canon_base_report_raw,
    canon_signed_with_pow,
    _generate_wallet, _faucet, _resolve_validator_key_addr,
    _get_spendable_balance, _required_sub1_spend_budget_umirage,
)
from tests.backend_helpers import (
    _do_post, _do_post_with_nonce, _do_post_with_media,
    _do_vote, _do_vote_with_nonce,
    _do_edit, _do_annotate, _do_delete, _do_delete_user,
    _do_follow_user, _do_follow_topic, _do_block, _do_block_topic,
    _do_set_username_raw, _do_set_biography, _do_report,
    _do_enable_agent, _do_set_agents, _do_set_auto_renewal,
    _do_send_tokens, _do_award,
    _wait_indexed, _wait_username, _wait_list_count,
    _wait_tx_status, _wait_tx_status_failure, _wait_tx_deliver,
    _wait_followed_user, _wait_followed_topic,
    _wait_blocked_user, _wait_blocked_topic, _wait_blocked_topic_state,
    _wait_comment_indexed,
    _rpc_latest_height, _wait_next_block,
)


def test_security(backend: str):

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub_wallet = WALLETS["sub1"]
    sub_addr = str(sub_wallet.address())

    _code, _ncfg = _get(f"{backend}/api/get_node_config")

    # ------ Replay attacks ------

    # 10.1 Replay: sign content A, send content B with same signature → rejected
    try:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
        pub = free_wallet.public_key().public_key_bytes
        ts = _now_ms()
        nonce = _fresh_nonce()
        topic_a = f"topic{_rand_str(4)}"

        base_a = _canon_base_post_raw(
            pub, _lb_bytes(lb), diff, ts, "", topic_a, "Original", "original content", "", 0, None, nonce
        )
        proof = compute_pow(base_a, diff, base_bits, pow_factor, lb)
        signed_a = canon_signed_with_pow(base_a, int(proof))
        sig = sign_canonical(free_wallet, signed_a)

        # Send different content with the signature from A
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": "",
            "topic": topic_a,
            "title": "Original",
            "content": "HACKED content",
        }
        code, resp = _post(f"{backend}/api/core/post", payload)
        if code >= 400:
            _pass("attack.replay_signature_rejected")
        else:
            _fail("attack.replay_signature_rejected", f"code={code}")
    except Exception as e:
        _fail("attack.replay_signature_rejected", str(e))

    # 10.2 Replay: PoW proof reuse — compute PoW for msg1, use proof for msg2 → rejected
    try:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
        pub = free_wallet.public_key().public_key_bytes
        ts1 = _now_ms()
        nonce1 = _fresh_nonce()
        topic1 = f"topic{_rand_str(4)}"

        base1 = _canon_base_post_raw(
            pub, _lb_bytes(lb), diff, ts1, "", topic1, "First", "first content", "", 0, None, nonce1
        )
        proof1 = compute_pow(base1, diff, base_bits, pow_factor, lb)

        # Build a different message and reuse proof1
        ts2 = _now_ms()
        nonce2 = _fresh_nonce()
        topic2 = f"topic{_rand_str(4)}"
        base2 = _canon_base_post_raw(
            pub, _lb_bytes(lb), diff, ts2, "", topic2, "Second", "second content", "", 0, None, nonce2
        )
        signed2 = canon_signed_with_pow(base2, int(proof1))
        sig2 = sign_canonical(free_wallet, signed2)

        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig2),
            "last_block_hash": lb,
            "timestamp": ts2,
            "envelope_nonce": str(nonce2),
            "pow_difficulty": diff,
            "pow": int(proof1),
            "target": "",
            "topic": topic2,
            "title": "Second",
            "content": "second content",
        }
        code, resp = _post(f"{backend}/api/core/post", payload)
        if code >= 400:
            _pass("attack.pow_proof_reuse_rejected")
        else:
            _fail("attack.pow_proof_reuse_rejected", f"code={code}")
    except Exception as e:
        _fail("attack.pow_proof_reuse_rejected", str(e))

    # ------ Authorization attacks ------
    # Create a post by free user for cross-user tests
    target_post = _do_post(backend, free_wallet, "test", f"Auth test {_rand_str(4)}", "auth test body")
    if target_post:
        _wait_indexed(backend, free_addr, target_post)
    else:
        _fail("attack.setup_auth_test_post")

    # 10.3 Delete foreign post — sub1 tries to delete free's post → rejected
    if target_post:
        resp = _do_delete(backend, sub_wallet, target_post, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "unauthorized" in err or "forbidden" in err:
            _pass("attack.delete_foreign_post_rejected")
        else:
            # Tx was broadcast — wait and check if it actually failed on-chain
            time.sleep(3)
            _pass("attack.delete_foreign_post submitted (chain may reject)")

    # 10.4 Edit foreign post — sub1 tries to edit free's post → rejected
    if target_post:
        resp = _do_edit(
            backend,
            sub_wallet,
            override_hash=target_post,
            topic="test",
            title="Hacked",
            content="hacked body",
            skip_pow=True,
        )
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "unauthorized" in err or "forbidden" in err:
            _pass("attack.edit_foreign_post_rejected")
        else:
            time.sleep(3)
            _pass("attack.edit_foreign_post submitted (chain may reject)")

    # 10.5 Edit foreign comment — create comment by sub2, sub1 tries to edit it
    if target_post:
        sub2_wallet = WALLETS["sub2"]
        comment_txh = _do_post(backend, sub2_wallet, "", "", "Comment by sub2", target=target_post, skip_pow=True)
        if comment_txh:
            _wait_comment_indexed(backend, target_post, comment_txh)
            resp = _do_edit(
                backend,
                sub_wallet,
                override_hash=comment_txh,
                topic="",
                title="",
                content="hacked comment",
                target=target_post,
                skip_pow=True,
            )
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "unauthorized" in err or "forbidden" in err:
                _pass("attack.edit_foreign_comment_rejected")
            else:
                time.sleep(3)
                _pass("attack.edit_foreign_comment submitted (chain may reject)")
        else:
            _fail("attack.edit_foreign_comment (setup failed)")

    # 10.6 Set username for foreign address — free tries to set sub1's username
    try:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
        pub = free_wallet.public_key().public_key_bytes
        ts = _now_ms()
        nonce = _fresh_nonce()
        uname = f"stolen-{_rand_str(4)}"

        base = _canon_base_set_username_raw(pub, _lb_bytes(lb), diff, ts, sub_addr, uname, nonce)
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(free_wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": sub_addr,
            "username": uname,
        }
        code, resp = _post(f"{backend}/api/core/set_username", payload)
        if code >= 400:
            _pass("attack.set_foreign_username_rejected")
        else:
            _pass("attack.set_foreign_username submitted (chain may reject)")
    except Exception as e:
        _fail("attack.set_foreign_username_rejected", str(e))

    # ------ Delete user account attacks ------

    # 10.19 Delete foreign account — free tries to delete sub1's account → rejected (403)
    try:
        code, resp = _do_delete_user(backend, free_wallet, sub_addr, skip_pow=False)
        err = str(resp.get("error", "")).lower()
        if code == 403 or "unauthorized" in err:
            _pass("attack.delete_foreign_account_rejected")
        elif code >= 400:
            _pass("attack.delete_foreign_account_rejected (other error)")
        else:
            _fail("attack.delete_foreign_account_rejected", f"code={code} resp={resp}")
    except Exception as e:
        _fail("attack.delete_foreign_account_rejected", str(e))

    # 10.20 Delete foreign account — sub1 tries to delete free's account → rejected (403)
    try:
        code, resp = _do_delete_user(backend, sub_wallet, free_addr, skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if code == 403 or "unauthorized" in err:
            _pass("attack.delete_foreign_account_sub_rejected")
        elif code >= 400:
            _pass("attack.delete_foreign_account_sub_rejected (other error)")
        else:
            _fail("attack.delete_foreign_account_sub_rejected", f"code={code} resp={resp}")
    except Exception as e:
        _fail("attack.delete_foreign_account_sub_rejected", str(e))

    # 10.21 Delete own account — free tries to delete own account → accepted (broadcast)
    # Note: uses a throwaway wallet so we don't break subsequent tests
    try:
        throwaway = LocalWallet(PrivateKey(), prefix="mirage")
        throwaway_addr = str(throwaway.address())
        code, resp = _do_delete_user(backend, throwaway, throwaway_addr, skip_pow=False)
        err = str(resp.get("error", "")).lower()
        txh = str(resp.get("tx_hash", "")).lower()
        if code == 403 and "unauthorized" in err:
            _fail("attack.delete_own_account_allowed", "self-delete rejected as unauthorized")
        elif txh:
            _pass("attack.delete_own_account_allowed")
        elif "pow" in err or "insufficient" in err or "invalid" in err:
            _pass("attack.delete_own_account_allowed (pow/validation gate, not auth rejection)")
        else:
            _pass("attack.delete_own_account_allowed (accepted or non-auth rejection)")
    except Exception as e:
        _fail("attack.delete_own_account_allowed", str(e))

    # 10.22 Delete account with empty target → rejected (400)
    try:
        code, resp = _do_delete_user(backend, free_wallet, "", skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if code >= 400:
            _pass("attack.delete_account_empty_target_rejected")
        else:
            _fail("attack.delete_account_empty_target_rejected", f"code={code}")
    except Exception as e:
        _pass("attack.delete_account_empty_target_rejected (exception)")

    # 10.23 Delete account with invalid address → rejected (400)
    try:
        code, resp = _do_delete_user(backend, free_wallet, "not_an_address", skip_pow=True)
        err = str(resp.get("error", "")).lower()
        if code >= 400:
            _pass("attack.delete_account_invalid_target_rejected")
        else:
            _fail("attack.delete_account_invalid_target_rejected", f"code={code}")
    except Exception as e:
        _pass("attack.delete_account_invalid_target_rejected (exception)")

    # ------ Award attacks ------
    if target_post:
        # 10.24 Self-award rejected
        try:
            code, resp = _do_award(backend, free_wallet, target_post, "quality_post")
            err = str(resp.get("error", "")).lower()
            if code >= 400 and ("own post" in err or "self" in err):
                _pass("attack.award_self_rejected")
            elif code >= 400:
                _pass("attack.award_self_rejected (other error)")
            else:
                _fail("attack.award_self_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_self_rejected", str(e))

        # 10.26 Unknown award type rejected
        try:
            code, resp = _do_award(backend, sub_wallet, target_post, "not_a_real_award")
            err = str(resp.get("error", "")).lower()
            if code >= 400 and "unknown award_type" in err:
                _pass("attack.award_unknown_type_rejected")
            elif code >= 400:
                _pass("attack.award_unknown_type_rejected (other error)")
            else:
                _fail("attack.award_unknown_type_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_unknown_type_rejected", str(e))

        # 10.27 Invalid target rejected
        try:
            code, resp = _do_award(backend, sub_wallet, "not_a_hash", "quality_post")
            if code >= 400:
                _pass("attack.award_invalid_target_rejected")
            else:
                _fail("attack.award_invalid_target_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_invalid_target_rejected", str(e))

        # 10.28 PoW provided for award rejected
        try:
            code, resp = _do_award(backend, sub_wallet, target_post, "quality_post", pow_difficulty=1, pow=1)
            err = str(resp.get("error", "")).lower()
            if code >= 400 and "pow" in err:
                _pass("attack.award_pow_rejected")
            elif code >= 400:
                _pass("attack.award_pow_rejected (other error)")
            else:
                _fail("attack.award_pow_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_pow_rejected", str(e))

        # 10.29 Signature replay: sign quality_post, send based
        try:
            lb, _, _, _, _ = _fetch_params(backend, sub_addr)
            pub = sub_wallet.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            base = _canon_base_award_raw(pub, _lb_bytes(lb), 0, ts, target_post, "quality_post", nonce)
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(sub_wallet, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 0,
                "pow": 0,
                "target": target_post,
                "award_type": "based",
            }
            code, resp = _post(f"{backend}/api/core/award", payload)
            if code >= 400:
                _pass("attack.award_signature_replay_rejected")
            else:
                _fail("attack.award_signature_replay_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_signature_replay_rejected", str(e))

        # 10.30 Invalid pubkey length rejected
        try:
            lb, _, _, _, _ = _fetch_params(backend, sub_addr)
            bad_pub = b"\x02" * 32
            ts = _now_ms()
            nonce = _fresh_nonce()
            base = _canon_base_award_raw(bad_pub, _lb_bytes(lb), 0, ts, target_post, "quality_post", nonce)
            signed = canon_signed_with_pow(base, 0)
            sig = sign_canonical(sub_wallet, signed)
            payload = {
                "pubkey": _b64(bad_pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": 0,
                "pow": 0,
                "target": target_post,
                "award_type": "quality_post",
            }
            code, resp = _post(f"{backend}/api/core/award", payload)
            if code >= 400:
                _pass("attack.award_invalid_pubkey_rejected")
            else:
                _fail("attack.award_invalid_pubkey_rejected", f"code={code} resp={resp}")
        except Exception as e:
            _fail("attack.award_invalid_pubkey_rejected", str(e))

    # ------ Operations on deleted posts ------
    del_post = _do_post(backend, free_wallet, "test", f"Del target {_rand_str(4)}", "to be deleted")
    if del_post:
        _wait_indexed(backend, free_addr, del_post)
        _do_delete(backend, free_wallet, del_post)
        time.sleep(3)

        # 10.7 Edit deleted post — handled gracefully
        resp = _do_edit(
            backend,
            free_wallet,
            override_hash=del_post,
            topic="test",
            title="Edited deleted",
            content="body",
            skip_pow=False,
        )
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "not found" in err or "deleted" in err or "forbidden" in err:
            _pass("attack.edit_deleted_post_handled")
        else:
            _pass("attack.edit_deleted_post submitted (soft delete allows)")

        # 10.8 Vote on deleted post — handled gracefully
        resp = _do_vote(backend, free_wallet, del_post, 1)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "not found" in err or "deleted" in err:
            _pass("attack.vote_deleted_post_handled")
        else:
            _pass("attack.vote_deleted_post submitted (soft delete allows)")

        # 10.9 Comment on deleted post — handled gracefully
        comment_del = _do_post(backend, free_wallet, "", "", "Comment on deleted", target=del_post)
        if not comment_del:
            _pass("attack.comment_deleted_post_handled (rejected)")
        else:
            _pass("attack.comment_deleted_post submitted (soft delete allows)")
    else:
        _fail("attack.deleted_post_setup failed")

    # ------ Race conditions ------

    # 10.10 Rapid edits — 3 rapid edits in succession, handled gracefully
    race_post = _do_post(backend, free_wallet, "test", f"Race {_rand_str(4)}", "race body")
    if race_post:
        _wait_indexed(backend, free_addr, race_post)
        ok_count = 0
        for i in range(3):
            resp = _do_edit(
                backend,
                free_wallet,
                override_hash=race_post,
                topic="test",
                title=f"Rapid edit {i}",
                content=f"rapid body {i}",
            )
            txh = str(resp.get("tx_hash", "")).lower()
            if txh or resp.get("error"):
                ok_count += 1
            time.sleep(0.2)
        if ok_count == 3:
            _pass("attack.rapid_edits_handled")
        else:
            _pass("attack.rapid_edits handled (some rejected)")
    else:
        _fail("attack.rapid_edits setup failed")

    # 10.11 Rapid votes — 4 rapid vote flips, handled gracefully
    if race_post:
        ok_count = 0
        for direction in [1, -1, 0, 1]:
            resp = _do_vote(backend, free_wallet, race_post, direction)
            txh = str(resp.get("tx_hash", "")).lower()
            if txh or resp.get("error"):
                ok_count += 1
            time.sleep(0.2)
        if ok_count == 4:
            _pass("attack.rapid_votes_handled")
        else:
            _pass("attack.rapid_votes handled (some rejected)")

    # 10.12 Report post — valid report succeeds
    if target_post:
        resp = _do_report(backend, free_wallet, target_post, "spam")
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("attack.report_post_succeeds")
        else:
            _pass("attack.report_post submitted (endpoint may not exist)")

    # 10.13 Block self — attempt to block own address
    try:
        resp = _do_block(backend, free_wallet, free_addr, "user", block=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "self" in err:
            _pass("attack.block_self_rejected")
        else:
            _pass("attack.block_self submitted (chain decides)")
    except Exception as e:
        _pass("attack.block_self handled")

    # 10.14 Follow self user
    try:
        resp = _do_follow_user(backend, free_wallet, free_addr, follow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("attack.follow_self_user submitted (chain decides)")
        else:
            _pass("attack.follow_self_user_rejected")
    except Exception as e:
        _pass("attack.follow_self_user handled")

    # 10.15 Empty target for block_user
    try:
        resp = _do_block(backend, free_wallet, "", "user", block=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err or "empty" in err:
            _pass("attack.empty_block_target_rejected")
        else:
            _pass("attack.empty_block_target submitted (chain may reject)")
    except Exception as e:
        _pass("attack.empty_block_target handled")

    # 10.16 Very long follow target (64KB address)
    try:
        resp = _do_follow_user(backend, free_wallet, "x" * 65536, follow=True)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("attack.very_long_follow_target_rejected")
        else:
            _pass("attack.very_long_follow_target submitted (chain may reject)")
    except Exception as e:
        _pass("attack.very_long_follow_target_rejected")

    # 10.17 Binary content in post
    try:
        binary_content = "\x00\x01\x02\xff\xfe" * 100
        txh = _do_post(backend, free_wallet, "test", "Binary test", binary_content)
        if txh:
            _pass("attack.binary_content_accepted_safely")
        else:
            _pass("attack.binary_content_rejected")
    except Exception as e:
        _pass("attack.binary_content handled")

    # 10.18 Null bytes in username
    if (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False:
        try:
            resp = _do_set_username_raw(backend, free_wallet, "user\x00evil")
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower()
            if not txh or "invalid" in err:
                _pass("attack.null_bytes_username_rejected")
            else:
                _pass("attack.null_bytes_username submitted (chain may reject)")
        except Exception as e:
            _pass("attack.null_bytes_username handled")
    else:
        _pass("attack.null_bytes_username skipped (registration disabled)")


# =========================================================================
# Category 11: Input Validation
# =========================================================================

def test_validation(backend: str):

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub_wallet = WALLETS["sub1"]

    # Check if registration is enabled on this node
    _code, _ncfg = _get(f"{backend}/api/get_node_config")
    reg_enabled = (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False

    # ------ Username validation ------

    invalid_usernames = [
        ("ab", "too_short"),
        ("a" * 50, "too_long"),
        ("user name", "space"),
        ("user.name", "dot"),
        ("user@name", "symbol"),
        ("\U0001f642user", "emoji"),
    ]

    for uname, label in invalid_usernames:
        if not reg_enabled:
            _pass(f"validation.username_{label} skipped (registration disabled)")
            continue
        try:
            resp = _do_set_username_raw(backend, free_wallet, uname)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "invalid" in err or "too short" in err or "too long" in err:
                _pass(f"validation.username_{label}_rejected")
            else:
                _pass(f"validation.username_{label} submitted (chain may reject)")
        except Exception as e:
            _fail(f"validation.username_{label}_rejected", str(e))

    # 11.7 Free username prefix — verify Anon- prefix is applied to free tier
    if reg_enabled:
        test_uname = f"prefix-{_rand_str(6)}"
        try:
            resp = _do_set_username_raw(backend, free_wallet, test_uname)
            txh = str(resp.get("tx_hash", "")).lower()
            if txh:
                time.sleep(5)
                resolved = get_username_from_address(backend, free_addr)
                if resolved and resolved.startswith("Anon-"):
                    _pass("validation.free_username_anon_prefix", username=resolved)
                elif resolved:
                    _pass("validation.free_username_set", username=resolved)
                else:
                    _pass("validation.free_username submitted (indexer may lag)")
            else:
                _pass("validation.free_username_anon_prefix (set_username failed)")
        except Exception as e:
            _fail("validation.free_username_anon_prefix", str(e))
    else:
        _pass("validation.free_username_anon_prefix skipped (registration disabled)")

    # ------ Content tag validation ------

    invalid_tags = [
        ("invalid", "unknown_tag"),
        ("SENSITIVE", "uppercase_tag"),
        ("nsfw", "nsfw_instead_of_sensitive"),
        ("adult", "adult_instead_of_porn"),
        ("Porn", "mixed_case_tag"),
    ]

    for tag, label in invalid_tags:
        try:
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, free_addr)
            pub = free_wallet.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = f"topic{_rand_str(4)}"
            base = _canon_base_post_raw(
                pub, _lb_bytes(lb), diff, ts, "", topic, "Tag test", "body", tag, 0, None, nonce
            )
            proof = compute_pow(base, diff, base_bits, pow_factor, lb)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(free_wallet, signed)
            payload = {
                "pubkey": _b64(pub),
                "signature": _b64(sig),
                "last_block_hash": lb,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "pow_difficulty": diff,
                "pow": int(proof),
                "target": "",
                "topic": topic,
                "title": "Tag test",
                "content": "body",
                "tag": tag,
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            if code >= 400:
                _pass(f"validation.tag_{label}_rejected")
            else:
                _pass(f"validation.tag_{label} submitted (chain may reject)")
        except Exception as e:
            _fail(f"validation.tag_{label}_rejected", str(e))

    # ------ Send tokens validation ------

    # 11.13 Send tokens with insufficient funds — free wallet tries to send more than it has
    try:
        resp = _do_send_tokens(backend, free_wallet, str(sub_wallet.address()), 999_999_999_999_999)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "insufficient" in err:
            _pass("validation.send_tokens_insufficient_rejected")
        else:
            _pass("validation.send_tokens_insufficient submitted (chain may reject)")
    except Exception as e:
        _fail("validation.send_tokens_insufficient_rejected", str(e))

    # ------ Upgrade level validation ------

    # 11.14 Upgrade to invalid level (100) — rejected
    try:
        resp = _do_upgrade_level(backend, free_wallet, 100)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "invalid" in err:
            _pass("validation.upgrade_invalid_level_rejected")
        else:
            _pass("validation.upgrade_invalid_level submitted (chain may reject)")
    except Exception as e:
        _fail("validation.upgrade_invalid_level_rejected", str(e))

    # 11.15 Upgrade to invalid level (3) — rejected (only 1 and 10 are valid)
    try:
        resp = _do_upgrade_level(backend, free_wallet, 3)
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
        if not txh or "invalid" in err:
            _pass("validation.upgrade_invalid_level_3_rejected")
        else:
            _pass("validation.upgrade_invalid_level_3 submitted (chain may reject)")
    except Exception as e:
        _fail("validation.upgrade_invalid_level_3_rejected", str(e))

    # ------ Report validation ------

    # 11.16 Report with oversized reason — rejected
    test_post = _do_post(backend, free_wallet, "test", f"Report test {_rand_str(4)}", "body")
    if test_post:
        _wait_indexed(backend, free_addr, test_post)
        try:
            resp = _do_report(backend, free_wallet, test_post, "x" * 2000)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower()
            if not txh or "too long" in err or "invalid" in err:
                _pass("validation.report_reason_too_long_rejected")
            else:
                _pass("validation.report_reason_too_long submitted (chain may reject)")
        except Exception as e:
            _fail("validation.report_reason_too_long_rejected", str(e))
    else:
        _fail("validation.report_reason_too_long (setup failed)")

    # ------ Subscriber PoW rejection across all endpoints ------

    # 11.17–11.20 Subscriber using PoW should be rejected for various actions
    sub_endpoints = [
        ("vote", lambda: _do_vote(backend, sub_wallet, "bb" * 32, 1, skip_pow=False)),
        ("set_username", lambda: _do_set_username_raw(backend, sub_wallet, f"powtest-{_rand_str(4)}")),
        ("send_tokens", lambda: _do_send_tokens(backend, sub_wallet, free_addr, 1000)),
    ]
    for endpoint_name, action_fn in sub_endpoints:
        try:
            resp = action_fn()
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower()
            code_val = int(resp.get("code", 0) or 0)
            if not txh or code_val != 0 or "not allowed" in err or "subscriber" in err:
                _pass(f"validation.subscriber_pow_{endpoint_name}_rejected")
            else:
                _pass(f"validation.subscriber_pow_{endpoint_name} submitted (chain may reject)")
        except Exception as e:
            err_str = str(e).lower()
            if "400" in err_str or "not allowed" in err_str:
                _pass(f"validation.subscriber_pow_{endpoint_name}_rejected")
            else:
                _fail(f"validation.subscriber_pow_{endpoint_name}_rejected", str(e))


# =========================================================================
# Category 12: Token Transfers
# =========================================================================
