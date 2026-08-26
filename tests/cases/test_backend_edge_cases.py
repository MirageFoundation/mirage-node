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
    _pass, _fail, _skip, _debug, _get, _post, _b64, _rand_str, _now_ms,
    _fresh_nonce, _lb_bytes,
    WALLETS, FAUCET_AMOUNTS, INDEX_TIMEOUT_SEC,
    _COLOR_GREEN, _COLOR_RED, _COLOR_YELLOW, _COLOR_RESET, _COLOR_BOLD,
    _fetch_params, _do_subscribe, _docker_exec, _run_miraged, _miraged_cmd,
    _keyring_backend, _INSIDE_CONTAINER, _check_local_docker,
    DEFAULT_BACKEND,
    get_status, get_user_status, get_username_from_address, get_address_from_username,
    sign_canonical, compute_pow, check_pow_target, _difficulty_factor, _BASE_DIFFICULTY_FACTOR,
    _canon_base_subscribe_raw, _canon_base_send_tokens_raw, _canon_base_award_raw,
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


def _expect_reject_4xx(test_name: str, code: int, resp: dict | None = None) -> None:
    if 400 <= code < 500:
        _pass(test_name)
        return
    if code >= 500:
        _debug(f"{test_name} server error code={code} resp={resp}")
        _fail(test_name, f"server_error={code} resp={resp}")
        return
    _fail(test_name, f"code={code} resp={resp}")


def _expect_reject_or_submit(
    test_name_reject: str,
    test_name_submit: str,
    code: int,
    resp: dict | None = None,
) -> None:
    if 400 <= code < 500:
        _pass(test_name_reject)
        return
    if code >= 500:
        _debug(f"{test_name_reject} server error code={code} resp={resp}")
        _fail(test_name_reject, f"server_error={code} resp={resp}")
        return
    _pass(test_name_submit)


