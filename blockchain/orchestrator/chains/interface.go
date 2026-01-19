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
	Amount             uint64
	Owner              string
}

type ChainWatcher interface {
	WatchBurns(ctx context.Context, events chan<- ExternalBurnEvent) error
	ExecuteMint(ctx context.Context, burn MirageBurnEvent) error
	ChainID() string
}
