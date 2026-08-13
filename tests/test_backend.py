#!/usr/bin/env python3
"""
Mirage Backend Test Suite — comprehensive end-to-end tests.

Run:
    docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in \
    /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage \
    python3 tests/test_backend.py [--category NAME]'

Host execution is rejected by tests.common.run_suite.
"""
import os
import sys

if __name__ == "__main__" and not os.path.isfile("/.dockerenv"):
    print("ABORT: tests/test_backend.py can only run inside the local Docker testnet container.")
    print(
        "Run: docker exec mirage bash -lc 'cd /opt/mirage && set -a; "
        'for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; '
        "PYTHONPATH=/opt/mirage python3 tests/test_backend.py'"
    )
    raise SystemExit(1)

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tests.common import run_suite
from tests.cases.test_backend_infra import (
    test_params,
    test_bootstrap,
    test_search,
    test_reports,
    test_tx_status,
    test_tx_status_non_post_vote,
    test_failed_tx_status,
    test_tx_status_matrix,
    test_failed_tx_non_post_vote,
    test_error_registry,
    test_indexer_fail_hard,
    test_indexer_profile_absent,
    test_block_hash_window_margin,
    test_node_join_bootstrap,
    test_runner_accounting,
)
from tests.cases.test_backend_accounts import test_account, test_profile_fields, test_subscribe_validation
from tests.cases.test_backend_content import (
    test_post_lifecycle,
    test_comments,
    test_media,
    test_content_limits,
    test_annotate,
    test_edit_target_immutability,
    test_seen_posts,
    test_image_impressions,
    test_upload_media,
    test_recent_content,
)
from tests.cases.test_backend_social import test_social_graph, test_hard_cap_vs_deque, test_indexer_deque_storage
from tests.cases.test_backend_tokens import test_pow, test_tokens
from tests.cases.test_backend_subscriptions import (
    test_subscriber,
    test_auto_renewal,
    test_tier_config_api,
    test_subscribe_gift_validation,
    test_subscribe_gift_agent,
)
from tests.cases.test_backend_edge_cases import test_edge_cases, test_frontend_bypass, test_rate_limit
from tests.cases.test_backend_security import (
    test_security,
    test_validation,
    test_relay_signing,
    test_envelope_timestamp_window,
    test_client_ip_trust,
    test_hash_salt_fail_hard,
    test_upload_body_bound,
    test_invite_code_hygiene,
    test_indexer_drift,
    test_fleet_url_validation,
    test_analytics_identity_trust,
)
from tests.cases.test_backend_authz import (
    test_route_authz_parity,
    test_admin_authz,
    test_reward_claim_authz,
    test_cross_user_reads,
)
from tests.cases.test_backend_agents import test_agents, test_agent_behavior
from tests.cases.test_backend_indexer import (
    test_indexer,
    test_tx_index,
    test_indexer_hardening,
    test_indexer_topic_edit,
)
from tests.cases.test_backend_stats import test_stats_admin_auth, test_stats_attribution, test_stats_pure
from tests.cases.test_backend_quests import test_quest_config, test_quest_assignment
from tests.cases.test_backend_payouts import (
    test_payout_schema,
    test_payout_transport,
    test_payout_reconciliation,
    test_payout_release_rules,
    test_payout_claim_gate,
)
from tests.cases.test_backend_push_outbox import (
    test_push_outbox_schema,
    test_push_outbox_enqueue,
    test_push_outbox_delivery,
    test_push_outbox_retry,
    test_push_outbox_cleanup,
)

