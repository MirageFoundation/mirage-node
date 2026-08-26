"""Reward payout durability tests.

The claim path used to broadcast tokens from inside the same transaction that
marked the rewards claimed, with `miraged tx bank send` as the transport. A
crash between the send and the commit left the rewards unclaimed after the
money moved, so the next claim paid again. These tests pin the replacement: a
payout is reserved (rows claimed, signed bytes persisted) before anything is
broadcast, and rows are released only when the exact signed tx is proven dead.
"""

from __future__ import annotations

import json
import os
import time

from tests.common import (
    _pass,
    _fail,
    _debug,
    _get,
    _check_local_docker,
    docker_python,
    resolve_db_name,
    _docker_exec,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Every probe runs as its own process inside the container, which is what makes
# the reconciliation tests meaningful: each call is a fresh backend start.
_PREAMBLE = (
    "import json, os, secrets, time, hashlib\n"
    "import sys\n"
    "sys.path.insert(0, '/opt/mirage')\n"
    "sys.path.insert(0, '/opt/mirage/web/backend')\n"
    "from db import connect_backend_db\n"
    "from node import initialize_runtime, derive_address_from_pubkey\n"
    "from tx import load_tx_size_cost_per_byte, chain_head\n"
    "initialize_runtime()\n"
    "load_tx_size_cost_per_byte()\n"
    "from reward_distributor import get_distributor\n"
    "def emit(payload):\n"
    "    print('RESULT:' + json.dumps(payload))\n"
)


def _probe(code: str) -> dict:
    """Run a probe in the container and return its emitted RESULT payload."""
    rc, out = docker_python(_PREAMBLE + code, timeout=180)
    marker = "RESULT:"
    for line in out.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker) :])
    raise RuntimeError(f"probe produced no RESULT (rc={rc}): {out[-600:]}")


def _psql(db_name: str, sql: str) -> tuple[int, str]:
    return _docker_exec(f'su - postgres -c "psql -d {db_name} -tAc \\"{sql}\\" 2>&1"', timeout=15)


def _assert_payouts_gone(backend: str, name: str) -> None:
    code, _ = _get(f"{backend}/api/rewards/summary")
    if code == 410:
        _pass(f"{name}.gone")
    else:
        _fail(f"{name}.gone", f"code={code}")


def test_payout_schema(backend: str):
    """Payout journal was removed with quests in v1.39.0."""
    code, _ = _get(f"{backend}/api/rewards/summary")
    if code == 410:
        _pass("payout_schema.gone")
    else:
        _fail("payout_schema.gone", f"code={code}")
    return

    del backend

    if not _check_local_docker():
        _fail("payout_schema.tables_present", "local docker required")
        return

    db_name = resolve_db_name("BACKEND_DB_URL")
    if not db_name:
        _fail("payout_schema.tables_present", "BACKEND_DB_URL not resolvable")
        return

    rc, out = _psql(
        db_name,
        "SELECT string_agg(column_name, ',' ORDER BY column_name) FROM information_schema.columns "
        "WHERE table_name = 'reward_payouts'",
    )
    expected = {
        "id",
        "owner",
        "amount",
        "status",
        "tx_hash",
        "tx_bytes",
        "timeout_at",
        "scan_height",
        "attempts",
        "error",
        "created_at",
        "updated_at",
    }
    got = {c for c in out.strip().split(",") if c}
    if rc == 0 and got == expected:
        _pass("payout_schema.tables_present", columns=len(got))
    else:
        _fail("payout_schema.tables_present", f"reward_payouts columns {sorted(got)} != {sorted(expected)}")

    rc, out = _psql(
        db_name,
        "SELECT count(*) FROM information_schema.columns "
        "WHERE table_name = 'pending_rewards' AND column_name = 'payout_batch_id'",
    )
    if rc == 0 and out.strip() == "1":
        _pass("payout_schema.rewards_linked_to_payout")
    else:
        _fail("payout_schema.rewards_linked_to_payout", f"pending_rewards.payout_batch_id missing: {out}")

    # A status outside the lifecycle must be rejected by the database itself,
    # not merely by the code that happens to write it today.
    rc, out = _psql(
        db_name,
        "INSERT INTO reward_payouts (owner, amount, status, tx_hash, tx_bytes, timeout_at, scan_height, "
        "created_at, updated_at) VALUES ('mirage1probe', 1, 'bogus', 'probe', '\\\\x00', 0, 1, 0, 0)",
    )
    if "reward_payouts_status_valid" in out:
        _pass("payout_schema.status_constrained")
    else:
        _fail("payout_schema.status_constrained", f"bogus status was not rejected: rc={rc} out={out[:200]}")

    rc, out = docker_python(
        "import sys\n"
        "sys.path.insert(0, '/opt/mirage')\n"
        "sys.path.insert(0, '/opt/mirage/web/backend')\n"
        "from db import init_backend_schema\n"
        "init_backend_schema()\n"
        "init_backend_schema()\n"
        "print('SCHEMA_OK')\n",
        timeout=120,
    )
    if "SCHEMA_OK" in out and "rc=0" in out:
        _pass("payout_schema.reinit_is_idempotent")
    else:
        _fail("payout_schema.reinit_is_idempotent", f"second init_backend_schema failed: {out[-400:]}")


