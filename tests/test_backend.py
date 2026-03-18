#!/usr/bin/env python3
"""
Mirage Backend Test Suite — comprehensive end-to-end tests.

Run:
    conda activate mirage-node
    python tests/test_backend.py [--backend URL] [--category NAME]
"""
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.common import run_suite
from tests.cases.test_backend_infra import (
    test_params,
    test_search,
    test_reports,
    test_tx_status,
    test_tx_status_non_post_vote,
    test_failed_tx_status,
    test_tx_status_matrix,
    test_failed_tx_non_post_vote,
)
from tests.cases.test_backend_accounts import test_account, test_profile_fields, test_upgrade_level_validation
from tests.cases.test_backend_content import (
    test_post_lifecycle,
    test_comments,
    test_media,
    test_content_limits,
    test_annotate,
    test_edit_target_immutability,
)
from tests.cases.test_backend_social import test_social_graph, test_hard_cap_vs_deque, test_indexer_deque_storage
from tests.cases.test_backend_tokens import test_pow, test_tokens
from tests.cases.test_backend_subscriptions import test_subscriber, test_auto_renewal, test_tier_config_api
from tests.cases.test_backend_edge_cases import test_edge_cases, test_frontend_bypass, test_rate_limit
from tests.cases.test_backend_security import test_security, test_validation
from tests.cases.test_backend_agents import test_agents, test_agent_behavior
from tests.cases.test_backend_indexer import test_indexer, test_tx_index

ALL_CATEGORIES = {
    "params": test_params,
    "account": test_account,
    "post": test_post_lifecycle,
    "comments": test_comments,
    "social": test_social_graph,
    "pow": test_pow,
    "subscriber": test_subscriber,
    "search": test_search,
    "edge": test_edge_cases,
    "security": test_security,
    "validation": test_validation,
    "tokens": test_tokens,
    "agents": test_agents,
    "media": test_media,
    "auto_renewal": test_auto_renewal,
    "reports": test_reports,
    "frontend_bypass": test_frontend_bypass,
    "rate_limit": test_rate_limit,
    "hard_cap_vs_deque": test_hard_cap_vs_deque,
    "tier_config_api": test_tier_config_api,
    "upgrade_validation": test_upgrade_level_validation,
    "indexer_deque": test_indexer_deque_storage,
    "content_limits": test_content_limits,
    "profile_fields": test_profile_fields,
    "agent_behavior": test_agent_behavior,
    "annotate": test_annotate,
    "edit_target": test_edit_target_immutability,
    "tx_status": test_tx_status,
    "tx_status_npv": test_tx_status_non_post_vote,
    "tx_status_matrix": test_tx_status_matrix,
    "failed_tx": test_failed_tx_status,
    "failed_tx_npv": test_failed_tx_non_post_vote,
    "indexer": test_indexer,
    "tx_index": test_tx_index,
}

STATELESS_CATEGORIES = {
    "params",
    "search",
    "tier_config_api",
}


def main() -> int:
    return run_suite("Mirage Local Test Suite", ALL_CATEGORIES, STATELESS_CATEGORIES)


if __name__ == "__main__":
    raise SystemExit(main())