ALL_CATEGORIES = {
    "params": test_params,
    "bootstrap": test_bootstrap,
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
    "relay_signing": test_relay_signing,
    "envelope_window": test_envelope_timestamp_window,
    "error_registry": test_error_registry,
    "indexer_fail_hard": test_indexer_fail_hard,
    "indexer_profile_absent": test_indexer_profile_absent,
    "block_hash_window": test_block_hash_window_margin,
    "node_join": test_node_join_bootstrap,
    "runner_accounting": test_runner_accounting,
    "route_authz": test_route_authz_parity,
    "admin_authz": test_admin_authz,
    "reward_claim_authz": test_reward_claim_authz,
    "cross_user_reads": test_cross_user_reads,
    "client_ip_trust": test_client_ip_trust,
    "hash_salt": test_hash_salt_fail_hard,
    "upload_bound": test_upload_body_bound,
    "invite_code_hygiene": test_invite_code_hygiene,
    "indexer_drift": test_indexer_drift,
    "tokens": test_tokens,
    "agents": test_agents,
    "media": test_media,
    "auto_renewal": test_auto_renewal,
    "reports": test_reports,
    "frontend_bypass": test_frontend_bypass,
    "rate_limit": test_rate_limit,
    "hard_cap_vs_deque": test_hard_cap_vs_deque,
    "tier_config_api": test_tier_config_api,
    "subscribe_validation": test_subscribe_validation,
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
    "indexer_hardening": test_indexer_hardening,
    "indexer_topic_edit": test_indexer_topic_edit,
    "tx_index": test_tx_index,
    "subscribe_gift_validation": test_subscribe_gift_validation,
    "subscribe_gift_agent": test_subscribe_gift_agent,
    "seen_posts": test_seen_posts,
    "image_impressions": test_image_impressions,
    "upload_media": test_upload_media,
    "recent_content": test_recent_content,
    "stats_admin_auth": test_stats_admin_auth,
    "stats_attribution": test_stats_attribution,
    "stats_pure": test_stats_pure,
    "quest_config": test_quest_config,
    "quest_assignment": test_quest_assignment,
    "fleet_url": test_fleet_url_validation,
    "analytics_identity": test_analytics_identity_trust,
    "payout_schema": test_payout_schema,
    "payout_transport": test_payout_transport,
    "payout_reconciliation": test_payout_reconciliation,
    "payout_release": test_payout_release_rules,
    "payout_gate": test_payout_claim_gate,
    "push_outbox_schema": test_push_outbox_schema,
    "push_outbox_enqueue": test_push_outbox_enqueue,
    "push_outbox_delivery": test_push_outbox_delivery,
    "push_outbox_retry": test_push_outbox_retry,
    "push_outbox_cleanup": test_push_outbox_cleanup,
}

STATELESS_CATEGORIES = {
    "params",
    "bootstrap",
    "search",
    "tier_config_api",
    "image_impressions",
    "upload_media",
    "stats_admin_auth",
    "stats_attribution",
    "stats_pure",
    "error_registry",
    "indexer_fail_hard",
    "block_hash_window",
    "indexer_hardening",
    "route_authz",
    "admin_authz",
    "cross_user_reads",
    "client_ip_trust",
    "hash_salt",
    "upload_bound",
    "invite_code_hygiene",
    "indexer_drift",
    "runner_accounting",
    "quest_config",
    "fleet_url",
    "analytics_identity",
    "payout_schema",
    "payout_transport",
    "payout_release",
    "payout_gate",
    # The other push outbox categories drive the shared outbox with their own
    # tick clock, so they run sequentially and never lease each other's rows.
    "push_outbox_schema",
}

# These categories use source probes, generated addresses, or direct database
# fixtures only. Running one of them must not create five wallets and broadcast
# setup transactions that the selected checks never consume.
WALLETLESS_CATEGORIES = {
    "stats_pure",
    "error_registry",
    "indexer_fail_hard",
    "indexer_profile_absent",
    "node_join",
    "block_hash_window",
    "route_authz",
    "client_ip_trust",
    "hash_salt",
    "upload_bound",
    "invite_code_hygiene",
    "runner_accounting",
    "quest_config",
    "quest_assignment",
    "fleet_url",
    "analytics_identity",
    "payout_schema",
    "payout_transport",
    "payout_reconciliation",
    "payout_release",
    "payout_gate",
    "push_outbox_schema",
    "push_outbox_enqueue",
    "push_outbox_delivery",
    "push_outbox_retry",
    "push_outbox_cleanup",
}

# Categories that guard a security or economic invariant. They must execute; a
# skip here means the invariant went unchecked, which is a failure, not a pass.
RELEASE_GATE_CATEGORIES = {
    "route_authz",
    "admin_authz",
    "reward_claim_authz",
    "cross_user_reads",
    "relay_signing",
    "envelope_window",
    "client_ip_trust",
    "hash_salt",
    "error_registry",
    "indexer_fail_hard",
    "indexer_profile_absent",
    "node_join",
    "block_hash_window",
    "invite_code_hygiene",
    "stats_pure",
    "runner_accounting",
    "quest_config",
    "quest_assignment",
    "fleet_url",
    "analytics_identity",
    "payout_schema",
    "payout_transport",
    "payout_reconciliation",
    "payout_release",
    "payout_gate",
    "push_outbox_schema",
    "push_outbox_enqueue",
    "push_outbox_delivery",
    "push_outbox_retry",
    "push_outbox_cleanup",
}


def main() -> int:
    return run_suite(
        "Mirage Local Test Suite",
        ALL_CATEGORIES,
        STATELESS_CATEGORIES,
        no_skip_categories=RELEASE_GATE_CATEGORIES,
        walletless_categories=WALLETLESS_CATEGORIES,
    )


if __name__ == "__main__":
    raise SystemExit(main())
