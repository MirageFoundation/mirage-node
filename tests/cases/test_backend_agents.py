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
