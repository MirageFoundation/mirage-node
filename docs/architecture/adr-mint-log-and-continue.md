# ADR: Mint Subsystem and Admin Fee Waiver Use Log-and-Continue

**Status:** Accepted  
**Date:** 2026-08-04  
**Related:** Security review 2026-08-04 M-9; incident 2026-07-12 full-chain halt

## Context

Most consensus-critical decode and state-write failures in Mirage use a
fail-fast contract: return a tagged `CONSENSUS_FATAL` error (or panic) so a
node stops rather than committing a divergent app hash. Two paths intentionally
depart from that contract:

1. **Mint distribution** — `mintAndDistribute` / `MintIfNeeded` in
   `blockchain/x/core/keeper/keeper.go`. Bank failures
   (`MintCoins`, `SendCoinsFromModuleToAccount`, `BurnCoins`) and related
   distribution failures are logged and the interval degrades (skip send,
   burn skipped reward, or track `stuckInModule`) without halting BeginBlock.
2. **Admin relay gas waiver** — the `userLevel >= 100` branch of
   `deductRelayGasFee` in `blockchain/x/core/module/module.go`. If
   `DeductFeeFromOwner` fails (insufficient balance), the fee is skipped and
   the transaction proceeds.

## Decision

Keep log-and-continue for these two paths. Do **not** promote them to
`CONSENSUS_FATAL` halt sites.

This decision was re-evaluated after v1.31.0 replaced consensus panics with
process exits and remains accepted for mint distribution and the admin fee
waiver. Relay-credit reset is excluded: a partial reset can commit different
mint inputs on one validator, so reset failures terminate the affected node.

## Rationale

On 2026-07-12 a deterministic fail-fast panic (false-positive `PRUNE_HOLE` in
the vendored IAVL fork) contributed to a multi-hour full-chain halt when
enough voting power entered a consensus-zombie state. That incident raised the
cost of adding further halt sites for failures that are:

- **Bank / balance conditioned**, not silent substitution of consensus params
  or profile decode;
- **Low divergence risk in practice** when the failure mode is deterministic
  across validators (same balances, same bank code path), or when the
  accepted drift is bounded accounting (missed mint interval, unpaid admin
  fee) rather than conflicting app hashes from asymmetric skips;
- **Liveness-sensitive** — BeginBlock mint runs every interval; admin ops
  should not be blocked solely on gas fee availability.

Preferring liveness here is an explicit tradeoff: a missed mint interval or a
waived admin fee is preferable to another chain-wide halt for these
subsystems. Divergence risk is accepted as low for deterministic bank
failures under homogeneous validator software and state.

## Consequences

- Reviewers must treat these sites as **documented exceptions**, not contract
  drift to be “fixed” by adding panic sites.
- Operators should monitor mint-interval and admin-fee-skip logs; sustained
  failures still warrant investigation.
- The v1.31.0 process-exit mechanism removes consensus zombies but does not
  change the liveness tradeoff accepted for mint distribution or admin fees.

## References

- Code: `mintAndDistribute`, `MintIfNeeded`, `deductRelayGasFee` admin branch
- `docs/security/blockchain/review-2026-08-04.md` (M-9, H-1)
- `docs/troubleshooting/postmortems/` (2026-07-12 / related halt notes)
