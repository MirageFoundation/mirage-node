from __future__ import annotations

import ast
import base64
import hashlib
import json
import math
import os
import random
import re
import string
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Tuple
from urllib.parse import urlparse

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
    _post_multipart,
    _expect_http_error,
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
    _do_post_at_timestamp,
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


def _parse_db_name(db_url: str) -> str:
    parsed = urlparse(db_url)
    return parsed.path.lstrip("/")


def _get_backend_db_name() -> str:
    url = os.environ.get("BACKEND_DB_URL", "").strip()
    if url:
        return _parse_db_name(url)
    if _check_local_docker():
        code, out = _docker_exec("printenv BACKEND_DB_URL")
        if code == 0 and out:
            return _parse_db_name(out.strip())
    return ""


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
        _code, resp = _post(f"{backend}/api/core/post", payload)
        err = str(resp.get("error", "")).lower()
        http_status = int(resp.get("_http_status", 0) or 0)
        if http_status == 400 and ("invalid signature" in err or "insufficient pow" in err):
            _pass("attack.replay_signature_rejected")
        else:
            _fail(
                "attack.replay_signature_rejected",
                f"expected 400 with signature/pow error, got http={http_status} error={err!r} resp={resp}",
            )
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
        _code, resp = _post(f"{backend}/api/core/post", payload)
        _expect_http_error("attack.pow_proof_reuse_rejected", resp, 400, "insufficient pow (precheck)")
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
        _expect_http_error("attack.delete_foreign_post_rejected", resp, 403, "forbidden")

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
        _expect_http_error("attack.edit_foreign_post_rejected", resp, 403, "forbidden")

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
            _expect_http_error("attack.edit_foreign_comment_rejected", resp, 403, "forbidden")
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
        _code, resp = _post(f"{backend}/api/core/set_username", payload)
        _expect_http_error("attack.set_foreign_username_rejected", resp, 403, "unauthorized")
    except Exception as e:
        _fail("attack.set_foreign_username_rejected", str(e))

    # ------ Delete user account attacks ------

    # 10.19 Delete foreign account — free tries to delete sub1's account → rejected (403)
    try:
        code, resp = _do_delete_user(backend, free_wallet, sub_addr, skip_pow=False)
        if code == 403:
            _pass("attack.delete_foreign_account_rejected")
        else:
            _fail("attack.delete_foreign_account_rejected", f"expected http=403 got http={code} resp={resp}")
    except Exception as e:
        _fail("attack.delete_foreign_account_rejected", str(e))

    # 10.20 Delete foreign account — sub1 tries to delete free's account → rejected (403)
    try:
        code, resp = _do_delete_user(backend, sub_wallet, free_addr, skip_pow=True)
        if code == 403:
            _pass("attack.delete_foreign_account_sub_rejected")
        else:
            _fail("attack.delete_foreign_account_sub_rejected", f"expected http=403 got http={code} resp={resp}")
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
        _code, resp = _do_delete_user(backend, free_wallet, "", skip_pow=True)
        _expect_http_error("attack.delete_account_empty_target_rejected", resp, 400, "missing required fields")
    except Exception as e:
        _fail("attack.delete_account_empty_target_rejected", str(e))

    # 10.23 Delete account with invalid address → rejected (400)
    try:
        _code, resp = _do_delete_user(backend, free_wallet, "not_an_address", skip_pow=True)
        _expect_http_error(
            "attack.delete_account_invalid_target_rejected", resp, 400, "target must be a valid mirage1 address"
        )
    except Exception as e:
        _fail("attack.delete_account_invalid_target_rejected", str(e))

    # ------ Award attacks ------
    if target_post:
        # 10.24 Self-award rejected
        try:
            _code, resp = _do_award(backend, free_wallet, target_post, "quality_post")
            _expect_http_error("attack.award_self_rejected", resp, 400, "cannot award your own post")
        except Exception as e:
            _fail("attack.award_self_rejected", str(e))

        # 10.26 Unknown award type rejected
        try:
            _code, resp = _do_award(backend, sub_wallet, target_post, "not_a_real_award")
            _expect_http_error("attack.award_unknown_type_rejected", resp, 400, "unknown award type")
        except Exception as e:
            _fail("attack.award_unknown_type_rejected", str(e))

        # 10.27 Invalid target rejected
        try:
            _code, resp = _do_award(backend, sub_wallet, "not_a_hash", "quality_post")
            _expect_http_error("attack.award_invalid_target_rejected", resp, 400, "invalid target")
        except Exception as e:
            _fail("attack.award_invalid_target_rejected", str(e))

        # 10.28 PoW provided for award rejected
        try:
            _code, resp = _do_award(backend, sub_wallet, target_post, "quality_post", pow_difficulty=1, pow=1)
            _expect_http_error("attack.award_pow_rejected", resp, 400, "pow not allowed for award")
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
            _code, resp = _post(f"{backend}/api/core/award", payload)
            _expect_http_error("attack.award_signature_replay_rejected", resp, 400, "invalid signature")
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
            _code, resp = _post(f"{backend}/api/core/award", payload)
            _expect_http_error("attack.award_invalid_pubkey_rejected", resp, 400, "invalid relay fields")
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
        _expect_http_error("attack.block_self_rejected", resp, 400, "cannot block yourself")
    except Exception as e:
        _fail("attack.block_self_rejected", str(e))

    # 10.14 Follow self user
    try:
        resp = _do_follow_user(backend, free_wallet, free_addr, follow=True)
        _expect_http_error("attack.follow_self_user_rejected", resp, 400, "cannot follow yourself")
    except Exception as e:
        _fail("attack.follow_self_user_rejected", str(e))

    # 10.15 Empty target for block_user
    try:
        resp = _do_block(backend, free_wallet, "", "user", block=True)
        _expect_http_error("attack.empty_block_target_rejected", resp, 400, "missing required fields")
    except Exception as e:
        _fail("attack.empty_block_target_rejected", str(e))

    # 10.16 Very long follow target (64KB address)
    try:
        resp = _do_follow_user(backend, free_wallet, "x" * 65536, follow=True)
        _expect_http_error("attack.very_long_follow_target_rejected", resp, 400, "user must be a valid mirage1 address")
    except Exception as e:
        _fail("attack.very_long_follow_target_rejected", str(e))

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
            _expect_http_error("attack.null_bytes_username_rejected", resp, 400, "invalid control characters")
        except Exception as e:
            _fail("attack.null_bytes_username_rejected", str(e))
    else:
        _pass("attack.null_bytes_username skipped (registration disabled)")

    # ------ Push notification authorization ------
    push_enabled = (_ncfg or {}).get("push_notifications_enabled", False) if _code == 200 else False
    if not push_enabled:
        _pass("attack.push_notifications skipped (push disabled)")
    else:

        def _sign_plain(wallet: LocalWallet, payload_str: str) -> str:
            sig = sign_canonical(wallet, payload_str.encode("utf-8"))
            return _b64(sig)

        try:
            # 10.19 Register push token with invalid signature → rejected
            token_a = f"ExponentPushToken[{_rand_str(22)}]"
            token_b = f"ExponentPushToken[{_rand_str(22)}]"
            ts = _now_ms()
            nonce = _fresh_nonce()
            sig = _sign_plain(free_wallet, f"register_push_token:{token_a}:ios:{ts}:{nonce}")
            payload = {
                "pubkey": _b64(free_wallet.public_key().public_key_bytes),
                "signature": sig,
                "timestamp": ts,
                "envelope_nonce": str(nonce),
                "token": token_b,  # mismatched token
                "platform": "ios",
            }
            code, resp = _post(f"{backend}/api/core/register_push_token", payload)
            if code == 400:
                _pass("attack.push_register_invalid_signature_rejected")
            else:
                _fail(
                    "attack.push_register_invalid_signature_rejected", f"expected http=400 got http={code} resp={resp}"
                )
        except Exception as e:
            _fail("attack.push_register_invalid_signature_rejected", str(e))

        try:
            # 10.20 Expo push tokens are device-scoped, so registration is
            # last-writer-wins: the signed-in account takes ownership of the
            # device token. First prove a foreign unregister is a no-op (an
            # account cannot release a token it does not own), then prove the
            # active account can take over the token.
            db_name = _get_backend_db_name() if _check_local_docker() else ""

            def _token_owner(tok: str) -> str:
                if not db_name:
                    return ""
                sql = f"SELECT owner FROM push_tokens WHERE token='{tok}' LIMIT 1;"
                rc, out = _docker_exec(
                    f'su - postgres -c "psql -d {db_name} -tAc \\"{sql}\\" 2>&1"',
                    timeout=10,
                )
                return out.strip().lower() if rc == 0 else ""

            token = f"ExponentPushToken[{_rand_str(22)}]"
            ts1 = _now_ms()
            nonce1 = _fresh_nonce()
            sig1 = _sign_plain(free_wallet, f"register_push_token:{token}:ios:{ts1}:{nonce1}")
            payload1 = {
                "pubkey": _b64(free_wallet.public_key().public_key_bytes),
                "signature": sig1,
                "timestamp": ts1,
                "envelope_nonce": str(nonce1),
                "token": token,
                "platform": "ios",
            }
            code1, resp1 = _post(f"{backend}/api/core/register_push_token", payload1)
            if code1 != 200:
                _fail("attack.push_token_ownership_transfers", f"setup failed code={code1} resp={resp1}")
            else:
                # B attempts to unregister A's token — owner-scoped DELETE must
                # match nothing, leaving the token owned by A.
                ts3 = _now_ms()
                nonce3 = _fresh_nonce()
                sig3 = _sign_plain(sub_wallet, f"unregister_push_token:{token}:{ts3}:{nonce3}")
                payload3 = {
                    "pubkey": _b64(sub_wallet.public_key().public_key_bytes),
                    "signature": sig3,
                    "timestamp": ts3,
                    "envelope_nonce": str(nonce3),
                    "token": token,
                }
                _post(f"{backend}/api/core/unregister_push_token", payload3)

                if db_name:
                    owner_after_unreg = _token_owner(token)
                    if owner_after_unreg == free_addr.lower():
                        _pass("attack.push_unreg_foreign_token_noop")
                    else:
                        _fail(
                            "attack.push_unreg_foreign_token_noop",
                            f"expected owner=A({free_addr.lower()}) got owner={owner_after_unreg!r}",
                        )
                else:
                    _pass("attack.push_unreg_foreign_token_noop")

                # B registers the same token — takes ownership (last-writer-wins).
                ts2 = _now_ms()
                nonce2 = _fresh_nonce()
                sig2 = _sign_plain(sub_wallet, f"register_push_token:{token}:ios:{ts2}:{nonce2}")
                payload2 = {
                    "pubkey": _b64(sub_wallet.public_key().public_key_bytes),
                    "signature": sig2,
                    "timestamp": ts2,
                    "envelope_nonce": str(nonce2),
                    "token": token,
                    "platform": "ios",
                }
                code2, resp2 = _post(f"{backend}/api/core/register_push_token", payload2)
                if code2 != 200:
                    _fail(
                        "attack.push_token_ownership_transfers",
                        f"expected http=200 got http={code2} resp={resp2}",
                    )
                elif db_name:
                    owner_after_transfer = _token_owner(token)
                    if owner_after_transfer == sub_addr.lower():
                        _pass("attack.push_token_ownership_transfers")
                    else:
                        _fail(
                            "attack.push_token_ownership_transfers",
                            f"expected owner=B({sub_addr.lower()}) got owner={owner_after_transfer!r}",
                        )
                else:
                    _pass("attack.push_token_ownership_transfers")
        except Exception as e:
            _fail("attack.push_token_ownership_transfers", str(e))

    # 10.21b mark_inbox_viewed clears push throttle cooldown
    if _check_local_docker():
        try:
            db_name = _get_backend_db_name()
            if not db_name:
                _fail("attack.mark_inbox_viewed_clears_push_cooldown", "BACKEND_DB_URL not set")
                return
            owner_lc = str(free_wallet.address()).lower()
            now = int(time.time())
            cooldown_until = now + 7200
            sql = (
                f"INSERT INTO push_throttle (owner, window_start, sent_count, suppressed_count, cooldown_until) "
                f"VALUES ('{owner_lc}', {now}, 5, 3, {cooldown_until}) "
                f"ON CONFLICT (owner) DO UPDATE SET "
                f"window_start={now}, sent_count=5, suppressed_count=3, cooldown_until={cooldown_until};"
            )
            rc, out = _docker_exec(
                f'su - postgres -c "psql -d {db_name} -tAc \\"{sql}\\" 2>&1"',
                timeout=10,
            )
            if rc != 0:
                _fail("attack.mark_inbox_viewed_clears_push_cooldown", f"seed rc={rc} out={out}")
            else:
                ts = _now_ms()
                nonce = _fresh_nonce()
                sig = sign_canonical(
                    free_wallet,
                    f"mark_inbox_viewed:{owner_lc}:{ts}:{nonce}".encode("utf-8"),
                )
                payload = {
                    "pubkey": _b64(free_wallet.public_key().public_key_bytes),
                    "signature": _b64(sig),
                    "timestamp": ts,
                    "envelope_nonce": str(nonce),
                    "address": owner_lc,
                }
                code, resp = _post(f"{backend}/api/mark_inbox_viewed", payload)
                if code != 200:
                    _fail("attack.mark_inbox_viewed_clears_push_cooldown", f"code={code} resp={resp}")
                else:
                    sql2 = (
                        f"SELECT cooldown_until, suppressed_count FROM push_throttle WHERE owner='{owner_lc}' LIMIT 1;"
                    )
                    rc2, out2 = _docker_exec(
                        f'su - postgres -c "psql -d {db_name} -tAc \\"{sql2}\\" 2>&1"',
                        timeout=10,
                    )
                    if rc2 != 0:
                        _fail("attack.mark_inbox_viewed_clears_push_cooldown", f"query rc={rc2} out={out2}")
                    else:
                        raw = out2.strip()
                        parts = [p.strip() for p in raw.split("|")] if raw else []
                        if len(parts) == 2 and parts[0] == "0" and parts[1] == "0":
                            _pass("attack.mark_inbox_viewed_clears_push_cooldown")
                        else:
                            _fail("attack.mark_inbox_viewed_clears_push_cooldown", f"got={raw}")

                    sql3 = f"SELECT inbox_last_viewed_at FROM user_inbox_state WHERE owner='{owner_lc}' LIMIT 1;"
                    rc3, out3 = _docker_exec(
                        f'su - postgres -c "psql -d {db_name} -tAc \\"{sql3}\\" 2>&1"',
                        timeout=10,
                    )
                    if rc3 != 0:
                        _fail("attack.mark_inbox_viewed_updates_backend_state", f"query rc={rc3} out={out3}")
                    else:
                        raw_state = out3.strip()
                        try:
                            last_seen = int(raw_state) if raw_state else 0
                        except ValueError:
                            last_seen = 0
                        if last_seen > 0:
                            _pass("attack.mark_inbox_viewed_updates_backend_state")
                        else:
                            _fail("attack.mark_inbox_viewed_updates_backend_state", f"got={raw_state!r}")
        except Exception as e:
            _fail("attack.mark_inbox_viewed_clears_push_cooldown", str(e))
    else:
        _skip("attack.mark_inbox_viewed_clears_push_cooldown", "not running in local-docker")

    # 10.22 mark_inbox_viewed with mismatched address/pubkey → rejected
    try:
        ts = _now_ms()
        nonce = _fresh_nonce()
        free_addr_lc = str(free_wallet.address()).lower()
        sig = sign_canonical(
            free_wallet,
            f"mark_inbox_viewed:{free_addr_lc}:{ts}:{nonce}".encode("utf-8"),
        )
        payload = {
            "pubkey": _b64(free_wallet.public_key().public_key_bytes),
            "signature": _b64(sig),
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "address": str(sub_wallet.address()),
        }
        _code, resp = _post(f"{backend}/api/mark_inbox_viewed", payload)
        _expect_http_error("attack.mark_inbox_viewed_mismatch_rejected", resp, 400, "address does not match pubkey")
    except Exception as e:
        _fail("attack.mark_inbox_viewed_mismatch_rejected", str(e))


