# Blockchain Security Review — Retest of 2026-08-07

**Retest of:** [`review-2026-08-07.md`](review-2026-08-07.md) — full `blockchain/` audit, 7 Medium, 11 Low, 7 Informational.
**Review baseline:** `dev` at `d9dbf87a` (`v1.32.4-1-gd9dbf87a`).
**Remediation baseline:** `dev` at `4acbf0b9` (`v1.33.10`). Ten releases landed between the review and the start of remediation; no blockchain remediation was among them, so every M and L finding was re-verified as present before being fixed.
**Retest state:** remediation implemented on `dev` for **v1.34.0**, a coordinated consensus upgrade. Not yet committed, tagged, or deployed at the time of writing.
**Scope of this document:** status of every Aug 7 finding, the test that proves each fix, and the residuals that remain accepted or deferred. Where this document and the original disagree about present-day state, **this one is authoritative**; the original is preserved as written.

> **Line references in the original are frozen at its baseline.** Commit `b69facef` net-added eleven lines inside `GetProfiles`, so every `x/core/module/module.go` citation in the review above line 1173 is shifted by +11 relative to current source. Locate findings by symbol name, not by line number.

---

## Summary

**All 7 Medium and 10 of 11 Low findings are fixed in v1.34.0.** The one remaining Low is the accepted `ProcessProposal` validation boundary (**L-6**). All seven Informational items keep their prior accepted, deferred, or ops-project status; none was silently closed.

The release is one coherent change rather than eighteen patches: node-local store failures on a consensus path now fail closed instead of decoding as absence, zero, or a logged warning. That single contract covers M-1, M-2, M-3, M-5, M-6, L-1, L-2, L-3, L-8, and L-10. On top of it, three narrower corrections: exact integer economics for the subscription reserve split (M-4, L-4), bounded parameters with checked arithmetic everywhere they are converted or multiplied (M-7), and explicit field presence for governance parameter updates through a `FieldMask` (L-9).

**The deliberate trade is a liveness cost.** Every core KV store is wrapped at the keeper boundary. A read, write, delete, or iterator failure remains a returned error during query/check/simulation wherever the API has an error channel, but during block finalization it calls `consensusfatal.HaltErr` before a MsgServer can turn the node-local failure into an ordinary transaction rejection. Balance and supply reads use iterator APIs that panic on storage failure instead of the SDK's single-value helpers that silently return zero; the finalization guard converts those panics into process exit. Selected non-deterministic bank/slashing failures use the same guard, while a genuine insufficient spendable balance remains a normal transaction error. An insufficient-funds result after a successful spendable-balance precheck is treated as node-local and fatal. Supply-invariant mismatches also terminate during finalization. The affected validator therefore exits with the block uncommitted instead of rejecting a transaction that healthy peers commit. Existing recovery tooling snapshots the diverged database before any wipe.

---

## Status of All Findings

| ID | Finding (abbreviated) | Status | Target |
|----|----------------------|--------|---------|
| M-1 | Subscription index/profile saves log-and-continue after value moved | **Fixed** | v1.34.0 |
| M-2 | Tier-cap counters default to zero on `store.Get` error | **Fixed** | v1.34.0 |
| M-3 | `DeleteUserState` fail-opens on profile reload and subscription removal | **Fixed** | v1.34.0 |
| M-4 | Period-zero expiry skips reserve burn and tier downgrade | **Fixed** | v1.34.0 |
| M-5 | Consensus write failures incorrectly described as fleet-wide | **Fixed** | v1.34.0 |
| M-6 | PoW cleanup marker read errors reset progress | **Fixed** | v1.34.0 |
| M-7 | Unbounded timing/window params can stall or corrupt state | **Fixed** | v1.34.0 |
| L-1 | Profile mutation paths discard profile Get/decode errors | **Fixed** | v1.34.0 |
| L-2 | `ClearPoWWindow` discards delete errors | **Fixed** | v1.34.0 |
| L-3 | `SetCurrentDifficulty` discards secondary writes | **Fixed** | v1.34.0 |
| L-4 | Reserve basis-point conversion uses `float64` | **Fixed** (runtime and wire) | v1.34.0 |
| L-5 | Relay registry and ante switches hand-maintained | **Fixed** (test-enforced parity) | v1.34.0 |
| L-6 | `ProcessProposal` performs minimal validation | **Accepted risk** | unchanged |
| L-7 | Stale PoW commentary and unused `PowDecorator.MinFee` | **Fixed** — dead field removed; envelope staleness now enforced from the on-chain window | v1.34.0 |
| L-8 | Mutual-exclusion list cleanup discards delete errors | **Fixed** | v1.34.0 |
| L-9 | Valid zero-valued params cannot be applied through governance | **Fixed** | v1.34.0 |
| L-10 | Admin gas waiver treats all deduction errors as insufficient balance | **Fixed** | v1.34.0 |
| L-11 | Store/v2 pruning logs and suppresses per-store failures | **Deferred** | trigger below |

