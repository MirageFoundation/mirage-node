from __future__ import annotations

import re
import time

import requests

from tests.common import (
    _pass,
    _fail,
    _debug,
    _get,
    WALLETS,
)
from tests.backend_helpers import (
    _do_send_tokens,
    _wait_tx_deliver,
)


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
                    time.sleep(3)
                    code_post, post_data = _get(f"{backend}/api/get_user_status", {"address": sub2_addr})
                    post_bal = int((post_data or {}).get("balance", 0)) if code_post == 200 else None
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
        if isinstance(tiers, list) and len(tiers) >= 3:
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

        # 3.5 chain_config block_time present
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

    # 3.6 params pow_base_bits present and in range
    if isinstance(params, dict) and params.get("pow_base_bits") is not None:
        pb = int(params.get("pow_base_bits") or 0)
        if 1 <= pb <= 256:
            _pass("indexer.params_pow_base_bits_present", pow_base_bits=pb)
        else:
            _fail("indexer.params_pow_base_bits_present", f"pow_base_bits={pb}")
    else:
        _fail("indexer.params_pow_base_bits_present", f"pow_base_bits={params.get('pow_base_bits') if isinstance(params, dict) else None}")

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
        b24 = ns.get("burned_24h")
        if e24 is not None and b24 is not None and int(e24) >= 0 and int(b24) >= 0:
            _pass("indexer.network_stats_has_earned_burned", earned_24h=e24, burned_24h=b24)
        else:
            _fail("indexer.network_stats_has_earned_burned", f"earned_24h={e24} burned_24h={b24}")

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
        r_ts = requests.get(f"{backend}/api/get_total_supply", timeout=10)
        if r_ts.status_code == 200:
            total_supply = float(r_ts.text.strip())
            if total_supply > 0:
                _pass("indexer.total_supply_positive", total_supply=total_supply)
            else:
                _fail("indexer.total_supply_positive", f"total_supply={total_supply}")
        else:
            _fail("indexer.total_supply_positive", f"code={r_ts.status_code}")
    except Exception as e:
        _fail("indexer.total_supply_positive", str(e))

    # 5.2 circulating_supply (plain-text endpoint, not JSON)
    circ_supply = None
    try:
        r_cs = requests.get(f"{backend}/api/get_circulating_supply", timeout=10)
        if r_cs.status_code == 200:
            circ_supply = float(r_cs.text.strip())
            if circ_supply > 0:
                _pass("indexer.circulating_supply_positive", circulating_supply=circ_supply)
            else:
                _fail("indexer.circulating_supply_positive", f"circulating_supply={circ_supply}")
        else:
            _fail("indexer.circulating_supply_positive", f"code={r_cs.status_code}")
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