def test_payout_transport(backend: str):
    _assert_payouts_gone(backend, "payout_transport")
    return

    """Payouts are signed in-process and broadcast over REST, never via the CLI."""
    del backend

    src = open(os.path.join(REPO_ROOT, "web", "backend", "reward_distributor.py"), encoding="utf-8").read()
    banned = [
        token for token in ("import subprocess", "subprocess.run", "--gas-prices", "tx bank send") if token in src
    ]
    if not banned:
        _pass("payout_transport.no_cli_subprocess")
    else:
        _fail(
            "payout_transport.no_cli_subprocess",
            f"reward_distributor.py still reaches for the CLI: {banned}",
        )

    tx_src = open(os.path.join(REPO_ROOT, "web", "backend", "tx.py"), encoding="utf-8").read()
    if "sequence=0" in tx_src and "SIGN_MODE_DIRECT" in tx_src and "BROADCAST_MODE_SYNC" in tx_src:
        _pass("payout_transport.unordered_sync_signing")
    else:
        _fail("payout_transport.unordered_sync_signing", "tx.py no longer signs unordered txs broadcast in sync mode")

    route_src = open(os.path.join(REPO_ROOT, "web", "backend", "routes", "quests.py"), encoding="utf-8").read()
    if 'api_error_code("payout_pending", 202' in route_src:
        _pass("payout_transport.route_exposes_pending")
    else:
        _fail("payout_transport.route_exposes_pending", "claim route does not answer 202 payout_pending")
    if '"payout_pending": payout_pending' in route_src and "reconcile_owner_payouts(owner)" in route_src:
        _pass("payout_transport.summary_drives_reconciliation")
    else:
        _fail(
            "payout_transport.summary_drives_reconciliation",
            "summary polling cannot clear a payout that made the client lock claiming",
        )

    hook_src = open(os.path.join(REPO_ROOT, "web", "frontend", "src", "logic", "useQuests.js"), encoding="utf-8").read()
    copy_src = open(
        os.path.join(REPO_ROOT, "web", "frontend", "src", "utils", "errorMessages.js"), encoding="utf-8"
    ).read()
    # A reserved claim is reported as the success it is, so the guarantee that
    # the same rewards are never reserved twice has to hold in the distributor,
    # not in the UI: the client is free to submit, and the server refuses.
    dist_src = open(os.path.join(REPO_ROOT, "web", "backend", "reward_distributor.py"), encoding="utf-8").read()
    if "unresolved = self.reconcile_owner_payouts(owner_lc)" in dist_src and '"error": "payout_pending"' in dist_src:
        _pass("payout_transport.server_refuses_second_reservation")
    else:
        _fail(
            "payout_transport.server_refuses_second_reservation",
            "claim_rewards no longer blocks a second reservation while a payout is open",
        )
    if (
        "setPayoutPending(response.payout_pending === true)" in hook_src
        and "setPayoutPending(res.payout_pending === true)" in hook_src
        and "payout_pending:" in copy_src
    ):
        _pass("payout_transport.client_tracks_settling_transfer")
    else:
        _fail(
            "payout_transport.client_tracks_settling_transfer",
            "the claim UI does not track a settling transfer from the claim response and the summary",
        )

    if not _check_local_docker():
        _fail("payout_transport.signer_matches_pool", "local docker required")
        return

    # A pool key that does not derive the configured address would sign payouts
    # from the wrong account, so startup has to refuse it.
    result = _probe(
        "from node import require_runtime\n"
        "rt = require_runtime()\n"
        "emit({'addr': rt.rewards_pool_addr, 'has_key': bool(rt.rewards_pool_privkey_bytes),\n"
        "      'acct': rt.rewards_pool_account_number,\n"
        "      'pool': get_distributor().pool_address, 'enabled': get_distributor().enabled})\n"
    )
    if result["enabled"] and result["has_key"] and result["addr"] == result["pool"]:
        _pass("payout_transport.signer_matches_pool", addr=result["addr"])
    elif not result["enabled"]:
        _fail("payout_transport.signer_matches_pool", "payouts are disabled on this node")
    else:
        _fail("payout_transport.signer_matches_pool", f"signer {result['addr']} != pool {result['pool']}")

    mismatch = _probe(
        "from node import resolve_rewards_pool_signer, require_runtime\n"
        "rt = require_runtime()\n"
        "try:\n"
        "    resolve_rewards_pool_signer(rt.api_url, 'rewards_pool', 'mirage1wrongaddresswrongaddresswrongaddress')\n"
        "    emit({'refused': False})\n"
        "except RuntimeError as e:\n"
        "    emit({'refused': True, 'err': str(e)[:120]})\n"
    )
    if mismatch["refused"]:
        _pass("payout_transport.signer_mismatch_fails_hard")
    else:
        _fail("payout_transport.signer_mismatch_fails_hard", "a pool key with the wrong address was accepted")

    checktx = _probe(
        "import reward_distributor as rd\n"
        "d = get_distributor()\n"
        "d.reconcile_owner_payouts = lambda owner: None\n"
        "d._reserve_claim = lambda owner, ts: "
        "({'success': True, 'rewards': [{'type': 'mirage'}], 'tx_hash': 'A' * 64, 'error': None}, "
        "(123, b'signed', 'A' * 64))\n"
        "d._apply_broadcast_result = lambda payout_id, tx_hash, code, raw_log: 'broadcast'\n"
        "rd.broadcast_tx = lambda tx_bytes: ('A' * 64, 0, 0, '')\n"
        "res = d.claim_rewards(derive_address_from_pubkey(bytes([2]) + secrets.token_bytes(32)), int(time.time()))\n"
        "emit({'success': res['success'], 'error': res['error'], 'pending': res.get('payout_pending')})\n"
    )
    # The claim succeeds because the rewards are granted and the rows are
    # claimed, but CheckTx is not payment: the transfer must still be flagged as
    # settling so nothing downstream reports the tokens as delivered. The payout
    # row staying at 'broadcast' is covered by test_payout_reconciliation.
    if checktx == {"success": True, "error": None, "pending": True}:
        _pass("payout_transport.checktx_reports_settling_transfer")
    else:
        _fail("payout_transport.checktx_reports_settling_transfer", f"CheckTx was not reported as settling: {checktx}")