Every accepted and deferred row below is also carried in the cross-component register at [`docs/security/open-items.md`](../open-items.md), together with the still-open backend, indexer, and frontend items. There is no longer a calendar-bound action: the backend claim grace that was due to expire 2026-10-05 UTC was removed in this same release.

Informational items:

| ID | Item | Current status |
| :--- | :--- | :--- |
| I-1 | Validator/query co-location | **Open — highest-priority ops project.** Fleet was not contacted. |
| I-2 | `upgrades.go` monolith and stateful historical tests | **Deferred.** Registration is now exhaustively enforced; decomposition awaits an upgrade-framework change. |
| I-3 | Genesis `raw_state` trust | **Accepted risk.** Params still validate before runtime writes, now against tighter bounds. |
| I-4 | Indexer edit/delete authorization | **Accepted risk.** Documented moderation boundary. |
| I-5 | Historical bridge-burn forensics | **Deferred** to a read-only forensic sprint. Prevention is structural. |
| I-6 | No ante fee ceiling | **By design; holds.** Signed exact-fee consent plus the separate paid-reserve cap. |
| I-7 | Prepaid reserve remains on delete | **Accepted risk.** Protocol escrow unless product policy changes. |

---

## Fixed

### M-6 — PoW cleanup cursor

`CleanupOldCounters` now distinguishes a genuinely absent `pow_cleanup_marker` (start at height 1) from a failed read, which returns a `CONSENSUS_FATAL:POW_CLEANUP_MARKER_GET` error. A non-empty marker must be exactly eight bytes and decode to a height within `[1, currentHeight]`; anything else is rejected before a single counter is deleted. `BeginBlock` propagates the error instead of logging and continuing, so the block is not committed.

Tests: `TestCleanupOldCountersFailsOnMarkerGetFailure`, `TestCleanupOldCountersFailsOnMalformedMarker`, `TestCleanupOldCountersFailsOnOutOfRangeMarker`, `TestCleanupOldCountersAbsentMarkerStartsAtGenesis`, `TestCleanupOldCountersFailsOnCounterDeleteFailure`, `TestBeginBlockFailsClosedOnCleanupMarkerGetFailure`.

### M-5, L-2, L-3 — the consensus lifecycle contract

`ClearPoWWindow` returns the first delete failure with the affected height. `SetCurrentDifficulty` propagates the `prev_difficulty` and `last_diff_change_height` writes, not only the primary one; block-cache rollback undoes a successful primary write when a secondary one fails. `BeginBlock` and `EndBlock` propagate fee-collector burning, mint distribution, expired-nonce pruning, base-difficulty initialization, every busy/calm `SetCurrentDifficulty`, every `ClearPoWWindow`, and every `SetConsecutiveLowUsage` call including the previously discarded neutral-window reset. Mint distribution stops on the first bank error and relies on block-cache rollback instead of trying to compensate recipient by recipient. The lifecycle comments were rewritten to distinguish a node-local database failure from a deterministic logic failure, which is what the old comments conflated.

No consensus-write exception remains. Mint distribution, fee-collector burning, and expired-nonce pruning all terminate the affected validator on node-local I/O failure: each can change committed balances, supply, or envelope admission on only that node. The revised [`adr-mint-log-and-continue.md`](../../architecture/adr-mint-log-and-continue.md) records why the earlier liveness exception was unsafe. The typed admin insufficient-funds waiver remains because that branch performs no state change; a non-deterministic admin bank error terminates finalization.

