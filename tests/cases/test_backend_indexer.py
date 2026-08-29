from __future__ import annotations

import base64
import json
import os
import re
import signal
import time
from urllib.parse import urlparse

from tests.common import (
    _pass,
    _fail,
    _skip,
    _debug,
    _get,
    _rand_str,
    _fresh_nonce,
    _docker_exec,
    _check_local_docker,
    WALLETS,
)


def _get_indexer_db_name() -> str:
    url = os.environ.get("INDEXER_DB_URL", "").strip()
    if url:
        return urlparse(url).path.lstrip("/")
    if _check_local_docker():
        code, out = _docker_exec("printenv INDEXER_DB_URL")
        if code == 0 and out:
            return urlparse(out.strip()).path.lstrip("/")
    return "mirage_indexer"


from tests.backend_helpers import (
    _do_send_tokens,
    _do_follow_user,
    _do_follow_user_with_nonce,
    _do_set_biography,
    _do_post,
    _do_vote,
    _do_edit,
    _wait_indexed,
    _wait_tx_deliver,
    _wait_tx_status,
    _wait_tx_status_failure,
    _wait_next_block,
)


def _topic_stats(owner: str, topic: str) -> tuple[int, int, int]:
    """Return (vote_count, net_votes, post_count) for one (owner, topic) row."""
    db_name = _get_indexer_db_name()
    rc, out = _docker_exec(
        f"""su - postgres -c "psql -d {db_name} -tAc \\"SELECT vote_count, net_votes, post_count
FROM user_topic_stats WHERE owner = LOWER('{owner}') AND topic = LOWER('{topic}');\\" 2>&1" """,
        timeout=15,
    )
    if rc != 0:
        raise RuntimeError(f"user_topic_stats query failed rc={rc} out={out}")
    line = out.strip()
    if not line:
        return (0, 0, 0)
    vote_count, net_votes, post_count = line.split("|")
    return (int(vote_count), int(net_votes), int(post_count))


def test_indexer_topic_edit(backend: str):
    """Editing a root post's topic must carry the thread's standing with it.

    `user_topic_stats` is applied as deltas but means "votes whose post is in this
    topic now", so before v1.34.0 a topic edit stranded every earlier delta —
    including the author's post-time auto-upvote — on the old topic forever. The
    comment is here because its own denormalised root_topic has to follow the root
    too, otherwise a vote on it stays counted against the original topic.
    """

    if not _check_local_docker():
        _skip("topic_edit.reattribution", "not running in local-docker")
        return

    author = WALLETS["sub1"]
    voter = WALLETS["sub2"]
    author_addr = str(author.address()).lower()
    voter_addr = str(voter.address()).lower()

    suffix = _rand_str(6).lower()
    old_topic = f"tea{suffix}"
    new_topic = f"teb{suffix}"

    root_hash = _do_post(backend, author, old_topic, f"Topic edit {suffix}", "reattribution probe", skip_pow=True)
    if not root_hash:
        _fail("topic_edit.setup", "root post was not accepted")
        return
    if not _wait_indexed(backend, author_addr, root_hash):
        _fail("topic_edit.setup", f"root post {root_hash[:12]} never indexed")
        return

    comment_hash = _do_post(backend, voter, "", "", "comment under the probe", target=root_hash, skip_pow=True)
    if not comment_hash or not _wait_indexed(backend, voter_addr, comment_hash):
        _fail("topic_edit.setup", "comment under the root post never indexed")
        return

    _do_vote(backend, voter, root_hash, 1, skip_pow=True)
    _do_vote(backend, author, comment_hash, 1, skip_pow=True)
    _wait_next_block()
    time.sleep(3)

    before_author = _topic_stats(author_addr, old_topic)
    before_voter = _topic_stats(voter_addr, old_topic)
    _debug(f"topic_edit: before edit {old_topic} author={before_author} voter={before_voter}")
    if before_author == (0, 0, 0) and before_voter == (0, 0, 0):
        _fail("topic_edit.setup", f"no standing recorded under {old_topic}; nothing to re-attribute")
        return

    edit = _do_edit(
        backend,
        author,
        root_hash,
        new_topic,
        f"Topic edit {suffix}",
        "reattribution probe",
        skip_pow=True,
    )
    edit_hash = str((edit or {}).get("tx_hash", "")).lower()
    delivered = _wait_tx_deliver(edit_hash) if edit_hash else None
    if not delivered or delivered[0] != 0:
        _fail("topic_edit.setup", f"topic edit was not delivered cleanly: {edit} result={delivered}")
        return
    _wait_next_block()
    time.sleep(3)

    after_old_author = _topic_stats(author_addr, old_topic)
    after_old_voter = _topic_stats(voter_addr, old_topic)
    after_new_author = _topic_stats(author_addr, new_topic)
    after_new_voter = _topic_stats(voter_addr, new_topic)
    _debug(
        f"topic_edit: after edit {old_topic} author={after_old_author} voter={after_old_voter} "
        f"| {new_topic} author={after_new_author} voter={after_new_voter}"
    )

    stranded = [
        f"{label}={stats}"
        for label, stats in (("author", after_old_author), ("voter", after_old_voter))
        if stats != (0, 0, 0)
    ]
    if stranded:
        _fail("topic_edit.old_topic_released", f"standing left on {old_topic}: {', '.join(stranded)}")
    else:
        _pass("topic_edit.old_topic_released")

    if after_new_author == before_author and after_new_voter == before_voter:
        _pass("topic_edit.new_topic_holds_standing")
    else:
        _fail(
            "topic_edit.new_topic_holds_standing",
            f"expected author={before_author} voter={before_voter}, "
            f"got author={after_new_author} voter={after_new_voter}",
        )

    # The whole thread must agree on the topic, or a vote on the comment keeps
    # being counted against the topic the root left behind.
    db_name = _get_indexer_db_name()
    rc, out = _docker_exec(
        f"""su - postgres -c "psql -d {db_name} -tAc \\"SELECT COALESCE(root_community, '')
FROM posts WHERE LOWER(txhash) = LOWER('{comment_hash}');\\" 2>&1" """,
        timeout=15,
    )
    comment_root_topic = out.strip().lower() if rc == 0 else f"query failed: {out}"
    if comment_root_topic == new_topic:
        _pass("topic_edit.comment_follows_root")
    else:
        _fail("topic_edit.comment_follows_root", f"comment root_topic={comment_root_topic!r}, expected {new_topic!r}")