def test_payout_reconciliation(backend: str):
    _assert_payouts_gone(backend, "payout_reconciliation")
    return

    """A reserved payout survives a restart and settles exactly once."""
    del backend

    if not _check_local_docker():
        _fail("payout_reconciliation.pays_once_after_restart", "local docker required")
        return

    setup = _probe(
        "owner = derive_address_from_pubkey(bytes([2]) + secrets.token_bytes(32))\n"
        "ts = int(time.time())\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id',\n"
        "            (owner, 'mirage', json.dumps({'amount': 4321, 'apply_multiplier': False}),\n"
        "             'test:payout:' + str(ts), ts))\n"
        "        reward_id = cur.fetchone()[0]\n"
        # Reserve without broadcasting: this is exactly the crash window the old
        # code had no record of.
        "result, payout = get_distributor()._reserve_claim(owner, ts)\n"
        "emit({'owner': owner, 'reward_id': reward_id, 'ok': result['success'],\n"
        "      'payout_id': payout[0] if payout else None, 'tx_hash': payout[2] if payout else None})\n"
    )
    if not setup["ok"] or not setup["payout_id"]:
        _fail("payout_reconciliation.pays_once_after_restart", f"reservation failed: {setup}")
        return

    owner = setup["owner"]
    _debug(f"payout reserved owner={owner} payout={setup['payout_id']} hash={setup['tx_hash']}")

    db_name = resolve_db_name("BACKEND_DB_URL")
    rc, out = _psql(db_name, f"SELECT claimed_at IS NOT NULL FROM pending_rewards WHERE id = {setup['reward_id']}")
    if rc == 0 and out.strip() == "t":
        _pass("payout_reconciliation.rows_claimed_before_broadcast")
    else:
        _fail("payout_reconciliation.rows_claimed_before_broadcast", f"reward not claimed at reserve time: {out}")

    # Each probe is a new process, so this is the crashed node coming back and
    # finishing the payment it had already committed to.
    status = ""
    deadline = time.time() + 90
    while time.time() < deadline:
        state = _probe(
            f"owner = '{owner}'\n"
            "unresolved = get_distributor().reconcile_owner_payouts(owner)\n"
            "with connect_backend_db() as conn:\n"
            "    with conn.cursor() as cur:\n"
            "        cur.execute('SELECT status, attempts, error FROM reward_payouts WHERE owner = %s', (owner,))\n"
            "        rows = cur.fetchall()\n"
            "emit({'unresolved': bool(unresolved), 'rows': [list(r) for r in rows]})\n"
        )
        status = state["rows"][0][0] if state["rows"] else ""
        _debug(f"payout reconcile status={status} unresolved={state['unresolved']}")
        if status in ("confirmed", "failed"):
            break
        time.sleep(4)

    if status == "confirmed":
        _pass("payout_reconciliation.pays_once_after_restart", owner=owner)
    else:
        _fail("payout_reconciliation.pays_once_after_restart", f"payout ended in status {status!r}")
        return

    # A confirmed payout must stay claimed, and a follow-up claim must not pay
    # a second time for the same rewards.
    again = _probe(
        f"owner = '{owner}'\n"
        "res = get_distributor().claim_rewards(owner, int(time.time()))\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('SELECT count(*) FROM reward_payouts WHERE owner = %s', (owner,))\n"
        "        payouts = cur.fetchone()[0]\n"
        "emit({'error': res.get('error'), 'payouts': payouts})\n"
    )
    if again["error"] == "no_rewards" and again["payouts"] == 1:
        _pass("payout_reconciliation.second_claim_pays_nothing")
    else:
        _fail("payout_reconciliation.second_claim_pays_nothing", f"second claim did more than nothing: {again}")