Tests: `TestHaltFinalizeStoreError`, `TestHaltFinalizeBankError`, `TestHaltFinalizeBankPanic`, `TestAssertSupplyInvariantMismatchHaltsDuringFinalize`, `TestMintAndDistribute_SendFailurePropagates`, `TestBeginBlockFailsClosedOnFeeCollectorBurnFailure`, `TestClearPoWWindowFailsOnDeleteFailure`, `TestSetCurrentDifficultyFailsOnSecondaryWriteFailure`, `TestEndBlockFailsClosedOnWindowClearFailureBusyPath`, `TestEndBlockFailsClosedOnDifficultyWriteFailureBusyPath`, `TestEndBlockFailsClosedOnNeutralCalmReset`, `TestEndBlockFailsClosedOnExpiredNonceDeleteFailure`, `TestBeginBlockFailsClosedOnDifficultyInitFailure`, plus the two inverted `never_halt_test.go` cases now named `TestEndBlockFailsClosedOnSetConsecutiveLowUsageFailure` and `TestEndBlockFailsClosedOnSetCurrentDifficultyFailureCalmDecrease`. `TestEndBlockNeverReturnsError_EmptyState` keeps the healthy-path guarantee.

### M-2 — error-returning count and sequence reads

`countSetEntries` and all six public `Count*` methods return `(uint32, error)`. `addSetEntry`, `removeSetEntry`, `addOrderedEntry`, and `addDequeEntry` propagate Get errors for both count and sequence keys. An absent key still means zero; a failed read, malformed encoding, or overflowing count/sequence never does. The three cap checks in `EnableAgent`, `FollowUser`, and `FollowTopic` wrap the error with operation and owner. Malformed committed metadata is rejected deterministically; node-local I/O terminates the affected validator during finalization.

The execution-mode guard keeps the query split the plan required: `GetProfiles` returns errors to its caller, while the same underlying store failure during block finalization terminates the affected node. That preserves the boundary `106e346e` restored after indexer hardening previously destabilized the nodes it was protecting without allowing a DeliverTx accept/reject split.

Tests: `TestListCountReadFailurePropagates`, `TestListSequenceReadFailurePropagates`, `TestListCountReadFailureOnRemovePropagates`, `TestCountReadFailurePropagatesThroughPublicCounters`, `TestListAddPropagatesCountReadFailure`, `TestListStoreFailureHaltsDuringFinalize`.

### M-3 — delete-user cleanup

`DeleteUserState` takes the username and subscription expiry the handler already decoded; the redundant keeper profile reload is gone, and with it the discarded Get/unmarshal errors. Subscription-index removal and username release propagate their errors, so a partial delete rolls the transaction back rather than leaving a profile deleted with its username mapping or subscription index surviving — the state that later triggers `CONSENSUS_FATAL:PROFILE_MISSING`.

Tests: `TestDeleteUserStateFailsOnSubscriptionIndexDeleteFailure`, `TestDeleteUserStateFailsOnUsernameReleaseFailure`, `TestDeleteUserStateRemovesEveryOwnedKey`, plus the existing `delete_user_test.go` suite, which now asserts real successful cleanup instead of tolerating a mock panic.

### L-1 — strict profile mutation reads

`updateProfileCore` propagates profile Get, profile decode, and enabled-agent list errors, and initializes a new core only when the profile key is genuinely absent. `SetUsername` propagates existing-profile Get/decode and `ReleaseUsername` errors while keeping release → claim → write ordering, which transaction rollback makes atomic. `FollowUser` and `FollowTopic` no longer discard profile existence, bootstrap, or update errors on either the user or the governance path.

Tests: `TestUpdateProfileCoreRefusesUnreadableProfile`, `TestUpdateProfileCoreRefusesCorruptProfile`, `TestUpdateProfileCoreRefusesUnreadableAgentList`.

### L-8 — mutual-exclusion cleanup

`BlockUser` propagates `RemoveFollowedUser`; `BlockTopic` propagates each matching `RemoveFollowedTopic`; `FollowTopic` propagates each matching `RemoveBlockedTopic`. Errors are wrapped with handler, owner, and target, and the primary add is never reached after a cleanup failure, so one node can no longer commit both mutually exclusive entries.

Tests: `TestBlockUserFailsWhenUnfollowFails`, `TestFollowTopicFailsWhenUnblockFails`.

### L-10 — admin gas waiver classification

`deductRelayGasFee` waives the fee for level-100+ profiles only on a typed Cosmos `ErrInsufficientFunds`. Every other bank or store error is returned as a transaction error. The liveness policy is unchanged; only its error classification narrowed. [`adr-mint-log-and-continue.md`](../../architecture/adr-mint-log-and-continue.md) now states that insufficient admin balance is the sole permitted waiver.

Test: `TestAdminGasWaiverAppliesOnlyToInsufficientFunds`.

### M-1 — subscription writes after value movement