def test_indexer(backend: str):
    """Verify the indexer-only backend architecture:
    all reads come from indexer DB (balances, profiles, params, blocks, supply).
    """

    _debug(f"indexer: begin backend={backend}")

    sub1 = WALLETS["sub1"]
    sub1_addr = str(sub1.address())
    sub2 = WALLETS["sub2"]
    sub2_addr = str(sub2.address())

    # ── Group 1: Balance reads ──────────────────────────────────────────

    # 1.1 balance in get_parameters
    code, params = _get(f"{backend}/api/get_parameters", {"address": sub1_addr})
    if code == 200 and "balance" in (params or {}):
        bal_p = int(params["balance"])
        if bal_p >= 0:
            _pass("indexer.balance_in_get_parameters", balance=bal_p)
        else:
            _fail("indexer.balance_in_get_parameters", f"negative balance={bal_p}")
    else:
        _fail("indexer.balance_in_get_parameters", f"code={code} keys={list((params or {}).keys())}")

    # 1.2 balance in get_user_status
    code, status = _get(f"{backend}/api/get_user_status", {"address": sub1_addr})
    if code == 200 and "balance" in (status or {}):
        bal_s = int(status["balance"])
        if bal_s >= 0:
            _pass("indexer.balance_in_get_user_status", balance=bal_s)
        else:
            _fail("indexer.balance_in_get_user_status", f"negative balance={bal_s}")
    else:
        _fail("indexer.balance_in_get_user_status", f"code={code} keys={list((status or {}).keys())}")

    # 1.3 balance in get_profile
    code, profile = _get(f"{backend}/api/get_profile", {"address": sub1_addr})
    if code == 200 and "balance" in (profile or {}):
        bal_pr = int(profile["balance"])
        if bal_pr >= 0:
            _pass("indexer.balance_in_get_profile", balance=bal_pr)
        else:
            _fail("indexer.balance_in_get_profile", f"negative balance={bal_pr}")
    else:
        _fail("indexer.balance_in_get_profile", f"code={code} keys={list((profile or {}).keys())}")

    # 1.4 balance consistency across endpoints
    try:
        if bal_p == bal_s == bal_pr:
            _pass("indexer.balance_consistency", balance=bal_p)
        else:
            _fail("indexer.balance_consistency", f"params={bal_p} status={bal_s} profile={bal_pr}")
    except NameError:
        _fail("indexer.balance_consistency", "could not compare (earlier fetch failed)")

    # 1.5 balance updates after token transfer
    code_pre, pre_data = _get(f"{backend}/api/get_user_status", {"address": sub2_addr})
    pre_bal = int((pre_data or {}).get("balance", 0)) if code_pre == 200 else None
    if pre_bal is not None:
        _debug(f"indexer.balance_after_transfer: send 1 to {sub2_addr[:12]}...")
        resp = _do_send_tokens(backend, sub1, sub2_addr, 1, skip_pow=True)
        txh = str(resp.get("tx_hash", "")).lower() if resp else ""
        if txh:
            deliver = _wait_tx_deliver(txh)
            if deliver is None:
                _fail("indexer.balance_after_transfer", "tx delivery not confirmed within timeout")
            else:
                code_deliver, log_deliver = deliver
                if code_deliver != 0:
                    _fail("indexer.balance_after_transfer", f"deliver code={code_deliver} log={log_deliver}")
                else:
                    deadline = time.time() + 15
                    post_bal = None
                    while time.time() < deadline:
                        code_post, post_data = _get(f"{backend}/api/get_user_status", {"address": sub2_addr})
                        post_bal = int((post_data or {}).get("balance", 0)) if code_post == 200 else None
                        if post_bal is not None and post_bal > pre_bal:
                            break
                        time.sleep(2)
                    if post_bal is not None and post_bal > pre_bal:
                        _pass("indexer.balance_after_transfer", before=pre_bal, after=post_bal)
                    else:
                        _fail("indexer.balance_after_transfer", f"before={pre_bal} after={post_bal}")
        else:
            _fail("indexer.balance_after_transfer", f"send failed: {resp}")
    else:
        _fail("indexer.balance_after_transfer", f"pre-balance fetch failed code={code_pre}")

    # ── Group 2: Profile fields from indexer ─────────────────────────────

    code, prof = _get(f"{backend}/api/get_profile", {"address": sub1_addr})
    if code != 200 or not prof:
        _fail("indexer.profile_has_reserve_funds", f"profile fetch failed code={code}")
    else:
        # 2.1 reserve_funds
        if "reserve_funds" in prof:
            rf = int(prof["reserve_funds"])
            if rf >= 0:
                _pass("indexer.profile_has_reserve_funds", reserve_funds=rf)
            else:
                _fail("indexer.profile_has_reserve_funds", f"negative reserve_funds={rf}")
        else:
            _fail("indexer.profile_has_reserve_funds", f"missing field, keys={list(prof.keys())}")

        # 2.2 subscription_expiry
        if "subscription_expiry" in prof:
            se = int(prof["subscription_expiry"])
            _pass("indexer.profile_has_subscription_expiry", subscription_expiry=se)
        else:
            _fail("indexer.profile_has_subscription_expiry", f"missing, keys={list(prof.keys())}")

        # 2.3 auto_renew
        if "auto_renew" in prof:
            _pass("indexer.profile_has_auto_renew", auto_renew=prof["auto_renew"])
        else:
            _fail("indexer.profile_has_auto_renew", f"missing, keys={list(prof.keys())}")

        # 2.4 biography
        if "biography" in prof:
            _pass("indexer.profile_has_biography_field", biography_len=len(str(prof["biography"])))
        else:
            _fail("indexer.profile_has_biography_field", f"missing, keys={list(prof.keys())}")

        # 2.5 created_at
        ca = prof.get("created_at")
        if ca is not None and int(ca) > 0:
            _pass("indexer.profile_has_created_at", created_at=ca)
        else:
            _fail("indexer.profile_has_created_at", f"created_at={ca}")

    # 2.6 reserve_funds in get_user_status
    code, st = _get(f"{backend}/api/get_user_status", {"address": sub1_addr})
    if code == 200 and "reserve_funds" in (st or {}):
        _pass("indexer.user_status_has_reserve_funds", reserve_funds=st["reserve_funds"])
    else:
        _fail("indexer.user_status_has_reserve_funds", f"code={code} keys={list((st or {}).keys())}")

    # ── Group 3: Chain params & config ───────────────────────────────────

    cfg_block_time = None
    code, cfg = _get(f"{backend}/api/get_chain_config")
    if code != 200 or not cfg:
        _fail("indexer.chain_config_has_tiers", f"fetch failed code={code}")
    else:
        # 3.1 tiers list
        tiers = cfg.get("tiers")
        if isinstance(tiers, list) and len(tiers) >= 2:
            _pass("indexer.chain_config_has_tiers", count=len(tiers))
        else:
            _fail(
                "indexer.chain_config_has_tiers",
                f"tiers={type(tiers).__name__} len={len(tiers) if isinstance(tiers, list) else 'N/A'}",
            )

        # 3.2 tier structure
        required_tier_fields = {"period_fee", "max_title_length", "vote_weight"}
        if isinstance(tiers, list) and tiers:
            t0 = tiers[0] if isinstance(tiers[0], dict) else {}
            present = required_tier_fields & set(t0.keys())
            if present == required_tier_fields:
                _pass("indexer.chain_config_tier_structure", fields=sorted(t0.keys()))
            else:
                _fail("indexer.chain_config_tier_structure", f"missing={required_tier_fields - present}")
        else:
            _fail("indexer.chain_config_tier_structure", "no tiers")

        # 3.3 subscription_period
        sp = cfg.get("subscription_period")
        if sp is not None and int(sp) > 0:
            _pass("indexer.chain_config_has_subscription_period", subscription_period=sp)
        else:
            _fail("indexer.chain_config_has_subscription_period", f"subscription_period={sp}")

        # 3.4 award_configs
        ac = cfg.get("award_configs")
        if isinstance(ac, (list, dict)) and ac:
            _pass("indexer.chain_config_has_award_configs", count=len(ac))
        else:
            _fail("indexer.chain_config_has_award_configs", f"award_configs={type(ac).__name__}")

        # 3.5 mint split is served from the backend's own parameter cache. This
        # catches a running backend that stayed on the pre-upgrade indexer row
        # even though direct chain queries already show the new field.
        try:
            floor = float(cfg["mint_floor_split"])
            dynamic = float(cfg["mint_dynamic_split"])
            if 0 <= floor <= 1 and 0 <= dynamic <= 1 and floor + dynamic <= 1:
                _pass("indexer.chain_config_mint_split", floor=floor, dynamic=dynamic)
            else:
                _fail("indexer.chain_config_mint_split", f"floor={floor} dynamic={dynamic}")
        except (KeyError, TypeError, ValueError) as e:
            _fail("indexer.chain_config_mint_split", str(e))

        # 3.6 chain_config block_time present
        bt = cfg.get("block_time")
        try:
            fbt = float(bt)
            if fbt > 0:
                cfg_block_time = fbt
                _pass("indexer.chain_config_block_time_positive", block_time=fbt)
            else:
                _fail("indexer.chain_config_block_time_positive", f"block_time={bt}")
        except Exception:
            _fail("indexer.chain_config_block_time_positive", f"block_time={bt}")

    # 3.7 params pow_base_bits present and in range
    if isinstance(params, dict) and params.get("pow_base_bits") is not None:
        pb = int(params.get("pow_base_bits") or 0)
        if 1 <= pb <= 256:
            _pass("indexer.params_pow_base_bits_present", pow_base_bits=pb)
        else:
            _fail("indexer.params_pow_base_bits_present", f"pow_base_bits={pb}")
    else:
        _fail(
            "indexer.params_pow_base_bits_present",
            f"pow_base_bits={params.get('pow_base_bits') if isinstance(params, dict) else None}",
        )

    # 3.8 chain_params in indexer DB contains both renamed proto keys and
    # legacy compatibility aliases (required by backend/frontend public API).
    if _check_local_docker():
        db_name = _get_indexer_db_name()
        rc_alias, out_alias = _docker_exec(
            f"""su - postgres -c "psql -d {db_name} -tAc \\"SELECT
((value ? 'min_difficulty')::int)::text || ',' ||
((value ? 'pow_base_bits')::int)::text || ',' ||
((value ? 'pow_message_limit')::int)::text || ',' ||
((value ? 'pow_increase_threshold')::int)::text || ',' ||
((value ? 'pow_difficulty_allowance')::int)::text || ',' ||
((value ? 'pow_difficulty_grace_period')::int)::text || ',' ||
((value ? 'pow_difficulty_step')::int)::text || ',' ||
((value ? 'pow_factor')::int)::text
FROM chain_stats
WHERE key='chain_params'
LIMIT 1;\\" 2>&1" """,
            timeout=10,
        )
        if rc_alias != 0:
            _fail("indexer.params_alias_contract", f"db query failed rc={rc_alias} out={out_alias}")
        else:
            raw = out_alias.strip()
            parts = [p.strip() for p in raw.split(",") if p.strip() != ""]
            if len(parts) != 8:
                _fail("indexer.params_alias_contract", f"unexpected query output: {raw}")
            elif all(p == "1" for p in parts):
                _pass("indexer.params_alias_contract")
            else:
                _fail("indexer.params_alias_contract", f"missing expected keys: {raw}")
    else:
        _skip("indexer.params_alias_contract", "not running in local-docker")

    # ── Group 4: Recent blocks & difficulty ──────────────────────────────

    pdata = params if isinstance(params, dict) else None
    if pdata:
        # 4.1 last_block_hash is 64-char hex
        lbh = str(pdata.get("last_block_hash", ""))
        if len(lbh) == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", lbh):
            _pass("indexer.params_has_last_block_hash", hash=lbh[:16] + "...")
        else:
            _fail("indexer.params_has_last_block_hash", f"len={len(lbh)} val={lbh[:32]}")

        # 4.2 pow_difficulty
        pd = pdata.get("pow_difficulty")
        if pd is not None and int(pd) >= 0:
            _pass("indexer.params_has_pow_difficulty", pow_difficulty=pd)
        else:
            _fail("indexer.params_has_pow_difficulty", f"pow_difficulty={pd}")

        # 4.3 pow_factor
        pf = pdata.get("pow_factor")
        try:
            fpf = float(pf)
            if 0 < fpf <= 1:
                _pass("indexer.params_has_pow_factor", pow_factor=fpf)
            else:
                _fail("indexer.params_has_pow_factor", f"out of range: {fpf}")
        except Exception:
            _fail("indexer.params_has_pow_factor", f"pow_factor={pf}")
    else:
        _fail("indexer.params_has_last_block_hash", "params fetch failed")
        _fail("indexer.params_has_pow_difficulty", "params fetch failed")
        _fail("indexer.params_has_pow_factor", "params fetch failed")

    # 4.4-4.8 network_stats
    code, ns = _get(f"{backend}/api/get_network_stats")
    if code == 200 and ns:
        ch = ns.get("current_height")
        if ch is not None and int(ch) > 0:
            _pass("indexer.network_stats_has_current_height", current_height=ch)
        else:
            _fail("indexer.network_stats_has_current_height", f"current_height={ch}")

        dh = ns.get("difficulty_history")
        if isinstance(dh, list):
            _pass("indexer.network_stats_has_difficulty_history", count=len(dh))
        else:
            _fail("indexer.network_stats_has_difficulty_history", f"type={type(dh).__name__}")

        sb = ns.get("staked_balance")
        if sb is not None and int(sb) >= 0:
            _pass("indexer.network_stats_has_staked_balance", staked_balance=sb)
        else:
            _fail("indexer.network_stats_has_staked_balance", f"staked_balance={sb}")

        svb = ns.get("server_balance")
        if svb is not None and int(svb) >= 0:
            _pass("indexer.network_stats_has_server_balance", server_balance=svb)
        else:
            _fail("indexer.network_stats_has_server_balance", f"server_balance={svb}")

        e24 = ns.get("earned_24h")
        s24 = ns.get("spent_24h")
        if e24 is not None and s24 is not None and int(e24) >= 0 and int(s24) >= 0:
            _pass("indexer.network_stats_has_earned_spent", earned_24h=e24, spent_24h=s24)
        else:
            _fail("indexer.network_stats_has_earned_spent", f"earned_24h={e24} spent_24h={s24}")
        # "burned" was the old name for money leaving the node, and it counted
        # every outgoing transfer, so a delegation showed up as tokens destroyed.
        if "burned_24h" in ns:
            _fail("indexer.network_stats_no_burned_24h", "get_network_stats still returns burned_24h")

        # 4.9 chain_config block_time consistency with network_stats
        ns_bt = ns.get("block_time")
        if cfg_block_time is not None and ns_bt is not None:
            try:
                f_ns_bt = float(ns_bt)
                if f_ns_bt > 0 and abs(f_ns_bt - cfg_block_time) <= 1.0:
                    _pass(
                        "indexer.chain_config_block_time_consistency",
                        chain_config=cfg_block_time,
                        network_stats=f_ns_bt,
                    )
                else:
                    _fail(
                        "indexer.chain_config_block_time_consistency",
                        f"chain_config={cfg_block_time} network_stats={f_ns_bt}",
                    )
            except Exception:
                _fail("indexer.chain_config_block_time_consistency", f"network_stats block_time={ns_bt}")
        else:
            _fail(
                "indexer.chain_config_block_time_consistency",
                f"chain_config={cfg_block_time} network_stats={ns_bt}",
            )
    else:
        _fail("indexer.network_stats_has_current_height", f"fetch failed code={code}")
        _fail("indexer.network_stats_has_difficulty_history", "skipped")
        _fail("indexer.network_stats_has_staked_balance", "skipped")
        _fail("indexer.network_stats_has_server_balance", "skipped")
        _fail("indexer.network_stats_has_earned_burned", "skipped")
        _fail("indexer.chain_config_block_time_consistency", "skipped")

    # ── Group 5: Supply endpoints ────────────────────────────────────────

    # 5.1 total_supply (plain-text endpoint, not JSON)
    total_supply = None
    try:
        code_ts, body_ts = _get(f"{backend}/api/get_total_supply")
        if code_ts == 200:
            total_supply = float(body_ts) if isinstance(body_ts, (int, float)) else float(str(body_ts).strip())
            if total_supply > 0:
                _pass("indexer.total_supply_positive", total_supply=total_supply)
            else:
                _fail("indexer.total_supply_positive", f"total_supply={total_supply}")
        else:
            _fail("indexer.total_supply_positive", f"code={code_ts}")
    except Exception as e:
        _fail("indexer.total_supply_positive", str(e))

    # 5.2 circulating_supply (plain-text endpoint, not JSON)
    circ_supply = None
    try:
        code_cs, body_cs = _get(f"{backend}/api/get_circulating_supply")
        if code_cs == 200:
            circ_supply = float(body_cs) if isinstance(body_cs, (int, float)) else float(str(body_cs).strip())
            if circ_supply > 0:
                _pass("indexer.circulating_supply_positive", circulating_supply=circ_supply)
            else:
                _fail("indexer.circulating_supply_positive", f"circulating_supply={circ_supply}")
        else:
            _fail("indexer.circulating_supply_positive", f"code={code_cs}")
    except Exception as e:
        _fail("indexer.circulating_supply_positive", str(e))

    # 5.3 circulating <= total
    if total_supply is not None and circ_supply is not None:
        if circ_supply <= total_supply + 0.01:
            _pass("indexer.circulating_lte_total", circulating=circ_supply, total=total_supply)
        else:
            _fail("indexer.circulating_lte_total", f"circulating={circ_supply} > total={total_supply}")
    else:
        _fail("indexer.circulating_lte_total", "could not compare (earlier fetch failed)")

    # 5.4 circulation_stats shape
    code, cstats = _get(f"{backend}/api/get_circulation_stats")
    if code == 200 and isinstance(cstats, dict):
        missing = {"total_supply", "top_accounts"} - set(cstats.keys())
        if missing:
            _fail("indexer.circulation_stats_shape", f"missing={sorted(missing)}")
        else:
            ts = cstats.get("total_supply")
            ta = cstats.get("top_accounts")
            if ts is None or float(ts) <= 0:
                _fail("indexer.circulation_stats_shape", f"total_supply={ts}")
            elif not isinstance(ta, list):
                _fail("indexer.circulation_stats_shape", f"top_accounts={type(ta).__name__}")
            elif len(ta) == 0:
                _fail("indexer.circulation_stats_shape", "top_accounts is empty")
            else:
                first = ta[0] if isinstance(ta[0], dict) else {}
                needed = {"address", "username", "balance"} - set(first.keys())
                if needed:
                    _fail("indexer.circulation_stats_shape", f"top_accounts missing={sorted(needed)}")
                else:
                    _pass("indexer.circulation_stats_shape", top_accounts=len(ta))
    else:
        _fail("indexer.circulation_stats_shape", f"code={code} type={type(cstats).__name__}")

    # 5.5 supply_history shape
    code, sh = _get(f"{backend}/api/get_supply_history")
    if code == 200 and isinstance(sh, dict) and "history" in sh and isinstance(sh.get("history"), list):
        history = sh.get("history") or []
        if len(history) == 0:
            _fail("indexer.supply_history_shape", "history is empty")
        else:
            first = history[0] if isinstance(history[0], dict) else {}
            needed = {"height", "total_supply", "timestamp"} - set(first.keys())
            if needed:
                _fail("indexer.supply_history_shape", f"history missing={sorted(needed)}")
            else:
                _pass("indexer.supply_history_shape", count=len(history))
    else:
        _fail("indexer.supply_history_shape", f"code={code} type={type(sh).__name__}")

    # ── Group 6: Indexer health ──────────────────────────────────────────

    # 6.1 endpoints are not returning 503 (indexer should be caught up)
    health_endpoints = [
        "/api/get_parameters",
        "/api/get_profile",
        "/api/get_network_stats",
        "/api/get_total_supply",
    ]
    all_ok = True
    for ep in health_endpoints:
        params = {"address": sub1_addr} if "profile" in ep or "status" in ep else {}
        c, _ = _get(f"{backend}{ep}", params)
        if c == 503:
            all_ok = False
            _debug(f"indexer.not_catching_up: 503 from {ep}")
            break
    if all_ok:
        _pass("indexer.not_catching_up")
    else:
        _fail("indexer.not_catching_up", "got 503 from at least one endpoint")

    # 6.2 node_config has validator_account_address
    code, nc = _get(f"{backend}/api/get_node_config")
    if code == 200 and (nc or {}).get("validator_account_address"):
        _pass("indexer.node_config_has_validator_address", addr=str(nc["validator_account_address"])[:20])
    else:
        _fail("indexer.node_config_has_validator_address", f"code={code} keys={list((nc or {}).keys())}")

    # 6.3 welcome_stats returns 200
    code, ws = _get(f"{backend}/api/get_welcome_stats")
    if code == 200:
        _pass("indexer.welcome_stats_shape")
    else:
        _fail("indexer.welcome_stats_shape", f"code={code}")

    _test_indexer_ws_reconnect_loop()


def _test_indexer_ws_reconnect_loop() -> None:
    _debug("indexer.ws_reconnect_loop: start")
    try:
        import indexer.main as indexer_main
    except Exception as e:
        _fail("indexer.ws_reconnect_loop.import", str(e))
        return

    class DummyWS:
        def __init__(self) -> None:
            self.sent: list[str] = []

        def send(self, msg: str) -> None:
            self.sent.append(msg)

    class FakeChain:
        def __init__(self, indexer) -> None:
            self.indexer = indexer
            self.run_count = 0
            self.open_count = 0
            self.close_count = 0
            self._on_open = None
            self._on_close = None

        def wait_for_rpc_ready(self) -> bool:
            return True

        def create_websocket_app(self, on_open, on_message, on_error, on_close):
            self._on_open = on_open
            self._on_close = on_close
            return DummyWS()

        def run_websocket_forever(self, ws, running: bool) -> None:
            self.run_count += 1
            try:
                if self._on_open:
                    self._on_open(ws)
                self.open_count += 1
            except Exception as e:
                _fail("indexer.ws_reconnect_loop.open", f"{type(e).__name__}: {e}")
                self.indexer.running = False
                return
            try:
                if self._on_close:
                    self._on_close(ws, 1000, "test-close")
                self.close_count += 1
            except Exception as e:
                _fail("indexer.ws_reconnect_loop.close", f"{type(e).__name__}: {e}")
                self.indexer.running = False
                return
            if self.run_count >= 3:
                self.indexer.running = False

    idx = indexer_main.Indexer.__new__(indexer_main.Indexer)
    idx.running = True
    idx.ws = None
    idx.chain = FakeChain(idx)

    prev_delay = indexer_main.WS_RECONNECT_DELAY
    indexer_main.WS_RECONNECT_DELAY = 0
    try:
        idx._run_websocket_loop()
    except Exception as e:
        _fail("indexer.ws_reconnect_loop", f"{type(e).__name__}: {e}")
    finally:
        indexer_main.WS_RECONNECT_DELAY = prev_delay

    runs = idx.chain.run_count
    closes = idx.chain.close_count
    if runs == 3 and closes == 3:
        _pass("indexer.ws_reconnect_loop", runs=runs, closes=closes)
    else:
        _fail("indexer.ws_reconnect_loop", f"runs={runs} closes={closes}")


class _StubEditDB:
    """Minimal DatabaseManager stand-in for driving MessageProcessor._handle_edit.

    Records every write so a test can assert that a rejected edit writes nothing.
    """

    def __init__(self, stored_owner: str):
        self._stored_owner = stored_owner
        self.writes: list[str] = []

    def get_post(self, txhash: str):
        # (topic, title, content, target, paid, thumbnail_url, created_at, media)
        return ("technology", "original title", "original content", "", True, None, 1000, None)

    def get_post_owner(self, txhash: str) -> str:
        return self._stored_owner

    def __getattr__(self, name: str):
        def _record(*_args, **_kwargs):
            self.writes.append(name)
            return None

        return _record


class _StubCurationDB:
    """Records the SQL process_curation_events issues, without a database."""

    def __init__(self):
        self.statements: list[tuple[str, tuple]] = []

    def _connect(self):
        return self

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        self.statements.append((" ".join(str(sql).split()), tuple(params)))

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def _edit_msg_bytes(pubkey: bytes, override: str) -> bytes:
    from shared.datatypes import MsgEdit

    msg = MsgEdit()
    msg.envelope_pubkey = pubkey
    msg.override = override
    msg.community = "technology"
    msg.title = "hijacked title"
    msg.content = "hijacked content"
    return msg.SerializeToString()


