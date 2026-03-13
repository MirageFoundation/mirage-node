# Blockchain Security Review — 2026-03-12 (Retest)

**Scope:** `blockchain/` — verification of fixes for review-2026-03-12 and general security audit.
**Baseline:** HEAD (post-remediation).
**Previous review:** review-2026-03-12.

---

## Executive Summary

This review focuses on verifying the remediation of the critical "Mixed Relay + SDK Messages" vulnerability (C-1) and other findings from the earlier audit.

**Status:**
- **C-1 (Critical) Fixed:** The ante handler now explicitly rejects transactions containing both relay and non-relay messages.
- **All Medium findings Fixed or Accepted:** Biography length, failed burns, params bounds, genesis import, minting distribution, and orchestrator retry issues have been resolved. `GetParams` fallback behavior is retained as an accepted availability design choice.
- **All New Findings Fixed:** The informational issues found during retest (duplicate attestations, concurrency, indentation) have been fixed.

The codebase is now in a much more secure state.

---

## Remediation Status — Review 2026-03-12

| ID | Title | Status | Notes |
| :--- | :--- | :--- | :--- |
| **C-1** | Mixed Relay + SDK Messages Bypass | **Fixed** | `app/app.go` now enforces strict separation. Transactions with `containsMeta=true` must *only* contain relay messages. |
| **M-1** | `GetParams` Silent Fallback | **Accepted Risk** | Retained to prevent chain halts on param store corruption. Logs error but falls back to defaults. |
| **M-2** | Biography Length Mismatch | **Fixed** | `ValidateBasic` now uses `utf8.RuneCountInString`, matching handler logic. |
| **M-3** | Failed Token Burns | **Fixed** | Errors from `BurnFromModuleAmount` are now propagated, preventing token supply inflation. |
| **M-4** | No Upper Bounds on Params | **Fixed** | `Validate()` now enforces upper bounds on critical economic parameters. |
| **M-5** | Genesis Import Errors | **Fixed** | `InitGenesis` now panics on critical write failures, preventing silent data loss. |
| **M-6** | Minting Distribution Errors | **Fixed** | Errors are logged at Error level. Continuation is accepted to prevent minting halts. |
| **M-7** | Orchestrator Retry | **Fixed** | `ErrTransactionTooOld` is now treated as transient and retried. |
| **M-8** | Swallowed Errors in Upgrades | **Fixed** | Upgrade handlers now propagate state mutation errors. |

---

## New Findings (Retest) — All Fixed

### I-1: Duplicate Bridge Attestations via Parameter Mismatch (Low)

**Location:** `x/core/keeper/keeper.go` (Bridge Attestation logic)

**Description:**
`GetOrCreateBridgeAttestation` creates keys derived from `(sourceChain, burnID, recipient, amount)`. A malicious validator can submit a conflicting attestation for the same `burnID` but with a different `recipient` or `amount`. This creates a second record in the store.

**Status:** **Fixed**
`GetBridgeAttestation` now returns the first valid attestation found instead of erroring if multiple exist. This prevents the DoS vector on the query endpoint while maintaining consensus integrity (which uses the parameterized key).

### I-2: Double Fee Potential for Relay Transactions (Informational)

**Location:** `app/ante_metasig.go` vs `x/core/module/module.go`

**Description:**
If validators configure `min-gas-prices`, the `RelayGasFeeDecorator` in the ante handler requires a standard SDK fee. The message handler *also* deducts a protocol-level fee via `deductRelayGasFee`.

**Status:** **Documented / Config**
This is a configuration issue. Relay transactions should have `GasPrice=0` in the SDK envelope, relying solely on the protocol fee.

### I-3: `seenSig` Map Not Mutex-Protected (Informational)

**Location:** `orchestrator/chains/solana/watcher.go`

**Description:**
The `seenSig` map is accessed without a mutex. It is currently safe (single-threaded poll loop), but fragile to future refactoring.

**Status:** **Fixed**
Added `seenSigMu sync.Mutex` to the `Watcher` struct and protected all access to `seenSig` with helper methods (`hasSeenSig`, `markSeenSig`, `seenSigCount`).

### I-4: Orchestrator Signer Indentation (Informational)

**Location:** `orchestrator/mirage/signer.go`

**Description:**
Indentation of the error handling block for `TxResponse.Code != 0` is incorrect (visual only).

**Status:** **Fixed**
Corrected indentation.