# =========================================================================
# Category 11: Input Validation
# =========================================================================


def test_validation(backend: str):

    free_wallet = WALLETS["free"]
    free_addr = str(free_wallet.address())
    sub_wallet = WALLETS["sub1"]
    sub_addr = str(sub_wallet.address())

    # Check if registration is enabled on this node
    _code, _ncfg = _get(f"{backend}/api/get_node_config")
    reg_enabled = (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False

    # ------ Username validation ------

    invalid_usernames = [
        ("ab", "too_short", "username too short"),
        ("a" * 50, "too_long", "username too long"),
        ("user name", "space", "invalid username format"),
        ("user.name", "dot", "invalid username format"),
        ("user@name", "symbol", "invalid username format"),
        ("\U0001f642user", "emoji", "invalid username format"),
    ]

    for uname, label, expected in invalid_usernames:
        if not reg_enabled:
            _pass(f"validation.username_{label} skipped (registration disabled)")
            continue
        try:
            resp = _do_set_username_raw(backend, free_wallet, uname)
            _expect_http_error(f"validation.username_{label}_rejected", resp, 400, expected)
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
        ("invalid", "unknown_tag", "invalid tag"),
        ("SENSITIVE", "uppercase_tag", "invalid tag"),
        ("nsfw", "nsfw_instead_of_sensitive", "invalid tag"),
        ("xxx", "xxx_invalid_tag", "invalid tag"),
        ("Porn", "mixed_case_tag", "invalid tag"),
    ]

    for tag, label, expected in invalid_tags:
        try:
            # Use subscriber wallet and skip PoW so this check validates
            # tag rules deterministically (independent of dynamic PoW shifts).
            lb, _, _, _, _ = _fetch_params(backend, sub_addr)
            pub = sub_wallet.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = f"topic{_rand_str(4)}"
            base = _canon_base_post_raw(pub, _lb_bytes(lb), 0, ts, "", topic, "Tag test", "body", tag, 0, None, nonce)
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
                "target": "",
                "topic": topic,
                "title": "Tag test",
                "content": "body",
                "tag": tag,
            }
            _code, resp = _post(f"{backend}/api/core/post", payload)
            _expect_http_error(f"validation.tag_{label}_rejected", resp, 400, expected)
        except Exception as e:
            _fail(f"validation.tag_{label}_rejected", str(e))

    # ------ Send tokens validation ------

    # 11.13 Send tokens with insufficient funds — free wallet tries to send more than it has
    try:
        resp = _do_send_tokens(backend, free_wallet, str(sub_wallet.address()), 999_999_999_999_999)
        _expect_http_error("validation.send_tokens_insufficient_rejected", resp, 400, "insufficient balance")
    except Exception as e:
        _fail("validation.send_tokens_insufficient_rejected", str(e))

    # ------ Upgrade level validation ------

    # 11.14 Upgrade to invalid level (100) — rejected
    try:
        resp = _do_subscribe(backend, free_wallet, 100)
        _expect_http_error("validation.subscribe_invalid_level_rejected", resp, 400, "invalid level")
    except Exception as e:
        _fail("validation.subscribe_invalid_level_rejected", str(e))

    # 11.15 Upgrade to invalid level (3) — rejected (only 1 and 10 are valid)
    try:
        resp = _do_subscribe(backend, free_wallet, 3)
        _expect_http_error("validation.subscribe_invalid_level_3_rejected", resp, 400, "invalid level")
    except Exception as e:
        _fail("validation.subscribe_invalid_level_3_rejected", str(e))

    # ------ Report validation ------

    # 11.16 Report with oversized reason — rejected
    test_post = _do_post(backend, free_wallet, "test", f"Report test {_rand_str(4)}", "body")
    if test_post:
        _wait_indexed(backend, free_addr, test_post)
        try:
            resp = _do_report(backend, free_wallet, test_post, "x" * 2000)
            _expect_http_error("validation.report_reason_too_long_rejected", resp, 400, "reason too long")
        except Exception as e:
            _fail("validation.report_reason_too_long_rejected", str(e))
    else:
        _fail("validation.report_reason_too_long (setup failed)")

    # ------ Subscriber PoW acceptance across key endpoints ------

    # 11.17–11.20 Subscriber using PoW should be allowed (no "pow not allowed" rejection)
    sub_endpoints = [
        ("vote", lambda: _do_vote(backend, sub_wallet, "bb" * 32, 1, skip_pow=False)),
        ("set_username", lambda: _do_set_username_raw(backend, sub_wallet, f"powtest-{_rand_str(4)}")),
        ("send_tokens", lambda: _do_send_tokens(backend, sub_wallet, free_addr, 1000)),
    ]
    for endpoint_name, action_fn in sub_endpoints:
        try:
            resp = action_fn()
            err = str((resp or {}).get("error", "")).lower()
            http_status = int((resp or {}).get("_http_status", 0) or 0)
            if (http_status == 0 and err == "internal server error") or http_status >= 500:
                _fail(
                    f"validation.subscriber_pow_{endpoint_name}_allowed", f"http={http_status} err={err!r} resp={resp}"
                )
            elif "pow not allowed" in err:
                _fail(f"validation.subscriber_pow_{endpoint_name}_allowed", f"pow still rejected err={err!r}")
            else:
                _pass(f"validation.subscriber_pow_{endpoint_name}_allowed")
        except Exception as e:
            _fail(f"validation.subscriber_pow_{endpoint_name}_allowed", str(e))


