package chains

// =============================================================================
// DORMANT - Bridge / Orchestrator (offline since v1.20.0)
//
// The off-chain orchestrator is intentionally OFFLINE. Its main binary is
// hard-disabled at startup (panic guard in blockchain/cmd/orchestrator/main.go)
// and no validator currently runs it. The error sentinels declared here are
// not raised in production. The code is retained to keep the package
// compilable and preserve the design while a bridge replacement is being
// scoped.
//
// SECURITY-REVIEW SCOPE: bridge / orchestrator findings are accepted-and-
// deferred. They are tracked in docs/security/blockchain/review-2026-04-24.md
// under "Outstanding bridge-scope" and will be revisited in a dedicated audit
// only when the bridge is reactivated. Do NOT surface findings from this file
// in live remediation queues until that time.
// =============================================================================

import "errors"

var (
	ErrTransactionTooOld         = errors.New("transaction too old")
	ErrBridgeMintAlreadyRecorded = errors.New("bridge mint already recorded")
)