Renewal `SetSubscription`, profile marshal, and `SetProfileCore` return their errors from `EndBlock`. Both the self and gift `Subscribe` paths propagate the old-index `RemoveSubscription` and the new-index `SetSubscription`. Renewal burn and escrow errors also propagate; they are never converted into a successful downgrade. During finalization, a node-local store or non-deterministic bank failure terminates the affected validator before its ordinary handler error can disagree with healthy peers. There is no compensating write anywhere: operation order stays simple and the transaction/block cache is discarded on failure.

Tests: `TestProcessSubscriptionsFailsOnProfileSaveFailure`, `TestProcessSubscriptionsFailsClosedOnRenewalBurnFailure`, `TestProcessSubscriptionsFailsClosedOnRenewalEscrowFailure`, `TestSubscribeFailsOnStaleIndexDeleteFailure`, `TestSubscribeFailsOnNewIndexWriteFailure`.

### M-4 — period-zero expiry

The early `SubscriptionPeriod == 0` `continue` in `processSubscriptions` is gone. An indexed subscription reaching its expiry under one-time-payment mode now burns any remaining reserve, clears level, expiry, and auto-renew, emits `subscription_expired` with reason `one_time_expired`, and persists the downgraded profile. Period zero never attempts renewal or re-indexing. Stale free-tier entries now clear expiry and auto-renew, reserve burns are always persisted, and an invalid subscription level is downgraded instead of leaving a profile inconsistent after its index is removed.

Tests: `TestProcessSubscriptionsPeriodZeroExpiresProfile`, `TestProcessSubscriptionsCleansStaleFreeProfile`, `TestProcessSubscriptionsPersistsReserveBurnForFreeTier`, `TestProcessSubscriptionsDowngradesInvalidSubscriptionLevel`, `TestProcessSubscriptionsFailsFastOnCorruptProfileOneTimePayment`.

### L-4 — exact reserve split, runtime and wire

`x/core/types/subscription_math.go` computes the split with checked multiplication so `reserve + burn == periodFee` exactly, and `SplitPeriodFee` now takes basis points directly instead of a percentage. Both the renewal and `Subscribe` calculations pass `params.SubscriptionReserveBps`; no float reaches the arithmetic and the truncating `uint64(percent * 10000)` expressions are gone.

The wire migration is done in this same release rather than deferred. `Params.subscription_reserve_bps` is new field 54 (`uint64`, `[0,10000]`) and is the sole authority. Field 42 `subscription_reserve_percent` is marked `deprecated` and kept only so pre-upgrade Params blobs still decode. The v1.34.0 handler converts the stored percentage once through `ReserveBasisPoints` (`round(percent*10000)`, so the live 0.95 lands on exactly 9500), refuses to proceed if a pre-set bps disagrees with the converted percentage, then zeroes the float. `ReserveBasisPoints` now exists only for that one-time conversion.

**The retired field is blocked at the governance layer, not in `Validate()`, and that distinction was a caught mistake.** The first implementation rejected any non-zero `subscription_reserve_percent` in `Validate()`. That would have made a from-genesis replay impossible: the v1.5.0, v1.8.0, and v1.11.0 handlers set the field and call `SetParams`, which validates, so a node syncing from genesis on the v1.34.0 binary would have failed at those heights. `Validate()` therefore leaves the field unconstrained, and the field instead has **no `paramFieldSetters` entry**, so an `update_mask` naming it is rejected as an unsupported path — an explicit failure rather than a silent write to a field nothing reads. `deprecatedParamFields` records the exclusion so the exhaustive mask-coverage test still fails on genuine drift.

Coordinated surfaces: `shared/datatypes.py` field 54 (parity verified against the proto — 24/24 fields, no number mismatches), `web/backend/params.py` requires the integer and no longer requires the float, `/api/get_parameters` exposes `subscription_reserve_bps` (no frontend consumer read the old key), `scripts/verify_upgrade.py` bounds the integer `[0,10000]` and pins the float to exactly `0.0` on a live upgraded chain so a missed migration surfaces, `docs/agents/agent-guide.md` documents the new key, and `proposal_change_reserve_percent.json` now selects the bps field.

Tests: `TestReserveBasisPointsRounding`, `TestReserveBasisPointsRejectsInvalid`, `TestSplitPeriodFeeIsExact` (bps table), `TestSplitPeriodFeeRejectsOverflow` (now also rejects out-of-range bps rather than clamping), `TestReserveConversionMatchesTheRetiredFloat` (the upgrade's conversion reproduces the float path's split at every value the chain has used), `TestSubscriptionReserveBpsIsBounded` (including that a stored pre-upgrade percentage still validates, pinning the replay constraint), and `TestUpdateParamsRejectsDeprecatedField`.