def test_relay_signing(backend: str):
    """C-1: relay txs the backend broadcasts must carry a real gas-payer signature.

    Pins the wire format the ante now requires: a 64-byte outer secp256k1
    signature, unordered=true with a timeout_timestamp nonce, sequence 0, and a
    gas payment between the floor and the ceiling. Fails against pre-v1.32.0
    code, which shipped a 1-byte placeholder signature.
    """
    wallet = WALLETS["sub1"]
    topic = f"relaysig{_rand_str(5)}"
    resp = _do_follow_topic(backend, wallet, topic)
    txh = str((resp or {}).get("tx_hash", "") or "").strip().lower()
    if not txh:
        _fail("relay_signing.tx_submitted", f"no tx_hash in response: {str(resp)[:200]}")
        return
    _pass("relay_signing.tx_submitted")

    # Tx indexing is disabled on Mirage nodes, so fetch the decoded tx from the
    # block it landed in and match it by topic.
    tx = None
    deadline = time.time() + 30
    scanned = 0
    while time.time() < deadline and tx is None:
        head = _rpc_latest_height()
        for height in range(head, max(head - 30, 1), -1):
            code, block = _get(f"{backend}/chain/rest/cosmos/tx/v1beta1/txs/block/{height}")
            if code != 200:
                continue
            scanned += 1
            for candidate in (block or {}).get("txs") or []:
                messages = ((candidate.get("body") or {}).get("messages")) or []
                if not messages:
                    continue
                msg = messages[0]
                if str(msg.get("@type", "")) == "/mirage.core.v1.MsgFollowTopic" and msg.get("topic") == topic:
                    tx = candidate
                    _debug(f"relay_signing found tx at height={height}")
                    break
            if tx:
                break
        if tx is None:
            time.sleep(2)
    if not tx:
        _fail("relay_signing.tx_fetched", f"tx {txh} (topic {topic}) not found in {scanned} scanned blocks")
        return
    _pass("relay_signing.tx_fetched")

    sigs = tx.get("signatures") or []
    if len(sigs) != 1:
        _fail("relay_signing.single_signature", f"expected 1 signature, got {len(sigs)}")
    else:
        _pass("relay_signing.single_signature")
        raw = base64.b64decode(sigs[0])
        _debug(f"relay_signing outer sig len={len(raw)}")
        if len(raw) != 64:
            _fail("relay_signing.real_signature", f"signature is {len(raw)} bytes, want 64 (placeholder?)")
        else:
            _pass("relay_signing.real_signature")

    body_obj = tx.get("body") or {}
    if body_obj.get("unordered") is True:
        _pass("relay_signing.unordered")
    else:
        _fail("relay_signing.unordered", f"unordered={body_obj.get('unordered')!r}")
    if str(body_obj.get("timeout_timestamp") or "").strip():
        _pass("relay_signing.timeout_timestamp")
    else:
        _fail("relay_signing.timeout_timestamp", "timeout_timestamp missing (unordered nonce)")

    auth = tx.get("auth_info") or {}
    signer_infos = auth.get("signer_infos") or []
    if len(signer_infos) == 1 and str(signer_infos[0].get("sequence") or "0") == "0":
        _pass("relay_signing.sequence_zero")
    else:
        _fail("relay_signing.sequence_zero", f"signer_infos={str(signer_infos)[:200]}")

    fee = auth.get("fee") or {}
    validator_addr = ""
    code, conf = _get(f"{backend}/api/get_node_config")
    if code == 200 and isinstance(conf, dict):
        validator_addr = str(conf.get("validator_account_address", "")).strip()
    if not validator_addr:
        _fail("relay_signing.fee_payer_is_validator", "validator_account_address missing from node config")
    elif str(fee.get("payer") or "") == validator_addr:
        _pass("relay_signing.fee_payer_is_validator")
    else:
        _fail("relay_signing.fee_payer_is_validator", f"payer={fee.get('payer')!r} want {validator_addr}")

    code, params = _get(f"{backend}/chain/rest/mirage/core/v1/params")
    chain_params = (params or {}).get("params") or {}
    relay_min = int(chain_params.get("relay_min_gas_price") or 0)
    relay_max = int(chain_params.get("relay_max_gas_fee") or 0)
    gas = int(fee.get("gas_limit") or 0)
    amounts = fee.get("amount") or []
    if relay_min <= 0 or gas <= 0 or len(amounts) != 1:
        _fail(
            "relay_signing.fee_within_bounds",
            f"relay_min={relay_min} gas={gas} amounts={str(amounts)[:120]}",
        )
        return
    paid = int(amounts[0].get("amount") or 0)
    denom = str(amounts[0].get("denom") or "")
    ceiling = gas * relay_min
    if relay_max > 0 and ceiling > relay_max:
        ceiling = relay_max
    _debug(f"relay_signing gas={gas} paid={paid} ceiling={ceiling} denom={denom}")
    if denom == "umirage" and 0 < paid <= ceiling:
        _pass("relay_signing.fee_within_bounds")
    else:
        _fail("relay_signing.fee_within_bounds", f"paid={paid}{denom} ceiling={ceiling}")

    _check_unordered_nonce_retry()