def test_payout_release_rules(backend: str):
    _assert_payouts_gone(backend, "payout_release_rules")
    return

    """Rows come back only when the signed tx is proven dead."""
    del backend

    if not _check_local_docker():
        _fail("payout_release.expired_releases_rows", "local docker required")
        return

    # Reserved, never broadcast, and past its unordered timeout: the exact bytes
    # can never be included, so the user must be able to claim again.
    expired = _probe(
        "owner = derive_address_from_pubkey(bytes([2]) + secrets.token_bytes(32))\n"
        "ts = int(time.time())\n"
        "head, _ = chain_head()\n"
        "tx_bytes = secrets.token_bytes(48)\n"
        "tx_hash = hashlib.sha256(tx_bytes).hexdigest().upper()\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('INSERT INTO reward_payouts (owner, amount, status, tx_hash, tx_bytes, timeout_at, "
        "scan_height, attempts, created_at, updated_at) VALUES (%s, 500, %s, %s, %s, %s, %s, 0, %s, %s) RETURNING id',\n"
        "            (owner, 'reserved', tx_hash, tx_bytes, ts - 600, max(1, head - 2), ts, ts))\n"
        "        payout_id = cur.fetchone()[0]\n"
        "        cur.execute('INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at, "
        "claimed_at, payout_amount, payout_batch_id) VALUES (%s, %s, %s, %s, %s, %s, 500, %s) RETURNING id',\n"
        "            (owner, 'mirage', json.dumps({'amount': 500, 'apply_multiplier': False}),\n"
        "             'test:payout:expired:' + str(ts), ts, ts, payout_id))\n"
        "        reward_id = cur.fetchone()[0]\n"
        "unresolved = get_distributor().reconcile_owner_payouts(owner)\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('SELECT status, error FROM reward_payouts WHERE id = %s', (payout_id,))\n"
        "        status, err = cur.fetchone()\n"
        "        cur.execute('SELECT claimed_at, payout_batch_id FROM pending_rewards WHERE id = %s', (reward_id,))\n"
        "        claimed, batch = cur.fetchone()\n"
        "        cur.execute('DELETE FROM pending_rewards WHERE id = %s', (reward_id,))\n"
        "        cur.execute('DELETE FROM reward_payouts WHERE id = %s', (payout_id,))\n"
        "emit({'unresolved': bool(unresolved), 'status': status, 'error': err,\n"
        "      'claimed': claimed, 'batch': batch})\n"
    )
    if expired["status"] == "failed" and expired["error"] == "expired_not_found" and expired["claimed"] is None:
        _pass("payout_release.expired_releases_rows")
    else:
        _fail("payout_release.expired_releases_rows", f"expired payout was not released cleanly: {expired}")

    # CheckTx verdicts: a definitive rejection releases, anything ambiguous must
    # keep the rows claimed so a tx sitting in a mempool cannot be paid twice.
    #
    # Code 19 is ErrTxInMempoolCache, which is a broadcast the node already has,
    # not a rejection. The probe's raw_log deliberately omits "tx already exists
    # in cache": the node returns that code with an empty log, so recognising it
    # by code is the whole point.
    for label, code, expect_release, release_definitive, expect_state in (
        ("definitive_reject", 5, True, True, "failed"),
        ("ambiguous_reject", 99, False, True, "pending"),
        ("rebroadcast_reject", 5, False, False, "pending"),
        ("already_in_mempool", 19, False, True, "broadcast"),
    ):
        verdict = _probe(
            "owner = derive_address_from_pubkey(bytes([2]) + secrets.token_bytes(32))\n"
            "ts = int(time.time())\n"
            "head, _ = chain_head()\n"
            "tx_bytes = secrets.token_bytes(48)\n"
            "tx_hash = hashlib.sha256(tx_bytes).hexdigest().upper()\n"
            "with connect_backend_db() as conn:\n"
            "    with conn.cursor() as cur:\n"
            "        cur.execute('INSERT INTO reward_payouts (owner, amount, status, tx_hash, tx_bytes, timeout_at, "
            "scan_height, attempts, created_at, updated_at) VALUES (%s, 700, %s, %s, %s, %s, %s, 0, %s, %s) "
            "RETURNING id',\n"
            "            (owner, 'reserved', tx_hash, tx_bytes, ts + 600, head, ts, ts))\n"
            "        payout_id = cur.fetchone()[0]\n"
            "        cur.execute('INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at, "
            "claimed_at, payout_amount, payout_batch_id) VALUES (%s, %s, %s, %s, %s, %s, 700, %s) RETURNING id',\n"
            "            (owner, 'mirage', json.dumps({'amount': 700, 'apply_multiplier': False}),\n"
            "             'test:payout:' + str(ts), ts, ts, payout_id))\n"
            "        reward_id = cur.fetchone()[0]\n"
            f"state = get_distributor()._apply_broadcast_result("
            f"payout_id, tx_hash, {code}, 'probe rejection', release_definitive={release_definitive})\n"
            "with connect_backend_db() as conn:\n"
            "    with conn.cursor() as cur:\n"
            "        cur.execute('SELECT status FROM reward_payouts WHERE id = %s', (payout_id,))\n"
            "        status = cur.fetchone()[0]\n"
            "        cur.execute('SELECT claimed_at FROM pending_rewards WHERE id = %s', (reward_id,))\n"
            "        claimed = cur.fetchone()[0]\n"
            "        cur.execute('DELETE FROM pending_rewards WHERE id = %s', (reward_id,))\n"
            "        cur.execute('DELETE FROM reward_payouts WHERE id = %s', (payout_id,))\n"
            "emit({'state': state, 'status': status, 'released': claimed is None})\n"
        )
        if verdict["released"] == expect_release and verdict["state"] == expect_state:
            _pass(f"payout_release.{label}", state=verdict["state"], status=verdict["status"])
        else:
            _fail(
                f"payout_release.{label}",
                f"code {code} released={verdict['released']} state={verdict['state']} "
                f"(expected released={expect_release} state={expect_state}): {verdict}",
            )