### M-7 — bounded params and checked arithmetic

`x/core/types/params.go` adds documented operational ceilings, and `Validate()` enforces them: `MaxPowMessageWindow` 1,000 blocks (aligned with the recent-hash cap and bounded EndBlock work), `MaxMintInterval` 10,512,000 blocks (about one year at three seconds), `MaxSubscriptionPeriodMinutes` 525,600 (one year), `MaxEnvelopeAgeSeconds` 86,400 (one day), and `MaxPowCalmSequenceThreshold` 1,000,000. The `PowDifficultyAllowance <= PowMessageWindow*2` cross-field check now uses checked multiplication instead of an unsigned multiply that could itself overflow.

`x/core/types/safe_math.go` provides checked uint64→int64 conversion, uint64 and int64 multiplication and addition, subscription expiry, PoW window start, and envelope-age duration. They return errors; they never clamp or fall back. Raw arithmetic was replaced in the keeper (mint interval, PoW counters and sum window, cleanup cutoff, clear window, list counts and sequences), the module (renewal, self and gift subscription expiries, gift reserve accumulation), and `app/ante_metasig.go` (timestamp window and nonce expiry). Difficulty, previous-difficulty, change-height, calm-sequence, subscription-index, and profile-list metadata now reject malformed or out-of-range encodings instead of truncating, clamping, or decoding them as zero. Tier list limits are bounded to the uint32 storage counters, and a zero blocked-list limit rejects additions rather than accidentally selecting the import-only unlimited deque mode.

Tests: `TestCheckedUint64ToInt64`, `TestCheckedMulUint64`, `TestCheckedAddUint64`, `TestCheckedMulAndAddInt64`, `TestCheckedSubscriptionExpiry`, `TestCheckedWindowStartIsBounded`, `TestCheckedEnvelopeAge`, `TestValidateEnvelopeTimestampBoundaries`, `TestParamsBoundsRejectRunawayValues`, `TestParamsRejectProfileListCounterOverflow`, `TestValidateV1340Params`, `TestListMetadataDecodeFailuresPropagate`, `TestListMetadataOverflowPropagates`, `TestExpiredSubscriptionIndexDecodeFailuresPropagate`, and the PoW/difficulty range tests in `store_failures_test.go`.

### L-9 — explicit field presence for governance params

`MsgUpdateParams` gains `google.protobuf.FieldMask update_mask = 3`. `applyParamUpdates` was replaced with an allowlisted mask-driven merge over canonical snake_case proto field names: it rejects a nil or empty mask, rejects unknown, duplicate, nested, and unsupported paths, applies masked scalars including zero, replaces `tiers` and `award_configs` as whole slices when masked, validates the merged Params, and rejects an update that selects no effective field. Zero no longer means "leave unchanged", which is also what made the documented one-time subscription mode unreachable through the normal params message.

Generated Go artifacts were regenerated through the repository workflow. `proto/buf.gen.gogo.yaml` maps `google/protobuf/field_mask.proto` to `github.com/cosmos/gogoproto/types`, because the standard `fieldmaskpb` type does not implement the gogo serialization methods the rest of the message uses. `shared/datatypes.py` mirrors field 3 and registers the well-known FieldMask descriptor in its dynamic pool. Every `MsgUpdateParams` proposal under `scripts/proposals/` carries exact mask paths.

Go tests: `TestUpdateParamsCoversAllFields`, `TestUpdateParamsSettersAssignOnlyTheirOwnField`, `TestApplyParamUpdatesAppliesOnlyMaskedFields`, `TestApplyParamUpdatesAppliesZeroValues`, `TestApplyParamUpdatesReplacesRepeatedFields`, `TestApplyParamUpdatesRejectsBadMasks`, `TestUpdateParamsRejectsMissingMask`, `TestApplyParamUpdatesRejectsNoOp`, `TestApplyParamUpdatesSurfacesInvalidMergedParams`.

Chain tests: `tests/cases/test_blockchain_params.py::test_params_schema` compares Go proto field names and numbers against `shared/datatypes.py` for both `Params` and `MsgUpdateParams` and checks that every proposal file's mask is well formed; `test_params_mask_governance` submits a masked proposal that sets a parameter to zero, votes it through, asserts only the masked field changed, and restores the original value. Both are registered in `tests/test_blockchain.py`; `params_schema` is stateless and walletless, `params_mask` walletless.