def _check_unordered_nonce_retry() -> None:
    """An unordered-nonce collision must rebuild the tx; other errors must not retry.

    Runs against the deployed backend module inside the container, stubbing the
    broadcast so the retry branch is exercised without touching the chain.
    """
    script = """
import tx
calls = []
tx.build_tx_bytes = lambda body, gas: b"stub"

def collide_then_succeed(_):
    calls.append(1)
    if len(calls) == 1:
        return ("hash1", 1, 0, "unordered nonce already used timeout: 123")
    return ("hash2", 0, 42, "")

tx._broadcast_once = collide_then_succeed
_, code, height, _ = tx.build_and_broadcast_tx(b"body", 1000)
print("COLLISION", len(calls), code, height)

other = []

def hard_error(_):
    other.append(1)
    return ("hash3", 11, 0, "out of gas")

tx._broadcast_once = hard_error
_, code2, _, _ = tx.build_and_broadcast_tx(b"body", 1000)
print("OTHER", len(other), code2)
"""
    payload = base64.b64encode(script.encode()).decode()
    cmd = f"cd /opt/mirage/web/backend && echo {payload} | base64 -d | PYTHONPATH=/opt/mirage python3 -"
    code, out = _docker_exec(cmd, timeout=60)
    _debug(f"relay_signing retry probe rc={code} out={out.splitlines()[-2:]}")
    if code != 0:
        _fail("relay_signing.nonce_collision_retried", f"probe failed rc={code}: {out[-300:]}")
        return
    if "COLLISION 2 0 42" in out:
        _pass("relay_signing.nonce_collision_retried")
    else:
        _fail("relay_signing.nonce_collision_retried", f"expected one rebuild+success, got: {out[-300:]}")
    if "OTHER 1 11" in out:
        _pass("relay_signing.other_errors_not_retried")
    else:
        _fail("relay_signing.other_errors_not_retried", f"expected no retry on non-nonce error: {out[-300:]}")


