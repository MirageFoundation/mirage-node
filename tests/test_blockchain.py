#!/usr/bin/env python3
"""
Mirage Blockchain Direct-Submit Test Suite.

Exercises chain-level defenses by submitting relay-style transactions
directly to the chain (bypassing the backend).

Run:
    docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in \
    /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage \
    python3 tests/test_blockchain.py [--category NAME]'

Host execution is rejected by tests.common.run_suite.
"""
import os
import sys

if __name__ == "__main__" and not os.path.isfile("/.dockerenv"):
    print("ABORT: tests/test_blockchain.py can only run inside the local Docker testnet container.")
    print(
        "Run: docker exec mirage bash -lc 'cd /opt/mirage && set -a; "
        'for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; '
        "PYTHONPATH=/opt/mirage python3 tests/test_blockchain.py'"
    )
    raise SystemExit(1)

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.common import _debug, _COLOR_RED, _COLOR_RESET, run_suite
from tests.blockchain_helpers import (
    _VALIDATOR_ADDR,
    _GOV_MODULE_ADDR,
    _validate_validator_funds,
    _get_validator_account_address,
    _get_gov_module_address,
)
import tests.blockchain_helpers as bh

from tests.cases.test_blockchain_envelope import (
    test_relay_sig,
    test_envelope_replay,
    test_mandatory_nonce,
    test_envelope_fields,
)
from tests.cases.test_blockchain_pow import test_pow
from tests.cases.test_blockchain_chain_rules import (
    test_authority,
    test_fee,
    test_c1_unauthorized_gas_payer,
    test_staking,
    test_msg_validation,
    test_msg_format,
    test_malicious_inputs,
)
from tests.cases.test_blockchain_tiers import (
    test_tier_enforcement,
    test_subscribe_validation,
    test_subscribe_gift_extends_expiry,
    test_tier_features,
)
from tests.cases.test_blockchain_governance import test_governance_reject, test_direct_bank
from tests.cases.test_blockchain_params import (
    test_params_schema,
    test_mint_split_params,
)
from tests.cases.test_blockchain_features import (
    test_chain_auto_renewal,
    test_biography,
    test_annotate_chain,
    test_security,
    test_send_tokens_raw_log_present,
)
from tests.cases.test_blockchain_net_tags import test_net_tags_chain
from tests.cases.test_blockchain_curation import test_curation_chain

ALL_CATEGORIES = {
    "net_tags_chain": test_net_tags_chain,
    "relay_sig": test_relay_sig,
    "pow": test_pow,
    "authority": test_authority,
    "fee": test_fee,
    "c1_gas_payer": test_c1_unauthorized_gas_payer,
    "staking": test_staking,
    "msg_validation": test_msg_validation,
    "direct_bank": test_direct_bank,
    "msg_format": test_msg_format,
    "malicious_inputs": test_malicious_inputs,
    "tier_enforcement": test_tier_enforcement,
    "auto_renewal": test_chain_auto_renewal,
    "governance": test_governance_reject,
    "params_schema": test_params_schema,
    "mint_split": test_mint_split_params,
    "subscribe_validation": test_subscribe_validation,
    "subscribe_gift_extends": test_subscribe_gift_extends_expiry,
    "tier_features": test_tier_features,
    "biography": test_biography,
    "annotate_chain": test_annotate_chain,
    "security": test_security,
    "send_tokens_raw_log": test_send_tokens_raw_log_present,
    "envelope_replay": test_envelope_replay,
    "mandatory_nonce": test_mandatory_nonce,
    "envelope_fields": test_envelope_fields,
    "curation": test_curation_chain,
}

STATELESS_CATEGORIES = {
    "authority",
    "fee",
    "c1_gas_payer",
    "staking",
    "malicious_inputs",
    "tier_enforcement",
    "governance",
    "subscribe_validation",
    "relay_sig",
    "pow",
    "msg_format",
    "direct_bank",
    "biography",
    "annotate_chain",
    "envelope_fields",
    "params_schema",
    "net_tags_chain",
}

# Source probes from the validator key; no suite wallets needed.
WALLETLESS_CATEGORIES = {
    "params_schema",
}


def _pre_run(backend: str) -> int | None:
    """Blockchain-specific setup after wallet creation."""
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
        "Mirage Blockchain Direct-Submit Test Suite",
        ALL_CATEGORIES,
        STATELESS_CATEGORIES,
        pre_run_hook=_pre_run,
        walletless_categories=WALLETLESS_CATEGORIES,
    )


if __name__ == "__main__":
    raise SystemExit(main())
