from __future__ import annotations

import json
import os
import re
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
    _wait_tx_deliver,
    _wait_tx_status,
    _wait_tx_status_failure,
    _wait_next_block,
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
        _fail(
            "indexer.params_pow_base_bits_present",
            f"pow_base_bits={params.get('pow_base_bits') if isinstance(params, dict) else None}",
        )

    # 3.7 chain_params in indexer DB contains both renamed proto keys and
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

    # Clean up follow
    try:
        _do_follow_user(backend, sub1, follow_target, follow=False, skip_pow=True)
    except Exception:
        pass

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
        _fail("tx_index.failure_write", "both txs failed to submit")
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
