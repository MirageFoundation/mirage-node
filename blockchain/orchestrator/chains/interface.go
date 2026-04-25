package chains

// =============================================================================
// DORMANT - Bridge / Orchestrator (offline since v1.20.0)
//
// The off-chain orchestrator is intentionally OFFLINE. Its main binary is
// hard-disabled at startup (panic guard in blockchain/cmd/orchestrator/main.go)
// and no validator currently runs it. No on-chain bridge_chain is enabled in
// chain params either, so the interfaces and types declared here are not
// consumed in production. The code is retained to keep the package compilable
// and preserve the design while a bridge replacement is being scoped.
//
// SECURITY-REVIEW SCOPE: bridge / orchestrator findings are accepted-and-
// deferred. They are tracked in docs/security/blockchain/review-2026-04-24.md
// under "Outstanding bridge-scope" and will be revisited in a dedicated audit
// only when the bridge is reactivated. Do NOT surface findings from this file
// in live remediation queues until that time.
// =============================================================================

import "context"

// ExternalBurnEvent represents a burn on an external chain (triggers mint on Mirage).
type ExternalBurnEvent struct {
	SourceChain     string
	BurnID          string
	MirageRecipient string
	Amount          uint64
	BlockHeight     uint64
}

// MirageBurnEvent represents a burn on Mirage (triggers mint on external chain).
type MirageBurnEvent struct {
	BurnID             string
	DestinationChain   string
	DestinationAddress string
	Amount             uint64 // Gross amount before fee
	BridgeFee          uint64 // Fee deducted from amount
	Owner              string
	Sequence           uint64
	TxHash             string // Mirage transaction hash (hex)
}

// ChainWatcher watches for burns on an external chain.
type ChainWatcher interface {
	WatchBurns(ctx context.Context, events chan<- ExternalBurnEvent) error
	ExecuteMint(ctx context.Context, burn MirageBurnEvent) (string, error)
	ChainID() string
	// GetLastSequence returns the last processed sequence number from the chain's bridge state.
	// Used for replay protection - orchestrator should reject sequences <= this value.
	GetLastSequence(ctx context.Context) (uint64, error)
}