The wire change is intentionally strict: an old `MsgUpdateParams` proposal without `update_mask` fails execution after the upgrade. Operators must confirm that no pre-v1.34 parameter proposal remains in deposit or voting period at the upgrade height; compatibility fallback would restore the ambiguity this fix removes.

### L-5 — relay registry parity

`relay_messages_test.go` adds two build-time protections. `TestRelayDecoratorSwitchParity` parses the `PowDecorator` and `RelaySigDecorator` switches and requires a concrete case for every registry prototype. `TestEveryEnvelopeMessageIsRoutedOrGovernanceOnly` walks the generated core messages and requires each one carrying envelope fields to be either relay-routed or on an explicit governance-only allowlist. Source/AST parity was chosen over refactoring both large switches purely for testability. The existing 25-message count pin and the fail-closed default tests are unchanged.

### L-7 — PoW cleanup and envelope staleness

The unused `PowDecorator.MinFee` field and its construction in `ante_relay_chain.go` are removed. The staleness half is now **fixed**, after two wrong turns worth recording.

The first attempt added a `requireLastBlockHash` helper that rejected an empty `LastBlockId.Hash` above bootstrap height. It rejected every transaction on the local testnet: under ABCI 2.0 the `FinalizeBlock` request carries no `LastBlockId`, so the header the ante handler sees has an empty hash on *every* path — simulate, check, and finalize alike. The guard was reverted and the finding was written up as unenforceable from the header. That conclusion was wrong: it stopped at the field that does not work instead of the one that does. The whole mechanism already existed — `RecentBlockHashesKey`, `block_hash_window`, `RecordRecentBlockHash`/`GetRecentBlockHashes`, and the ante's `lookupHash` closure — and was inert only because `BeginBlock` fed it from that same empty field, filling the window with empty strings that `RecordRecentBlockHash` discards.

The fix has three parts:

- **Source.** `x/core/module/module.go` BeginBlock records `sdkCtx.HeaderHash()`, which baseapp sets from `RequestFinalizeBlock.Hash` on both the finalize state (`baseapp/abci.go:827`) and the CheckTx state (`:852`), so it is populated and identical fleet-wide. A client can only have seen an already-committed block, so recording the current hash keeps the window a superset of what any honest envelope references. An absent hash (genesis/InitChain) records nothing rather than an empty entry.
- **Enforcement.** `ante_pow.go` reads the window once per transaction and derives `skipHashCheck` from it, so every message in a tx is judged against one read and a read failure propagates instead of degrading to an empty window. The validator's gate no longer disables itself when `currentLastID` is empty, and an empty envelope hash is refused explicitly — without that it would compare equal to the empty header hash and bypass the window. Enforcement is off only while the window holds no real hash, and the only state that satisfies that is a chain with no committed block yet; it is logged at info. It deliberately does **not** cover the upgrade block: baseapp runs `preBlock` before `beginBlock`, so the handler clears the stale window and BeginBlock immediately records the real hash, and that block's transactions are judged normally. An earlier draft of this section claimed a one-block exemption there, which was wrong in the safe direction.
- **Window width.** `block_hash_window` defaulted to 10 blocks, which is 20s at the 2.01s block interval measured on the local chain and 30s at the 3s the node template configures — *stricter* than `max_envelope_age` (60s), so it would have rejected work the age check still accepts, and the backend would have served clients from the same too-narrow window since `get_recent_block_hashes` reads this param with `LIMIT window`. The default is now 60 blocks, which is 120s locally and 180s at 3s, generous against the 60s expiry at both block times. `verify_upgrade.py` bounds the live chain `[20,1000]` and the upgrade handler widens a stored value below the floor *before* validating.

  **The floor is deliberately not in `Validate()`, and that was a caught mistake — the second of this kind in this release.** The first implementation enforced `MinBlockHashWindow = 20` there. The live genesis stores `block_hash_window: "10"`, and `InitGenesis` substitutes `DefaultParams()` only when the value is *zero*, so it would have passed 10 to `SetParams`, hit the floor, and panicked on `InitGenesis: SetParams failed`. Every node starting from genesis would have died before its first block, including the genesis that `scripts/reset_local_testnet.py` builds from an export. `Validate()` therefore keeps its original `[1,1000]` bound, and the floor is asserted in `validateV1340Params` — the one place that both knows the value is post-migration and can refuse to proceed — plus `verify_upgrade.py` on the live chain. `TestBlockHashWindowAcceptsTheGenesisValue` pins 10 as valid so the floor cannot creep back into `Validate()`. Governance can still set a narrower window than the floor; that degrades submission for everyone equally rather than diverging, and `verify_upgrade.py` flags it.