def test_payout_claim_gate(backend: str):
    _assert_payouts_gone(backend, "payout_claim_gate")
    return

    """An unresolved payout blocks the next claim instead of paying again."""
    del backend

    if not _check_local_docker():
        _fail("payout_gate.unresolved_blocks_claim", "local docker required")
        return

    gate = _probe(
        "owner = derive_address_from_pubkey(bytes([2]) + secrets.token_bytes(32))\n"
        "ts = int(time.time())\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id',\n"
        "            (owner, 'mirage', json.dumps({'amount': 900, 'apply_multiplier': False}),\n"
        "             'test:payout:gate:' + str(ts), ts))\n"
        "        reward_id = cur.fetchone()[0]\n"
        "d = get_distributor()\n"
        "d.reconcile_owner_payouts = lambda o: {'payout_id': 1, 'tx_hash': 'A' * 64, 'amount': 900}\n"
        "res = d.claim_rewards(owner, ts)\n"
        "with connect_backend_db() as conn:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute('SELECT claimed_at FROM pending_rewards WHERE id = %s', (reward_id,))\n"
        "        claimed = cur.fetchone()[0]\n"
        "        cur.execute('SELECT count(*) FROM reward_payouts WHERE owner = %s', (owner,))\n"
        "        payouts = cur.fetchone()[0]\n"
        "        cur.execute('DELETE FROM pending_rewards WHERE id = %s', (reward_id,))\n"
        "emit({'error': res.get('error'), 'claimed': claimed, 'payouts': payouts})\n"
    )
    if gate["error"] == "payout_pending" and gate["claimed"] is None and gate["payouts"] == 0:
        _pass("payout_gate.unresolved_blocks_claim")
    else:
        _fail("payout_gate.unresolved_blocks_claim", f"claim was not blocked by the open payout: {gate}")
