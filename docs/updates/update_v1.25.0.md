# Mirage v1.25.0 Release Notes

### Why This Release Exists

On May 4, 2026 the production validator at mirage.talk forked off the network at block 4,349,996. A transient PebbleDB read failure inside the chain's parameter loader did not stop block production — instead the node silently fell back to default parameters while every peer kept using the stored ones, and the very next consensus round computed a different app hash than the rest of the network. The node was jailed within minutes and a state-sync recovery returned it to active duty the same day, but the underlying fault — silent fallbacks on consensus-critical decode paths — was the kind of bug that only takes one bad disk read to surface and one missed log line to misdiagnose. v1.25.0 removes that entire class of fault by inverting the previous "never halt the chain" policy on the paths where halting is strictly safer than diverging.

### Fail-Fast Consensus Decode

Reading and decoding chain parameters is now a fail-fast operation. If the parameter row is missing, unreadable, malformed, or fails validation, the call panics with a tagged CONSENSUS_FATAL message instead of substituting defaults. The same contract applies to the relay-gas fee deduction, the subscription renewal pass in EndBlock, and the proof-of-work ante's user-tier and reserve checks: any decode failure on a stored profile now rejects the offending transaction with a CONSENSUS_FATAL error rather than quietly routing it through the wrong code branch. Peers seeing the same corrupt bytes reject identically, so consensus is preserved without silent skew. The trade-off is honest and intentional — a clean halt is detected by the divergence watchdog shipped in v1.24, which state-syncs the node back to a healthy snapshot in minutes, while a silent divergence can sit undetected for hours.

### On-Chain Recent-Block Window For PoW

The proof-of-work ante validates that an envelope's last_block_hash references a recently committed block. In v1.24 that window of accepted block hashes was kept as a per-process in-memory cache, which meant a freshly restarted node started with an empty cache and rejected envelopes that warm peers happily accepted — a non-deterministic behavior gap that could turn a routine restart into a fork. v1.25.0 moves the window into on-chain state under a new key recent_block_hashes, written every BeginBlock from the previous block's hash and bounded in length by the existing block_hash_window parameter. Acceptance is now identical across restarts and across peers by construction, and the in-memory cache is gone for good.

### Stronger Invariants In EndBlock

EndBlock used to swallow iterator failures from the expired-subscriptions index and continue. v1.25.0 propagates those errors instead. A failure here is a state-store fault that affects every node identically and the safest response is the same as for the params and profile paths: halt cleanly, get noticed, and let the watchdog state-sync. The non-consensus-critical writes inside EndBlock — pruning expired nonces, adjusting dynamic difficulty, recording low-usage counters — keep their previous "log and try again next block" behavior because their failure modes are local and their state simply doesn't update for one tick.

### Brief Upgrade-Time UX Dip

Because the recent-block-hash window now lives in chain state and starts empty at the upgrade height, PoW envelopes that reference a pre-upgrade block hash will be rejected for roughly the first ten blocks after the switch — the time it takes BeginBlock to refill the window. Wallets and clients automatically retry with the new last_block_hash, so the user-visible effect is at worst a single retry on a post under construction. There is no on-chain state migration, no new chain parameter, no new module store, and no deploy-side migration. The upgrade is state-machine-breaking in the strict sense — the new behavior diverges from old binaries on the first edge case — and must therefore run as a coordinated network upgrade.

### Operator Notes

The new fail-fast paths are tagged with CONSENSUS_FATAL prefixes for grep-friendly triage, and the operator runbook at docs/troubleshooting/incident-recovery.md section 2.2 now documents what each tag means, when it should fire, and what the watchdog will do automatically. Verification after the upgrade is straightforward: scripts/verify_upgrade.py confirms the handler ran, scans the latest node log for unexpected CONSENSUS_FATAL panics, checks the indexer for fresh blocks to prove liveness, and cross-checks the frontend version. If a CONSENSUS_FATAL line ever appears in normal operation that is not a deliberate corruption test, that is a real bug worth opening — the new contract is that those paths fail loudly so operators can find them.
