"""Backend-specific transaction helpers and wait/poll utilities."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from typing import Optional, Tuple

import requests

from tests.common import (
    _b64,
    _debug,
    _lb_bytes,
    _now_ms,
    _fresh_nonce,
    _rand_str,
    _get,
    _post,
    _fetch_params,
    _canon_base_post_raw,
    _canon_base_vote_raw,
    _canon_base_edit_raw,
    _canon_base_delete_raw,
    _canon_base_delete_user_raw,
    _canon_base_set_username_raw,
    _canon_base_set_biography_raw,
    _canon_base_follow_user_raw,
    _canon_base_unfollow_user_raw,
    _canon_base_follow_topic_raw,
    _canon_base_unfollow_topic_raw,
    _canon_base_block_post_raw,
    _canon_base_unblock_post_raw,
    _canon_base_block_user_raw,
    _canon_base_unblock_user_raw,
    _canon_base_block_topic_raw,
    _canon_base_unblock_topic_raw,
    _canon_base_send_tokens_raw,
    _canon_base_subscribe_raw,
    _canon_base_report_raw,
    _canon_base_set_auto_renewal_raw,
    _canon_base_award_raw,
    _canon_base_join_community_raw,
    _canon_base_leave_community_raw,
    _canon_base_block_community_raw,
    _canon_base_unblock_community_raw,
    canon_signed_with_pow,
    sign_canonical,
    compute_pow,
    get_status,
    get_username_from_address,
    INDEX_TIMEOUT_SEC,
)
from cosmpy.aerial.wallet import LocalWallet

from shared.canon import (
    canon_base_create_curation_team as _canon_base_create_curation_team_raw,
    canon_base_set_curation_preference as _canon_base_set_curation_preference_raw,
    canon_base_set_curation_post_hidden as _canon_base_set_curation_post_hidden_raw,
    canon_base_set_curation_user_hidden as _canon_base_set_curation_user_hidden_raw,
    canon_base_set_curation_team_profile as _canon_base_set_curation_team_profile_raw,
    canon_base_invite_curator as _canon_base_invite_curator_raw,
    canon_base_revoke_curator_invite as _canon_base_revoke_curator_invite_raw,
    canon_base_accept_curator_invite as _canon_base_accept_curator_invite_raw,
    canon_base_decline_curator_invite as _canon_base_decline_curator_invite_raw,
    canon_base_leave_curation_team as _canon_base_leave_curation_team_raw,
    canon_base_remove_curator as _canon_base_remove_curator_raw,
    canon_base_transfer_curation_team as _canon_base_transfer_curation_team_raw,
    canon_base_delete_curation_team as _canon_base_delete_curation_team_raw,
    canon_base_set_curation_thread_locked as _canon_base_set_curation_thread_locked_raw,
    canon_base_set_curation_subscriber_only as _canon_base_set_curation_subscriber_only_raw,
    canon_base_set_curation_tag as _canon_base_set_curation_tag_raw,
    canon_base_set_curation_post_tag as _canon_base_set_curation_post_tag_raw,
)

def _do_send_tokens(backend: str, wallet: LocalWallet, target: str, amount: int, skip_pow: bool = False) -> dict:
    """Send tokens from wallet to target address via the backend API."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_send_tokens_raw(pub, _lb_bytes(lb), d, ts, addr, target, amount, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "amount": amount,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/send_tokens", payload)
    return resp


def _do_award(
    backend: str,
    wallet: LocalWallet,
    target: str,
    award_type: str,
    pow_difficulty: int = 0,
    pow: int = 0,
    last_block_hash: str | None = None,
    timestamp: int | None = None,
    sig_override: bytes | None = None,
    pub_override: bytes | None = None,
) -> tuple[int, dict]:
    """Send an award via the backend API (burn-only)."""
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = last_block_hash or str(st.get("last_block_hash", ""))
    pub = pub_override or wallet.public_key().public_key_bytes
    ts = int(timestamp or _now_ms())
    nonce = _fresh_nonce()
    base = _canon_base_award_raw(pub, _lb_bytes(lb), int(pow_difficulty), ts, target, award_type, nonce)
    signed = canon_signed_with_pow(base, int(pow))
    sig = sig_override or sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": int(pow_difficulty),
        "pow": int(pow),
        "target": target,
        "award_type": award_type,
    }
    code, resp = _post(f"{backend}/api/core/award", payload)
    return code, resp