def test_indexer_hardening(backend: str):
    """Regression checks for the 2026-08-07 indexer review remediation.

    Mostly unit-style so it runs without a provisioned chain; the checks that need
    real indexer rows are gated on local docker and skip cleanly otherwise.
    """

    _debug(f"indexer_hardening: begin backend={backend}")

    import indexer.main as indexer_main
    import indexer.message_processor as mp_module
    import indexer.settings as indexer_settings
    from indexer.address_utils import addr_from_pubkey, derive_owner_from_dict
    from indexer.database import DatabaseManager, format_db_target
    from indexer.message_processor import MessageProcessor, _vote_direction

    # ── M-6: the database URL must never be logged with credentials ──────

    redacted = format_db_target("postgresql://indexer_rw:s3kr3t@127.0.0.1:5432/mirage_indexer")
    if redacted == "127.0.0.1:5432/mirage_indexer" and "s3kr3t" not in redacted and "@" not in redacted:
        _pass("indexer_hardening.db_target_redacted", target=redacted)
    else:
        _fail("indexer_hardening.db_target_redacted", f"got {redacted!r}")

    if format_db_target("postgresql://u:p@db.internal/mirage_indexer") == "db.internal:5432/mirage_indexer":
        _pass("indexer_hardening.db_target_default_port")
    else:
        _fail(
            "indexer_hardening.db_target_default_port", format_db_target("postgresql://u:p@db.internal/mirage_indexer")
        )

    try:
        format_db_target("mirage_indexer")
        _fail("indexer_hardening.db_target_fails_hard", "unparseable URL did not raise")
    except RuntimeError:
        _pass("indexer_hardening.db_target_fails_hard")

    # ── L-1: width/height metadata survives insert ───────────────────────

    meta = DatabaseManager._extract_media_meta(
        [
            "https://cdn.example.com/a.jpg?w=640&h=480",
            "https://cdn.example.com/b.jpg",
            "https://cdn.example.com/c.jpg?w=0&h=480",
            "https://cdn.example.com/d.jpg?w=abc&h=480",
            "https://cdn.example.com/e.jpg?w=99999&h=480",
        ]
    )
    if meta == [{"w": 640, "h": 480}, {}, {}, {}, {}]:
        _pass("indexer_hardening.media_meta_extraction", meta=meta)
    else:
        _fail("indexer_hardening.media_meta_extraction", f"got {meta}")

    if DatabaseManager._sanitize_wh(1, 10000) == {"w": 1, "h": 10000} and DatabaseManager._sanitize_wh(0, 5) == {}:
        _pass("indexer_hardening.sanitize_wh_bounds")
    else:
        _fail("indexer_hardening.sanitize_wh_bounds", "bounds check wrong")

    # ── Membership must be projected from events, not just from messages ─
    #
    # Accepting a curator invite auto-joins the community, and the gov curator /
    # preference messages execute at EndBlock. None of those arrive as a
    # MsgJoinCommunity, so a member-message-only projection leaves the chain
    # saying "joined" while the API says otherwise.

    membership_db = _StubCurationDB()
    membership_proc = MessageProcessor(membership_db, None, lambda *a, **k: None, lambda t: "")
    membership_proc.process_curation_events(
        [
            {
                "type": "community_joined",
                "attributes": [
                    {"key": "address", "value": "mirage1joiner"},
                    {"key": "community", "value": "photography"},
                ],
            },
            {
                "type": "community_left",
                "attributes": [
                    {"key": "address", "value": "mirage1leaver"},
                    {"key": "community", "value": "photography"},
                ],
            },
        ],
        4242,
    )
    joined_sql = [s for s, p in membership_db.statements if "INSERT INTO community_curation_preferences" in s]
    left_sql = [s for s, p in membership_db.statements if "DELETE FROM community_curation_preferences" in s]
    joined_params = [p for s, p in membership_db.statements if "INSERT INTO community_curation_preferences" in s]
    if len(joined_sql) == 1 and len(left_sql) == 1 and joined_params[0] == ("mirage1joiner", "photography", 4242):
        _pass("indexer_hardening.membership_from_events", statements=len(membership_db.statements))
    else:
        _fail(
            "indexer_hardening.membership_from_events",
            f"joined={len(joined_sql)} left={len(left_sql)} statements={membership_db.statements}",
        )

    missing_addr = _StubCurationDB()
    try:
        MessageProcessor(missing_addr, None, lambda *a, **k: None, lambda t: "").process_curation_events(
            [{"type": "community_joined", "attributes": [{"key": "community", "value": "photography"}]}],
            4243,
        )
        _fail("indexer_hardening.membership_event_fails_hard", "community_joined without address was accepted")
    except RuntimeError:
        _pass("indexer_hardening.membership_event_fails_hard")

    # ── A curator's empty tag is a decision; only `cleared` removes the row ──
    #
    # If the projection treated tag='' as "no override" the whole precedence
    # chain would collapse: the community tag would leak back onto a post a
    # curator deliberately marked untagged.

    def _post_tag_event(tag: str, cleared: bool) -> dict:
        return {
            "type": "curation_post_tag_changed",
            "attributes": [
                {"key": "community", "value": "photography"},
                {"key": "team_id", "value": "3"},
                {"key": "target", "value": "abc123"},
                {"key": "tag", "value": tag},
                {"key": "cleared", "value": "true" if cleared else "false"},
                {"key": "actor", "value": "mirage1curator"},
            ],
        }

    tag_db = _StubCurationDB()
    MessageProcessor(tag_db, None, lambda *a, **k: None, lambda t: "").process_curation_events(
        [_post_tag_event("gore", False), _post_tag_event("", False), _post_tag_event("", True)],
        4244,
    )
    inserts = [p for s, p in tag_db.statements if "INSERT INTO curation_post_tags" in s]
    deletes = [p for s, p in tag_db.statements if "DELETE FROM curation_post_tags" in s]
    if (
        len(inserts) == 2
        and len(deletes) == 1
        and inserts[0] == ("photography", 3, "abc123", "gore", "mirage1curator", 4244)
        and inserts[1] == ("photography", 3, "abc123", "", "mirage1curator", 4244)
        and deletes[0] == ("photography", 3, "abc123")
    ):
        _pass("indexer_hardening.post_tag_projection", inserts=len(inserts), deletes=len(deletes))
    else:
        _fail(
            "indexer_hardening.post_tag_projection",
            f"inserts={inserts} deletes={deletes}",
        )

    missing_cleared = _StubCurationDB()
    try:
        MessageProcessor(missing_cleared, None, lambda *a, **k: None, lambda t: "").process_curation_events(
            [
                {
                    "type": "curation_post_tag_changed",
                    "attributes": [
                        {"key": "community", "value": "photography"},
                        {"key": "team_id", "value": "3"},
                        {"key": "target", "value": "abc123"},
                    ],
                }
            ],
            4245,
        )
        _fail("indexer_hardening.post_tag_event_fails_hard", "event without cleared was accepted")
    except RuntimeError:
        _pass("indexer_hardening.post_tag_event_fails_hard")

    # ── Every relayable message must be one this indexer build knows ─────
    #
    # A message the chain relays but process_core_message has no branch for
    # falls through to the unhandled_message_type error, which tells an
    # operator to upgrade the indexer and replay the height, and skips the
    # relay-quota refresh so a paid user's remaining quota goes stale. That
    # is exactly what happened to the two v1.39 tag messages: the curation
    # projection runs off block events so the data still landed, and nothing
    # else noticed. Deriving the expected set from relay_messages.go means
    # the next relayable message cannot be added without teaching the indexer.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    relay_go = os.path.join(repo_root, "blockchain", "app", "relay_messages.go")
    processor_py = os.path.join(repo_root, "indexer", "message_processor.py")
    if not (os.path.exists(relay_go) and os.path.exists(processor_py)):
        _skip("indexer_hardening.relay_types_known", "chain or indexer source not in this image")
    else:
        with open(relay_go, encoding="utf-8") as fh:
            relay_src = fh.read()
        prototypes = relay_src[relay_src.index("relayMessagePrototypes") :]
        relayable = set(re.findall(r"&coretypes\.(Msg[A-Za-z]+)\{\}", prototypes))
        with open(processor_py, encoding="utf-8") as fh:
            processor_src = fh.read()
        unknown = sorted(
            name for name in relayable if f'"/mirage.core.v1.{name}"' not in processor_src
        )
        if not relayable:
            _fail("indexer_hardening.relay_types_known", "could not parse relay_messages.go")
        elif unknown:
            _fail(
                "indexer_hardening.relay_types_known",
                f"{len(unknown)} relayable types the indexer cannot decode: {', '.join(unknown)}",
            )
        else:
            _pass("indexer_hardening.relay_types_known", checked=len(relayable))

    # ── H-5: thumbnails are derived offline and deterministically ────────

    proc = MessageProcessor(None, None, lambda *a, **k: None, lambda t: "")
    thumb_cases = [
        (
            "watch https://www.youtube.com/watch?v=dQw4w9WgXcQ now",
            "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        ),
        ("https://youtu.be/dQw4w9WgXcQ", "https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg"),
        (
            "https://vz-abc123.b-cdn.net/9f1e2d3c/playlist.m3u8",
            "https://vz-abc123.b-cdn.net/9f1e2d3c/thumbnail.jpg",
        ),
        (
            "https://videodelivery.net/abc123def/manifest/video.m3u8",
            "https://videodelivery.net/abc123def/thumbnails/thumbnail.jpg?time=1s",
        ),
        ("https://cdn.example.com/pic.png", "https://cdn.example.com/pic.png"),
        ("https://news.example.com/some-article", None),
        ("no url at all here", None),
        ("ftp://example.com/pic.png", None),
        # Nested markdown links: the URL regex runs through the "]", leaving an
        # authority urlsplit reads as a broken IPv6 literal. This exact content
        # halted the live indexer at height 6754167 — the block is on chain, so
        # an unhandled raise here stops every node at the same height forever.
        ("[link [text](https://)](https://)https://youtu.be/Wz_s1_D2-xQ", None),
        ("https://exa]mple.com/pic.png", None),
        ("https://[example.com/pic.png", None),
    ]
    bad_thumbs = []
    for content, expected in thumb_cases:
        got = proc.discover_post_thumbnail(content)
        again = proc.discover_post_thumbnail(content)
        if got != expected:
            bad_thumbs.append(f"{content!r} -> {got!r} (want {expected!r})")
        elif got != again:
            bad_thumbs.append(f"{content!r} not deterministic: {got!r} then {again!r}")
    if bad_thumbs:
        _fail("indexer_hardening.thumbnail_deterministic", "; ".join(bad_thumbs))
    else:
        _pass("indexer_hardening.thumbnail_deterministic", cases=len(thumb_cases))

    # ── No derivation over untrusted content may ever raise ──────────────
    #
    # On 2026-08-11 one post halted indexing on every node at height 6754167:
    # urlsplit raised on a nested markdown link and the exception escaped
    # discover_post_thumbnail. The block is on chain, so every node replays it
    # and dies at the same height — a permanent, network-wide DoS for the cost
    # of a single post. Enumerating known-bad URLs is not enough; the property
    # under test is that NOTHING derived from post content can throw.

    hostile = [
        # The live payload that caused the outage, plus the shapes around it.
        "[link [text](https://)](https://)https://youtu.be/Wz_s1_D2-xQ",
        "[a](https://)[b](https://)https://x.com/y",
        "https://",
        "https://[",
        "https://]",
        "https://[/",
        "https://a]b.com/pic.png",
        "https://[a.com/pic.png",
        "https://[[]]/pic.png",
        "https://user@[v1.fe80::a]/pic.png",
        # Ports and authorities urlsplit validates lazily.
        "https://[::1]:notaport/pic.png",
        "https://example.com:99999999/pic.png",
        "https://example.com:-1/pic.png",
        # Control characters and encoding tricks.
        "https://exa\x00mple.com/pic.png",
        "https://exam\nple.com/pic.png",
        "https://ex\tample.com/pic.png",
        "https://%00%01%02.com/pic.png",
        "https://xn--/pic.png",
        "https://\u0001\u0002.com/pic.gif",
        # Unicode / IDNA / bidi.
        "https://\u202eexample.com/pic.png",
        "https://ex\u0430mple.com/pic.png",
        "https://😀.example.com/pic.gif",
        # Size and repetition.
        "https://" + "a" * 5000 + ".com/pic.png",
        "https://example.com/" + "../" * 2000 + "pic.png",
        "https://" + "[" * 500 + "example.com/pic.png",
        "https://example.com/?" + "w=1&" * 5000,
        # Scheme confusion.
        "https:///pic.png",
        "https://:@/pic.png",
        "https://@@@/pic.png",
        "HTTPS://EXAMPLE.COM/PIC.PNG",
        # Empty-ish inputs.
        "",
        " ",
        "\x00",
        "@" * 1000,
        "`" * 1000,
        "```" + "@user " * 1000,
    ]

    derive_failures = []
    for payload in hostile:
        try:
            proc.discover_post_thumbnail(payload)
        except Exception as exc:
            derive_failures.append(f"thumbnail({payload[:40]!r}): {type(exc).__name__}: {exc}")
        try:
            mp_module._parse_mentions(payload)
        except Exception as exc:
            derive_failures.append(f"mentions({payload[:40]!r}): {type(exc).__name__}: {exc}")
        try:
            DatabaseManager._extract_media_meta([payload])
        except Exception as exc:
            derive_failures.append(f"media_meta({payload[:40]!r}): {type(exc).__name__}: {exc}")

    if derive_failures:
        _fail("indexer_hardening.untrusted_derivation_never_raises", "; ".join(derive_failures[:5]))
    else:
        _pass("indexer_hardening.untrusted_derivation_never_raises", payloads=len(hostile))

    # The chokepoint itself must swallow and log, so a derivation added later
    # is safe by construction as long as it is routed through it.
    def _boom(_):
        raise ValueError("derivation exploded")

    try:
        swallowed = mp_module.derive_from_content("test", _boom, "x", default="fallback-marker")
        if swallowed == "fallback-marker":
            _pass("indexer_hardening.derive_chokepoint_swallows")
        else:
            _fail("indexer_hardening.derive_chokepoint_swallows", f"returned {swallowed!r}")
    except Exception as exc:
        _fail("indexer_hardening.derive_chokepoint_swallows", f"raised {type(exc).__name__}: {exc}")

    # The point of H-5 is that no fetch happens at all, so assert the capability
    # is absent rather than trying to observe a request that should never occur.
    leaked_modules = [
        n for n in ("requests", "socket", "ipaddress", "httpx", "BeautifulSoup", "Image") if hasattr(mp_module, n)
    ]
    leaked_helpers = [
        n
        for n in (
            "_fetch_html",
            "_probe_dimensions",
            "_probe_media_dimensions",
            "discover_media_dimensions",
            "_extract_html_meta_dimensions",
            "_is_public_http_url",
        )
        if hasattr(MessageProcessor, n)
    ]
    if leaked_modules or leaked_helpers:
        _fail(
            "indexer_hardening.no_remote_media",
            f"modules={leaked_modules} helpers={leaked_helpers}",
        )
    else:
        _pass("indexer_hardening.no_remote_media")

    # ── H-4: proposal Any extraction handles gov v1 and v1beta1 ──────────

    class _Any:
        def __init__(self, type_url: str):
            self.type_url = type_url
            self.value = b"\x00"

    class _V1:
        messages = [_Any("/mirage.core.v1.MsgUpdateParams"), _Any("/mirage.core.v1.MsgSetLevel")]

    class _V1Beta1:
        content = _Any("/mirage.core.v1.MsgUpdateParams")

    class _EmptyContent:
        content = _Any("")

    class _Neither:
        pass

    extraction_ok = (
        len(MessageProcessor.extract_inner_anys(_V1())) == 2
        and len(MessageProcessor.extract_inner_anys(_V1Beta1())) == 1
        and MessageProcessor.extract_inner_anys(_EmptyContent()) == []
        and MessageProcessor.extract_inner_anys(_Neither()) == []
    )
    if extraction_ok:
        _pass("indexer_hardening.extract_inner_anys")
    else:
        _fail("indexer_hardening.extract_inner_anys", "v1/v1beta1/empty handling wrong")

    # ── I-1: envelope signer beats an unsigned owner field ───────────────

    pubkey = bytes([2]) + bytes(range(32))
    envelope_addr = addr_from_pubkey(pubkey)
    pub_b64 = base64.b64encode(pubkey).decode("ascii")
    if not envelope_addr:
        _fail("indexer_hardening.derive_owner_envelope_first", "could not derive test address")
    else:
        derived = derive_owner_from_dict(
            {"envelope_pubkey": pub_b64, "owner": "mirage1attacker", "authority": "mirage1relay"}
        )
        if derived == envelope_addr:
            _pass("indexer_hardening.derive_owner_envelope_first", owner=envelope_addr[:16])
        else:
            _fail("indexer_hardening.derive_owner_envelope_first", f"got {derived!r} want {envelope_addr!r}")

    fallbacks_ok = (
        derive_owner_from_dict({"owner": "Mirage1Owner"}) == "mirage1owner"
        and derive_owner_from_dict({"authority": "Mirage1Gov"}) == "mirage1gov"
    )
    try:
        derive_owner_from_dict({})
        raised = False
    except RuntimeError:
        raised = True
    if fallbacks_ok and raised:
        _pass("indexer_hardening.derive_owner_fallbacks")
    else:
        _fail("indexer_hardening.derive_owner_fallbacks", f"fallbacks_ok={fallbacks_ok} raised={raised}")

    # ── I-1: a foreign edit must not touch indexed content ───────────────

    override = "a" * 64
    if envelope_addr:
        foreign_db = _StubEditDB(stored_owner="mirage1someoneelse")
        foreign_proc = MessageProcessor(foreign_db, None, lambda *a, **k: None, lambda t: "")
        foreign_proc._handle_edit("/mirage.core.v1.MsgEdit", _edit_msg_bytes(pubkey, override), "b" * 64, 1234, 99)
        if foreign_db.writes:
            _fail("indexer_hardening.foreign_edit_rejected", f"wrote {sorted(set(foreign_db.writes))}")
        else:
            _pass("indexer_hardening.foreign_edit_rejected")

        # Control: the real owner's edit must still be applied, otherwise the
        # rejection above would pass for the wrong reason.
        own_db = _StubEditDB(stored_owner=envelope_addr)
        own_proc = MessageProcessor(own_db, None, lambda *a, **k: None, lambda t: "")
        own_proc._handle_edit("/mirage.core.v1.MsgEdit", _edit_msg_bytes(pubkey, override), "c" * 64, 1234, 99)
        if "upsert_post" in own_db.writes:
            _pass("indexer_hardening.owner_edit_applied")
        else:
            _fail("indexer_hardening.owner_edit_applied", f"wrote {sorted(set(own_db.writes))}")
    else:
        _skip("indexer_hardening.foreign_edit_rejected", "could not derive test address")
        _skip("indexer_hardening.owner_edit_applied", "could not derive test address")

    # ── M-7: a message the chain accepted must never be able to halt a node ──
    #
    # The chain only checks that a vote target is well-formed hex, and does not
    # constrain direction at all, so both reach the indexer with code=0. If either
    # raised, the block could never be projected and every indexer on the network
    # would stop at that height — a one-transaction kill switch.

    class _NoTargetDB(_StubEditDB):
        def get_post(self, txhash: str):
            return None

        def post_exists(self, txhash: str) -> bool:
            return False

    if envelope_addr:
        from shared.datatypes import MsgVote

        def _vote_bytes(target: str, direction: int) -> bytes:
            msg = MsgVote()
            msg.envelope_pubkey = pubkey
            msg.target = target
            msg.direction = direction
            return msg.SerializeToString()

        missing_db = _NoTargetDB(stored_owner=envelope_addr)
        missing_proc = MessageProcessor(missing_db, None, lambda *a, **k: None, lambda t: "")
        try:
            missing_proc._handle_vote("/mirage.core.v1.MsgVote", _vote_bytes("b" * 64, 1), "e" * 64, 1234, 99)
            if missing_db.writes:
                _fail("indexer_hardening.vote_missing_target_skipped", f"wrote {sorted(set(missing_db.writes))}")
            else:
                _pass("indexer_hardening.vote_missing_target_skipped")
        except Exception as e:
            _fail("indexer_hardening.vote_missing_target_skipped", f"raised {type(e).__name__}: {e}")

        bad_dir_db = _StubEditDB(stored_owner=envelope_addr)
        bad_dir_proc = MessageProcessor(bad_dir_db, None, lambda *a, **k: None, lambda t: "")
        try:
            bad_dir_proc._handle_vote("/mirage.core.v1.MsgVote", _vote_bytes("a" * 64, 7), "f" * 64, 1234, 99)
            _pass("indexer_hardening.vote_bad_direction_skipped")
        except Exception as e:
            _fail("indexer_hardening.vote_bad_direction_skipped", f"raised {type(e).__name__}: {e}")

        missing_edit_db = _NoTargetDB(stored_owner=envelope_addr)
        missing_edit_proc = MessageProcessor(missing_edit_db, None, lambda *a, **k: None, lambda t: "")
        try:
            missing_edit_proc._handle_edit(
                "/mirage.core.v1.MsgEdit", _edit_msg_bytes(pubkey, "b" * 64), "0" * 64, 1234, 99
            )
            if missing_edit_db.writes:
                _fail("indexer_hardening.edit_missing_override_skipped", f"wrote {sorted(set(missing_edit_db.writes))}")
            else:
                _pass("indexer_hardening.edit_missing_override_skipped")
        except Exception as e:
            _fail("indexer_hardening.edit_missing_override_skipped", f"raised {type(e).__name__}: {e}")
    else:
        _skip("indexer_hardening.vote_missing_target_skipped", "could not derive test address")
        _skip("indexer_hardening.vote_bad_direction_skipped", "could not derive test address")
        _skip("indexer_hardening.edit_missing_override_skipped", "could not derive test address")

    # ── H-1: the checkpoint may only be written inside a block txn ───────

    bare_db = DatabaseManager.__new__(DatabaseManager)
    try:
        bare_db.set_checkpoint(10, "d" * 64, "mirage-local")
        _fail("indexer_hardening.checkpoint_requires_txn", "set_checkpoint ran outside a transaction")
    except RuntimeError:
        _pass("indexer_hardening.checkpoint_requires_txn")

    # ── M-8: the stats writer takes a delta, not a raw direction ─────────

    import inspect

    stats_params = inspect.signature(DatabaseManager.update_user_topic_stats).parameters
    if "net_votes_delta" in stats_params and "direction" not in stats_params:
        _pass("indexer_hardening.net_votes_delta_signature")
    else:
        _fail("indexer_hardening.net_votes_delta_signature", f"params={list(stats_params)}")

    direction_cases = {1.0: 1, 0.15: 1, -1.0: -1, -0.15: -1, 0.0: 0, None: 0}
    bad_dirs = {k: _vote_direction(k) for k, v in direction_cases.items() if _vote_direction(k) != v}
    if bad_dirs:
        _fail("indexer_hardening.vote_direction_normalized", f"wrong: {bad_dirs}")
    else:
        # Same arithmetic the handler applies: delta = new - previous.
        transitions = {(0, 1): 1, (1, 1): 0, (1, -1): -2, (-1, 0): 1, (-1, 1): 2}
        bad_tr = {k: v for k, v in transitions.items() if (k[1] - k[0]) != v}
        if bad_tr:
            _fail("indexer_hardening.vote_direction_normalized", f"delta table wrong: {bad_tr}")
        else:
            _pass("indexer_hardening.vote_direction_normalized")

    # ── M-1: history gaps are normalized, merged, and validated ──────────

    merge = indexer_main.Indexer._merge_history_gaps
    merged = merge(
        [
            {"start": 10, "end": 20, "reason": "pruned"},
            {"start": 21, "end": 30, "reason": "pruned"},
            {"start": 40, "end": 50, "reason": "height_override"},
            {"start": 1, "end": 5, "reason": "pruned"},
        ]
    )
    expected_merge = [
        {"start": 1, "end": 5, "reason": "pruned"},
        {"start": 10, "end": 30, "reason": "pruned"},
        {"start": 40, "end": 50, "reason": "height_override"},
    ]
    if merged == expected_merge:
        _pass("indexer_hardening.history_gap_merge", gaps=len(merged))
    else:
        _fail("indexer_hardening.history_gap_merge", f"got {merged}")

    cross = merge(
        [
            {"start": 10, "end": 20, "reason": "pruned_before_verification"},
            {"start": 11, "end": 25, "reason": "checkpoint_behind_pruning_window"},
        ]
    )
    if (
        len(cross) == 1
        and cross[0]["start"] == 10
        and cross[0]["end"] == 25
        and "pruned_before_verification" in cross[0]["reason"]
        and "checkpoint_behind_pruning_window" in cross[0]["reason"]
    ):
        _pass("indexer_hardening.history_gap_merge_cross_reason")
    else:
        _fail("indexer_hardening.history_gap_merge_cross_reason", f"got {cross}")

    try:
        merge([{"start": 10, "end": 5, "reason": "pruned"}])
        _fail("indexer_hardening.history_gap_validation", "inverted range did not raise")
    except RuntimeError:
        _pass("indexer_hardening.history_gap_validation")

    # ── H-2: continuity adopts node-confirmed provenance, refuses the rest ────

    class _ContinuityDB:
        def __init__(self, meta, height, recent):
            self.meta = dict(meta)
            self.height = height
            self.recent = dict(recent)

        def get_meta(self, key):
            return self.meta.get(key)

        def set_meta(self, key, value):
            self.meta[key] = value

        def get_last_height(self):
            return self.height

        def get_recent_block_hashes(self, limit=500):
            return [{"height": h, "hash": v} for h, v in sorted(self.recent.items())][-limit:]

    class _ContinuityChain:
        def __init__(self, chain_id, head, earliest, hashes):
            self.chain_id = chain_id
            self.head = head
            self.earliest = earliest
            self.hashes = dict(hashes)

        def get_chain_id(self):
            return self.chain_id

        def get_current_height(self):
            return self.head

        def get_earliest_height(self):
            return self.earliest

        def get_block(self, height):
            return {"result": {"block_id": {"hash": self.hashes.get(height, "")}}}

    def _continuity(db, chain):
        idx = indexer_main.Indexer.__new__(indexer_main.Indexer)
        idx.db = db
        idx.chain = chain
        idx._verify_chain_continuity()
        return db.meta

    node_hashes = {100: "AA", 101: "BB", 102: "CC"}

    # A pre-provenance database whose recent_blocks the node confirms is adopted.
    adopt_db = _ContinuityDB({}, 102, {100: "AA", 101: "BB", 102: "CC"})
    try:
        meta_after = _continuity(adopt_db, _ContinuityChain("mirage-1", 102, 90, node_hashes))
        if (
            meta_after.get("chain_id") == "mirage-1"
            and meta_after.get("last_block_hash") == "CC"
            and meta_after.get("continuity_status") == "adopted"
        ):
            _pass("indexer_hardening.continuity_adopts_confirmed_provenance")
        else:
            _fail("indexer_hardening.continuity_adopts_confirmed_provenance", f"meta={meta_after}")
    except Exception as e:
        _fail("indexer_hardening.continuity_adopts_confirmed_provenance", f"{type(e).__name__}: {e}")

    # Adoption must not launder a diverged database: the hashes still have to match.
    diverged_db = _ContinuityDB({}, 102, {100: "AA", 101: "BB", 102: "ZZ"})
    try:
        _continuity(diverged_db, _ContinuityChain("mirage-1", 102, 90, node_hashes))
        _fail("indexer_hardening.continuity_adoption_rejects_diverged", "mismatch was adopted")
    except RuntimeError as e:
        if "MISMATCH" in str(e) and "chain_id" not in diverged_db.meta:
            _pass("indexer_hardening.continuity_adoption_rejects_diverged")
        else:
            _fail("indexer_hardening.continuity_adoption_rejects_diverged", f"{e} meta={diverged_db.meta}")

    # No provenance and no confirmable row at the checkpoint height stays fatal.
    unconfirmable_db = _ContinuityDB({}, 102, {100: "AA", 101: "BB"})
    try:
        _continuity(unconfirmable_db, _ContinuityChain("mirage-1", 102, 90, node_hashes))
        _fail("indexer_hardening.continuity_requires_checkpoint_evidence", "unconfirmable DB was accepted")
    except RuntimeError:
        _pass("indexer_hardening.continuity_requires_checkpoint_evidence")

    # Below the retained window nothing can be confirmed, so chain_id must already be recorded.
    pruned_bare_db = _ContinuityDB({}, 50, {})
    try:
        _continuity(pruned_bare_db, _ContinuityChain("mirage-1", 102, 90, node_hashes))
        _fail("indexer_hardening.continuity_pruned_requires_chain_id", "bare pruned DB was accepted")
    except RuntimeError:
        _pass("indexer_hardening.continuity_pruned_requires_chain_id")

    pruned_stamped_db = _ContinuityDB({"chain_id": "mirage-1"}, 50, {})
    try:
        meta_after = _continuity(pruned_stamped_db, _ContinuityChain("mirage-1", 102, 90, node_hashes))
        gaps = json.loads(meta_after.get("history_gaps") or "[]")
        if (
            meta_after.get("continuity_status") == "unverified_pruned_gap"
            and gaps
            and gaps[0]["start"] == 51
            and gaps[0]["end"] == 89
        ):
            _pass("indexer_hardening.continuity_pruned_records_gap")
        else:
            _fail("indexer_hardening.continuity_pruned_records_gap", f"meta={meta_after}")
    except Exception as e:
        _fail("indexer_hardening.continuity_pruned_records_gap", f"{type(e).__name__}: {e}")

    # A stamped chain_id from another network is still fatal.
    wrong_net_db = _ContinuityDB({"chain_id": "mirage-testnet"}, 102, {102: "CC"})
    try:
        _continuity(wrong_net_db, _ContinuityChain("mirage-1", 102, 90, node_hashes))
        _fail("indexer_hardening.continuity_rejects_wrong_network", "wrong chain_id was accepted")
    except RuntimeError:
        _pass("indexer_hardening.continuity_rejects_wrong_network")

    # reset_local_testnet stamps the chain it just built, otherwise the restore cannot start.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    with open(os.path.join(repo_root, "scripts", "reset_local_testnet.py"), "r", encoding="utf-8") as fh:
        reset_src = fh.read()
    if 'restore_indexer_database(json.loads(genesis_json)["chain_id"]' in reset_src and "'chain_id'" in reset_src:
        _pass("indexer_hardening.reset_stamps_chain_id")
    else:
        _fail("indexer_hardening.reset_stamps_chain_id", "reset_local_testnet.py does not stamp meta.chain_id")

    # ── H-3: a short block_results is retried, never read as success ─────

    from indexer.chain_client import ChainClient

    class _LaggingResults(ChainClient):
        def __init__(self):
            self.calls = 0
            self.jsonrpc_url = "http://unused"

        def get_block_results(self, height: int) -> dict:
            self.calls += 1
            if self.calls == 1:
                return {"result": {"txs_results": []}}
            return {"result": {"txs_results": [{"code": 0}, {"code": 5}]}}

    lagging = _LaggingResults()
    try:
        out = lagging.get_block_results_matching(42, 2, deadline_s=2.0)
        codes = [int(r["code"]) for r in out["result"]["txs_results"]]
        if codes == [0, 5] and lagging.calls >= 2:
            _pass("indexer_hardening.block_results_retry", calls=lagging.calls)
        else:
            _fail("indexer_hardening.block_results_retry", f"codes={codes} calls={lagging.calls}")
    except Exception as e:
        _fail("indexer_hardening.block_results_retry", f"{type(e).__name__}: {e}")

    class _NeverMatches(ChainClient):
        def __init__(self):
            self.jsonrpc_url = "http://unused"

        def get_block_results(self, height: int) -> dict:
            return {"result": {"txs_results": [{"code": 0}]}}

    try:
        _NeverMatches().get_block_results_matching(7, 2, deadline_s=0.3)
        _fail("indexer_hardening.block_results_deadline", "a permanent mismatch did not raise")
    except RuntimeError as e:
        if "never reached expected tx count" in str(e):
            _pass("indexer_hardening.block_results_deadline")
        else:
            _fail("indexer_hardening.block_results_deadline", str(e))
    except Exception as e:
        _fail("indexer_hardening.block_results_deadline", f"{type(e).__name__}: {e}")

    # ── H-4 / policy: the indexer never speaks REST ──────────────────────

    indexer_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "indexer")
    rest_hits = []
    for root, _dirs, files in os.walk(indexer_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            with open(path, "r", encoding="utf-8") as fh:
                for lineno, line in enumerate(fh, 1):
                    # ":1317" is how a REST base URL is actually built; the bare
                    # number also appears in the policy docstring saying not to.
                    if ":1317" in line:
                        rest_hits.append(f"{fname}:{lineno}")
    if rest_hits:
        _fail("indexer_hardening.no_rest_port", f"port 1317 referenced at {rest_hits}")
    else:
        _pass("indexer_hardening.no_rest_port")

    mp_path = os.path.join(indexer_dir, "message_processor.py")
    with open(mp_path, "r", encoding="utf-8") as fh:
        mp_src = fh.read()
    http_imports = [tok for tok in ("import requests", "import httpx", "urllib.request") if tok in mp_src]
    if http_imports:
        _fail("indexer_hardening.message_processor_no_http", f"found {http_imports}")
    else:
        _pass("indexer_hardening.message_processor_no_http")

    # Every derivation over post content must go through derive_from_content.
    # The guard inside a single derivation only protects the payloads someone
    # thought of; routing the call sites is what makes the next derivation safe
    # by default. A direct call here is how the 2026-08-11 outage happened.
    unrouted = []
    for lineno, line in enumerate(mp_src.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("def "):
            continue
        for fn_name in ("discover_post_thumbnail(", "_parse_mentions("):
            if fn_name in line and "derive_from_content" not in line:
                unrouted.append(f"{fn_name.rstrip('(')} at message_processor.py:{lineno}")
    if unrouted:
        _fail(
            "indexer_hardening.derivations_routed_through_chokepoint",
            f"called directly instead of via derive_from_content: {unrouted}",
        )
    else:
        _pass("indexer_hardening.derivations_routed_through_chokepoint")

    # ── I-3: obsolete queue/config surface is gone ───────────────────────

    stale_settings = [
        n
        for n in (
            "SEEN_TXS_MAX_SIZE",
            "SEEN_TXS_CLEANUP_BATCH",
            "DB_LIST_CAP_MULTIPLIER",
            "DB_MAX_FOLLOWED_USERS",
            "DB_MAX_FOLLOWED_TOPICS",
            "DB_MAX_BLOCKED_USERS",
            "DB_MAX_BLOCKED_POSTS",
            "DB_MAX_BLOCKED_TOPICS",
        )
        if hasattr(indexer_settings, n)
    ]
    stale_db = [
        n for n in ("insert_pending_tx", "get_pending_txs", "update_pending_tx_status") if hasattr(DatabaseManager, n)
    ]
    stale_indexer = [
        n for n in ("_seen_txs", "_proposal_cache", "_skipped_proposals") if hasattr(indexer_main.Indexer, n)
    ]
    if stale_settings or stale_db or stale_indexer:
        _fail(
            "indexer_hardening.obsolete_surface_removed",
            f"settings={stale_settings} db={stale_db} indexer={stale_indexer}",
        )
    else:
        _pass("indexer_hardening.obsolete_surface_removed")

    _indexer_hardening_2026_08_14_checks()
    _indexer_hardening_db_checks(backend)


def _indexer_hardening_2026_08_14_checks() -> None:
    """Regressions for the 2026-08-14 indexer review.

    All stub-level: no docker, no chain, no DB. Each one pins a value that used to
    make a required code path raise inside the block transaction, which rolls the
    block back and re-fails at the same height on every restart forever.
    """
    from contextlib import contextmanager

    import indexer.main as indexer_main
    from indexer import params as indexer_params
    from indexer.chain_client import ChainClient, GOVERNANCE_ONLY_TYPE_URLS
    from indexer.database import DatabaseManager
    from indexer.message_processor import MessageProcessor, TYPE_URL_TO_PROTO, attr_text

    # ── H-1: event attributes are plain text, never base64-guessed ───────
    #
    # CometBFT types EventAttribute.Key/.Value as `string`, so a plain value that
    # happens to be well-formed base64 must survive untouched. Proposal id "1401"
    # is the first four-digit id that decodes to something int() rejects.
    poisoned = ["1400", "1401", "1412", "2400", "7768"]
    events = [{"type": "active_proposal", "attributes": [{"key": "proposal_id", "value": pid}]} for pid in poisoned]
    decoded = MessageProcessor.decode_events(events)
    mangled = [
        (pid, attrs.get("proposal_id"))
        for pid, (_t, attrs) in zip(poisoned, decoded)
        if attrs.get("proposal_id") != pid
    ]
    if mangled:
        _fail("indexer_hardening.event_attrs_not_base64_decoded", f"mangled: {mangled}")
    else:
        _pass("indexer_hardening.event_attrs_not_base64_decoded", ids=len(poisoned))

    try:
        pids = [MessageProcessor.extract_proposal_id(attrs) for _t, attrs in decoded]
        if pids == [int(p) for p in poisoned]:
            _pass("indexer_hardening.proposal_id_parses_after_decode")
        else:
            _fail("indexer_hardening.proposal_id_parses_after_decode", f"got {pids}")
    except Exception as e:
        _fail("indexer_hardening.proposal_id_parses_after_decode", f"{type(e).__name__}: {e}")

    # A genuinely unparseable id must still be fatal: skipping it would advance the
    # checkpoint past a governance action that was never projected.
    try:
        MessageProcessor.extract_proposal_id({"proposal_id": "not-a-number"})
        _fail("indexer_hardening.proposal_id_unparseable_fatal", "did not raise")
    except RuntimeError:
        _pass("indexer_hardening.proposal_id_unparseable_fatal")
    except Exception as e:
        _fail("indexer_hardening.proposal_id_unparseable_fatal", f"raised {type(e).__name__}, expected RuntimeError")

    if attr_text(b"already-bytes") == "already-bytes" and attr_text(None) == "":
        _pass("indexer_hardening.attr_text_decodes_bytes_only")
    else:
        _fail("indexer_hardening.attr_text_decodes_bytes_only", "bytes/None handling changed")

    # ── H-2: any admin level >= 100 resolves, matching the chain ─────────

    idx_map = {lvl: indexer_params.level_to_tier_index(lvl) for lvl in (0, 1, 10, 100, 101, 110, 150, 999)}
    expected_idx = {0: 0, 1: 1, 10: -1, 100: 2, 101: 2, 110: 2, 150: 2, 999: 2}
    if idx_map == expected_idx:
        _pass("indexer_hardening.admin_levels_resolve_to_admin_tier")
    else:
        _fail("indexer_hardening.admin_levels_resolve_to_admin_tier", f"got {idx_map}")

    if indexer_params.level_to_tier_index(50) == -1 and indexer_params.level_to_tier_index(2) == -1:
        _pass("indexer_hardening.unknown_levels_still_rejected")
    else:
        _fail("indexer_hardening.unknown_levels_still_rejected", "a level the chain rejects was accepted")

    # ── M-3: deleting a post retracts the standing it granted ────────────
    #
    # post_count and the author's own auto-upvote must both drop out of the
    # canonical definition, or post-and-delete cycling manufactures the topic
    # standing that gates downvote weight while leaving no visible content.
    post_sql = " ".join(DatabaseManager._POST_STATS_FROM_CANONICAL.split())
    vote_sql = " ".join(DatabaseManager._VOTE_STATS_FROM_CANONICAL.split())
    problems = []
    if "COALESCE(p.deleted, FALSE) = FALSE" not in post_sql:
        problems.append("post_count counts deleted posts")
    if "COALESCE(p.deleted, FALSE) AND LOWER(v.owner) = LOWER(p.owner)" not in vote_sql:
        problems.append("author's own vote on a deleted post still counts")
    if problems:
        _fail("indexer_hardening.deleted_posts_grant_no_standing", "; ".join(problems))
    else:
        _pass("indexer_hardening.deleted_posts_grant_no_standing")

    # The wiring that makes the above take effect on delete is exercised for real
    # in _indexer_hardening_sql_behaviour_checks; this only pins the definition.

    # ── M-2: a suspicious profile inventory must not wipe the index ──────
    #
    # Driven against a stub DB rather than read from source: what matters is that
    # the guards refuse, and equally that a fresh chain and ordinary churn still pass.

    class _StubDb:
        def __init__(self, owners):
            self._owners = owners
            self.soft_deleted = []

        @contextmanager
        def _connect(self):
            rows = [(o,) for o in self._owners]

            class _Cur:
                def __enter__(inner):
                    return inner

                def __exit__(inner, *a):
                    return False

                def execute(inner, *a, **k):
                    return None

                def fetchall(inner):
                    return rows

            class _Conn:
                def cursor(inner):
                    return _Cur()

            yield _Conn()

        def soft_delete_profile(self, owner, now):
            self.soft_deleted.append(owner)

    def _run_sync(db_owners, chain_owners):
        idx = indexer_main.Indexer.__new__(indexer_main.Indexer)
        idx.db = _StubDb(db_owners)
        return idx, idx._soft_delete_absent_owners({o.lower() for o in chain_owners}, 0)

    many = [f"mirage1u{i:03d}" for i in range(100)]

    try:
        _run_sync(many, [])
        _fail("indexer_hardening.profile_sync_rejects_empty_inventory", "an empty chain inventory was accepted")
    except RuntimeError:
        _pass("indexer_hardening.profile_sync_rejects_empty_inventory")

    try:
        _run_sync(many, many[:50])
        _fail("indexer_hardening.profile_sync_bounds_blast_radius", "a 50% wipe was accepted")
    except RuntimeError:
        _pass("indexer_hardening.profile_sync_bounds_blast_radius")

    try:
        _, absent = _run_sync([], [])
        if absent == 0:
            _pass("indexer_hardening.profile_sync_allows_fresh_chain")
        else:
            _fail("indexer_hardening.profile_sync_allows_fresh_chain", f"returned {absent}")
    except Exception as e:
        _fail("indexer_hardening.profile_sync_allows_fresh_chain", f"fresh chain refused: {type(e).__name__}: {e}")

    try:
        idx, absent = _run_sync(many, many[:97])
        if absent == 3 and len(idx.db.soft_deleted) == 3:
            _pass("indexer_hardening.profile_sync_allows_normal_churn", absent=absent)
        else:
            _fail("indexer_hardening.profile_sync_allows_normal_churn", f"absent={absent}")
    except Exception as e:
        _fail("indexer_hardening.profile_sync_allows_normal_churn", f"{type(e).__name__}: {e}")

    # ── L-2: governance cannot silently drop a core message ──────────────

    class _Any:
        def __init__(self, type_url, value=b""):
            self.type_url = type_url
            self.value = value

    try:
        ChainClient._filter_trackable_anys([_Any("/mirage.core.v1.MsgTotallyNew")], TYPE_URL_TO_PROTO)
        _fail("indexer_hardening.untracked_core_message_fatal", "an untracked core message was silently dropped")
    except RuntimeError:
        _pass("indexer_hardening.untracked_core_message_fatal")

    kept = ChainClient._filter_trackable_anys(
        [_Any("/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade"), _Any("/mirage.core.v1.MsgPost")],
        TYPE_URL_TO_PROTO,
    )
    if [k["type_url"] for k in kept] == ["/mirage.core.v1.MsgPost"]:
        _pass("indexer_hardening.cosmos_messages_still_ignored")
    else:
        _fail("indexer_hardening.cosmos_messages_still_ignored", f"kept={kept}")

    if "/mirage.core.v1.MsgAnnotate" in TYPE_URL_TO_PROTO:
        _pass("indexer_hardening.annotate_is_governance_trackable")
    else:
        _fail("indexer_hardening.annotate_is_governance_trackable", "MsgAnnotate is dispatched but not trackable")

    # A mint/burn/punish proposal projects nothing, so the untracked-is-fatal check
    # must not fire on it. It used to, which crash-looped every indexer on the block
    # that executed the proposal while the chain itself was perfectly healthy.
    for governance_only in sorted(GOVERNANCE_ONLY_TYPE_URLS):
        name = governance_only.rsplit(".", 1)[-1]
        try:
            kept = ChainClient._filter_trackable_anys([_Any(governance_only)], TYPE_URL_TO_PROTO)
            if kept:
                _fail(f"indexer_hardening.governance_only_skipped.{name}", f"projected {kept}")
            else:
                _pass(f"indexer_hardening.governance_only_skipped.{name}")
        except RuntimeError as e:
            _fail(f"indexer_hardening.governance_only_skipped.{name}", f"treated as untracked: {e}")

    # Mixed proposal (the make-admin shape): the tracked message still projects.
    try:
        kept = ChainClient._filter_trackable_anys(
            [_Any("/mirage.core.v1.MsgSetLevel"), _Any("/mirage.core.v1.MsgMintTokens")],
            TYPE_URL_TO_PROTO,
        )
        if [k["type_url"] for k in kept] == ["/mirage.core.v1.MsgSetLevel"]:
            _pass("indexer_hardening.governance_only_mixed_proposal")
        else:
            _fail("indexer_hardening.governance_only_mixed_proposal", f"kept={kept}")
    except RuntimeError as e:
        _fail("indexer_hardening.governance_only_mixed_proposal", f"treated as untracked: {e}")

    # The exemption is a named list, not a hole: a core type that is neither
    # projected nor listed must still be fatal (covered above by MsgTotallyNew).
    overlap = GOVERNANCE_ONLY_TYPE_URLS & set(TYPE_URL_TO_PROTO)
    if overlap:
        _fail("indexer_hardening.governance_only_disjoint", f"also projected: {sorted(overlap)}")
    else:
        _pass("indexer_hardening.governance_only_disjoint")

    # ── L-3: a mid-run chain_id change is rejected ───────────────────────
    #
    # Exercised against a bare instance rather than asserted from source: the
    # latch is the whole behaviour, and a source check would pass on a version
    # that latched but never compared.

    probe = indexer_main.Indexer.__new__(indexer_main.Indexer)
    probe._expected_chain_id = None
    probe._verify_chain_id(100, "mirage-1")
    probe._verify_chain_id(101, "mirage-1")
    try:
        probe._verify_chain_id(102, "mirage-other")
        _fail("indexer_hardening.chain_id_checked_per_block", "a mid-run chain_id change was accepted")
    except RuntimeError:
        _pass("indexer_hardening.chain_id_checked_per_block")

    # ── minor: an interrupted indexer must not look like a clean stop ────

    sig_probe = indexer_main.Indexer.__new__(indexer_main.Indexer)
    sig_probe.running = True
    sig_probe._lock_file = None
    sig_probe._lock_path = "/tmp/does-not-exist.lock"
    try:
        sig_probe._handle_signal(signal.SIGTERM, None)
        _fail("indexer_hardening.signal_exit_nonzero", "_handle_signal did not exit")
    except SystemExit as e:
        if e.code == 128 + int(signal.SIGTERM):
            _pass("indexer_hardening.signal_exit_nonzero", code=e.code)
        else:
            _fail("indexer_hardening.signal_exit_nonzero", f"exit code {e.code}, expected {128 + int(signal.SIGTERM)}")

    _indexer_hardening_sql_behaviour_checks()


def _indexer_hardening_sql_behaviour_checks() -> None:
    """Execute the SQL-level fixes against a real PostgreSQL, in a scratch schema.

    The guards these cover (SAVEPOINT, the LIKE escaping, the walk depth cap, the
    delete-time recompute) can all be satisfied by a source-level string match while
    being behaviourally broken, so they are run rather than read. A throwaway schema
    is created, the real `DatabaseManager` builds the real tables inside it via
    `search_path`, and the schema is dropped afterwards — nothing touches live rows.

    Needs a psycopg-reachable INDEXER_DB_URL, which only holds inside the container.
    """
    import psycopg

    from indexer.database import DatabaseManager, MAX_ANCESTOR_WALK_DEPTH

    names = [
        "indexer_hardening.legacy_backfill_uses_savepoint",
        "indexer_hardening.unblock_pattern_escaped",
        "indexer_hardening.ancestor_walk_bounded",
        "indexer_hardening.delete_retracts_topic_standing",
    ]

    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        code, out = _docker_exec("printenv INDEXER_DB_URL")
        if code == 0 and out:
            db_url = out.strip()
    if not db_url:
        for n in names:
            _skip(n, "INDEXER_DB_URL unavailable")
        return

    schema = f"hardening_{_rand_str(8)}"
    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(f'CREATE SCHEMA "{schema}"')
    except Exception as e:
        for n in names:
            _skip(n, f"indexer DB not reachable from here: {e}")
        return

    sep = "&" if "?" in db_url else "?"
    scoped_url = f"{db_url}{sep}options=-csearch_path%3D{schema},public"

    try:
        db = DatabaseManager(scoped_url)

        # ── L-1: the legacy backfill must not poison the block transaction ──
        #
        # A CHECK constraint makes only the backfill UPDATE fail, leaving the read
        # that precedes it working — otherwise the function would fail for an
        # unrelated reason and prove nothing. Without a SAVEPOINT, PostgreSQL aborts
        # the whole transaction and the *next* statement raises, which is the
        # misattribution the finding described.
        with psycopg.connect(scoped_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO posts(txhash, owner, community, created_at) VALUES('legacy1','u','tech',1)")
                cur.execute("ALTER TABLE posts ADD CONSTRAINT no_backfill CHECK (root_community IS NULL)")
        try:
            with db.transaction(label="hardening_savepoint"):
                resolved = db.get_root_topic_for_post("legacy1")
                # The real assertion: the transaction is still usable afterwards.
                with db._connect() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        survived = cur.fetchone()[0] == 1
            if survived and resolved == ("tech", "legacy1"):
                _pass("indexer_hardening.legacy_backfill_uses_savepoint")
            else:
                _fail(
                    "indexer_hardening.legacy_backfill_uses_savepoint",
                    f"survived={survived} resolved={resolved}",
                )
        except Exception as e:
            _fail("indexer_hardening.legacy_backfill_uses_savepoint", f"transaction was poisoned: {e}")

        with psycopg.connect(scoped_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("ALTER TABLE posts DROP CONSTRAINT no_backfill")
                cur.execute("DELETE FROM posts")

        # ── I-1: stored %/_ are literals; only * globs ──────────────────────
        with psycopg.connect(scoped_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO blocked_communities(owner, target, position) VALUES('u', %s, %s)",
                    [("100%", 1), ("a_b", 2), ("spo*", 3)],
                )
        wildcard_bugs = []
        if db.unblock_topics_matching("u", "1000") != 0:
            wildcard_bugs.append("stored % matched an unrelated topic")
        if db.unblock_topics_matching("u", "axb") != 0:
            wildcard_bugs.append("stored _ matched an unrelated topic")
        if db.unblock_topics_matching("u", "sports") != 1:
            wildcard_bugs.append("* no longer globs")
        if wildcard_bugs:
            _fail("indexer_hardening.unblock_pattern_escaped", "; ".join(wildcard_bugs))
        else:
            _pass("indexer_hardening.unblock_pattern_escaped")

        # ── minor: the ancestor walk stops at the cap ───────────────────────
        depth = MAX_ANCESTOR_WALK_DEPTH + 25
        with psycopg.connect(scoped_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM posts")
                cur.execute(
                    "INSERT INTO posts(txhash, owner, community, comment_count, created_at) " "VALUES('d0','u','tech',0,1)"
                )
                for i in range(1, depth):
                    cur.execute(
                        "INSERT INTO posts(txhash, owner, community, target, comment_count, created_at) "
                        "VALUES(%s,'u','tech',%s,0,1)",
                        (f"d{i}", f"d{i - 1}"),
                    )
                db._update_ancestor_comment_counts(cur, f"d{depth - 1}", delta=1)
                cur.execute("SELECT COUNT(*) FROM posts WHERE comment_count > 0")
                touched = int(cur.fetchone()[0])
        if touched == MAX_ANCESTOR_WALK_DEPTH:
            _pass("indexer_hardening.ancestor_walk_bounded", touched=touched)
        else:
            _fail(
                "indexer_hardening.ancestor_walk_bounded",
                f"walked {touched} levels, expected the cap of {MAX_ANCESTOR_WALK_DEPTH}",
            )

        # ── M-3: deleting retracts the author's standing, not the voters' ───
        with psycopg.connect(scoped_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM posts")
                for i in range(3):
                    cur.execute(
                        "INSERT INTO posts(txhash, owner, community, root_community, root_post_id, created_at) "
                        "VALUES(%s,'attacker','tech','tech',%s,1)",
                        (f"p{i}", f"p{i}"),
                    )
                    cur.execute(
                        "INSERT INTO votes(txhash, owner, target, user_vote, created_at) "
                        "VALUES(%s,'attacker',%s,1.0,1)",
                        (f"v{i}", f"p{i}"),
                    )
                cur.execute(
                    "INSERT INTO votes(txhash, owner, target, user_vote, created_at) "
                    "VALUES('vh','honest','p0',1.0,1)"
                )
                db._recompute_topic_stats(cur, ["attacker", "honest"], ["tech"])
                cur.execute("SELECT post_count FROM user_topic_stats WHERE owner='attacker' AND topic='tech'")
                seeded = cur.fetchone()

        for i in range(3):
            db.delete_post(f"p{i}")

        with psycopg.connect(scoped_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vote_count, net_votes, unique_root_posts, post_count "
                    "FROM user_topic_stats WHERE owner='attacker' AND topic='tech'"
                )
                attacker = cur.fetchone()
                cur.execute(
                    "SELECT vote_count, net_votes, unique_root_posts "
                    "FROM user_topic_stats WHERE owner='honest' AND topic='tech'"
                )
                honest = cur.fetchone()

        problems = []
        if not seeded or int(seeded[0]) != 3:
            problems.append(f"setup did not credit the author (post_count={seeded})")
        if attacker not in (None, (0, 0, 0, 0)):
            problems.append(f"author kept standing after deleting: {attacker}")
        if honest != (1, 1, 1):
            problems.append(f"an unrelated voter lost standing they earned: {honest}")
        if problems:
            _fail("indexer_hardening.delete_retracts_topic_standing", "; ".join(problems))
        else:
            _pass("indexer_hardening.delete_retracts_topic_standing")

    except Exception as e:
        _fail("indexer_hardening.sql_behaviour_harness", f"{type(e).__name__}: {e}")
    finally:
        try:
            with psycopg.connect(db_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        except Exception as e:
            _fail("indexer_hardening.sql_behaviour_harness", f"scratch schema {schema} not dropped: {e}")


def _indexer_hardening_db_checks(backend: str) -> None:
    """Live indexer DB assertions. Skipped when local docker is unavailable."""

    if not _check_local_docker():
        _skip("indexer_hardening.checkpoint_has_provenance", "not running in local-docker")
        _skip("indexer_hardening.net_votes_matches_canonical_votes", "not running in local-docker")
        _skip("indexer_hardening.block_transaction_rolls_back", "not running in local-docker")
        _skip("indexer_hardening.corrupt_profile_degrades", "not running in local-docker")
        return

    db_name = _get_indexer_db_name()
    _indexer_hardening_txn_check()
    _indexer_hardening_startup_backfill_check()
    _indexer_hardening_corrupt_profile_check(backend)

    # H-1/H-2: last_height is never written without the chain_id and block hash
    # that let the next startup prove the rows belong to this chain.
    rc, out = _docker_exec(
        f"""su - postgres -c "psql -d {db_name} -tAc \\"SELECT string_agg(key, ',' ORDER BY key)
FROM meta WHERE key IN ('chain_id', 'last_block_hash', 'last_height');\\" 2>&1" """,
        timeout=10,
    )
    if rc != 0:
        _fail("indexer_hardening.checkpoint_has_provenance", f"db query failed rc={rc} out={out}")
    else:
        keys = out.strip()
        if keys == "chain_id,last_block_hash,last_height":
            _pass("indexer_hardening.checkpoint_has_provenance")
        elif keys in ("", "last_height"):
            # Pre-remediation DBs only store last_height until the upgraded indexer
            # writes its first atomic checkpoint. That is not a regression of the
            # new code path — just an undeployed runtime.
            _skip(
                "indexer_hardening.checkpoint_has_provenance",
                f"legacy/incomplete checkpoint meta keys={keys!r}; redeploy indexer to populate",
            )
        else:
            _fail("indexer_hardening.checkpoint_has_provenance", f"meta keys={keys!r}")

    # M-8: net_votes must equal the sum of the user's current canonical vote
    # signs in that topic. Re-votes and cleared votes are what used to break it.
    #
    # The canonical sum below must exclude an author's own vote on their own
    # deleted post, matching _VOTE_STATS_FROM_CANONICAL in indexer/database.py.
    # Without that clause this asserts the pre-v1.36.0 definition and fails on
    # any database where somebody has ever deleted a post they upvoted.
    #
    # Skip until the v1_33_0 rebuild migration has actually run on this DB.
    rc_mig, out_mig = _docker_exec(
        f"""su - postgres -c "psql -d {db_name} -tAc \\"SELECT value FROM meta WHERE key='migration_v1.33.0_rebuild_derived_stats';\\" 2>&1" """,
        timeout=10,
    )
    migration_done = rc_mig == 0 and out_mig.strip() not in ("",)
    if not migration_done:
        _skip(
            "indexer_hardening.net_votes_matches_canonical_votes",
            "v1_33_0_rebuild_derived_stats not applied on this database yet",
        )
        return

    rc2, out2 = _docker_exec(
        f"""su - postgres -c "psql -d {db_name} -tAc \\"SELECT count(*) FROM (
SELECT s.owner, s.topic
FROM user_topic_stats s
LEFT JOIN (
  SELECT LOWER(v.owner) AS owner,
         LOWER(COALESCE(NULLIF(p.root_community, ''), p.community)) AS topic,
         SUM(CASE WHEN v.user_vote > 0 THEN 1 WHEN v.user_vote < 0 THEN -1 ELSE 0 END)::int AS net
  FROM votes v
  JOIN posts p ON LOWER(p.txhash) = LOWER(v.target)
  WHERE COALESCE(NULLIF(p.root_community, ''), p.community) <> ''
    AND NOT (COALESCE(p.deleted, FALSE) AND LOWER(v.owner) = LOWER(p.owner))
  GROUP BY 1, 2
) d ON d.owner = s.owner AND d.topic = s.topic
WHERE s.net_votes <> COALESCE(d.net, 0)
) mismatched;\\" 2>&1" """,
        timeout=20,
    )
    if rc2 != 0:
        _fail("indexer_hardening.net_votes_matches_canonical_votes", f"db query failed rc={rc2} out={out2}")
    else:
        try:
            mismatched = int(out2.strip())
        except ValueError:
            _fail("indexer_hardening.net_votes_matches_canonical_votes", f"non-numeric output: {out2}")
            return
        if mismatched == 0:
            _pass("indexer_hardening.net_votes_matches_canonical_votes")
        else:
            _fail(
                "indexer_hardening.net_votes_matches_canonical_votes",
                f"{mismatched} (owner, topic) rows disagree with their canonical votes",
            )


def _indexer_hardening_startup_backfill_check() -> None:
    """Indexer startup must not resurrect standing the repair migration removed.

    _init_db() used to carry its own copy of the vote-stats definition, without the
    exclusion for an author's self-upvote on their own deleted post. The repair
    migration deletes those rows outright, so ON CONFLICT DO NOTHING stopped
    suppressing anything and the next restart re-inserted them with the pre-fix
    values. The fix survived until the first restart, on every node.

    Exercised against the real schema init in a scratch schema: build the exact
    shape (a deleted post, its author's own upvote, no other votes), run _init_db,
    and require that no stats row appears for it.
    """
    from indexer.database import DatabaseManager

    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        code, out = _docker_exec("printenv INDEXER_DB_URL")
        if code == 0 and out:
            db_url = out.strip()
    if not db_url:
        _skip("indexer_hardening.startup_does_not_resurrect_standing", "INDEXER_DB_URL unavailable")
        return

    try:
        import psycopg
    except ImportError:
        _skip("indexer_hardening.startup_does_not_resurrect_standing", "psycopg unavailable")
        return

    schema = f"hardening_probe_{_rand_str(8)}"
    scratch_url = f"{db_url}{'&' if '?' in db_url else '?'}options=-csearch_path%3D{schema}"
    owner = f"mirage1probe{_rand_str(20)}"
    topic = f"probe{_rand_str(6)}"
    txhash = _rand_str(64)

    admin = None
    try:
        admin = psycopg.connect(db_url, autocommit=True)
        with admin.cursor() as cur:
            cur.execute(f"CREATE SCHEMA {schema}")

        # First init builds the schema in the scratch namespace.
        DatabaseManager(scratch_url)

        with psycopg.connect(scratch_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO posts (txhash, owner, community, root_community, root_post_id, created_at, deleted) "
                    "VALUES (%s, %s, %s, %s, %s, %s, TRUE)",
                    (txhash, owner, topic, topic, txhash, 1700000000),
                )
                cur.execute(
                    "INSERT INTO votes (txhash, owner, target, user_vote, created_at) VALUES (%s, %s, %s, %s, %s)",
                    (_rand_str(64), owner, txhash, 1, 1700000000),
                )
                # What the repair migration leaves behind: no stats row at all.
                cur.execute("DELETE FROM user_topic_stats WHERE LOWER(owner) = LOWER(%s)", (owner,))

        # Second init is the restart.
        DatabaseManager(scratch_url)

        with psycopg.connect(scratch_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT vote_count, net_votes, unique_root_posts FROM user_topic_stats "
                    "WHERE LOWER(owner) = LOWER(%s) AND LOWER(topic) = LOWER(%s)",
                    (owner, topic),
                )
                row = cur.fetchone()

        if row is None:
            _pass("indexer_hardening.startup_does_not_resurrect_standing")
        else:
            _fail(
                "indexer_hardening.startup_does_not_resurrect_standing",
                f"schema init re-created standing for a deleted self-voted post: "
                f"vote_count={row[0]} net_votes={row[1]} unique_root_posts={row[2]}",
            )
    except Exception as e:
        _fail("indexer_hardening.startup_does_not_resurrect_standing", f"{type(e).__name__}: {e}")
    finally:
        if admin is not None:
            try:
                with admin.cursor() as cur:
                    cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            finally:
                admin.close()


def _indexer_hardening_txn_check() -> None:
    """H-1: an exception inside a block transaction must leave nothing behind.

    Needs a psycopg-reachable INDEXER_DB_URL, which only holds when the suite runs
    inside the container. From the host the URL points at the container's own
    loopback, so this skips rather than reporting a connection error as a failure.
    """
    from indexer.database import DatabaseManager

    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        code, out = _docker_exec("printenv INDEXER_DB_URL")
        if code == 0 and out:
            db_url = out.strip()
    if not db_url:
        _skip("indexer_hardening.block_transaction_rolls_back", "INDEXER_DB_URL unavailable")
        return

    try:
        db = DatabaseManager(db_url)
    except Exception as e:
        _skip("indexer_hardening.block_transaction_rolls_back", f"indexer DB not reachable from here: {e}")
        return

    probe_key = f"hardening_probe_{_rand_str(8)}"
    try:
        try:
            with db.transaction(label="hardening_probe"):
                db.set_meta(probe_key, "should_roll_back")
                raise RuntimeError("injected failure after set_meta")
        except RuntimeError as e:
            if "injected failure" not in str(e):
                raise
        after = db.get_meta(probe_key)
        if after is None:
            _pass("indexer_hardening.block_transaction_rolls_back")
        else:
            _fail("indexer_hardening.block_transaction_rolls_back", f"meta survived rollback: {after!r}")
    except Exception as e:
        _fail("indexer_hardening.block_transaction_rolls_back", f"{type(e).__name__}: {e}")


def _indexer_hardening_corrupt_profile_check(backend: str) -> None:
    """A corrupt or unreadable profile row must degrade this node, never halt it.

    The blockchain retest left this as a manual pre-deployment exercise: read a
    damaged profile row and record whether the backend degrades or halts. It is
    automated here instead, because the answer only stays true if something keeps
    checking it.

    The row is written straight into the indexer DB, bypassing the indexer, so it
    holds shapes the indexer would never produce: a NULL username where the
    reader coerces, a negative level and expiry that no handler can emit, and an
    owner that is not a valid address. What must hold is that the request fails
    or degrades visibly, the process survives, and nothing about it can reach
    consensus - the row exists only in this node's index.

    created_at is negative on purpose, not arbitrarily. This category runs in the
    parallel stateless set, so for the ~1s the row exists it is visible to other
    categories, and test_backend_stats aggregates profiles by created_at. A
    negative value falls outside every time-windowed query (stats bounds its scan
    to the last 120 days), so it cannot shift a bucket, a COUNT or a MIN. A
    plausible recent timestamp would look tidier and would make that test flaky.
    """
    db_url = os.environ.get("INDEXER_DB_URL", "").strip()
    if not db_url:
        code, out = _docker_exec("printenv INDEXER_DB_URL")
        if code == 0 and out:
            db_url = out.strip()
    if not db_url:
        _skip("indexer_hardening.corrupt_profile_degrades", "INDEXER_DB_URL unavailable")
        return

    owner = f"not_a_valid_address_{_rand_str(10)}"
    try:
        import psycopg
    except Exception as e:
        _skip("indexer_hardening.corrupt_profile_degrades", f"psycopg unavailable: {e}")
        return

    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO profiles(owner, username, level, created_at, subscription_expiry)
                       VALUES(%s, NULL, %s, %s, %s)""",
                    (owner, -1, -1, -1),
                )
    except Exception as e:
        _fail("indexer_hardening.corrupt_profile_degrades", f"could not seed the corrupt row: {e}")
        return

    try:
        code, data = _get(f"{backend}/api/get_profile", {"address": owner})
        # Two verdicts are acceptable degradations: a served profile, or a clean
        # error. What is not acceptable is a dead worker, which is what 502/504
        # indicate here since the backend sits behind the container's own proxy.
        # A hang shows up as the _get timeout rather than as a code.
        if code in (502, 504):
            _fail("indexer_hardening.corrupt_profile_degrades", f"worker died on the corrupt row: code={code}")
        elif code == 200 and isinstance(data, dict):
            # Pin what actually happens, which is narrower than "sanitised": the
            # NULL is coerced to a default because the reader guards for None,
            # while a type-valid but nonsensical number is passed through to the
            # client verbatim. Both are degradations rather than halts, but only
            # the first is coercion, and saying so keeps the recorded answer
            # honest if someone later assumes the row is cleaned.
            if data.get("username") != "":
                _fail(
                    "indexer_hardening.corrupt_profile_degrades",
                    f"a NULL username must read as empty, got {data.get('username')!r}",
                )
            else:
                _pass(
                    "indexer_hardening.corrupt_profile_degrades",
                    verdict="degraded",
                    null_coerced=True,
                    level_passed_through=(data.get("level") == -1),
                )
        elif 400 <= code < 600:
            _pass("indexer_hardening.corrupt_profile_degrades", verdict=f"clean_error_{code}")
        else:
            _fail("indexer_hardening.corrupt_profile_degrades", f"unexpected code={code} data={str(data)[:200]}")

        # Liveness: the process must still serve the next request. This is the
        # half that distinguishes "degraded" from "halted".
        code_after, _ = _get(f"{backend}/api/get_parameters")
        if code_after in (200, 503):
            _pass("indexer_hardening.corrupt_profile_leaves_node_alive", code=code_after)
        else:
            _fail(
                "indexer_hardening.corrupt_profile_leaves_node_alive",
                f"backend unhealthy after reading the corrupt row: code={code_after}",
            )
    finally:
        try:
            with psycopg.connect(db_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM profiles WHERE owner = %s", (owner,))
        except Exception as e:
            _fail("indexer_hardening.corrupt_profile_cleanup", f"left the corrupt row behind: {e}")


def test_redgifs_thumbnails(backend: str):
    """The RedGIFs resolver, which is the one place the indexer talks to a third party.

    Hermetic: no network. What matters is not that a live lookup works but that
    the guards around it hold — the id that goes out, the URL that comes back,
    the batch cap, and the fact that a dead gif cannot wedge the pass.
    """
    del backend

    if not _check_local_docker():
        _skip("redgifs.id_extraction", "local docker required")
        return

    import sys

    sys.path.insert(0, "/opt/mirage")
    from indexer import redgifs
    from indexer.main import Indexer, REDGIFS_BACKFILL_BATCH

    # ── the id that goes out ──────────────────────────────────────────────
    # Only the id is attacker-controlled, so it is the only thing that could
    # bend the request away from the fixed host it is interpolated into.
    id_cases = [
        ("https://www.redgifs.com/watch/prettywrithinghornet", "prettywrithinghornet"),
        ("https://redgifs.com/watch/craftysimplebettong", "craftysimplebettong"),
        ("https://v3.redgifs.com/watch/857346293912490649", "857346293912490649"),
        ("https://www.redgifs.com/ifr/everyawfulmullet", "everyawfulmullet"),
        ("https://www.redgifs.com/watch/foo?utm=1", "foo"),
        ("https://evil.example/watch/foo", None),
        ("https://notredgifs.com.evil.example/watch/foo", None),
        ("https://www.redgifs.com/watch/../../etc/passwd", None),
        ("https://www.redgifs.com/", None),
        ("javascript:alert(1)", None),
    ]
    bad_ids = [f"{raw} -> {redgifs.extract_gif_id(raw)} (want {want})" for raw, want in id_cases if redgifs.extract_gif_id(raw) != want]
    if bad_ids:
        _fail("redgifs.id_extraction", "; ".join(bad_ids))
    else:
        _pass("redgifs.id_extraction", cases=len(id_cases))

    # ── the URL that comes back ───────────────────────────────────────────
    # This is the allowlist that matters: the value is stored and later handed
    # to a browser as an image source, and it arrives from a third party.
    url_cases = [
        ("https://media.redgifs.com/X-mobile.jpg", True),
        ("https://redgifs.com/x.jpg", True),
        ("http://media.redgifs.com/X.jpg", False),
        ("https://evil.example/X.jpg", False),
        ("https://media.redgifs.com.evil.example/X.jpg", False),
        ("javascript:alert(1)", False),
        ("", False),
    ]
    bad_urls = [f"{raw} -> {redgifs._is_redgifs_media_url(raw)}" for raw, want in url_cases if redgifs._is_redgifs_media_url(raw) != want]
    if bad_urls:
        _fail("redgifs.response_url_allowlist", "; ".join(bad_urls))
    else:
        _pass("redgifs.response_url_allowlist", cases=len(url_cases))

    # A non-id must be refused before a request is built, not sanitized into one.
    refused = []
    for probe in ("../../etc/passwd", "a/b", "", "x" * 100, "a b"):
        try:
            redgifs.RedgifsResolver().resolve_thumbnail(probe)
            refused.append(f"accepted {probe!r}")
        except ValueError:
            pass
        except Exception as e:
            refused.append(f"{probe!r} raised {type(e).__name__} instead of ValueError: {e}")
    if refused:
        _fail("redgifs.refuses_non_id_before_request", "; ".join(refused))
    else:
        _pass("redgifs.refuses_non_id_before_request")

    # ── the backfill loop ─────────────────────────────────────────────────
    class _StubDB:
        """Stands in for the real query, including its exclusion behaviour."""

        def __init__(self, rows):
            self.rows = rows
            self.updated: list[tuple[str, str]] = []

        def select_redgifs_posts_missing_thumbnail(self, limit, exclude_txhashes=()):
            excluded = set(exclude_txhashes)
            live = [r for r in self.rows if r[0] not in excluded and not any(u[0] == r[0] for u in self.updated)]
            return live[:limit]

        def update_post_thumbnail(self, txhash, url):
            self.updated.append((txhash, url))

    class _StubResolver:
        def __init__(self, behavior):
            self.behavior = behavior
            self.calls: list[str] = []

        def resolve_thumbnail(self, gif_id):
            self.calls.append(gif_id)
            outcome = self.behavior(gif_id)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class _Stub:
        def __init__(self, db, resolver):
            self.db = db
            self._redgifs = resolver
            self._redgifs_missing = set()
            self._redgifs_skip = set()

        _skip_redgifs_post = Indexer._skip_redgifs_post

    rows = [(f"tx{i:03d}", "[]", f"https://www.redgifs.com/watch/gif{i:03d}") for i in range(REDGIFS_BACKFILL_BATCH + 7)]

    db = _StubDB(rows)
    resolver = _StubResolver(lambda gid: f"https://media.redgifs.com/{gid}-mobile.jpg")
    Indexer._backfill_redgifs_thumbnails(_Stub(db, resolver))
    if len(resolver.calls) == REDGIFS_BACKFILL_BATCH and len(db.updated) == REDGIFS_BACKFILL_BATCH:
        _pass("redgifs.batch_is_capped", batch=REDGIFS_BACKFILL_BATCH)
    else:
        _fail(
            "redgifs.batch_is_capped",
            f"{len(resolver.calls)} lookups and {len(db.updated)} writes for a cap of {REDGIFS_BACKFILL_BATCH}",
        )

    # A gif that is gone is recorded once and never asked about again, or a
    # handful of deleted ids would fill every pass and starve the live ones.
    db = _StubDB(rows)
    resolver = _StubResolver(lambda gid: None)
    stub = _Stub(db, resolver)
    Indexer._backfill_redgifs_thumbnails(stub)
    first_pass = list(resolver.calls)
    Indexer._backfill_redgifs_thumbnails(stub)
    repeated = sorted(set(first_pass) & set(resolver.calls[len(first_pass):]))
    # Each pass spends its whole budget on ids it has not seen, so two passes
    # record two batches and revisit nothing.
    expected_missing = 2 * REDGIFS_BACKFILL_BATCH
    if not db.updated and len(stub._redgifs_missing) == expected_missing and not repeated:
        _pass("redgifs.gone_ids_are_not_retried", recorded=expected_missing)
    else:
        _fail(
            "redgifs.gone_ids_are_not_retried",
            f"writes={db.updated} missing={len(stub._redgifs_missing)} "
            f"(expected {expected_missing}) retried={repeated}",
        )

    # An unreachable API aborts the pass instead of grinding through the batch,
    # and must not leave a transient failure recorded as a permanent one.
    db = _StubDB(rows)
    resolver = _StubResolver(lambda gid: redgifs.RedgifsUnavailable("probe outage"))
    stub = _Stub(db, resolver)
    try:
        Indexer._backfill_redgifs_thumbnails(stub)
        aborted = False
    except redgifs.RedgifsUnavailable:
        aborted = True
    if aborted and len(resolver.calls) == 1 and not stub._redgifs_missing and not db.updated:
        _pass("redgifs.outage_aborts_pass")
    else:
        _fail(
            "redgifs.outage_aborts_pass",
            f"aborted={aborted} calls={len(resolver.calls)} missing={len(stub._redgifs_missing)}",
        )

    # A row that can never resolve must not hold its place in the scan window.
    # Dead gifs only accumulate, so if they stayed, the window would eventually
    # be nothing but rows that cannot resolve and every older post behind them
    # would be stranded. This is the check that the backlog keeps draining.
    from indexer.main import REDGIFS_BACKFILL_SCAN

    dead = [(f"dead{i:03d}", "[]", f"https://www.redgifs.com/watch/gone{i:03d}") for i in range(REDGIFS_BACKFILL_SCAN)]
    unparseable = [(f"bare{i:03d}", "[]", "see redgifs.com for more") for i in range(5)]
    alive = [("live001", "[]", "https://www.redgifs.com/watch/stillhere")]
    db = _StubDB(dead + unparseable + alive)
    resolver = _StubResolver(lambda gid: "https://media.redgifs.com/StillHere-mobile.jpg" if gid == "stillhere" else None)
    stub = _Stub(db, resolver)

    # Enough passes to clear the dead head of the window, with a hard bound so
    # a regression fails the test rather than spinning.
    max_passes = (len(dead) // REDGIFS_BACKFILL_BATCH) + 5
    for _ in range(max_passes):
        Indexer._backfill_redgifs_thumbnails(stub)
        if db.updated:
            break
    if db.updated == [("live001", "https://media.redgifs.com/StillHere-mobile.jpg")]:
        _pass("redgifs.backlog_drains_past_dead_rows", passes_bounded_by=max_passes)
    else:
        _fail(
            "redgifs.backlog_drains_past_dead_rows",
            f"the reachable post was never resolved in {max_passes} passes: updated={db.updated} "
            f"skipped={len(stub._redgifs_skip)}",
        )

    # ── the architectural boundary ────────────────────────────────────────
    # The whole point of putting this in its own module is that block
    # projection stays offline. Importing it into the message path would undo
    # H-5 while every H-5 guard kept passing, since they only look for the
    # HTTP libraries by name.
    mp_path = os.path.join("/opt/mirage", "indexer", "message_processor.py")
    with open(mp_path, "r", encoding="utf-8") as fh:
        mp_src = fh.read()
    leaked = [tok for tok in ("import redgifs", "from indexer.redgifs", "from . import redgifs", "redgifs.") if tok in mp_src]
    if leaked:
        _fail("redgifs.absent_from_message_path", f"message_processor.py references the resolver: {leaked}")
    else:
        _pass("redgifs.absent_from_message_path")


def test_rumble_embeds(backend: str):
    """Rumble resolution, whose whole reason to exist is a wrong-video bug.

    Rumble runs two id namespaces that collide: an embed built from a watch id
    frames an unrelated video instead of failing. These checks pin that the
    embed id can only come from a resolved answer and never from the URL.
    """
    del backend

    if not _check_local_docker():
        _skip("rumble.canonical_url", "local docker required")
        return

    import sys

    sys.path.insert(0, "/opt/mirage")
    from indexer import rumble
    from indexer.main import Indexer, RUMBLE_BACKFILL_BATCH

    # ── what may reach the wire ───────────────────────────────────────────
    # oEmbed matches on the full watch URL, so unlike RedGIFs the posted URL
    # itself is sent. It only goes as a urlencoded parameter of a fixed
    # endpoint, and only after the host and path shape are confirmed.
    url_cases = [
        ("https://rumble.com/v7b3y1w-outlaws.html?e9s=src", "https://rumble.com/v7b3y1w-outlaws.html"),
        ("https://www.rumble.com/v7am7nc-insomnia.html", "https://rumble.com/v7am7nc-insomnia.html"),
        ("https://rumble.com/v7b3y1w-outlaws", "https://rumble.com/v7b3y1w-outlaws.html"),
        ("https://rumble.com/embed/v78xa1o/", "https://rumble.com/embed/v78xa1o/"),
        ("https://evil.example/v7b3y1w-x.html", None),
        ("https://rumble.com.evil.example/v7b3y1w-x.html", None),
        ("https://rumble.com/user/blackpilled", None),
        ("javascript:alert(1)", None),
        ("https://rumble.com/v7b3y1w-x.html?url=https://evil.example", "https://rumble.com/v7b3y1w-x.html"),
    ]
    bad = [f"{raw} -> {rumble.canonical_watch_url(raw)} (want {want})" for raw, want in url_cases if rumble.canonical_watch_url(raw) != want]
    if bad:
        _fail("rumble.canonical_url", "; ".join(bad))
    else:
        _pass("rumble.canonical_url", cases=len(url_cases))

    refused = []
    for probe in ("https://evil.example/x", "https://rumble.com/user/x", ""):
        try:
            rumble.RumbleResolver().resolve(probe)
            refused.append(f"accepted {probe!r}")
        except ValueError:
            pass
        except Exception as e:
            refused.append(f"{probe!r} raised {type(e).__name__}: {e}")
    if refused:
        _fail("rumble.refuses_non_canonical_before_request", "; ".join(refused))
    else:
        _pass("rumble.refuses_non_canonical_before_request")

    # ── what may come back ────────────────────────────────────────────────
    # Both values are stored: the thumbnail becomes an image source and the
    # embed id is interpolated into an iframe src.
    thumb_cases = [
        ("https://1a-1791.com/video/x.jpg", True),
        ("https://sp.rmbl.ws/x.jpg", True),
        ("http://1a-1791.com/x.jpg", False),
        ("https://evil.example/x.jpg", False),
        ("https://1a-1791.com.evil.example/x.jpg", False),
    ]
    bad = [raw for raw, want in thumb_cases if rumble._is_rumble_thumbnail_url(raw) != want]
    embed_cases = [
        ('<iframe src="https://rumble.com/embed/v78xa1o/">', "v78xa1o"),
        ('<iframe src="https://rumble.com/embed/uABC.v78xa1o/">', "uABC.v78xa1o"),
        ('<iframe src="https://evil.example/embed/v1/">', None),
        ('<iframe src="https://rumble.com/embed/../../x/">', None),
        ("", None),
    ]
    bad += [html for html, want in embed_cases if rumble._embed_id_from_html(html) != want]
    if bad:
        _fail("rumble.response_allowlists", f"{len(bad)} wrong: {bad[:3]}")
    else:
        _pass("rumble.response_allowlists", cases=len(thumb_cases) + len(embed_cases))

    # ── URL discovery in real post content ────────────────────────────────
    # Posts are markdown, so [title](url) is the common shape and a greedy
    # match takes the closing bracket with it.
    content_cases = [
        ("[Crowder vs Fuentes](https://rumble.com/v79qrke-crowder.html) debate", "https://rumble.com/v79qrke-crowder.html"),
        ("https://rumble.com/v7am7nc-insomnia.html?e9s=sr", "https://rumble.com/v7am7nc-insomnia.html"),
        ("watch it https://rumble.com/v75gmmg-shorts.html.", "https://rumble.com/v75gmmg-shorts.html"),
        ("nothing here", None),
    ]
    bad = [f"{txt!r} -> {rumble.find_watch_url([], txt)}" for txt, want in content_cases if rumble.find_watch_url([], txt) != want]
    if bad:
        _fail("rumble.finds_url_in_markdown", "; ".join(bad))
    else:
        _pass("rumble.finds_url_in_markdown", cases=len(content_cases))

    # ── the media_meta merge ──────────────────────────────────────────────
    # The embed rides in an existing column beside dimensions the offline
    # derivation wrote. Losing those would resize every such post.
    merge_cases = [
        ('[{"w": 320, "h": 180}]', [{"w": 320, "h": 180, "embed": "v1"}]),
        ("[]", [{"embed": "v1"}]),
        ("not json", [{"embed": "v1"}]),
        ('[{"w": 1, "h": 2}, {"w": 3, "h": 4}]', [{"w": 1, "h": 2, "embed": "v1"}, {"w": 3, "h": 4}]),
        ('["junk"]', [{"embed": "v1"}]),
    ]
    bad = []
    for raw, want in merge_cases:
        got = json.loads(Indexer._media_meta_with_embed(raw, "v1"))
        if got != want:
            bad.append(f"{raw} -> {got} (want {want})")
    if bad:
        _fail("rumble.media_meta_merge_preserves_dimensions", "; ".join(bad))
    else:
        _pass("rumble.media_meta_merge_preserves_dimensions", cases=len(merge_cases))

    # ── the backfill loop ─────────────────────────────────────────────────
    class _StubDB:
        def __init__(self, rows):
            self.rows = rows
            self.thumbs: list[tuple[str, str]] = []
            self.metas: list[tuple[str, str]] = []

        def select_rumble_posts_needing_resolution(self, limit, exclude_txhashes=()):
            excluded = set(exclude_txhashes)
            return [r for r in self.rows if r[0] not in excluded][:limit]

        def update_post_thumbnail(self, txhash, url):
            self.thumbs.append((txhash, url))

        def update_post_media_meta(self, txhash, meta_json):
            self.metas.append((txhash, meta_json))

    class _StubResolver:
        def __init__(self, behavior):
            self.behavior = behavior
            self.calls: list[str] = []

        def resolve(self, watch_url):
            self.calls.append(watch_url)
            outcome = self.behavior(watch_url)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    class _Stub:
        def __init__(self, db, resolver):
            self.db = db
            self._rumble = resolver
            self._rumble_skip = set()

        _skip_rumble_post = Indexer._skip_rumble_post
        _media_meta_with_embed = staticmethod(Indexer._media_meta_with_embed)

    def _rows(n, thumbnail=""):
        return [
            (f"tx{i:03d}", "[]", f"https://rumble.com/v{i:03d}aaa-slug.html", "[]", thumbnail)
            for i in range(n)
        ]

    answer = {"embed_id": "v78xa1o", "thumbnail": "https://1a-1791.com/x.jpg"}

    db = _StubDB(_rows(RUMBLE_BACKFILL_BATCH + 4))
    resolver = _StubResolver(lambda u: dict(answer))
    Indexer._backfill_rumble_media(_Stub(db, resolver))
    if len(resolver.calls) == RUMBLE_BACKFILL_BATCH and len(db.metas) == RUMBLE_BACKFILL_BATCH:
        _pass("rumble.batch_is_capped", batch=RUMBLE_BACKFILL_BATCH)
    else:
        _fail("rumble.batch_is_capped", f"{len(resolver.calls)} lookups, {len(db.metas)} writes")

    # An author's own attached image already won the offline derivation; the
    # video's poster frame must not displace it.
    db = _StubDB(_rows(1, thumbnail="https://imagedelivery.net/mine/public"))
    Indexer._backfill_rumble_media(_Stub(db, _StubResolver(lambda u: dict(answer))))
    if not db.thumbs and len(db.metas) == 1:
        _pass("rumble.keeps_existing_thumbnail")
    else:
        _fail("rumble.keeps_existing_thumbnail", f"overwrote thumbnail: {db.thumbs}")

    db = _StubDB(_rows(1))
    Indexer._backfill_rumble_media(_Stub(db, _StubResolver(lambda u: dict(answer))))
    if db.thumbs == [("tx000", answer["thumbnail"])]:
        _pass("rumble.fills_empty_thumbnail")
    else:
        _fail("rumble.fills_empty_thumbnail", f"{db.thumbs}")

    db = _StubDB(_rows(RUMBLE_BACKFILL_BATCH + 4))
    resolver = _StubResolver(lambda u: rumble.RumbleUnavailable("probe outage"))
    stub = _Stub(db, resolver)
    try:
        Indexer._backfill_rumble_media(stub)
        aborted = False
    except rumble.RumbleUnavailable:
        aborted = True
    if aborted and len(resolver.calls) == 1 and not stub._rumble_skip and not db.metas:
        _pass("rumble.outage_aborts_pass")
    else:
        _fail("rumble.outage_aborts_pass", f"aborted={aborted} calls={len(resolver.calls)}")

    # ── the architectural boundary ────────────────────────────────────────
    mp_path = os.path.join("/opt/mirage", "indexer", "message_processor.py")
    with open(mp_path, "r", encoding="utf-8") as fh:
        mp_src = fh.read()
    leaked = [tok for tok in ("import rumble", "from indexer.rumble", "rumble.") if tok in mp_src]
    if leaked:
        _fail("rumble.absent_from_message_path", f"message_processor.py references the resolver: {leaked}")
    else:
        _pass("rumble.absent_from_message_path")

    # ── the client contract ───────────────────────────────────────────────
    # The backend strips anything it does not recognise out of media_meta, so
    # an embed id that does not survive sanitising never reaches a client and
    # the fix silently does nothing.
    backend_src = "/opt/mirage/web/backend"
    if backend_src not in sys.path:
        sys.path.insert(0, backend_src)
    try:
        from routes.public import _sanitize_media_meta_list
    except Exception as e:
        _skip("rumble.embed_survives_backend_sanitizer", f"backend modules not importable: {e}")
        _sanitize_media_meta_list = None

    sanitize_cases = [
        ([{"embed": "v78xa1o"}], [{"embed": "v78xa1o"}]),
        ([{"w": 320, "h": 180, "embed": "uABC.v1"}], [{"w": 320, "h": 180, "embed": "uABC.v1"}]),
        ([{"embed": "../../evil"}], [{}]),
        ([{"embed": '"><script>'}], [{}]),
        ([{"embed": "x" * 99}], [{}]),
        ([{"embed": 123}], [{}]),
        ([{"w": 320, "h": 180}], [{"w": 320, "h": 180}]),
    ]
    if _sanitize_media_meta_list is not None:
        bad = [f"{raw} -> {_sanitize_media_meta_list(raw)}" for raw, want in sanitize_cases if _sanitize_media_meta_list(raw) != want]
        if bad:
            _fail("rumble.embed_survives_backend_sanitizer", "; ".join(bad))
        else:
            _pass("rumble.embed_survives_backend_sanitizer", cases=len(sanitize_cases))

    # The clients must never build an embed from the posted URL. That is the
    # bug: watch id v7b3y1w embeds "Tokyo Revengers", not "Outlaws".
    guessers = []
    for theme in ("default", "onyx", "bluemoon", "oldreddit"):
        path = os.path.join("/opt/mirage/web/frontend/src/themes", theme, "components/InlineMedia.js")
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        if "buildRumbleEmbedUrl(rumbleId" in src:
            guessers.append(theme)
    if guessers:
        _fail("rumble.client_never_guesses_embed_id", f"themes still building an embed from the URL id: {guessers}")
    else:
        _pass("rumble.client_never_guesses_embed_id")


def test_tx_index(backend: str):
    """Verify tx_index table behaviour: successful non-post/vote txs are indexed,
    failed txs (same-nonce) are indexed with error details, and the old tx_receipts
    table is dropped.
    """

    free = WALLETS.get("free")
    sub1 = WALLETS.get("sub1")
    if not free or not sub1:
        _skip("tx_index.setup", "free/sub1 wallets not available")
        return

    _debug("tx_index: begin")
    free_addr = str(free.address())
    sub2_addr = str(WALLETS["sub2"].address())
    agent1_addr = str(WALLETS["agent1"].address())
    agent2_addr = str(WALLETS["agent2"].address())

    # Use sub1 (subscriber, level>=1) as actor — free (tier 0) has low limits.

    def _pick_unfollowed_user() -> str:
        code, data = _get(f"{backend}/api/get_user_followed", {"address": str(sub1.address())})
        if code != 200:
            _fail("tx_index.follow_user.target_lookup", f"code={code} data={data}")
            return ""
        users = (data or {}).get("followed_users") or (data or {}).get("users") or []
        candidates = [free_addr, sub2_addr, agent1_addr, agent2_addr]
        for addr in candidates:
            if not any(addr.lower() in json.dumps(u).lower() for u in users):
                return addr
        _fail("tx_index.follow_user.target_lookup", "no unfollowed target available")
        return ""

    # ── 1. Successful non-post/vote tx is resolvable via tx_index ─────

    bio_resp = _do_set_biography(backend, sub1, f"txidx bio {_rand_str(6)}", skip_pow=True)
    if not isinstance(bio_resp, dict):
        _fail("tx_index.success_write", f"set_biography submit failed: {bio_resp}")
    else:
        bio_txh_raw = bio_resp.get("tx_hash")
        bio_txh = str(bio_txh_raw).lower() if bio_txh_raw else ""
        if not bio_txh or len(bio_txh) != 64:
            _fail("tx_index.success_write", f"set_biography submit failed: {bio_resp}")
        else:
            status = _wait_tx_status(backend, bio_txh, expect_type="set_biography", require_details=False)
            if status and status.get("found") and status.get("indexed") and status.get("success") is True:
                _pass("tx_index.success_write", tx_type=status.get("tx_type"))
            else:
                _fail("tx_index.success_write", f"status={status}")

    # ── 2. Successful tx has correct tx_type field ────────────────────

    follow_target = _pick_unfollowed_user()
    if not follow_target:
        return
    follow_resp = _do_follow_user(backend, sub1, follow_target, follow=True, skip_pow=True)
    if not isinstance(follow_resp, dict):
        _fail("tx_index.tx_type_correct", f"follow submit failed: {follow_resp}")
    else:
        follow_txh_raw = follow_resp.get("tx_hash")
        follow_txh = str(follow_txh_raw).lower() if follow_txh_raw else ""
        if not follow_txh or len(follow_txh) != 64:
            _fail("tx_index.tx_type_correct", f"follow submit failed: {follow_resp}")
        else:
            fstatus = _wait_tx_status(backend, follow_txh, expect_type="follow_user", require_details=False)
            if fstatus and fstatus.get("tx_type") == "follow_user":
                _pass("tx_index.tx_type_correct", tx_type="follow_user")
            else:
                _fail("tx_index.tx_type_correct", f"status={fstatus}")

    # Clean up the follow, and wait for the unfollow to be *indexed* rather than
    # merely committed. The replay pair below re-follows this same target, and
    # the backend refuses a duplicate follow from its own indexed view before it
    # ever builds a transaction — so an unprojected unfollow makes both halves of
    # the pair fail with already_followed and the replay is never exercised.
    unfollow_resp = _do_follow_user(backend, sub1, follow_target, follow=False, skip_pow=True)
    unfollow_txh = str((unfollow_resp or {}).get("tx_hash", "") or "").lower()
    if not unfollow_txh:
        _fail("tx_index.failure_write.unfollow_cleanup", f"resp={unfollow_resp}")
        return
    if not _wait_tx_status(backend, unfollow_txh, expect_type="unfollow_user", require_details=False):
        _fail("tx_index.failure_write.unfollow_cleanup", f"unfollow {unfollow_txh[:16]} not indexed")
        return

    # ── 3. Failed tx (same-nonce) is recorded with success=false ──────

    try:
        _wait_next_block()
    except Exception as e:
        _fail("tx_index.failure_write.block_sync", str(e))
        return

    nonce = _fresh_nonce()
    r1 = _do_follow_user_with_nonce(backend, sub1, follow_target, nonce, follow=True, skip_pow=True)
    r2 = _do_follow_user_with_nonce(backend, sub1, follow_target, nonce, follow=True, skip_pow=True)
    if not isinstance(r1, dict) or not isinstance(r2, dict):
        _fail("tx_index.failure_write", f"resp1={r1} resp2={r2}")
        return
    t1_raw = r1.get("tx_hash")
    t2_raw = r2.get("tx_hash")
    t1 = str(t1_raw).lower() if t1_raw else ""
    t2 = str(t2_raw).lower() if t2_raw else ""

    if not t1 and not t2:
        _fail("tx_index.failure_write", f"both txs failed to submit: resp1={r1} resp2={r2}")
    elif (not t1) != (not t2):
        # One rejected at CheckTx — ensure we captured an error response
        fail_resp = r1 if not t1 else r2
        if fail_resp.get("code", 0) or fail_resp.get("error") or fail_resp.get("message") or fail_resp.get("reason"):
            _pass("tx_index.failure_write", note="one rejected at CheckTx")
        else:
            _fail("tx_index.failure_write", f"checktx fail_resp={fail_resp}")
    else:
        c1 = int(r1.get("code", 0) or 0)
        c2 = int(r2.get("code", 0) or 0)
        if c1 == 0 and c2 == 0:
            fail1 = _wait_tx_status_failure(backend, t1, expect_type="follow_user")
            fail2 = _wait_tx_status_failure(backend, t2, expect_type="follow_user")
            if bool(fail1) != bool(fail2):
                ftx = fail1 or fail2
                _pass("tx_index.failure_write", code=ftx.get("code"))
                if ftx.get("error_details"):
                    _pass("tx_index.failure_has_error_details")
                else:
                    _fail("tx_index.failure_has_error_details", f"fail={ftx}")
            else:
                _fail("tx_index.failure_write", f"fail1={bool(fail1)} fail2={bool(fail2)}")
        elif (c1 == 0) != (c2 == 0):
            fail_resp = r1 if c1 != 0 else r2
            if fail_resp.get("code", 0) and (
                fail_resp.get("reason") or fail_resp.get("message") or fail_resp.get("error")
            ):
                _pass("tx_index.failure_write", note="one rejected at CheckTx")
            else:
                _fail("tx_index.failure_write", f"checktx fail_resp={fail_resp}")
        else:
            _fail("tx_index.failure_write", f"both rejected c1={c1} c2={c2}")

    # Clean up
    try:
        _do_follow_user(backend, sub1, follow_target, follow=False, skip_pow=True)
    except Exception:
        pass

    # ── 4. Direct DB check: tx_index exists, tx_receipts is gone ──────

    if not _check_local_docker():
        _skip("tx_index.db_table_exists", "not running in local-docker")
        _skip("tx_index.tx_receipts_dropped", "not running in local-docker")
        return

    db_name = _get_indexer_db_name()

    rc, out = _docker_exec(
        f"""su - postgres -c "psql -d {db_name} -tAc 'SELECT count(*) FROM tx_index' 2>&1" """,
        timeout=10,
    )
    if rc == 0:
        try:
            cnt = int(out.strip())
            if cnt >= 0:
                _pass("tx_index.db_table_exists", row_count=cnt)
            else:
                _fail("tx_index.db_table_exists", f"unexpected count={cnt}")
        except ValueError:
            _fail("tx_index.db_table_exists", f"non-numeric output: {out}")
    else:
        _fail("tx_index.db_table_exists", f"rc={rc} out={out}")

    rc2, out2 = _docker_exec(
        f"""su - postgres -c "psql -d {db_name} -tAc 'SELECT count(*) FROM tx_receipts' 2>&1" """,
        timeout=10,
    )
    if rc2 != 0 or "does not exist" in out2:
        _pass("tx_index.tx_receipts_dropped")
    else:
        _fail("tx_index.tx_receipts_dropped", f"tx_receipts still exists: rc={rc2} out={out2}")
