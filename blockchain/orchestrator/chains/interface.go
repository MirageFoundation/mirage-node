package chains

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
}

// ChainWatcher watches for burns on an external chain.
type ChainWatcher interface {
	WatchBurns(ctx context.Context, events chan<- ExternalBurnEvent) error
	ExecuteMint(ctx context.Context, burn MirageBurnEvent) error
	ChainID() string
}
