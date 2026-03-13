# Mirage v1.20.0 Release Notes

### Mandatory Replay Protection

The temporary legacy compatibility window from v1.19.0 is now closed. Every relay message must include an envelope nonce greater than zero. Messages with a missing or zero nonce are rejected before signature verification even runs. This restores strict replay protection across the entire network for all message types — posts, votes, comments, follows, awards, tokens, deletions, and everything else that goes through the relay envelope.

All clients, bots, and integrations that were updated for v1.18.0 continue to work without changes. Anything still relying on the v1.19.0 legacy path will stop working after this upgrade.

### Disk Usage Cleanup

CometBFT's built-in transaction index has been switched from `kv` to `null`. The `tx_index.db` directory grows without bound on every node and serves no purpose for non-archive deployments. The deploy migration that ships with this release automatically deletes the existing `tx_index.db` directory on each node, reclaiming the disk space. The `tx_index.db` store is also removed from the PebbleDB compaction list since there is nothing left to compact.

### Orchestrator Hard-Disable

The bridge orchestrator is not in use while the Solana bridge is offline. Rather than leave the binary runnable in a dormant state, v1.20.0 adds a panic guard at the very top of the orchestrator's main function. The binary prints a clear message and exits immediately if anyone tries to start it. The entrypoint script also gates orchestrator startup behind an explicit `ORCHESTRATOR_ENABLED=true` environment variable, which defaults to `false`.

The original orchestrator logic is preserved in the codebase and can be re-enabled by removing the panic guard once the bridge replacement is ready and approved.

### Input Validation Hardening

The backend API now performs stricter type and range validation on the `envelope_nonce` field, rejecting non-scalar types, strings that cannot be parsed as positive integers, and values that exceed the uint64 range. This ensures garbage inputs are caught with a clear 400 response instead of propagating to the chain layer.

### Upgrade Instructions

The upgrade name is `v1.20.0` and the binary must be built from the `v1.20.0` tag. The on-chain migration logs operator action reminders but requires no data migration. The deploy migration handles `tx_index.db` cleanup and sets `ORCHESTRATOR_ENABLED=false` automatically. All relay clients must already be sending `envelope_nonce > 0` — no client changes are needed if they were updated for v1.18.0.
