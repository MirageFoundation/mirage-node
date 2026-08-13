# ADR: Mint Fail-Fast and the Admin Insufficient-Funds Waiver

**Status:** Superseded for mint distribution in v1.34.0; admin waiver retained
**Date:** 2026-08-04
**Revised:** 2026-08-12
**Related:** Security review 2026-08-04 M-9; incident 2026-07-12 full-chain halt

## Context

Most consensus-critical decode and state-write failures in Mirage use a
fail-fast contract: return a tagged `CONSENSUS_FATAL` error (or panic) so a
node stops rather than committing a divergent app hash. This ADR originally
made two exceptions:

1. **Mint distribution** — `mintAndDistribute` / `MintIfNeeded` in
   `blockchain/x/core/keeper/keeper.go`.
2. **Admin relay gas waiver** — the `userLevel >= 100` branch of
   `deductRelayGasFee` in `blockchain/x/core/module/module.go`. If
   `DeductFeeFromOwner` fails with `ErrInsufficientFunds`, the fee is skipped
   and the transaction proceeds.

   The waiver is scoped to that one typed error. Every other
   `DeductFeeFromOwner` failure (bank or store level) rejects the transaction:
   those failures are node-local, so skipping the deduction on the failing node
   while peers deduct and burn is exactly the asymmetric skip this ADR does not
   accept. See review L-10 in `docs/security/2026-08-07/blockchain-review.md`.

## Revised decision

Mint distribution and fee-collector burning now fail closed. Every
non-deterministic bank, distribution, supply-delta, and relay-credit-reset
failure terminates the affected validator during finalization, so the SDK
discards the block cache. Per-recipient compensation is unnecessary because
the entire mint and every earlier send roll back together.

The typed admin insufficient-funds waiver remains. It performs no state change
on any validator and is determined by the signed payer's on-chain balance.
Every other deduction error still rejects the transaction.

## Rationale

On 2026-07-12 a deterministic fail-fast panic (false-positive `PRUNE_HOLE` in
the vendored IAVL fork) contributed to a multi-hour full-chain halt when
enough voting power entered a consensus-zombie state. That incident raised the
cost of halt sites, but the original mint conclusion was wrong. A node that
skips a mint or fee burn remains locally supply-consistent while still
committing different balances and supply from peers that succeeded. A
node-local store or bank failure therefore creates an app-hash split; calling
the drift “bounded accounting” does not make it safe.

The process-exit recovery mechanism addresses the 2026-07-12 zombie behavior.
It is safer to stop the affected node with its block uncommitted than to let it
continue from a state no healthy peer has.

## Consequences

- Mint and fee-collector bank failures halt the affected node and trigger the
  normal recovery path.
- A failed distribution cannot leave partially paid validators or coins stuck
  in the core module account.
- Operators should still monitor the typed admin insufficient-funds waiver.

## References

- Code: `mintAndDistribute`, `MintIfNeeded`, `BeginBlock`,
  `deductRelayGasFee` admin branch
- `docs/security/2026-08-04/blockchain-review.md` (M-9, H-1)
- `docs/troubleshooting/postmortems/` (2026-07-12 / related halt notes)