Enforcement is a consensus-behavior change, which is why it ships in this already-coordinated upgrade rather than alongside a normal release. Envelopes minted before the upgrade height reference hashes that were never recorded and are refused until clients refresh, bounded by `max_envelope_age` and falling inside the upgrade's own halt.

Residual exposure before this fix, stated precisely: freshness rested on the metasig timestamp window and nonce replay protection, so replay of an identical action was blocked and envelopes still expired after 60s. The gap was that precomputed work could be spent against any block within that age bound rather than a recent one — a weakening of PoW freshness, not an authentication hole.

**New operational coupling to monitor.** The backend hands clients `last_block_hash` from the indexer's `recent_blocks` table, bounded by the same `block_hash_window` param. Enforcement makes indexer freshness load-bearing for transaction submission: if the indexer falls further behind than the window (120s locally, 180s at the 3s template block time), every hash it serves has aged out of the chain's window and submissions are refused chain-side. Before this change indexer lag could not block submission this way. The failure is loud — clients see `invalid last_block_hash` and the ante logs it — but the cause is one component away from the symptom, so indexer lag belongs on the watch list for this release.

Tests: `TestStalenessEnforcedFromWindowNotHeader` (in-window accepted with an empty header hash, out-of-window refused, empty envelope hash refused), `TestEmptyWindowSkipsStalenessCheck` (the bootstrap boundary), `TestBeginBlockRecordsHeaderHash` and `TestBeginBlockRecordsNothingWithoutHeaderHash` (pin the recording source, so routing it back through a field `FinalizeBlock` does not carry fails the build rather than silently disabling the check).

### Carryover test gaps

- **PoW per-envelope benchmark.** `BenchmarkValidatePoWBytesArgon2`. Baseline on an Intel Core Ultra 9 285K, `-benchmem`: **1,653,845 ns/op, 4,196,854 B/op, 24 allocs/op**. Recorded here rather than as a wall-clock CI threshold, which would be flaky across machines.
- **Wedged user.** `TestWedgedPaidUserDowngradesThenSucceedsAsFreeTier` — a paid profile with zero reserve reaches the handler-side downgrade during an ordinary relay operation, and the next operation succeeds as free tier.
- **Reserved-profile bootstrap idempotence.** `TestBeginBlockReservedProfileBootstrapIsIdempotent` — the first `BeginBlock` creates profiles and the sentinel; the second performs no profile or username write. Error injection is scoped to the profile and username prefixes so legitimate per-block writes still proceed.
- **Exhaustive upgrade registration.** `TestUpgradeHandlersRegistered` enumerates all 45 handler names and pins the count. `TestUpgradeHandlerListIsExhaustive` parses `upgrades.go`, resolves string constants such as `sdkRestoreUpgradeName`, and fails if the registered set differs from the list. Adding or renaming a handler now requires updating the list.

### Coordinated upgrade

Handler `"v1.34.0"` is registered as handler 45 in `blockchain/app/upgrades.go`. It runs module migrations, loads Params, and calls the newly tightened `Validate()`, so an out-of-range stored value fails the upgrade before block production rather than during a block. There is no state rewrite and no fallback default.

`scripts/proposals/proposal_upgrade.json` carries the matching plan name. `scripts/verify_upgrade.py` was rewritten from its `v1.32.0` pin — including the now-irrelevant fee-ceiling and pruned-node checks — to contain only `v1.34.0` checks: the reported version, the chain live past the upgrade height, every required parameter present, and every parameter within the new bounds. No backend or indexer database migration is required, and no deploy migration was needed because no env or config template changed.

---

## Accepted and Deferred

### L-6 — `ProcessProposal` minimal validation (accepted risk)

A proposer can make peers perform full DeliverTx ante work. Signature-before-PoW ordering and fee-payer consent materially reduce exposure. Revisit only on evidence of proposer-driven DoS or a threat-model change; otherwise the cheap non-mutating ante subset is not worth the divergence surface.

### L-11 — store/v2 pruning policy (deferred)

