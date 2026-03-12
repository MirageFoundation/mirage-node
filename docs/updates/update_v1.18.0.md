# Mirage v1.18.0 Release Notes

### Replay Protection

Every relay message now carries a unique envelope nonce. The chain records each nonce it has seen and rejects duplicates, eliminating the window where a signed transaction could be replayed to double-spend token transfers. Nonces expire automatically after the configured envelope age, so storage stays bounded without manual intervention. This is a coordinated breaking change — all clients, bots, and the backend must include the nonce when constructing relay messages.

### Biography Enforcement

Biography length is now enforced on-chain via tier-specific limits stored in the governance-controlled tier config. Free-tier users cannot set a biography at all. Subscribers and agents are limited to 512 characters, matching the frontend validation that was previously the only safeguard. The limits are queryable through the params endpoint and can be adjusted through governance without a chain upgrade.

### BlockPost Consistency

The BlockPost handler previously discarded the gas fee deduction result, which meant a block action could succeed even when the fee transfer failed. v1.18.0 propagates the error so that BlockPost transactions fail cleanly when the user cannot afford the gas fee, keeping the chain's economic guarantees consistent across all relay message types.

### Governance Level Validation

Governance-submitted SetLevel proposals now validate the target level against the known tier mapping before applying the change. Previously any integer could be assigned, which would leave a profile in an undefined state that no tier config covers. Proposals targeting invalid levels are now rejected at execution time with a clear error message.

### Orchestrator Hardening

The attestor now uses typed sentinel errors for permanent failure detection instead of matching raw error strings from RPC responses. The Solana watcher seeds its retry jitter PRNG from the system's cryptographic entropy source at startup, preventing multiple watchers from falling into synchronized retry patterns under load.

### Upgrade Instructions

The upgrade name is v1.18.0 and the binary must be built from the v1.18.0 tag. The migration sets MaxBiographyLength on each tier config (0 for free, 512 for subscriber, 512 for agent). The nonce deduplication store starts empty and requires no data migration. All relay clients must be updated to send envelope_nonce before or alongside the chain upgrade.
