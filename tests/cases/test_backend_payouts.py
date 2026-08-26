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


def test_payout_transport(backend: str):
    _assert_payouts_gone(backend, "payout_transport")


def test_payout_reconciliation(backend: str):
    _assert_payouts_gone(backend, "payout_reconciliation")


def test_payout_release_rules(backend: str):
    _assert_payouts_gone(backend, "payout_release_rules")


def test_payout_claim_gate(backend: str):
    _assert_payouts_gone(backend, "payout_claim_gate")