Non-`ErrVersionDoesNotExist` IAVL prune failures, earliest-version persistence, and commit-info persistence remain logged and suppressed in `patches/cosmos-sdk-store-v2/rootmulti/store.go`. This is an operational and query-history risk rather than a current app-hash risk, and changing local-pruning error propagation needs an ops decision about halt versus alert. Trigger: a `failed to prune store` or `failed to persist earliest version` log, unexplained disk growth, or the next patch rebase. Acceptance: an injected per-store prune failure either propagates safely or produces a tested actionable alert, with provenance and rootmulti tests still passing.

### I-2 — historical upgrade handlers (deferred, posture changed)

Old handlers still contain error-discard patterns, notably v1.17.0 subscription-index deletion. Those upgrades have executed on live chains; rewriting their bodies does not remediate committed state and adds risk without a scheduled replay path. The prospective half of the review's recommendation is done — registration is exhaustively enforced and this release's handler propagates every error. Still deferred: splitting the 2,304-line file and adding execution tests for already-run stateful handlers, starting with v1.31.0 bridge cleanup, v1.17.0 subscription reindex, and v1.16.0 list migration. Trigger: handler 46+, the file exceeding 2,500 lines, or the next change to the migration framework.

### I-1 — validator/query co-location (open)

Unchanged and unverified; no fleet host was contacted for this retest. This remains the highest-value operational prevention and belongs to a separate ops project, not a chain-code release. Acceptance: a read-only fleet inventory showing validator processes isolated from public query workloads, followed by 30 days without a load-correlated divergence. Production must not be changed without separate explicit approval.

### I-5 — historical bridge-burn forensics (deferred)

Prevention is structural: the handlers are gone and legacy bridge messages are ante-rejected. The historical accounting question is unanswered and belongs to a read-only forensic sprint. Trigger: a user loss report, a compliance request, or a scheduled historical audit.

---

## Verification Performed

All gates were run at the remediation baseline `4acbf0b9` plus this working tree, not carried over from the review.

- `go build ./...` — pass.
- `go vet ./...` — pass.
- `make test-fast` — pass: main module `./...`, patched IAVL, patched store/v2 `rootmulti`, and patch provenance.
- `scripts/check_patches.sh` — IAVL and store/v2 provenance diffs OK.
- `make build-all` — pass, including `go mod verify` (all modules verified) and both binaries.
- Proto regeneration run a second time — the only diff against `HEAD` is the intended `x/core/types/tx.pb.go` change for `update_mask`. Checked-in generated Go is reproducible.
- `BenchmarkValidatePoWBytesArgon2 -benchmem` — 1,653,845 ns/op, 4,196,854 B/op, 24 allocs/op.
- `make govulncheck` — both patch modules clean. The main module reports the **same two advisories as Aug 6 and Aug 7**, unchanged and with no upstream fix available:
  - `GO-2026-5932` — unmaintained OpenPGP reached through SDK keyring/CLI dependency paths. Production uses the `test` keyring backend.
  - `GO-2026-4479` — Pion DTLS random-nonce issue reached through CometBFT's optional libp2p/WebRTC paths. `[p2p.libp2p] enabled=false`.

  The target exits nonzero because of these two; that result is recorded rather than suppressed. Production mitigations were not reverified against hosts.

Not run for this retest, deliberately: the Docker-based `tests/test_blockchain.py` suites and `scripts/reset_local_testnet.py --latest`. Both require a local testnet and must run before deployment. `test_params_schema` is stateless and was exercised on the host through the `mirage-node` conda environment; `test_params_mask_governance` needs a running chain and has not been executed.

**Pre-deployment gate.** Before v1.34.0 ships to any validator: run `scripts/reset_local_testnet.py --latest` to confirm the export → transform → init → start flow across the proto change, run the local `tests/test_blockchain.py` suites including `params_schema` and `params_mask` after raising `pow_message_limit`, exercise a corrupt or unreadable profile row against a local indexer and record whether it degrades or halts, and validate the coordinated upgrade on UAT (`val2` / `mirage.vote`). This is a consensus-breaking release: every validator must cross the same height on the same binary.

---

## Assumptions

- No production or UAT server was contacted for this retest.
- Governance has an honest majority, but an approved parameter value must still be safe to execute — which is why the bounds are enforced in `Validate()` and again at runtime.
- Node-local store Get/Set/Delete failures are realistic and must never be treated as fleet-wide deterministic failures.
- Cosmos SDK transaction and block cache semantics roll back writes when a handler or lifecycle method returns an error. Every fix in this release relies on that instead of compensating writes.
- Genesis `raw_state` trust and the indexer moderation boundary remain accepted architecture boundaries.
