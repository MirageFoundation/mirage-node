#!/usr/bin/env python3
"""
Slow / fill-heavy checks that do not belong in the rehearsal suites.

Cap fills, indexer projection, and governance mask round-trips spend minutes
of chain time. Rehearsal runs tests/test_backend.py and tests/test_blockchain.py
only. Run this suite when you want the full picture.

Run:
    docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in \
    /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage \
    python3 tests/test_extended.py [--category NAME]'
"""
import os
import sys

if __name__ == "__main__" and not os.path.isfile("/.dockerenv"):
    print("ABORT: tests/test_extended.py can only run inside the local Docker testnet container.")
    print(
        "Run: docker exec mirage bash -lc 'cd /opt/mirage && set -a; "
        'for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; '
        "PYTHONPATH=/opt/mirage python3 tests/test_extended.py'"
    )
    raise SystemExit(1)

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.common import _debug, _COLOR_RED, _COLOR_RESET, run_suite
from tests.blockchain_helpers import (
    _get_validator_account_address,
    _get_gov_module_address,
    _validate_validator_funds,
)
import tests.blockchain_helpers as bh

from tests.cases.test_backend_social import test_hard_cap_vs_deque, test_indexer_deque_storage
from tests.cases.test_backend_indexer import test_indexer, test_tx_index, test_indexer_topic_edit
from tests.cases.test_blockchain_social import (
    test_follow_limits,
    test_hard_cap_vs_deque as test_chain_hard_cap_vs_deque,
)
from tests.cases.test_blockchain_params import test_params_mask_governance
from tests.cases.test_blockchain_chain_rules import test_block_list_cap_fills

ALL_CATEGORIES = {
    "hard_cap_vs_deque": test_hard_cap_vs_deque,
    "indexer_deque": test_indexer_deque_storage,
    "indexer": test_indexer,
    "tx_index": test_tx_index,
    "indexer_topic_edit": test_indexer_topic_edit,
    "follow_limits": test_follow_limits,
    "chain_hard_cap_vs_deque": test_chain_hard_cap_vs_deque,
    "block_list_cap_fills": test_block_list_cap_fills,
    "params_mask": test_params_mask_governance,
}

# Categories that must run alone. The cap fills are heavy but wallet-scoped, so
# they are wallet-bound rather than exclusive.
EXCLUSIVE_CATEGORIES = {
    "params_mask",  # masked governance proposal mutates params, then restores them
}

# params_mask uses the validator key only.
WALLETLESS_CATEGORIES = {
    "params_mask",
}

# Every category is a release gate. A test that may skip without failing the
# release is a test nobody relies on, and the answer to that is to delete it,
# not to leave it in the suite reporting green. Skips are still printed with
# their reason; they just end the run non-zero.
RELEASE_GATE_CATEGORIES = frozenset(ALL_CATEGORIES)


def _pre_run(backend: str) -> int | None:
    try:
        bh._VALIDATOR_ADDR = _get_validator_account_address(backend)
        bh._GOV_MODULE_ADDR = _get_gov_module_address()
        _debug(f"validator_addr={bh._VALIDATOR_ADDR}")
        _debug(f"gov_module_addr={bh._GOV_MODULE_ADDR}")
    except Exception as e:
        print(f"\n{_COLOR_RED}ABORT: Cannot resolve validator/gov addresses: {e}{_COLOR_RESET}")
        return 1

    if not _validate_validator_funds():
        print(f"\n{_COLOR_RED}ABORT: Validator fee payer is underfunded.{_COLOR_RESET}")
        return 1
    return None


def main() -> int:
    return run_suite(
        "Mirage Extended Test Suite",
        ALL_CATEGORIES,
        EXCLUSIVE_CATEGORIES,
        pre_run_hook=_pre_run,
        no_skip_categories=RELEASE_GATE_CATEGORIES,
        walletless_categories=WALLETLESS_CATEGORIES,
    )


if __name__ == "__main__":
    raise SystemExit(main())
