# Mirage v1.17.0 Release Notes

### Stronger Foundations

Mirage v1.17.0 is a security-focused upgrade that hardens the chain, the bridge, and the orchestrator against vulnerabilities identified in a comprehensive audit. There are no new user-facing features — this release is about making everything that already exists more resilient.

### Subscription Engine Overhaul

The subscription renewal engine had a subtle bug where Agent-tier users could retain their level indefinitely after their subscription expired. This happened because the tier lookup used an array-length check that didn't account for how user levels map to tier indices. v1.17.0 fixes this with a canonical level-to-tier mapping and includes a one-time migration that re-evaluates every non-free profile on the chain. Expired subscriptions are properly downgraded, ghost reserves are burned, and the subscription index is rebuilt from scratch so every future renewal cycle works correctly.

### Bridge Security

The bridge attestation system now prevents first-writer poisoning — a scenario where a malicious validator could create an attestation with wrong parameters before honest validators could attest. Attestation records are now keyed by the burn parameters (recipient and amount), so each unique combination has its own record. The threshold math has been upgraded from floating-point to integer basis-point arithmetic for deterministic consensus, and destination chain identifiers are validated more strictly.

### Orchestrator Hardening

The Solana watcher is more secure on three fronts: it now tracks program invocation context to only process events from the bridge program (preventing event forgery from other programs), it skips failed transactions, and it loads the signing keypair once at startup instead of re-reading the keyfile on every mint. The deduplication cache uses time-based eviction instead of periodic full clears, eliminating a window where events could be re-processed. Watcher failures are now propagated to the attestor process instead of silently dying.

### Ante Handler Improvements

MsgDeleteUser is now fully routed through the relay signature verification chain with PoW enforcement, closing a gap where account deletions could bypass the relay ante pipeline. The PoW validator no longer leaks internal state in error messages, and a data race on difficulty parameters is fixed with proper locking. ProcessProposal performs basic transaction validation instead of unconditionally accepting all proposals.

### Governance Safety

The UpdateParams handler now requires a complete parameter set from governance proposals rather than merging non-zero fields onto existing parameters. This prevents the old behavior where it was impossible to explicitly set a parameter to zero through governance. Relay gas fee deductions now fail hard on save errors instead of silently swallowing them.

### Upgrade Instructions

- **Upgrade name**: `v1.17.0-security`
- Binary must be built from the v1.17.0 tag
- The migration re-evaluates all profiles and rebuilds the subscription index; expect slightly longer upgrade execution on chains with many profiles
- No new governance parameters; existing parameters are preserved