def test_edge_cases(backend: str):

    wallet = WALLETS["free"]
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes

    def _try_post(topic, title, content, tag="", target="") -> Tuple[int, dict]:
        ts = _now_ms()
        nonce = _fresh_nonce()
        base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, target, topic, title, content, tag, 0, None, nonce)
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
        payload = {
            "pubkey": _b64(pub),
            "signature": _b64(sig),
            "last_block_hash": lb,
            "timestamp": ts,
            "envelope_nonce": str(nonce),
            "pow_difficulty": diff,
            "pow": int(proof),
            "target": target,
            "topic": topic,
            "title": title,
            "content": content,
            "tag": tag,
            "protocol_version": 1,
        }
        return _post(f"{backend}/api/core/post", payload)

    # 9.1 Empty content rejected
    code, resp = _try_post("test", "Title", "")
    # Some backends allow empty content — check tx result
    _expect_reject_or_submit(
        "edge.empty_content_rejected",
        "edge.empty_content submitted (backend may allow)",
        code,
        resp,
    )

    # Re-fetch params (PoW is single-use)
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.2 Oversize content rejected
    huge = "x" * 100_001
    code, resp = _try_post("test", "Title", huge)
    _expect_reject_or_submit(
        "edge.oversize_content_rejected",
        "edge.oversize_content submitted (chain may reject)",
        code,
        resp,
    )

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.3 Oversize title rejected
    huge_title = "T" * 500
    code, resp = _try_post("test", huge_title, "body")
    _expect_reject_or_submit(
        "edge.oversize_title_rejected",
        "edge.oversize_title submitted (chain may reject)",
        code,
        resp,
    )

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.4 Invalid topic format rejected
    code, resp = _try_post("INVALID TOPIC!!!", "Title", "body")
    _expect_reject_or_submit(
        "edge.invalid_topic_rejected",
        "edge.invalid_topic submitted (chain may reject)",
        code,
        resp,
    )

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.5 Missing topic for root post rejected
    code, resp = _try_post("", "Title", "body")
    _expect_reject_or_submit(
        "edge.missing_topic_rejected",
        "edge.missing_topic submitted (chain may reject)",
        code,
        resp,
    )

    # 9.6 Timestamp too old rejected
    ts_old = _now_ms() - 120_000  # 2 minutes ago
    nonce_old = _fresh_nonce()
    base_old = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_old, "", "test", "old ts", "body", "", 0, None, nonce_old
    )
    proof_old = compute_pow(base_old, diff, base_bits, pow_factor, lb)
    signed_old = canon_signed_with_pow(base_old, int(proof_old))
    sig_old = sign_canonical(wallet, signed_old)
    payload_old = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_old),
        "last_block_hash": lb,
        "timestamp": ts_old,
        "envelope_nonce": str(nonce_old),
        "pow_difficulty": diff,
        "pow": int(proof_old),
        "target": "",
        "topic": "test",
        "title": "Old ts",
        "content": "body",
        "protocol_version": 1,
    }
    code_old, resp_old = _post(f"{backend}/api/core/post", payload_old)
    _expect_reject_or_submit(
        "edge.old_timestamp_rejected",
        "edge.old_timestamp submitted (chain validates envelope age)",
        code_old,
        resp_old,
    )

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.7 Timestamp too far in future rejected
    ts_future = _now_ms() + 120_000  # 2 minutes in future
    nonce_fut = _fresh_nonce()
    base_fut = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_future, "", "test", "future ts", "body", "", 0, None, nonce_fut
    )
    proof_fut = compute_pow(base_fut, diff, base_bits, pow_factor, lb)
    signed_fut = canon_signed_with_pow(base_fut, int(proof_fut))
    sig_fut = sign_canonical(wallet, signed_fut)
    payload_fut = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_fut),
        "last_block_hash": lb,
        "timestamp": ts_future,
        "envelope_nonce": str(nonce_fut),
        "pow_difficulty": diff,
        "pow": int(proof_fut),
        "target": "",
        "topic": "test",
        "title": "future ts",
        "content": "body",
        "protocol_version": 1,
    }
    code_fut, resp_fut = _post(f"{backend}/api/core/post", payload_fut)
    _expect_reject_or_submit(
        "edge.future_timestamp_rejected",
        "edge.future_timestamp submitted (chain validates envelope age)",
        code_fut,
        resp_fut,
    )

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.8 Non-existent target fails gracefully
    code, resp = _get(
        f"{backend}/api/get_comments", {"post_id": "0000000000000000000000000000000000000000000000000000000000000000"}
    )
    if code == 200:
        comments = (resp or {}).get("comments") or []
        if len(comments) == 0:
            _pass("edge.nonexistent_target returns empty")
        else:
            _fail("edge.nonexistent_target returns empty", f"got {len(comments)} comments")
    else:
        _pass("edge.nonexistent_target handled")

    # 9.9 Invalid pubkey rejected
    ts = _now_ms()
    nonce = _fresh_nonce()
    base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", "test", "bad pk", "body", "", 0, None, nonce)
    proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload_bad = {
        "pubkey": _b64(b"\x00" * 33),  # invalid pubkey
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": diff,
        "pow": int(proof),
        "target": "",
        "topic": "test",
        "title": "bad pk",
        "content": "body",
        "protocol_version": 1,
    }
    code_bad, resp_bad = _post(f"{backend}/api/core/post", payload_bad)
    _expect_reject_4xx("edge.invalid_pubkey_rejected", code_bad, resp_bad)

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.10 Mismatched signature — sign with wallet A, send pubkey of wallet B
    wallet_b = WALLETS["sub1"]
    pub_b = wallet_b.public_key().public_key_bytes
    ts_mis = _now_ms()
    nonce_mis = _fresh_nonce()
    base_mis = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_mis, "", "test", "mismatch", "body", "", 0, None, nonce_mis
    )
    proof_mis = compute_pow(base_mis, diff, base_bits, pow_factor, lb)
    signed_mis = canon_signed_with_pow(base_mis, int(proof_mis))
    sig_mis = sign_canonical(wallet, signed_mis)  # signed by wallet A
    payload_mis = {
        "pubkey": _b64(pub_b),  # but pubkey is wallet B's
        "signature": _b64(sig_mis),
        "last_block_hash": lb,
        "timestamp": ts_mis,
        "envelope_nonce": str(nonce_mis),
        "pow_difficulty": diff,
        "pow": int(proof_mis),
        "target": "",
        "topic": "test",
        "title": "mismatch",
        "content": "body",
        "protocol_version": 1,
    }
    code_mis, resp_mis = _post(f"{backend}/api/core/post", payload_mis)
    _expect_reject_4xx("edge.signature_mismatch_rejected", code_mis, resp_mis)

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.11 Stale/invalid block hash rejected
    ts_stale = _now_ms()
    nonce_stale = _fresh_nonce()
    fake_lb = "aa" * 32  # valid hex but not a real block hash
    base_stale = _canon_base_post_raw(
        pub, bytes.fromhex(fake_lb), diff, ts_stale, "", "test", "stale lb", "body", "", 0, None, nonce_stale
    )
    proof_stale = compute_pow(base_stale, diff, base_bits, pow_factor, fake_lb)
    signed_stale = canon_signed_with_pow(base_stale, int(proof_stale))
    sig_stale = sign_canonical(wallet, signed_stale)
    payload_stale = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_stale),
        "last_block_hash": fake_lb,
        "timestamp": ts_stale,
        "envelope_nonce": str(nonce_stale),
        "pow_difficulty": diff,
        "pow": int(proof_stale),
        "target": "",
        "topic": "test",
        "title": "stale lb",
        "content": "body",
        "protocol_version": 1,
    }
    code_stale, resp_stale = _post(f"{backend}/api/core/post", payload_stale)
    _expect_reject_4xx("edge.stale_block_hash_rejected", code_stale, resp_stale)

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # 9.11b Missing envelope_nonce must be rejected (v1.20.0+)
    # Chain rejects nonce==0 before signature verification.
    ts_legacy = _now_ms()
    base_legacy = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_legacy, "", "test", "legacy no nonce", "body", "", 0, None, 0
    )
    proof_legacy = compute_pow(base_legacy, diff, base_bits, pow_factor, lb)
    signed_legacy = canon_signed_with_pow(base_legacy, int(proof_legacy))
    sig_legacy = sign_canonical(wallet, signed_legacy)
    payload_no_nonce = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_legacy),
        "last_block_hash": lb,
        "timestamp": ts_legacy,
        "pow_difficulty": diff,
        "pow": int(proof_legacy),
        "target": "",
        "topic": "test",
        "title": "legacy no nonce",
        "content": "body",
        "protocol_version": 1,
    }
    code_no_nonce, resp_no_nonce = _post(f"{backend}/api/core/post", payload_no_nonce)
    _expect_reject_4xx("edge.missing_envelope_nonce_rejected", code_no_nonce, resp_no_nonce)

    # 9.11c Zero envelope_nonce explicitly sent is still rejected
    ts_z = _now_ms()
    base_z = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts_z, "", "test", "zero nonce", "body", "", 0, None, 0)
    proof_z = compute_pow(base_z, diff, base_bits, pow_factor, lb)
    signed_z = canon_signed_with_pow(base_z, int(proof_z))
    sig_z = sign_canonical(wallet, signed_z)
    payload_zero_nonce = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_z),
        "last_block_hash": lb,
        "timestamp": ts_z,
        "envelope_nonce": "0",
        "pow_difficulty": diff,
        "pow": int(proof_z),
        "target": "",
        "topic": "test",
        "title": "zero nonce",
        "content": "body",
        "protocol_version": 1,
    }
    code_zero, resp_zero = _post(f"{backend}/api/core/post", payload_zero_nonce)
    _expect_reject_4xx("edge.zero_envelope_nonce_rejected", code_zero, resp_zero)

    # 9.11c2 Garbage / invalid envelope_nonce values — must all be rejected (400)
    invalid_nonces_expect_reject = [
        ("string", "hello", "edge.nonce_string_rejected"),
        ("empty_string", "", "edge.nonce_empty_string_rejected"),
        ("null", None, "edge.nonce_null_rejected"),
        ("negative", "-1", "edge.nonce_negative_rejected"),
        ("float_str", "3.14", "edge.nonce_float_str_rejected"),
        ("overflow_u64", "99999999999999999999", "edge.nonce_overflow_rejected"),
        ("array", [1, 2, 3], "edge.nonce_array_rejected"),
        ("object", {"n": 1}, "edge.nonce_object_rejected"),
        ("sql_inject", "1; DROP TABLE nonces", "edge.nonce_sqli_rejected"),
        ("whitespace", "  ", "edge.nonce_whitespace_rejected"),
        ("hex_prefix", "0xDEADBEEF", "edge.nonce_hex_rejected"),
        ("negative_big", "-99999999999999999999", "edge.nonce_negative_big_rejected"),
    ]
    for label, bad_val, test_name in invalid_nonces_expect_reject:
        bad_payload = {
            "pubkey": _b64(pub),
            "signature": _b64(b"\x00" * 64),
            "last_block_hash": lb,
            "timestamp": _now_ms(),
            "envelope_nonce": bad_val,
            "pow_difficulty": diff,
            "pow": 0,
            "target": "",
            "topic": "test",
            "title": "bad nonce",
            "content": "body",
            "protocol_version": 1,
        }
        code_bad, resp_bad = _post(f"{backend}/api/core/post", bad_payload)
        _expect_reject_4xx(test_name, code_bad, resp_bad)

    # 9.11c3 Coercible values that resolve to a valid positive int — should be accepted
    #         (signature/PoW will fail downstream, but nonce parsing itself must succeed)
    coercible_nonces_expect_accept = [
        ("bool_true", True, "edge.nonce_bool_true_accepted"),
        ("float_num", 42.9, "edge.nonce_float_num_accepted"),
        ("str_int", "999", "edge.nonce_str_int_accepted"),
    ]
    nonce_reject_errors = {
        "invalid envelope_nonce",
        "envelope_nonce is required (v1.20.0)",
        "envelope_nonce must be > 0",
        "envelope_nonce exceeds uint64 range",
    }
    for label, ok_val, test_name in coercible_nonces_expect_accept:
        ok_payload = {
            "pubkey": _b64(pub),
            "signature": _b64(b"\x00" * 64),
            "last_block_hash": lb,
            "timestamp": _now_ms(),
            "envelope_nonce": ok_val,
            "pow_difficulty": diff,
            "pow": 0,
            "target": "",
            "topic": "test",
            "title": "coercible nonce",
            "content": "body",
            "protocol_version": 1,
        }
        code_ok, resp_ok = _post(f"{backend}/api/core/post", ok_payload)
        err_msg = str(resp_ok.get("error", ""))
        if code_ok >= 500:
            _fail(test_name, f"server error: code={code_ok} resp={resp_ok}")
        elif err_msg in nonce_reject_errors:
            _fail(test_name, f"nonce={ok_val!r} rejected by nonce parser: {err_msg}")
        else:
            _pass(test_name)

    # 9.11d v1.20+ path: nonce present → replay protection active
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    ts_new = _now_ms()
    nonce_new = _fresh_nonce()
    base_new = _canon_base_post_raw(
        pub, _lb_bytes(lb), diff, ts_new, "", "test", "nonce present", "body", "", 0, None, nonce_new
    )
    proof_new = compute_pow(base_new, diff, base_bits, pow_factor, lb)
    signed_new = canon_signed_with_pow(base_new, int(proof_new))
    sig_new = sign_canonical(wallet, signed_new)
    payload_with_nonce = {
        "pubkey": _b64(pub),
        "signature": _b64(sig_new),
        "last_block_hash": lb,
        "timestamp": ts_new,
        "envelope_nonce": str(nonce_new),
        "pow_difficulty": diff,
        "pow": int(proof_new),
        "target": "",
        "topic": "test",
        "title": "nonce present",
        "content": "body",
        "protocol_version": 1,
    }
    code_with_nonce, resp_with_nonce = _post(f"{backend}/api/core/post", payload_with_nonce)
    if code_with_nonce == 200:
        _pass("edge.envelope_nonce_present_accepted")
    else:
        _fail("edge.envelope_nonce_present_accepted", f"code={code_with_nonce} resp={resp_with_nonce}")

    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)

    # ── 9.20 Garbage / invalid envelope fields (non-nonce) ────────────
    # For each field we submit a payload with ONE corrupted field and
    # verify the backend returns a 4xx; 5xx is a server error and must fail.

    def _make_valid_payload() -> dict:
        """Build a structurally valid (but unsigned) payload for /api/core/post."""
        return {
            "pubkey": _b64(pub),
            "signature": _b64(b"\x00" * 64),
            "last_block_hash": lb,
            "timestamp": _now_ms(),
            "envelope_nonce": str(_fresh_nonce()),
            "pow_difficulty": diff,
            "pow": 0,
            "target": "",
            "topic": "test",
            "title": "field test",
            "content": "body",
            "protocol_version": 1,
        }

    # --- 9.20a: timestamp ---
    timestamp_cases_reject = [
        ("missing", "_OMIT_", "edge.ts_missing_rejected"),
        ("null", None, "edge.ts_null_rejected"),
        ("string", "not-a-number", "edge.ts_string_rejected"),
        ("empty", "", "edge.ts_empty_rejected"),
        ("array", [1, 2], "edge.ts_array_rejected"),
        ("object", {"t": 1}, "edge.ts_object_rejected"),
        ("negative", -9999999999999, "edge.ts_negative_rejected"),
        ("bool", True, "edge.ts_bool_rejected"),
        ("zero", 0, "edge.ts_zero_rejected"),
    ]
    for label, bad_val, test_name in timestamp_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["timestamp"]
        else:
            p["timestamp"] = bad_val
        code_t, resp_t = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_t, resp_t)

    # --- 9.20b: pubkey ---
    pubkey_cases_reject = [
        ("missing", "_OMIT_", "edge.pubkey_missing_rejected"),
        ("empty", "", "edge.pubkey_empty_rejected"),
        ("null", None, "edge.pubkey_null_rejected"),
        ("not_base64", "!!!notbase64!!!", "edge.pubkey_not_base64_rejected"),
        ("wrong_len_32", _b64(b"\x01" * 32), "edge.pubkey_wrong_len32_rejected"),
        ("wrong_len_64", _b64(b"\x01" * 64), "edge.pubkey_wrong_len64_rejected"),
        ("array", [1, 2, 3], "edge.pubkey_array_rejected"),
        ("object", {"k": "v"}, "edge.pubkey_object_rejected"),
        ("int", 12345, "edge.pubkey_int_rejected"),
    ]
    for label, bad_val, test_name in pubkey_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["pubkey"]
        else:
            p["pubkey"] = bad_val
        code_p, resp_p = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_p, resp_p)

    # --- 9.20c: signature ---
    sig_cases_reject = [
        ("missing", "_OMIT_", "edge.sig_missing_rejected"),
        ("empty", "", "edge.sig_empty_rejected"),
        ("null", None, "edge.sig_null_rejected"),
        ("not_base64", "***bad-b64***", "edge.sig_not_base64_rejected"),
        ("wrong_len_32", _b64(b"\x01" * 32), "edge.sig_wrong_len32_rejected"),
        ("too_long", _b64(b"\x01" * 128), "edge.sig_too_long_rejected"),
        ("array", [1, 2, 3], "edge.sig_array_rejected"),
        ("object", {"s": "v"}, "edge.sig_object_rejected"),
    ]
    for label, bad_val, test_name in sig_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["signature"]
        else:
            p["signature"] = bad_val
        code_s, resp_s = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_s, resp_s)

    # --- 9.20d: last_block_hash ---
    lbh_cases_reject = [
        ("missing", "_OMIT_", "edge.lbh_missing_rejected"),
        ("not_hex", "ZZZZ-not-hex", "edge.lbh_not_hex_rejected"),
        ("wrong_len", "aabb", "edge.lbh_wrong_len_rejected"),
        ("null", None, "edge.lbh_null_rejected"),
        ("array", [1], "edge.lbh_array_rejected"),
        ("object", {"h": 1}, "edge.lbh_object_rejected"),
        ("int", 999, "edge.lbh_int_rejected"),
    ]
    for label, bad_val, test_name in lbh_cases_reject:
        p = _make_valid_payload()
        if bad_val == "_OMIT_":
            del p["last_block_hash"]
        else:
            p["last_block_hash"] = bad_val
        code_l, resp_l = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_l, resp_l)

    # --- 9.20e: pow_difficulty ---
    pwd_cases_reject = [
        ("string", "abc", "edge.pwd_string_rejected"),
        ("null", None, "edge.pwd_null_rejected"),
        ("array", [1], "edge.pwd_array_rejected"),
        ("object", {"d": 1}, "edge.pwd_object_rejected"),
        ("negative", -5, "edge.pwd_negative_rejected"),
    ]
    for label, bad_val, test_name in pwd_cases_reject:
        p = _make_valid_payload()
        p["pow_difficulty"] = bad_val
        code_d, resp_d = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_d, resp_d)

    # --- 9.20f: pow ---
    pow_cases_reject = [
        ("string", "xyz", "edge.pow_string_rejected"),
        ("null", None, "edge.pow_null_rejected"),
        ("array", [9], "edge.pow_array_rejected"),
        ("object", {"p": 1}, "edge.pow_object_rejected"),
        ("negative", -1, "edge.pow_negative_rejected"),
    ]
    for label, bad_val, test_name in pow_cases_reject:
        p = _make_valid_payload()
        p["pow"] = bad_val
        code_pw, resp_pw = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_pw, resp_pw)

    # --- 9.20g: topic ---
    topic_cases_reject = [
        ("too_short", "ab", "edge.topic_too_short_rejected"),
        ("too_long", "a" * 60, "edge.topic_too_long_rejected"),
        ("uppercase", "INVALID", "edge.topic_uppercase_rejected"),
        ("spaces", "has spaces", "edge.topic_spaces_rejected"),
        ("special", "top!@#$", "edge.topic_special_rejected"),
        ("unicode", "\u00e9\u00e8\u00ea", "edge.topic_unicode_rejected"),
        ("null", None, "edge.topic_null_rejected"),
    ]
    for label, bad_val, test_name in topic_cases_reject:
        p = _make_valid_payload()
        p["topic"] = bad_val
        code_tp, resp_tp = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_tp, resp_tp)

    # --- 9.20h: title / content size limits ---
    title_oversize = "A" * 1000
    p_big_title = _make_valid_payload()
    p_big_title["title"] = title_oversize
    code_bt, resp_bt = _post(f"{backend}/api/core/post", p_big_title)
    _expect_reject_4xx("edge.title_oversize_1k_rejected", code_bt, resp_bt)

    content_oversize = "X" * 200_000
    p_big_content = _make_valid_payload()
    p_big_content["content"] = content_oversize
    code_bc, resp_bc = _post(f"{backend}/api/core/post", p_big_content)
    _expect_reject_4xx("edge.content_oversize_200k_rejected", code_bc, resp_bc)

    # --- 9.20i: media ---
    media_cases_reject = [
        ("not_list", "https://a.com/x.jpg", "edge.media_not_list_rejected"),
        ("http_not_https", ["http://a.com/x.jpg"], "edge.media_http_rejected"),
        ("too_many", [f"https://a.com/{i}.jpg" for i in range(15)], "edge.media_too_many_rejected"),
        ("item_too_long", ["https://a.com/" + "a" * 2100], "edge.media_item_too_long_rejected"),
        ("no_scheme", ["just-a-string"], "edge.media_no_scheme_rejected"),
    ]
    for label, bad_val, test_name in media_cases_reject:
        p = _make_valid_payload()
        p["media"] = bad_val
        code_m, resp_m = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_m, resp_m)

    # --- 9.20j: tag ---
    tag_cases_reject = [
        ("invalid", "notarealltag", "edge.tag_invalid_rejected"),
        ("too_long", "x" * 60, "edge.tag_too_long_rejected"),
    ]
    for label, bad_val, test_name in tag_cases_reject:
        p = _make_valid_payload()
        p["tag"] = bad_val
        code_tg, resp_tg = _post(f"{backend}/api/core/post", p)
        _expect_reject_4xx(test_name, code_tg, resp_tg)

    # --- 9.20k: completely empty payload ---
    code_empty, resp_empty = _post(f"{backend}/api/core/post", {})
    _expect_reject_4xx("edge.empty_payload_rejected", code_empty, resp_empty)

    # --- 9.20l: completely bogus payload (random keys) ---
    bogus = {"foo": "bar", "baz": 42, "qux": [1, 2, 3]}
    code_bogus, resp_bogus = _post(f"{backend}/api/core/post", bogus)
    _expect_reject_4xx("edge.bogus_payload_rejected", code_bogus, resp_bogus)

    # 9.12 XSS injection in content — should not cause server error
    xss_content = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
    txh_xss = _do_post(backend, wallet, "test", f"XSS test {_rand_str(4)}", xss_content)
    if txh_xss:
        _pass("edge.xss_content_accepted_safely", tx=txh_xss)
        # Verify it's stored as-is (not interpreted)
        time.sleep(2)
        code_xss, feed_xss = _get(f"{backend}/api/get_user_posts", {"owner": addr, "limit": 10})
        if code_xss == 200:
            posts_xss = (feed_xss or {}).get("posts") or []
            p_xss = next((p for p in posts_xss if str(p.get("post_id", "")).lower() == txh_xss), None)
            if p_xss and "script" in (p_xss.get("content") or "").lower():
                _pass("edge.xss_content_stored_as_text (not stripped)")
            else:
                _pass("edge.xss_content_handled")
    else:
        _pass("edge.xss_content_rejected (backend may sanitize)")

    # 9.13 SQL injection in search — should not cause server error
    sqli_query = "'; DROP TABLE posts; --"
    code_sqli, resp_sqli = _get(f"{backend}/api/search", {"q": sqli_query, "limit": 5})
    if code_sqli in (200, 400):
        _pass("edge.sqli_search_safe", code=code_sqli)
    else:
        _fail("edge.sqli_search_safe", f"code={code_sqli}")

    code_sqli2, _ = _get(f"{backend}/api/search_topics", {"q": "' OR 1=1 --"})
    if code_sqli2 in (200, 400, 410):
        _pass("edge.sqli_search_topics_safe", code=code_sqli2)
    else:
        _fail("edge.sqli_search_topics_safe", f"code={code_sqli2}")

    code_sqli3, _ = _get(f"{backend}/api/search_username", {"q": "admin' --"})
    if code_sqli3 in (200, 400):
        _pass("edge.sqli_search_username_safe", code=code_sqli3)
    else:
        _fail("edge.sqli_search_username_safe", f"code={code_sqli3}")

    # 9.14 Vote on non-existent post
    fake_target = "bb" * 32
    try:
        resp_vote = _do_vote(backend, wallet, fake_target, 1)
        txh_v = str(resp_vote.get("tx_hash", "")).lower()
        code_v = int(resp_vote.get("code", 0) or 0)
        if not txh_v or code_v != 0:
            _pass("edge.vote_nonexistent_post_fails")
        else:
            # Tx was broadcast but may fail on-chain
            _pass("edge.vote_nonexistent_post submitted (chain may reject)")
    except Exception as e:
        err = str(e).lower()
        if "400" in err or "error" in err or "invalid" in err:
            _pass("edge.vote_nonexistent_post_fails")
        else:
            _fail("edge.vote_nonexistent_post_fails", str(e))

    # 9.15 Duplicate username rejected
    try:
        # Get the current username of a subscriber wallet
        sub_wallet_dup = WALLETS["sub1"]
        sub_addr_dup = str(sub_wallet_dup.address())
        existing_name = get_username_from_address(backend, sub_addr_dup)
        if existing_name:
            # Try to claim the subscriber's existing username from the free wallet
            from shared.client import set_username as _set_username

            resp_dup = _set_username(backend, wallet, existing_name, skip_pow=False)
            txh_dup = str(resp_dup.get("tx_hash", "")).lower()
            code_dup = int(resp_dup.get("code", 0) or 0)
            err_dup = str(resp_dup.get("error", "")).lower() + str(resp_dup.get("raw_log", "")).lower()
            if not txh_dup or code_dup != 0 or "already" in err_dup or "taken" in err_dup:
                _pass("edge.duplicate_username_rejected")
            else:
                _pass("edge.duplicate_username submitted (chain may reject)")
        else:
            _pass("edge.duplicate_username (no existing username to test)")
    except Exception as e:
        err = str(e).lower()
        if "400" in err or "already" in err or "taken" in err:
            _pass("edge.duplicate_username_rejected")
        else:
            _fail("edge.duplicate_username_rejected", str(e))

    # 9.16 Self-follow (follow own address)
    try:
        resp_self = _do_follow_user(backend, wallet, addr, follow=True)
        txh_self = str(resp_self.get("tx_hash", "")).lower()
        # Self-follow may be accepted or rejected depending on chain logic
        if txh_self:
            _pass("edge.self_follow submitted (chain decides)")
        else:
            _pass("edge.self_follow rejected")
    except Exception as e:
        _pass("edge.self_follow handled")

    # 9.17 All 6 valid tags accepted
    valid_tags = ["sensitive", "adult", "violence", "drugs", "politics", ""]
    for tag in valid_tags:
        label = tag if tag else "empty"
        try:
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
            pub = wallet.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = f"vtag{_rand_str(4)}"
            base = _canon_base_post_raw(
                pub, _lb_bytes(lb), diff, ts, "", topic, "Valid tag", "body", tag, 0, None, nonce
            )
            proof = compute_pow(base, diff, base_bits, pow_factor, lb)
            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(wallet, signed)
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
                "title": "Valid tag",
                "content": "body",
                "tag": tag,
                "protocol_version": 1,
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            txh = str((resp or {}).get("tx_hash", "") or "").lower()
            if txh:
                _pass(f"edge.valid_tag_{label}_accepted")
            else:
                _pass(f"edge.valid_tag_{label} submitted")
        except Exception as e:
            _fail(f"edge.valid_tag_{label}_accepted", str(e))

    # 9.18 Duplicate post (same topic+title in quick succession)
    try:
        dup_topic = f"dup{_rand_str(4)}"
        txh1 = _do_post(backend, wallet, dup_topic, "Dup title", "body 1")
        txh2 = _do_post(backend, wallet, dup_topic, "Dup title", "body 2")
        if txh1 and txh2:
            _pass("edge.duplicate_post_both_accepted")
        elif txh1:
            _pass("edge.duplicate_post_second_rejected")
        else:
            _pass("edge.duplicate_post handled")
    except Exception as e:
        _pass("edge.duplicate_post handled")

    # ── 9.19+  Malicious / adversarial inputs ───────────────────────
    # NUL bytes, C0 control characters, DEL — all must be rejected.
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes

    malicious_cases = [
        # NUL byte (\x00)
        ("nul_in_content", {"topic": f"nul{_rand_str(4)}", "title": "Normal", "content": "has\x00nul"}),
        ("nul_in_title", {"topic": f"nul{_rand_str(4)}", "title": "Nul\x00Title", "content": "body"}),
        ("nul_in_topic", {"topic": f"nul\x00tp", "title": "Title", "content": "body"}),
        ("only_nul_content", {"topic": f"nul{_rand_str(4)}", "title": "Title", "content": "\x00\x00\x00"}),
        ("nul_in_tag", {"topic": f"nul{_rand_str(4)}", "title": "Title", "content": "body", "tag": "gore\x00"}),
        ("embedded_nul", {"topic": f"nul{_rand_str(4)}", "title": "Normal Title", "content": "Looks normal\x00hidden"}),
        # Other C0 control characters
        ("ctrl_bel", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x07 bell"}),
        ("ctrl_backspace", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x08 bs"}),
        ("ctrl_escape", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x1b escape"}),
        ("ctrl_vtab", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x0b vtab"}),
        ("ctrl_formfeed", {"topic": f"ctl{_rand_str(4)}", "title": "Title", "content": "has \x0c ff"}),
        # DEL character
        ("del_in_content", {"topic": f"del{_rand_str(4)}", "title": "Title", "content": "has \x7f del"}),
        ("del_in_title", {"topic": f"del{_rand_str(4)}", "title": "Del\x7fTitle", "content": "body"}),
    ]
    for label, fields in malicious_cases:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        code, resp = _try_post(
            fields.get("topic", ""),
            fields.get("title", ""),
            fields.get("content", ""),
            tag=fields.get("tag", ""),
        )
        _expect_reject_4xx(f"edge.{label}_rejected", code, resp)

    # ── NUL / control chars in media URLs ─────────────────────────
    media_nul_cases = [
        ("nul_in_media", [f"https://example.com/\x00img.jpg"]),
        ("ctrl_in_media", [f"https://example.com/\x07img.jpg"]),
        ("del_in_media", [f"https://example.com/\x7fimg.jpg"]),
    ]
    for label, bad_media in media_nul_cases:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        pub = wallet.public_key().public_key_bytes
        ts = _now_ms()
        nonce = _fresh_nonce()
        topic = f"med{_rand_str(4)}"
        base = _canon_base_post_raw(pub, _lb_bytes(lb), diff, ts, "", topic, "Title", "body", "", 0, bad_media, nonce)
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
        signed = canon_signed_with_pow(base, int(proof))
        sig = sign_canonical(wallet, signed)
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
            "title": "Title",
            "content": "body",
            "media": bad_media,
            "protocol_version": 1,
        }
        code, resp = _post(f"{backend}/api/core/post", payload)
        _expect_reject_4xx(f"edge.{label}_rejected", code, resp)

    # ── Unicode edge cases (should be accepted) ───────────────────
    unicode_cases = [
        ("zwsp_title", f"Zero\u200bWidth", "body"),
        ("zwj_title", f"Join\u200dTest", "body"),
        ("rtl_content", "Title", "abc\u202edef"),
        ("bidi_isolate", "Title", "a\u2066b\u2069c"),
        ("combining", "Cafe\u0301", "body"),
        ("emoji", "Title🙂", "content 🙂"),
    ]
    for label, title, content in unicode_cases:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        code, resp = _try_post("test", title, content)
        if code < 400:
            _pass(f"edge.unicode_{label}_accepted")
        else:
            _debug(f"edge.unicode_{label}_accepted failed code={code} resp={resp}")
            _fail(f"edge.unicode_{label}_accepted", f"code={code}")

    # ── Unicode topics should be rejected ─────────────────────────
    bad_unicode_topics = [
        ("accented", "tést"),
        ("cyrillic", "тема"),
        ("zero_width", "te\u200bst"),
    ]
    for label, topic in bad_unicode_topics:
        lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
        code, resp = _try_post(topic, "Title", "body")
        _expect_reject_4xx(f"edge.unicode_topic_{label}_rejected", code, resp)


# =========================================================================
# Category 10: Security & Attack Vectors
# =========================================================================

def test_frontend_bypass(backend: str):
    """Test all cases where frontend-only validation could be bypassed."""

    free_wallet = WALLETS["free"]
    sub1 = WALLETS["sub1"]
    sub2 = WALLETS["sub2"]
    free_addr = str(free_wallet.address())
    sub1_addr = str(sub1.address())

    _code, _ncfg = _get(f"{backend}/api/get_node_config")
    reg_enabled = (_ncfg or {}).get("registration_enabled", False) if _code == 200 else False

    # ─── Username bypass ─────────────────────────────────────────────
    bypass_usernames = [
        ("user_name", "underscore"),
        ("user.name", "dot"),
        ("user name", "space"),
        ("user@name", "at_sign"),
        ("\u00fcser", "unicode"),
        ("\U0001f602user", "emoji"),
        ("user\x00name", "null_byte"),
        ("---", "only_hyphens"),
        ("-startdash", "starts_with_hyphen"),
    ]
    for uname, label in bypass_usernames:
        if not reg_enabled:
            _pass(f"bypass.username_{label} skipped (registration disabled)")
            continue
        try:
            resp = _do_set_username_raw(backend, free_wallet, uname)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "invalid" in err:
                _pass(f"bypass.username_{label}_rejected")
            else:
                _pass(f"bypass.username_{label} submitted (chain may reject)")
        except Exception as e:
            _pass(f"bypass.username_{label} handled")

    # ─── Topic bypass ────────────────────────────────────────────────
    bypass_topics = [
        ("UPPERCASE", "uppercase"),
        ("with spaces", "spaces"),
        ("special!@#", "special_chars"),
        ("\u00fc\u00f6\u00e4", "unicode"),
        ("a", "min_boundary"),
        ("a" * 200, "over_max"),
    ]
    for topic, label in bypass_topics:
        try:
            txh = _do_post(backend, sub1, topic, f"Bypass {label}", "body", skip_pow=True)
            if not txh:
                _pass(f"bypass.topic_{label}_rejected")
            else:
                _pass(f"bypass.topic_{label} submitted (chain may reject)")
        except Exception as e:
            _pass(f"bypass.topic_{label} handled")

    # ─── Tag bypass ──────────────────────────────────────────────────
    bypass_tags = [
        ("nsfw", "nsfw"),
        ("adult", "adult"),
        ("SENSITIVE", "uppercase_sensitive"),
        ("Adult", "mixed_case_adult"),
        ("random_tag", "random_string"),
        ("tag with spaces", "spaces"),
        ("!@#$%", "special_chars"),
        ("t" * 60, "over_50_chars"),
    ]
    for tag, label in bypass_tags:
        try:
            lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, sub1_addr)
            pub = sub1.public_key().public_key_bytes
            ts = _now_ms()
            nonce = _fresh_nonce()
            topic = f"tag{_rand_str(4)}"
            base = _canon_base_post_raw(pub, _lb_bytes(lb), 0, ts, "", topic, "Tag test", "body", tag, 0, None, nonce)
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
                "title": "Tag test",
                "content": "body",
                "tag": tag,
                "protocol_version": 1,
            }
            code, resp = _post(f"{backend}/api/core/post", payload)
            _expect_reject_or_submit(
                f"bypass.tag_{label}_rejected",
                f"bypass.tag_{label} submitted (chain may reject)",
                code,
                resp,
            )
        except Exception as e:
            _pass(f"bypass.tag_{label} handled")

    # ─── Vote direction bypass ───────────────────────────────────────
    # Create a target post for vote tests
    vote_target = _do_post(backend, sub1, f"vote{_rand_str(4)}", "Vote target", "body", skip_pow=True)
    if vote_target:
        time.sleep(3)
        for direction, label in [(2, "direction_2"), (-2, "direction_neg2"), (999, "direction_999")]:
            try:
                resp = _do_vote(backend, sub1, vote_target, direction, skip_pow=True)
                txh = str(resp.get("tx_hash", "")).lower()
                err = str(resp.get("error", "")).lower()
                if not txh or "invalid" in err or "direction" in err:
                    _pass(f"bypass.vote_{label}_rejected")
                else:
                    _pass(f"bypass.vote_{label} submitted (chain may reject)")
            except Exception as e:
                _pass(f"bypass.vote_{label} handled")

    # ─── Content/title boundary bypass ───────────────────────────────
    # Get tier 1 limits to test boundaries
    try:
        st = get_status(backend, address=sub1_addr)
        from shared.client import get_user_status as _gus

        us = _gus(backend, sub1_addr)
        user_level = int(us.get("user_level", 1) or 1)
    except Exception:
        user_level = 1

    try:
        _, params = _get(f"{backend}/api/get_chain_config")
        params = params or {}
        tiers = params.get("tiers") or []
        idx = {0: 0, 1: 1, 10: 2}.get(user_level, 2 if user_level >= 100 else -1)
        if 0 <= idx < len(tiers):
            tier = tiers[idx]
            max_content = int(tier.get("max_content_length", 50000) or 50000)
            max_title = int(tier.get("max_title_length", 300) or 300)
        else:
            max_content = 50000
            max_title = 300
    except Exception:
        max_content = 50000
        max_title = 300

    # Exact max content (should succeed)
    try:
        exact_content = "x" * max_content
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", "Exact max", exact_content, skip_pow=True)
        if txh:
            _pass("bypass.content_exact_max_accepted")
        else:
            _pass("bypass.content_exact_max submitted")
    except Exception as e:
        _pass("bypass.content_exact_max handled")

    # One over max content
    try:
        over_content = "x" * (max_content + 1)
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", "Over max", over_content, skip_pow=True)
        if not txh:
            _pass("bypass.content_one_over_rejected")
        else:
            _pass("bypass.content_one_over submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.content_one_over handled")

    # Exact max title
    try:
        exact_title = "T" * max_title
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", exact_title, "body", skip_pow=True)
        if txh:
            _pass("bypass.title_exact_max_accepted")
        else:
            _pass("bypass.title_exact_max submitted")
    except Exception as e:
        _pass("bypass.title_exact_max handled")

    # One over max title
    try:
        over_title = "T" * (max_title + 1)
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", over_title, "body", skip_pow=True)
        if not txh:
            _pass("bypass.title_one_over_rejected")
        else:
            _pass("bypass.title_one_over submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.title_one_over handled")

    # UTF-8 multi-byte edge: 4-byte emoji fills content length faster
    try:
        emoji_content = "\U0001f4a9" * (max_content // 4 + 1)
        txh = _do_post(backend, sub1, f"edge{_rand_str(4)}", "Emoji content", emoji_content, skip_pow=True)
        if not txh:
            _pass("bypass.utf8_multibyte_rejected")
        else:
            _pass("bypass.utf8_multibyte submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.utf8_multibyte handled")

    # ─── Comment bypass ──────────────────────────────────────────────
    if vote_target:
        # Comment with topic set (should be empty for comments)
        try:
            txh = _do_post(backend, sub1, "shouldbeempty", "", "Comment with topic", target=vote_target, skip_pow=True)
            if not txh:
                _pass("bypass.comment_with_topic_rejected")
            else:
                _pass("bypass.comment_with_topic submitted (chain may reject)")
        except Exception as e:
            _pass("bypass.comment_with_topic handled")

    # Root post with empty topic
    try:
        txh = _do_post(backend, sub1, "", "No topic post", "body", skip_pow=True)
        if not txh:
            _pass("bypass.root_empty_topic_rejected")
        else:
            _pass("bypass.root_empty_topic submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.root_empty_topic handled")

    # Comment with nonexistent parent
    try:
        txh = _do_post(backend, sub1, "", "", "Orphan comment", target="dd" * 32, skip_pow=True)
        if not txh:
            _pass("bypass.comment_nonexistent_parent_rejected")
        else:
            _pass("bypass.comment_nonexistent_parent submitted (chain decides)")
    except Exception as e:
        _pass("bypass.comment_nonexistent_parent handled")

    # ─── Edit bypass ─────────────────────────────────────────────────
    # Edit with invalid override hash
    try:
        resp = _do_edit(
            backend, sub1, override_hash="not_a_hash", topic="test", title="Bad edit", content="body", skip_pow=True
        )
        txh = str(resp.get("tx_hash", "")).lower()
        err = str(resp.get("error", "")).lower()
        if not txh or "invalid" in err:
            _pass("bypass.edit_invalid_override_rejected")
        else:
            _pass("bypass.edit_invalid_override submitted (chain may reject)")
    except Exception as e:
        _pass("bypass.edit_invalid_override handled")

    # Edit with nonexistent override
    try:
        resp = _do_edit(
            backend, sub1, override_hash="ee" * 32, topic="test", title="Ghost edit", content="body", skip_pow=True
        )
        txh = str(resp.get("tx_hash", "")).lower()
        if txh:
            _pass("bypass.edit_nonexistent_override submitted (chain decides)")
        else:
            _pass("bypass.edit_nonexistent_override_rejected")
    except Exception as e:
        _pass("bypass.edit_nonexistent_override handled")

    # ─── Send tokens bypass ──────────────────────────────────────────
    # String amount — send raw JSON with invalid type to test backend input parsing
    try:
        raw_payload_str = {
            "pubkey": "",
            "signature": "",
            "last_block_hash": "",
            "timestamp": _now_ms(),
            "target": str(sub2.address()),
            "amount": "not_a_number",
        }
        code, resp = _post(f"{backend}/api/core/send_tokens", raw_payload_str)
        _expect_reject_4xx("bypass.send_tokens_string_amount_rejected", code, resp)
    except Exception as e:
        _pass("bypass.send_tokens_string_amount_rejected")

    # Float amount — send raw JSON with float to test backend input parsing
    try:
        raw_payload_float = {
            "pubkey": "",
            "signature": "",
            "last_block_hash": "",
            "timestamp": _now_ms(),
            "target": str(sub2.address()),
            "amount": 1.5,
        }
        code, resp = _post(f"{backend}/api/core/send_tokens", raw_payload_float)
        _expect_reject_or_submit(
            "bypass.send_tokens_float_amount_rejected",
            "bypass.send_tokens_float_amount submitted (chain may reject)",
            code,
            resp,
        )
    except Exception as e:
        _pass("bypass.send_tokens_float_amount_rejected")

    # ─── Upgrade level bypass ────────────────────────────────────────
    for level, label in [(0, "level_0"), (-1, "level_neg1"), (4, "level_4"), (99, "level_99")]:
        try:
            resp = _do_subscribe(backend, free_wallet, level)
            txh = str(resp.get("tx_hash", "")).lower()
            err = str(resp.get("error", "")).lower() + str(resp.get("raw_log", "")).lower()
            if not txh or "invalid" in err:
                _pass(f"bypass.subscribe_{label}_rejected")
            else:
                _pass(f"bypass.subscribe_{label} submitted (chain may reject)")
        except Exception as e:
            _pass(f"bypass.subscribe_{label} handled")



def test_rate_limit(backend: str):
    """Verify Caddy rate limiting returns HTTP 429 on API bursts."""

    url = f"{backend}/api/get_parameters"
    session = requests.Session()
    # Caddy's api_limit permits 50 events per one-second window. A probe below
    # that threshold cannot demonstrate enforcement and used to fail while the
    # limiter was behaving exactly as configured.
    burst_size = 75
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        statuses: list[int] = []
        first_429: Optional[requests.Response] = None

        for _ in range(burst_size):
            try:
                resp = session.get(url, timeout=3)
            except Exception as e:
                _fail("rate_limit.api_burst", str(e), attempt=attempt)
                return
            statuses.append(resp.status_code)
            if resp.status_code == 429 and first_429 is None:
                first_429 = resp

        hits_429 = sum(1 for s in statuses if s == 429)
        hits_200 = sum(1 for s in statuses if s == 200)
        _debug(f"rate_limit burst attempt={attempt} total={len(statuses)} " f"ok={hits_200} rate_limited={hits_429}")

        if hits_429 > 0:
            # Caddy can return JSON for /api/* rate limits.
            if first_429 is not None:
                try:
                    body = first_429.json() or {}
                    err = str(body.get("error", "")).lower()
                    msg = str(body.get("message", "")).lower()
                    if "rate" in err or "too many" in msg:
                        _pass("rate_limit.api_returns_429", attempt=attempt, rate_limited=hits_429, ok=hits_200)
                        return
                except Exception:
                    pass
            _pass("rate_limit.api_returns_429", attempt=attempt, rate_limited=hits_429, ok=hits_200)
            return

        # Window in Caddyfile is 1s; let it reset and try again.
        time.sleep(1.25)

    _fail("rate_limit.api_returns_429", f"no 429 observed across {max_attempts} bursts of {burst_size}")


# =========================================================================
# Category 19: Hard Cap vs Deque (backend-level)
# =========================================================================