def _do_post(
    backend: str, wallet, community: str, title: str, content: str, target: str = "", tag: str = "", skip_pow: bool = False
) -> str | None:
    """Create a post/comment and return the tx_hash or None."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_post_raw(pub, _lb_bytes(lb), d, ts, target, community, title, content, tag, 0, None, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "community": community,
        "protocol_version": 1,
        "title": title,
        "content": content,
        "tag": tag,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/post", payload)
    resp = resp or {}
    if resp.get("error"):
        _debug(f"post.submit error={resp.get('error')}")
        return None
    tx_code = int(resp.get("code", 0) or 0)
    if tx_code != 0:
        _debug(f"post.submit failed code={tx_code} log={str(resp.get('raw_log', ''))[:200]}")
        return None
    txh = str(resp.get("tx_hash", "") or "").lower()
    return txh if txh else None


def _do_post_at_timestamp(
    backend: str,
    wallet,
    community: str,
    title: str,
    content: str,
    timestamp_ms: int,
    nonce: int | None = None,
    target: str = "",
    tag: str = "",
    skip_pow: bool = False,
) -> tuple[int, dict]:
    """Create a post with an explicit envelope timestamp; return (status, body)."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = int(timestamp_ms)
    nonce = _fresh_nonce() if nonce is None else int(nonce)
    d = 0 if skip_pow else diff

    base = _canon_base_post_raw(pub, _lb_bytes(lb), d, ts, target, community, title, content, tag, 0, None, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "community": community,
        "protocol_version": 1,
        "title": title,
        "content": content,
        "tag": tag,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/post", payload)
    return code, (resp or {})


def _do_post_with_nonce(
    backend: str,
    wallet,
    community: str,
    title: str,
    content: str,
    nonce: int,
    target: str = "",
    tag: str = "",
    skip_pow: bool = False,
) -> dict:
    _, resp = _do_post_at_timestamp(
        backend,
        wallet,
        community,
        title,
        content,
        _now_ms(),
        nonce=nonce,
        target=target,
        tag=tag,
        skip_pow=skip_pow,
    )
    return resp


def _do_vote(backend: str, wallet, target: str, direction: int, skip_pow: bool = False) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_vote_raw(pub, _lb_bytes(lb), d, ts, target, int(direction), nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "direction": direction,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/vote", payload)
    return resp


def _do_vote_with_nonce(
    backend: str,
    wallet,
    target: str,
    direction: int,
    nonce: int,
    skip_pow: bool = False,
) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    d = 0 if skip_pow else diff

    base = _canon_base_vote_raw(pub, _lb_bytes(lb), d, ts, target, int(direction), nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "direction": direction,
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/vote", payload)
    return resp or {}


def _do_edit(
    backend: str,
    wallet,
    override_hash: str,
    community: str,
    title: str,
    content: str,
    target: str = "",
    tag: str = "",
    skip_pow: bool = False,
) -> dict:
    """Edit a post or comment.

    Args:
        override_hash: The tx hash of the post/comment being edited.
        community:         Community (required for root posts, empty for comments).
        title:         New title (root posts only).
        content:       New content.
        target:        Parent post hash (for comments) or "" for root posts.
        tag:           Content tag.
        skip_pow:      True for subscribers.
    """
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_edit_raw(
        pub, _lb_bytes(lb), d, ts, target, community, title, content, tag, override_hash, None, nonce
    )
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "community": community,
        "protocol_version": 1,
        "title": title,
        "content": content,
        "tag": tag,
        "override": override_hash,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/edit", payload)
    return resp


def _do_delete(backend: str, wallet, target: str, skip_pow: bool = False) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_delete_raw(pub, _lb_bytes(lb), d, ts, target, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/delete_post", payload)
    return resp


def _do_delete_user(backend: str, wallet, target_addr: str, skip_pow: bool = False) -> Tuple[int, dict]:
    """Delete a user account. Returns (status_code, response_dict)."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_delete_user_raw(pub, _lb_bytes(lb), d, ts, target_addr, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target_addr,
    }
    payload["pow"] = int(proof)
    return _post(f"{backend}/api/core/delete_user", payload)


def _do_follow_user(backend: str, wallet, user_addr: str, follow: bool = True, skip_pow: bool = False) -> dict:
    """Follow or unfollow a user."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    canon_fn = _canon_base_follow_user_raw if follow else _canon_base_unfollow_user_raw
    endpoint = "follow_user" if follow else "unfollow_user"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, addr, user_addr, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "user": user_addr,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_follow_user_with_nonce(
    backend: str, wallet, user_addr: str, nonce: int, follow: bool = True, skip_pow: bool = False
) -> dict:
    """Follow/unfollow with a caller-supplied nonce (for duplicate-nonce failure tests)."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    d = 0 if skip_pow else diff
    canon_fn = _canon_base_follow_user_raw if follow else _canon_base_unfollow_user_raw
    endpoint = "follow_user" if follow else "unfollow_user"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, addr, user_addr, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "user": user_addr,
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_follow_topic(
    backend: str,
    wallet,
    community: str,
    follow: bool = True,
    skip_pow: bool = False,
    mode: int = 0,
    pinned_team_id: int = 0,
) -> dict:
    """Join or leave a community (legacy helper name used by existing tests).

    A join carries the lens the joiner was shown; the chain locks it in.
    """
    slug = (community or "").strip().lower()
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    endpoint = "join_community" if follow else "leave_community"

    if follow:
        base = _canon_base_join_community_raw(
            pub, _lb_bytes(lb), d, ts, slug, int(mode), int(pinned_team_id), nonce
        )
    else:
        base = _canon_base_leave_community_raw(pub, _lb_bytes(lb), d, ts, slug, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "community": slug,
    }
    if follow:
        payload["mode"] = int(mode)
        payload["pinned_team_id"] = int(pinned_team_id)
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_block(backend: str, wallet, target: str, block_type: str, block: bool = True, skip_pow: bool = False) -> dict:
    """Block or unblock a post/user. block_type is 'post' or 'user'."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    if block_type == "post":
        canon_fn = _canon_base_block_post_raw if block else _canon_base_unblock_post_raw
        endpoint = "block_post" if block else "unblock_post"
    else:
        canon_fn = _canon_base_block_user_raw if block else _canon_base_unblock_user_raw
        endpoint = "block_user" if block else "unblock_user"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, target, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_block_with_nonce(
    backend: str, wallet, target: str, block_type: str, nonce: int, block: bool = True, skip_pow: bool = False
) -> dict:
    """Block/unblock with a caller-supplied nonce (for duplicate-nonce failure tests)."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    d = 0 if skip_pow else diff

    if block_type == "post":
        canon_fn = _canon_base_block_post_raw if block else _canon_base_unblock_post_raw
        endpoint = "block_post" if block else "unblock_post"
    else:
        canon_fn = _canon_base_block_user_raw if block else _canon_base_unblock_user_raw
        endpoint = "block_user" if block else "unblock_user"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, target, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_block_topic(backend: str, wallet, community: str, block: bool = True, skip_pow: bool = False) -> dict:
    """Block or unblock a community (legacy helper name used by existing tests)."""
    slug = (community or "").strip().lower()
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    canon_fn = _canon_base_block_community_raw if block else _canon_base_unblock_community_raw
    endpoint = "block_community" if block else "unblock_community"

    base = canon_fn(pub, _lb_bytes(lb), d, ts, addr, slug, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "community": slug,
    }
    payload["pow"] = int(proof)
    print(f"    [debug] {endpoint} community={slug} difficulty={d}")
    _, resp = _post(f"{backend}/api/core/{endpoint}", payload)
    return resp


def _do_set_username_raw(
    backend: str,
    wallet,
    username: str,
    skip_pow: bool = False,
) -> dict:
    """Set username via the backend API (raw payload construction)."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_set_username_raw(pub, _lb_bytes(lb), d, ts, addr, username, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "username": username,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/set_username", payload)
    return resp


def _do_set_biography(backend: str, wallet, biography: str, skip_pow: bool = False) -> dict:
    """Set biography via the backend API."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_set_biography_raw(pub, _lb_bytes(lb), d, ts, addr, biography, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": addr,
        "biography": biography,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/set_biography", payload)
    return resp


def _do_report(backend: str, wallet, target: str, reason: str, skip_pow: bool = False) -> dict:
    """Report a post via the backend API."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_report_raw(pub, _lb_bytes(lb), d, ts, target, reason, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "reason": reason,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/report", payload)
    return resp


def _do_set_auto_renewal(backend: str, wallet, auto_renew: bool) -> dict:
    """Toggle auto-renewal for a subscriber."""
    addr = str(wallet.address())
    st = get_status(backend, address=addr)
    lb = str(st.get("last_block_hash", ""))
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()

    base = _canon_base_set_auto_renewal_raw(pub, _lb_bytes(lb), 0, ts, auto_renew, nonce)
    signed = canon_signed_with_pow(base, 0)
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "auto_renew": auto_renew,
    }
    code, resp = _post(f"{backend}/api/core/set_auto_renewal", payload)
    return resp


def _do_post_with_media(
    backend: str,
    wallet,
    community: str,
    title: str,
    content: str,
    media: list,
    target: str = "",
    tag: str = "",
    skip_pow: bool = False,
) -> str | None:
    """Create a post with media attachments; returns tx_hash or None."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff

    base = _canon_base_post_raw(pub, _lb_bytes(lb), d, ts, target, community, title, content, tag, 0, media, nonce)
    if skip_pow:
        proof = 0
    else:
        proof = compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "target": target,
        "community": community,
        "protocol_version": 1,
        "title": title,
        "content": content,
        "tag": tag,
        "media": media,
    }
    payload["pow"] = int(proof)
    code, resp = _post(f"{backend}/api/core/post", payload)
    txh = str((resp or {}).get("tx_hash", "") or "").lower()
    return txh if txh else None


def _wait_list_count(
    backend: str,
    address: str,
    list_key: str,
    expected: int,
    timeout: float = 30.0,
    *,
    at_most: bool = False,
) -> int:
    """Poll until a profile/followed list reaches expected count (or timeout).

    list_key: "followed_users", "joined_communities", "enabled_agents"
    By default waits until count >= expected (fill). With at_most=True waits
    until count <= expected (after unfollow/disable).
    Returns the actual count observed.
    """
    endpoint = (
        "get_user_followed" if list_key.startswith("followed_") or list_key == "joined_communities" else "get_profile"
    )
    deadline = time.perf_counter() + timeout
    actual = 0
    while time.perf_counter() < deadline:
        try:
            code, data = _get(f"{backend}/api/{endpoint}", {"address": address})
            if code == 200 and data:
                actual = len(data.get(list_key) or [])
                if at_most:
                    if actual <= expected:
                        return actual
                elif actual >= expected:
                    return actual
        except Exception:
            pass
        time.sleep(0.4)
    return actual


def _wait_indexed(backend: str, owner: str, tx_hash: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    """Wait until the indexer has recorded this post.

    Asks get_tx_status rather than scanning the author's feed. The feed scan
    used to request limit=100, which get_user_posts silently clamps to 50, so it
    answered "not indexed" for any post the author had since buried under 50
    newer ones. Every caller means "is it indexed yet", and this reads that
    directly instead of inferring it from one page of one ordering.
    """
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_tx_status", {"hash": h})
        if code == 200 and (data or {}).get("indexed") and data.get("success") is True:
            return True
        time.sleep(0.5)
    print(f"    [debug] _wait_indexed timeout owner={owner[:12]} tx={h[:16]}")
    return False


def _wait_tx_status(
    backend: str,
    tx_hash: str,
    expect_type: str | None = None,
    timeout: float = INDEX_TIMEOUT_SEC,
    require_details: bool = True,
) -> dict | None:
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_tx_status", {"hash": h})
        if code == 200 and data:
            if not data.get("found"):
                time.sleep(0.5)
                continue
            if expect_type and data.get("tx_type") != expect_type:
                time.sleep(0.5)
                continue
            if require_details:
                if data.get("indexed") and data.get("details"):
                    return data
            else:
                if data.get("indexed"):
                    return data
        time.sleep(0.5)
    return None

def _wait_tx_status_failure(
    backend: str,
    tx_hash: str,
    expect_type: str | None = None,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> dict | None:
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_tx_status", {"hash": h})
        if code == 200 and data:
            if not data.get("found"):
                time.sleep(0.5)
                continue
            if data.get("success") is True:
                time.sleep(0.5)
                continue
            if expect_type and data.get("tx_type") != expect_type:
                time.sleep(0.5)
                continue
            return data
        time.sleep(0.5)
    return None


def _wait_tx_deliver(
    tx_hash: str, timeout: float = INDEX_TIMEOUT_SEC, from_height: int | None = None
) -> tuple[int, str] | None:
    """Scan blocks for tx_hash and return (code, log) from DeliverTx."""
    if not tx_hash:
        return None
    h = tx_hash.strip().lower().removeprefix("0x")
    deadline = time.perf_counter() + timeout
    if from_height is not None:
        last_height = max(1, from_height - 1)
    else:
        try:
            last_height = max(1, _rpc_latest_height() - 1)
        except Exception:
            last_height = 1
    while time.perf_counter() < deadline:
        cur = _rpc_latest_height()
        for height in range(last_height + 1, cur + 1):
            block = requests.get(f"http://127.0.0.1:26657/block?height={height}", timeout=3).json()
            txs = block.get("result", {}).get("block", {}).get("data", {}).get("txs") or []
            tx_index = None
            for idx, tx_b64 in enumerate(txs):
                raw = base64.b64decode(tx_b64)
                if hashlib.sha256(raw).hexdigest().lower() == h:
                    tx_index = idx
                    break
            if tx_index is not None:
                while time.perf_counter() < deadline:
                    br = requests.get(f"http://127.0.0.1:26657/block_results?height={height}", timeout=3).json()
                    deliver = br.get("result", {}).get("txs_results") or []
                    if tx_index < len(deliver):
                        tx_result = deliver[tx_index]
                        code = int(tx_result.get("code", 0) or 0)
                        log = str(tx_result.get("log", "") or "")
                        return code, log
                    time.sleep(0.5)
                return None
        last_height = cur
        time.sleep(0.5)
    return None


def _wait_username(
    backend: str,
    address: str,
    timeout: float = INDEX_TIMEOUT_SEC,
    expected: str | None = None,
) -> str | None:
    """Wait until a username, or the requested username, is visible via get_profile."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            uname = get_username_from_address(backend, address)
            if uname and (expected is None or uname == expected):
                return uname
        except Exception:
            pass
        time.sleep(0.5)
    return None


def _wait_blocked_community_state(
    backend: str,
    address: str,
    community: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    community_lower = (community or "").strip().lower()
    while time.perf_counter() < deadline:
        # Check indexed DB first (fast, eventually consistent)
        code, data = _get(f"{backend}/api/get_user_blocked", {"address": address})
        if code == 200:
            blocked = (data or {}).get("blocked_communities") or (data or {}).get("blocked_communities") or []
            present = any(str(t or "").strip().lower() == community_lower for t in blocked)
            if present == expect_present:
                return True
        # Fall back to chain profile (authoritative, always current)
        code2, profile = _get(f"{backend}/api/get_profile", {"address": address})
        if code2 == 200:
            chain_blocked = (profile or {}).get("blocked_communities") or (profile or {}).get("blocked_communities") or []
            present2 = any(str(t or "").strip().lower() == community_lower for t in chain_blocked)
            if present2 == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_blocked_community(backend: str, address: str, community: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    return _wait_blocked_community_state(backend, address, community, True, timeout)


def _wait_followed_community(
    backend: str,
    address: str,
    community: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    community_lower = (community or "").strip().lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_user_followed", {"address": address})
        if code == 200:
            communities = (data or {}).get("joined_communities") or (data or {}).get("joined_communities") or []
            present = any(str(t or "").strip().lower() == community_lower for t in communities)
            if present == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_followed_user(
    backend: str,
    address: str,
    user: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    user_lower = (user or "").strip().lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_user_followed", {"address": address})
        if code == 200:
            users = (data or {}).get("followed_users") or (data or {}).get("users") or []
            present = any(user_lower in json.dumps(u).lower() for u in users)
            if present == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_blocked_user(
    backend: str,
    address: str,
    user: str,
    expect_present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    deadline = time.perf_counter() + timeout
    user_lower = (user or "").strip().lower()
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/get_user_blocked", {"address": address})
        if code == 200:
            blocked = (data or {}).get("blocked_users") or []
            present = any(str(u or "").strip().lower() == user_lower for u in blocked)
            if present == expect_present:
                return True
        time.sleep(0.5)
    return False


def _wait_comment_indexed(backend: str, parent: str, tx_hash: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    deadline = time.perf_counter() + timeout
    h = (tx_hash or "").lower()
    while time.perf_counter() < deadline:
        try:
            code, data = _get(f"{backend}/api/get_comments", {"post_id": parent, "limit": 100})
            if code == 200:
                children = (data or {}).get("children") or []
                if any(str(c.get("post_id", "")).lower() == h for c in children):
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _feed_has_post(backend: str, viewer_addr: str, post_id: str, timeout: float = INDEX_TIMEOUT_SEC) -> bool:
    """Check if a post appears in the newest feed for the given viewer."""
    deadline = time.perf_counter() + timeout
    pid = (post_id or "").lower()
    while time.perf_counter() < deadline:
        code, feed = _get(f"{backend}/api/get_posts", {"limit": 100, "by": "newest", "address": viewer_addr})
        if code == 200:
            posts = (feed or {}).get("posts") or []
            if any(str(p.get("post_id", "")).lower() == pid for p in posts):
                return True
        time.sleep(1)
    return False


def _feed_missing_post(backend: str, viewer_addr: str, post_id: str, timeout: float = 8.0) -> bool:
    """Confirm a post does NOT appear in the newest feed for the given viewer.

    Polls a few times to account for indexer lag.  Returns True when the post
    is consistently absent.
    """
    pid = (post_id or "").lower()
    checks = 0
    for _ in range(int(timeout)):
        code, feed = _get(f"{backend}/api/get_posts", {"limit": 100, "by": "newest", "address": viewer_addr})
        if code == 200:
            posts = (feed or {}).get("posts") or []
            if any(str(p.get("post_id", "")).lower() == pid for p in posts):
                return False
            checks += 1
            if checks >= 3:
                return True
        time.sleep(1)
    return checks >= 2


def _rpc_latest_height() -> int:
    r = requests.get("http://127.0.0.1:26657/status", timeout=2)
    if not r.ok:
        raise RuntimeError(f"rpc status failed: http={r.status_code}")
    data = r.json()
    return int(data["result"]["sync_info"]["latest_block_height"])


def _wait_next_block(timeout: float = 8.0) -> int:
    start = _rpc_latest_height()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        cur = _rpc_latest_height()
        if cur > start:
            return cur
        time.sleep(0.2)
    raise RuntimeError(f"timeout waiting for next block (start={start})")


def _do_create_curation_team(
    backend: str,
    wallet,
    community: str,
    name: str,
    description: str = "",
    skip_pow: bool = False,
) -> dict:
    """Create a curator team via the backend API; return response body."""
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    slug = (community or "").strip().lower()
    base = _canon_base_create_curation_team_raw(pub, _lb_bytes(lb), d, ts, slug, name, description, nonce)
    proof = 0 if skip_pow else compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "community": slug,
        "name": name,
        "description": description,
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/create_curation_team", payload)
    return resp or {}


def _do_set_curation_preference(
    backend: str,
    wallet,
    community: str,
    mode: int,
    pinned_team_id: int = 0,
    skip_pow: bool = False,
) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    slug = (community or "").strip().lower()
    base = _canon_base_set_curation_preference_raw(
        pub, _lb_bytes(lb), d, ts, slug, mode, pinned_team_id, nonce
    )
    proof = 0 if skip_pow else compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "community": slug,
        "mode": int(mode),
        "pinned_team_id": int(pinned_team_id),
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/set_curation_preference", payload)
    return resp or {}


def _do_set_curation_post_hidden(
    backend: str,
    wallet,
    community: str,
    team_id: int,
    target: str,
    hidden: bool = True,
    skip_pow: bool = False,
) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    slug = (community or "").strip().lower()
    base = _canon_base_set_curation_post_hidden_raw(
        pub, _lb_bytes(lb), d, ts, slug, team_id, target, hidden, nonce
    )
    proof = 0 if skip_pow else compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "community": slug,
        "team_id": int(team_id),
        "target": target,
        "hidden": bool(hidden),
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/set_curation_post_hidden", payload)
    return resp or {}


def _do_set_curation_user_hidden(
    backend: str,
    wallet,
    community: str,
    team_id: int,
    target: str,
    hidden: bool = True,
    skip_pow: bool = False,
) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    slug = (community or "").strip().lower()
    base = _canon_base_set_curation_user_hidden_raw(
        pub, _lb_bytes(lb), d, ts, slug, team_id, target, hidden, nonce
    )
    proof = 0 if skip_pow else compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "community": slug,
        "team_id": int(team_id),
        "target": target,
        "hidden": bool(hidden),
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/set_curation_user_hidden", payload)
    return resp or {}


def _do_set_curation_team_profile(
    backend: str,
    wallet,
    community: str,
    team_id: int,
    name: str,
    description: str = "",
    skip_pow: bool = False,
) -> dict:
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    slug = (community or "").strip().lower()
    base = _canon_base_set_curation_team_profile_raw(
        pub, _lb_bytes(lb), d, ts, slug, team_id, name, description, nonce
    )
    proof = 0 if skip_pow else compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "community": slug,
        "team_id": int(team_id),
        "name": name,
        "description": description,
    }
    payload["pow"] = int(proof)
    _, resp = _post(f"{backend}/api/core/set_curation_team_profile", payload)
    return resp or {}


def _do_curation_team_msg(
    backend: str,
    wallet,
    route: str,
    canon_fn,
    canon_args: tuple,
    payload_fields: dict,
    skip_pow: bool = False,
) -> dict:
    """POST one signed curation route.

    canon_args are the message payload fields in proto field-number order, and
    must be byte-identical to what the backend rebuilds from payload_fields —
    the signature covers the canonical bytes, so a lowercase mismatch on a slug
    or an address is rejected on chain rather than at the API.
    """
    addr = str(wallet.address())
    lb, diff, base_bits, pow_factor, _ = _fetch_params(backend, addr)
    pub = wallet.public_key().public_key_bytes
    ts = _now_ms()
    nonce = _fresh_nonce()
    d = 0 if skip_pow else diff
    base = canon_fn(pub, _lb_bytes(lb), d, ts, *canon_args, nonce=nonce)
    proof = 0 if skip_pow else compute_pow(base, diff, base_bits, pow_factor, lb)
    signed = canon_signed_with_pow(base, int(proof))
    sig = sign_canonical(wallet, signed)
    payload = {
        "pubkey": _b64(pub),
        "signature": _b64(sig),
        "last_block_hash": lb,
        "timestamp": ts,
        "envelope_nonce": str(nonce),
        "pow_difficulty": d,
        "pow": int(proof),
        **payload_fields,
    }
    _, resp = _post(f"{backend}{route}", payload)
    return resp or {}


def _do_invite_curator(
    backend: str, wallet, community: str, team_id: int, target: str, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    tgt = (target or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/invite_curator",
        _canon_base_invite_curator_raw,
        (slug, int(team_id), tgt),
        {"community": slug, "team_id": int(team_id), "target": tgt},
        skip_pow,
    )


def _do_revoke_curator_invite(
    backend: str, wallet, community: str, team_id: int, target: str, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    tgt = (target or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/revoke_curator_invite",
        _canon_base_revoke_curator_invite_raw,
        (slug, int(team_id), tgt),
        {"community": slug, "team_id": int(team_id), "target": tgt},
        skip_pow,
    )


def _do_accept_curator_invite(
    backend: str, wallet, community: str, team_id: int, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/accept_curator_invite",
        _canon_base_accept_curator_invite_raw,
        (slug, int(team_id)),
        {"community": slug, "team_id": int(team_id)},
        skip_pow,
    )


def _do_decline_curator_invite(
    backend: str, wallet, community: str, team_id: int, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/decline_curator_invite",
        _canon_base_decline_curator_invite_raw,
        (slug, int(team_id)),
        {"community": slug, "team_id": int(team_id)},
        skip_pow,
    )


def _do_leave_curation_team(
    backend: str, wallet, community: str, team_id: int, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/leave_curation_team",
        _canon_base_leave_curation_team_raw,
        (slug, int(team_id)),
        {"community": slug, "team_id": int(team_id)},
        skip_pow,
    )


def _do_remove_curator(
    backend: str, wallet, community: str, team_id: int, target: str, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    tgt = (target or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/remove_curator",
        _canon_base_remove_curator_raw,
        (slug, int(team_id), tgt),
        {"community": slug, "team_id": int(team_id), "target": tgt},
        skip_pow,
    )


def _do_transfer_curation_team(
    backend: str, wallet, community: str, team_id: int, new_owner: str, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    owner = (new_owner or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/transfer_curation_team",
        _canon_base_transfer_curation_team_raw,
        (slug, int(team_id), owner),
        {"community": slug, "team_id": int(team_id), "new_owner": owner},
        skip_pow,
    )


def _do_delete_curation_team(
    backend: str, wallet, community: str, team_id: int, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/delete_curation_team",
        _canon_base_delete_curation_team_raw,
        (slug, int(team_id)),
        {"community": slug, "team_id": int(team_id)},
        skip_pow,
    )


def _do_set_curation_thread_locked(
    backend: str,
    wallet,
    community: str,
    team_id: int,
    root_hash: str,
    locked: bool = True,
    skip_pow: bool = False,
) -> dict:
    slug = (community or "").strip().lower()
    root = (root_hash or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/set_curation_thread_locked",
        _canon_base_set_curation_thread_locked_raw,
        (slug, int(team_id), root, bool(locked)),
        {"community": slug, "team_id": int(team_id), "root_hash": root, "locked": bool(locked)},
        skip_pow,
    )


def _do_set_curation_subscriber_only(
    backend: str, wallet, community: str, team_id: int, enabled: bool = True, skip_pow: bool = False
) -> dict:
    slug = (community or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/set_curation_subscriber_only",
        _canon_base_set_curation_subscriber_only_raw,
        (slug, int(team_id), bool(enabled)),
        {"community": slug, "team_id": int(team_id), "enabled": bool(enabled)},
        skip_pow,
    )


def _do_set_curation_tag(
    backend: str, wallet, community: str, team_id: int, tag: str, skip_pow: bool = False
) -> dict:
    """The backend normalizes the tag before rebuilding the message, so callers
    must pass an already-canonical tag or the signature will not match."""
    slug = (community or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/set_curation_tag",
        _canon_base_set_curation_tag_raw,
        (slug, int(team_id), tag),
        {"community": slug, "team_id": int(team_id), "tag": tag},
        skip_pow,
    )


def _do_set_curation_post_tag(
    backend: str,
    wallet,
    community: str,
    team_id: int,
    target: str,
    tag: str = "",
    clear: bool = False,
    skip_pow: bool = False,
) -> dict:
    slug = (community or "").strip().lower()
    tgt = (target or "").strip().lower()
    return _do_curation_team_msg(
        backend,
        wallet,
        "/api/core/set_curation_post_tag",
        _canon_base_set_curation_post_tag_raw,
        (slug, int(team_id), tgt, tag, bool(clear)),
        {
            "community": slug,
            "team_id": int(team_id),
            "target": tgt,
            "tag": tag,
            "clear": bool(clear),
        },
        skip_pow,
    )


def _wait_team_member(
    backend: str,
    community: str,
    team_id: int,
    address: str,
    *,
    present: bool = True,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    """Poll team detail until address is (or is no longer) on the roster."""
    slug = (community or "").strip().lower()
    want = (address or "").strip().lower()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        code, detail = _get(f"{backend}/api/communities/{slug}/teams/{team_id}")
        if code == 200 and isinstance(detail, dict):
            members = {
                str(m.get("address") or "").lower() for m in (detail.get("members") or [])
            }
            if (want in members) is present:
                return True
        time.sleep(0.5)
    return False


def _wait_team_owner(
    backend: str,
    community: str,
    team_id: int,
    owner: str,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> bool:
    slug = (community or "").strip().lower()
    want = (owner or "").strip().lower()
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        code, detail = _get(f"{backend}/api/communities/{slug}/teams/{team_id}")
        if code == 200 and isinstance(detail, dict):
            if str(detail.get("owner") or "").lower() == want:
                return True
        time.sleep(0.5)
    return False


def _wait_curation_team(
    backend: str,
    community: str,
    *,
    owner: str | None = None,
    name: str | None = None,
    timeout: float = INDEX_TIMEOUT_SEC,
) -> dict | None:
    """Poll community teams until a matching live team appears."""
    slug = (community or "").strip().lower()
    owner_l = (owner or "").strip().lower() or None
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        code, data = _get(f"{backend}/api/communities/{slug}/teams")
        if code == 200 and isinstance(data, dict):
            for item in data.get("items") or []:
                if item.get("deleted"):
                    continue
                if owner_l and str(item.get("owner") or "").lower() != owner_l:
                    continue
                if name is not None and str(item.get("name") or "") != name:
                    continue
                return item
        time.sleep(0.5)
    return None