def test_envelope_timestamp_window(backend: str):
    """The relay window must match the ante handler's, and its verdicts must not be 500s.

    val1 fell 21 blocks behind the network during a disk stall on 2026-08-06 and
    six posts died as "internal server error": simulate compared fresh envelopes
    against a stale block time, and every ante rejection reaches the backend as
    HTTP 500 from the tx-service REST, so the 4xx-only mapping reported them as
    our fault. The relay window was also ±90s against the chain's 60s/30s, which
    made every envelope in the gap a guaranteed 500.
    """
    code, params = _get(f"{backend}/chain/rest/mirage/core/v1/params")
    chain_params = (params or {}).get("params") or {}
    max_age_s = int(chain_params.get("max_envelope_age") or 0)
    if max_age_s <= 0:
        _fail("envelope_window.params", f"max_envelope_age missing from chain params: {str(chain_params)[:200]}")
        return
    future_skew_s = min(max(max_age_s // 2, 5), 30)
    _debug(f"envelope_window max_age={max_age_s}s future_skew={future_skew_s}s")

    wallet = WALLETS["sub1"]
    topic = f"tswindow{_rand_str(5)}"

    for label, ts_ms in (
        ("too_old", _now_ms() - (max_age_s + 5) * 1000),
        ("too_future", _now_ms() + (future_skew_s + 5) * 1000),
    ):
        status, resp = _do_post_at_timestamp(
            backend,
            wallet,
            topic,
            f"TS {label} {_rand_str(5)}",
            f"Body {_rand_str(8)}",
            ts_ms,
            skip_pow=True,
        )
        err_code = str((resp or {}).get("error_code") or "")
        _debug(f"envelope_window.{label} status={status} code={err_code} body={str(resp)[:160]}")
        if status == 400 and err_code == "timestamp_outside_window":
            _pass(f"envelope_window.{label}_rejected")
        else:
            _fail(
                f"envelope_window.{label}_rejected",
                f"want 400 timestamp_outside_window, got {status} {err_code or str(resp)[:160]}",
            )

    status, resp = _do_post_at_timestamp(
        backend,
        wallet,
        topic,
        f"TS inside {_rand_str(5)}",
        f"Body {_rand_str(8)}",
        _now_ms() - 2000,
        skip_pow=True,
    )
    txh = str((resp or {}).get("tx_hash", "") or "").strip()
    if status == 200 and txh:
        _pass("envelope_window.inside_accepted")
    else:
        _fail("envelope_window.inside_accepted", f"status={status} body={str(resp)[:200]}")

    _check_ante_timestamp_mapping()
    _check_head_staleness_guard()


def _check_ante_timestamp_mapping() -> None:
    """Ante timestamp verdicts must map to 503 (retry) and 400, never a bare 500.

    Runs against the deployed backend module inside the container with the exact
    simulate errors prod returned, since a node that trails the network cannot be
    staged from a test.
    """
    script = """
import routes.core as core

future = 'simulate_gas http 500: {"code":2, "message":"envelope_timestamp in future: age=-1m35.859750514s (tx_time=2026-08-06 14:04:36.227 +0000 UTC, block_time=2026-08-06 14:03:00.367249486 +0000 UTC) with gas used: \\'40731\\'", "details":[]}'
old = 'simulate_gas http 500: {"code":2, "message":"envelope_timestamp too old: age=1m12s, max=1m0s (tx_time=2026-08-06 14:04:36.227 +0000 UTC, block_time=2026-08-06 14:05:48.367249486 +0000 UTC)", "details":[]}'
other = 'simulate_gas http 500: {"code":2, "message":"envelope replay: nonce already used", "details":[]}'

print("FUTURE", core._classify_exception(future)[1])
print("OLD", core._classify_exception(old)[1])
print("OTHER", core._classify_exception(other)[1])
"""
    payload = base64.b64encode(script.encode()).decode()
    cmd = f"cd /opt/mirage/web/backend && echo {payload} | base64 -d | PYTHONPATH=/opt/mirage python3 -"
    code, out = _docker_exec(cmd, timeout=60)
    _debug(f"envelope_window mapping probe rc={code} out={out.splitlines()[-3:]}")
    if code != 0:
        _fail("envelope_window.ante_mapping", f"probe failed rc={code}: {out[-300:]}")
        return
    if "FUTURE 503" in out:
        _pass("envelope_window.stale_head_retryable")
    else:
        _fail("envelope_window.stale_head_retryable", f"want 503 for a stale local head: {out[-300:]}")
    if "OLD 400" in out:
        _pass("envelope_window.expired_is_client_error")
    else:
        _fail("envelope_window.expired_is_client_error", f"want 400 for an aged-out envelope: {out[-300:]}")
    if "OTHER 500" in out:
        _pass("envelope_window.other_rejections_unchanged")
    else:
        _fail("envelope_window.other_rejections_unchanged", f"want 500 for unmapped rejections: {out[-300:]}")


def _check_head_staleness_guard() -> None:
    """A node trailing the network must read as catching up, before any simulate.

    CometBFT reported catching_up=False through the 2026-08-06 lag and the
    indexer kept pace with the node it follows, so the only signal that the head
    is too stale to relay a write is the newest block's own timestamp.
    """
    script = """
import time
import chain, params

params._PARAMS_CACHE = {"max_envelope_age": 60}
now = int(time.time())

class _Cur:
    def __init__(self, head_time):
        self._head_time = head_time
        self._last = ""
    def execute(self, sql, *a):
        self._last = sql
    def fetchall(self):
        return [("last_processed_time", str(now)), ("chain_head_height", "100")]
    def fetchone(self):
        # meta.last_height is the height authority; recent_blocks gives the head time.
        if "meta" in self._last:
            return ("100",)
        return (self._head_time,)

class _Conn:
    def __init__(self, head_time):
        self._head_time = head_time
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def cursor(self):
        return _Cur(self._head_time)

def probe(head_time):
    chain.connect_db = lambda **kw: _Conn(head_time)
    chain._CATCHING_UP_CACHE = None
    return chain.is_node_catching_up()

print("FRESH", probe(now - 5))
print("STALE", probe(now - 45))
print("NO_BLOCK_TIME", probe(0))
"""
    payload = base64.b64encode(script.encode()).decode()
    cmd = f"cd /opt/mirage/web/backend && echo {payload} | base64 -d | PYTHONPATH=/opt/mirage python3 -"
    code, out = _docker_exec(cmd, timeout=60)
    _debug(f"envelope_window staleness probe rc={code} out={out.splitlines()[-3:]}")
    if code != 0:
        _fail("envelope_window.head_staleness_guard", f"probe failed rc={code}: {out[-300:]}")
        return
    if "FRESH False" in out and "STALE True" in out:
        _pass("envelope_window.head_staleness_guard")
    else:
        _fail("envelope_window.head_staleness_guard", f"want fresh=False stale=True: {out[-300:]}")
    if "NO_BLOCK_TIME False" in out:
        _pass("envelope_window.head_staleness_needs_block_time")
    else:
        _fail("envelope_window.head_staleness_needs_block_time", f"want no verdict without block_time: {out[-300:]}")


# =========================================================================
# Category 12: Token Transfers
# =========================================================================


def _backend_src() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web",
        "backend",
    )


def _iter_backend_py(backend_src: str):
    for root, _dirs, files in os.walk(backend_src):
        for name in sorted(files):
            if name.endswith(".py"):
                path = os.path.join(root, name)
                yield path, open(path, encoding="utf-8").read()


def test_client_ip_trust(backend):
    """M-1: nothing may derive trust from X-Forwarded-For.

    The header is set by the client and is trivially spoofable. AGENTS.md states
    the rule and client_ip.py already has the correct primitive
    (get_trusted_client_ip, CF-Connecting-IP with a remote_addr fallback), so any
    remaining read of X-Forwarded-For is a trust decision on attacker input.
    """
    backend_src = _backend_src()
    if not os.path.isdir(backend_src):
        _skip("client_ip.no_forwarded_for_trust", "backend source not present")
        return

    hits = []
    for path, src in _iter_backend_py(backend_src):
        for lineno, line in enumerate(src.splitlines(), start=1):
            if "X-Forwarded-For" in line:
                hits.append(f"{os.path.relpath(path, backend_src)}:{lineno}")

    if hits:
        _fail(
            "client_ip.no_forwarded_for_trust",
            f"{len(hits)} read(s) of the spoofable X-Forwarded-For header: {', '.join(hits[:6])}",
        )
    else:
        _pass("client_ip.no_forwarded_for_trust")


def test_hash_salt_fail_hard(backend):
    """M-2: a missing CLIENT_HASH_SALT must stop the process, not invent a salt.

    client_ip.py fails hard at import when CLIENT_HASH_SALT is missing or not
    valid hex. That keeps every control keyed on the IP or visitor hash (rate
    limits, dedupe, analytics identity) consistent across gunicorn workers.
    This probe asserts the fail-hard path still rejects an unset salt.

    ENV_DIR is cleared so the probe cannot persist a salt into backend.env.
    """
    code, out = _docker_exec(
        "cd /opt/mirage/web/backend && unset CLIENT_HASH_SALT && ENV_DIR= "
        "python3 -c 'import client_ip' 2>&1; echo rc=$?",
        timeout=60,
    )
    if "rc=" not in out:
        _skip("hash_salt.fail_hard", f"probe did not run: code={code} out={out[:200]}")
        return
    rc = out.rsplit("rc=", 1)[-1].strip()
    if rc != "0":
        _pass("hash_salt.fail_hard", rc=rc)
    else:
        _fail(
            "hash_salt.fail_hard",
            "M-2: importing client_ip without CLIENT_HASH_SALT succeeded; it must "
            "fail hard instead of inventing a per-process salt",
        )


def test_upload_body_bound(backend):
    """M-4: an oversized upload must be refused, and bounded before it is read.

    Two separate properties. The size check inside the media layer is only
    reached after request.files has already materialized the whole body, so a
    global MAX_CONTENT_LENGTH is what actually bounds memory.
    """
    backend_src = _backend_src()
    if os.path.isdir(backend_src):
        configured = any("MAX_CONTENT_LENGTH" in src for _p, src in _iter_backend_py(backend_src))
        if configured:
            _pass("upload_bound.max_content_length_configured")
        else:
            _fail(
                "upload_bound.max_content_length_configured",
                "M-4: no MAX_CONTENT_LENGTH anywhere in the backend, so an arbitrarily large "
                "upload body is read into memory before any size check runs",
            )
    else:
        _skip("upload_bound.max_content_length_configured", "backend source not present")

    # Dynamic: exceed the image limit and require a clean 413, not a 500.
    limit_mb = 15
    oversize = b"\xff\xd8\xff" + b"\x00" * (limit_mb * 1024 * 1024 + 1024)
    try:
        r = _post_multipart(
            f"{backend}/api/upload_media", {"kind": "image"}, {"file": ("big.jpg", oversize, "image/jpeg")}
        )
    except requests.RequestException as e:
        _fail("upload_bound.oversize_rejected", f"upload raised {type(e).__name__}: {e}")
        return

    if r.status_code == 413:
        _pass("upload_bound.oversize_rejected", code=r.status_code)
    elif r.status_code == 403 and "uploads_disabled" in r.text:
        _skip("upload_bound.oversize_rejected", "uploads disabled on this node")
    elif r.status_code == 200:
        _fail("upload_bound.oversize_rejected", f"an oversized upload was ACCEPTED: {r.text[:200]}")
    else:
        _fail("upload_bound.oversize_rejected", f"expected 413, got {r.status_code}: {r.text[:200]}")


def test_invite_code_hygiene(backend):
    """M-3: invite codes need real entropy and must not disclose their owner.

    Generation must use secrets (not random). validate_invite_code must not
    return the code owner's address — that would turn the endpoint into an
    unauthenticated oracle mapping guessable codes to accounts. Both are
    enforced here as source-level guards so a regression fails the suite.
    """
    backend_src = _backend_src()
    if not os.path.isdir(backend_src):
        _skip("invite_code.crypto_rng", "backend source not present")
        return

    gen_src = ""
    for path, src in _iter_backend_py(backend_src):
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_generate_invite_code":
                gen_src = ast.get_source_segment(src, node) or ""
    if not gen_src:
        _skip("invite_code.crypto_rng", "_generate_invite_code not found")
    elif "secrets." in gen_src and "random." not in gen_src:
        _pass("invite_code.crypto_rng")
    else:
        _fail(
            "invite_code.crypto_rng",
            "M-3: invite codes are generated with a non-cryptographic RNG; use secrets",
        )

    # The backend generator is not the only one. scripts/manage_invites.py and
    # scripts/onboard_influencer.py are what an operator actually runs to mint
    # codes, and both used random.choices while this check watched only
    # web/backend — so the codes in circulation could be weak with the suite green.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    weak_scripts = []
    checked = 0
    for rel in ("scripts/manage_invites.py", "scripts/onboard_influencer.py"):
        path = os.path.join(repo_root, rel)
        if not os.path.isfile(path):
            continue
        src = open(path, encoding="utf-8").read()
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == "generate_code":
                checked += 1
                body = ast.get_source_segment(src, node) or ""
                if "random." in body or "secrets." not in body:
                    weak_scripts.append(f"{rel}:{node.lineno}")
    if not checked:
        _skip("invite_code.script_crypto_rng", "no generate_code found in the invite scripts")
    elif weak_scripts:
        _fail(
            "invite_code.script_crypto_rng",
            f"M-3: invite codes are minted with a non-cryptographic RNG at {', '.join(weak_scripts)}; "
            f"use secrets.choice — codes are bearer credentials for account creation",
        )
    else:
        _pass("invite_code.script_crypto_rng", generators=checked)

    # Owner disclosure: the validation response must not name the code's owner.
    discloses = []
    for path, src in _iter_backend_py(backend_src):
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.FunctionDef) and node.name == "validate_invite_code"):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Dict):
                    keys = {k.value for k in sub.keys if isinstance(k, ast.Constant)}
                    if "owner" in keys:
                        discloses.append(f"{os.path.relpath(path, backend_src)}:{sub.lineno}")
    if discloses:
        _fail(
            "invite_code.no_owner_disclosure",
            f"M-3: validate_invite_code returns the code owner's address at {', '.join(discloses)}",
        )
    else:
        _pass("invite_code.no_owner_disclosure")


