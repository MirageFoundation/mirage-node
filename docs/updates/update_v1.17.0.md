# Mirage v1.17.0 Release Notes

### Stronger Foundations

Mirage v1.17.0 is a security-focused upgrade that hardens the chain, the bridge, and the orchestrator against vulnerabilities identified in a comprehensive audit. There are no new user-facing features — this release is about making everything that already exists more resilient.

### Subscription Engine Overhaul

The subscription renewal engine had a subtle bug where Agent-tier users could retain their level indefinitely after their subscription expired. v1.17.0 fixes this with a canonical level-to-tier mapping and includes a one-time migration that re-evaluates every non-free profile on the chain. Expired subscriptions are properly downgraded, ghost reserves are burned, and the subscription index is rebuilt from scratch so every future renewal cycle works correctly.

### Bridge Security

Bridge confirmations now defend against first-writer poisoning by scoping confirmations to the intended recipient and amount, so honest validators cannot be boxed out by a bad first write. Legacy bridge records are automatically migrated during the upgrade, and the threshold math is now deterministic across all nodes.

### Orchestrator Hardening

The Solana watcher is more secure on three fronts: it now only processes events emitted by the bridge program itself, it skips failed transactions, and it loads the signing keypair once at startup instead of re-reading the keyfile on every mint. The deduplication cache uses time-based eviction instead of periodic full clears, eliminating a window where events could be re-processed. Watcher failures are now propagated to the attestor process instead of silently dying.

### Governance Safety

Governance proposals continue to apply targeted updates without requiring a full configuration rewrite, keeping upgrades practical and focused. Critical save failures now surface immediately so issues cannot be silently masked during parameter changes.

### Upgrade Instructions

The upgrade name is v1.17.0-security and the binary must be built from the v1.17.0 tag. The migration re-evaluates profiles and rebuilds the subscription index, so expect a longer upgrade window on chains with many profiles, and no new governance parameters are introduced.