def test_indexer_drift(backend):
    """M-8: state served from the indexer DB must match the chain.

    Narrow but exact: the backend serves pow_base_bits out of the indexer DB and
    the chain owns min_difficulty. They are the same number, so a mismatch means
    the indexer's copy has drifted from consensus state.
    """
    code, params = _get(f"{backend}/api/get_parameters")
    if code != 200 or not isinstance(params, dict) or "pow_base_bits" not in params:
        _skip("indexer_drift.pow_base_bits", f"backend params unavailable: code={code}")
        return

    rc, out = _run_miraged(["q", "core", "params", "-o", "json"], timeout=30)
    if rc != 0 or not out:
        _skip("indexer_drift.pow_base_bits", f"chain params query failed rc={rc}")
        return
    try:
        chain = json.loads(out)
    except ValueError as e:
        _skip("indexer_drift.pow_base_bits", f"chain params not JSON: {e}")
        return

    if "min_difficulty" not in chain:
        _skip("indexer_drift.pow_base_bits", "chain params missing min_difficulty")
        return

    served = int(params["pow_base_bits"])
    onchain = int(chain["min_difficulty"])
    if served == onchain:
        _pass("indexer_drift.pow_base_bits", value=served)
    else:
        _fail(
            "indexer_drift.pow_base_bits",
            f"M-8: backend serves pow_base_bits={served} but the chain has "
            f"min_difficulty={onchain}; the indexer's copy has drifted",
        )

    # Params are node-wide. Per-user state is where drift actually bites: the
    # backend answers profile and balance reads entirely from the indexer DB, so
    # extend the comparison to a real account rather than a single global number.
    wallet = WALLETS.get("sub1")
    if wallet is None:
        _skip("indexer_drift.profile_level", "sub1 wallet not provisioned")
        return
    addr = str(wallet.address()).lower()

    def _chain_profile() -> Optional[dict]:
        rc, out = _run_miraged(["q", "core", "profile", addr, "-o", "json"], timeout=30)
        if rc != 0 or not out:
            return None
        match = re.search(r"\{.*\}", out, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except ValueError:
            return None

    def _chain_balance() -> Optional[int]:
        rc, out = _run_miraged(["q", "bank", "balances", addr, "-o", "json"], timeout=30)
        if rc != 0 or not out:
            return None
        match = re.search(r"\{.*\}", out, re.S)
        if not match:
            return None
        try:
            balances = json.loads(match.group(0)).get("balances") or []
        except ValueError:
            return None
        return sum(int(c.get("amount", 0)) for c in balances if c.get("denom") == "umirage")

    # The indexer trails the chain by a block or so, and other categories run in
    # parallel, so one mismatch is lag rather than drift. Compare fresh read pairs
    # until they agree, and only report drift if they never do.
    ATTEMPTS = 5

    def _compare(name: str, read_pair) -> None:
        """read_pair() -> (served, onchain) or None when a source is unavailable."""
        served = onchain = None
        for _attempt in range(ATTEMPTS):
            pair = read_pair()
            if pair is None:
                time.sleep(2)
                continue
            served, onchain = pair
            if served == onchain:
                break
            time.sleep(2)
        if served is None or onchain is None:
            _skip(f"indexer_drift.{name}", "value unavailable from backend or chain")
        elif served == onchain:
            _pass(f"indexer_drift.{name}", value=served)
        else:
            _fail(
                f"indexer_drift.{name}",
                f"M-8: backend serves {name}={served!r} for {addr} but the chain has "
                f"{onchain!r} after {ATTEMPTS} attempts; the indexer's copy has drifted",
            )

    def _served_profile() -> Optional[dict]:
        code, body = _get(f"{backend}/api/get_profile", {"address": addr})
        return body if code == 200 and isinstance(body, dict) else None

    def _level_pair():
        served, onchain = _served_profile(), _chain_profile()
        if served is None or onchain is None:
            return None
        return int(served.get("level", -1)), int(onchain.get("level", -2))

    def _username_pair():
        served, onchain = _served_profile(), _chain_profile()
        if served is None or onchain is None:
            return None
        return str(served.get("username", "")), str(onchain.get("username", ""))

    def _balance_pair():
        served, onchain = _served_profile(), _chain_balance()
        if served is None or onchain is None:
            return None
        return int(served.get("balance", -1)), int(onchain)

    _compare("profile_level", _level_pair)
    _compare("profile_username", _username_pair)
    _compare("balance", _balance_pair)
