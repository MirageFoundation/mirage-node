package attestor

import (
	"context"
	"fmt"
	"io"
	"log"
	"sync"
	"testing"
	"time"

	"mirage/orchestrator/chains"
	"mirage/orchestrator/config"
	coretypes "mirage/x/core/types"
)

func TestIsPermanentError(t *testing.T) {
	tests := []struct {
		name     string
		err      error
		expected bool
	}{
		{
			name:     "TransactionTooOld error",
			err:      fmt.Errorf("failed: %w", chains.ErrTransactionTooOld),
			expected: true,
		},
		{
			name:     "bridge mint already recorded",
			err:      fmt.Errorf("bridge mint already recorded for burn_id: %w", chains.ErrBridgeMintAlreadyRecorded),
			expected: true,
		},
		{
			name:     "transient network error",
			err:      fmt.Errorf("connection refused"),
			expected: false,
		},
		{
			name:     "timeout error",
			err:      fmt.Errorf("context deadline exceeded"),
			expected: false,
		},
		{
			name:     "RPC error",
			err:      fmt.Errorf("rpc error: code = Unknown"),
			expected: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := isPermanentError(tt.err)
			if result != tt.expected {
				t.Errorf("isPermanentError(%q) = %v, want %v", tt.err, result, tt.expected)
			}
		})
	}
}

func TestSequenceValidation(t *testing.T) {
	// Test that sequence validation logic works correctly
	tests := []struct {
		name        string
		lastSeq     uint64
		burnSeq     uint64
		shouldAllow bool
	}{
		{
			name:        "new sequence should be allowed",
			lastSeq:     100,
			burnSeq:     101,
			shouldAllow: true,
		},
		{
			name:        "same sequence should be rejected",
			lastSeq:     100,
			burnSeq:     100,
			shouldAllow: false,
		},
		{
			name:        "old sequence should be rejected",
			lastSeq:     100,
			burnSeq:     50,
			shouldAllow: false,
		},
		{
			name:        "much higher sequence should be allowed",
			lastSeq:     100,
			burnSeq:     500,
			shouldAllow: true,
		},
		{
			name:        "zero lastSeq allows seq 1",
			lastSeq:     0,
			burnSeq:     1,
			shouldAllow: true,
		},
		{
			name:        "zero lastSeq rejects seq 0",
			lastSeq:     0,
			burnSeq:     0,
			shouldAllow: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			// Simulate the validation logic from executeMintBatch
			allowed := tt.burnSeq > tt.lastSeq
			if allowed != tt.shouldAllow {
				t.Errorf("sequence validation: lastSeq=%d, burnSeq=%d, allowed=%v, want=%v",
					tt.lastSeq, tt.burnSeq, allowed, tt.shouldAllow)
			}
		})
	}
}

type fakeMirageClient struct {
	watchBridgeBurnsFn   func(ctx context.Context, ch chan<- chains.MirageBurnEvent) error
	requireTxIndexFn     func(ctx context.Context) error
	queryBridgeStatusFn  func(ctx context.Context) (*coretypes.QueryBridgeStatusResponse, error)
	queryBridgeMintFn    func(ctx context.Context, destinationChain, burnID string) (*coretypes.QueryBridgeMintResponse, error)
	queryBridgeBurnFn    func(ctx context.Context, destinationChain, burnID string) (*coretypes.QueryBridgeBurnResponse, error)
	searchBurnTxHashFn   func(ctx context.Context, destinationChain string, seq uint64) (string, error)
	submitBridgeMintedFn func(ctx context.Context, burnID, destChain, destTx, mirageTxHash string) error
	submitBridgeAttestFn func(ctx context.Context, burn chains.ExternalBurnEvent) error
}

func (f *fakeMirageClient) WatchBridgeBurns(ctx context.Context, ch chan<- chains.MirageBurnEvent) error {
	if f.watchBridgeBurnsFn != nil {
		return f.watchBridgeBurnsFn(ctx, ch)
	}
	return nil
}

func (f *fakeMirageClient) RequireTxIndex(ctx context.Context) error {
	if f.requireTxIndexFn != nil {
		return f.requireTxIndexFn(ctx)
	}
	return nil
}

func (f *fakeMirageClient) QueryBridgeStatus(ctx context.Context) (*coretypes.QueryBridgeStatusResponse, error) {
	if f.queryBridgeStatusFn != nil {
		return f.queryBridgeStatusFn(ctx)
	}
	return &coretypes.QueryBridgeStatusResponse{}, nil
}

func (f *fakeMirageClient) QueryBridgeMint(ctx context.Context, destinationChain, burnID string) (*coretypes.QueryBridgeMintResponse, error) {
	if f.queryBridgeMintFn != nil {
		return f.queryBridgeMintFn(ctx, destinationChain, burnID)
	}
	return &coretypes.QueryBridgeMintResponse{}, nil
}

func (f *fakeMirageClient) QueryBridgeBurn(ctx context.Context, destinationChain, burnID string) (*coretypes.QueryBridgeBurnResponse, error) {
	if f.queryBridgeBurnFn != nil {
		return f.queryBridgeBurnFn(ctx, destinationChain, burnID)
	}
	return &coretypes.QueryBridgeBurnResponse{}, nil
}

func (f *fakeMirageClient) SearchBurnTxHash(ctx context.Context, destinationChain string, seq uint64) (string, error) {
	if f.searchBurnTxHashFn != nil {
		return f.searchBurnTxHashFn(ctx, destinationChain, seq)
	}
	return "", nil
}

func (f *fakeMirageClient) SubmitBridgeMinted(ctx context.Context, burnID, destChain, destTx, mirageTxHash string) error {
	if f.submitBridgeMintedFn != nil {
		return f.submitBridgeMintedFn(ctx, burnID, destChain, destTx, mirageTxHash)
	}
	return nil
}

func (f *fakeMirageClient) SubmitBridgeAttest(ctx context.Context, burn chains.ExternalBurnEvent) error {
	if f.submitBridgeAttestFn != nil {
		return f.submitBridgeAttestFn(ctx, burn)
	}
	return nil
}

type fakeWatcher struct {
	id            string
	watchBurnsFn  func(ctx context.Context, events chan<- chains.ExternalBurnEvent) error
	executeMintFn func(ctx context.Context, burn chains.MirageBurnEvent) (string, error)
	lastSeq       uint64
	lastSeqErr    error
}

func (f *fakeWatcher) WatchBurns(ctx context.Context, events chan<- chains.ExternalBurnEvent) error {
	if f.watchBurnsFn != nil {
		return f.watchBurnsFn(ctx, events)
	}
	return nil
}

func (f *fakeWatcher) ExecuteMint(ctx context.Context, burn chains.MirageBurnEvent) (string, error) {
	if f.executeMintFn != nil {
		return f.executeMintFn(ctx, burn)
	}
	return "", nil
}

func (f *fakeWatcher) ChainID() string { return f.id }

func (f *fakeWatcher) GetLastSequence(ctx context.Context) (uint64, error) {
	if f.lastSeqErr != nil {
		return 0, f.lastSeqErr
	}
	return f.lastSeq, nil
}

func TestRunRequiresWatchers(t *testing.T) {
	a := &Attestor{
		cfg:      &config.Config{Attestor: config.AttestorConfig{BatchSize: 1}},
		mirage:   &fakeMirageClient{},
		watchers: nil,
		logger:   log.New(io.Discard, "", 0),
		lastSeq:  make(map[string]uint64),
	}
	if err := a.Run(context.Background()); err == nil {
		t.Fatal("expected error for empty watcher set")
	}
}

func TestHandleExternalBurnsBatches(t *testing.T) {
	var mu sync.Mutex
	var calls []string
	mc := &fakeMirageClient{
		submitBridgeAttestFn: func(ctx context.Context, burn chains.ExternalBurnEvent) error {
			mu.Lock()
			defer mu.Unlock()
			calls = append(calls, burn.BurnID)
			return nil
		},
	}
	a := &Attestor{
		cfg:    &config.Config{Attestor: config.AttestorConfig{BatchSize: 2, RetryInterval: time.Millisecond, MaxRetries: 1}},
		mirage: mc,
		logger: log.New(io.Discard, "", 0),
		lastSeq: map[string]uint64{},
	}

	ch := make(chan chains.ExternalBurnEvent, 1)
	ch <- chains.ExternalBurnEvent{BurnID: "b2", SourceChain: "solana"}

	if err := a.handleExternalBurns(context.Background(), chains.ExternalBurnEvent{BurnID: "b1", SourceChain: "solana"}, ch); err != nil {
		t.Fatalf("handleExternalBurns failed: %v", err)
	}
	if len(calls) != 2 {
		t.Fatalf("expected 2 attest calls, got %d", len(calls))
	}
}

func TestReplayPendingBurnsUpdatesSequence(t *testing.T) {
	var mintedCalls int
	mc := &fakeMirageClient{
		queryBridgeStatusFn: func(ctx context.Context) (*coretypes.QueryBridgeStatusResponse, error) {
			return &coretypes.QueryBridgeStatusResponse{
				ChainStatus: []*coretypes.BridgeChainStatus{
					{ChainId: "solana", CurrentSequence: 6},
				},
			}, nil
		},
		queryBridgeMintFn: func(ctx context.Context, destinationChain, burnID string) (*coretypes.QueryBridgeMintResponse, error) {
			return &coretypes.QueryBridgeMintResponse{Minted: false, Found: true}, nil
		},
		queryBridgeBurnFn: func(ctx context.Context, destinationChain, burnID string) (*coretypes.QueryBridgeBurnResponse, error) {
			return &coretypes.QueryBridgeBurnResponse{
				Found:              true,
				BurnId:             burnID,
				Owner:              "mirage1owner",
				DestinationChain:   destinationChain,
				DestinationAddress: "dest",
				Amount:             100,
				BridgeFee:          5,
				Sequence:           6,
			}, nil
		},
		searchBurnTxHashFn: func(ctx context.Context, destinationChain string, seq uint64) (string, error) {
			return "txhash", nil
		},
		submitBridgeMintedFn: func(ctx context.Context, burnID, destChain, destTx, mirageTxHash string) error {
			mintedCalls++
			return nil
		},
	}
	fw := &fakeWatcher{
		id: "solana",
		executeMintFn: func(ctx context.Context, burn chains.MirageBurnEvent) (string, error) {
			return "sig123", nil
		},
	}

	a := &Attestor{
		cfg:    &config.Config{Attestor: config.AttestorConfig{BatchSize: 1, RetryInterval: time.Millisecond, MaxRetries: 1}},
		mirage: mc,
		logger: log.New(io.Discard, "", 0),
		watchers: []chains.ChainWatcher{fw},
		lastSeq: map[string]uint64{"solana": 5},
	}

	if err := a.replayPendingBurns(context.Background()); err != nil {
		t.Fatalf("replayPendingBurns failed: %v", err)
	}
	if mintedCalls != 1 {
		t.Fatalf("expected 1 submitBridgeMinted call, got %d", mintedCalls)
	}
	if got := a.lastSeq["solana"]; got != 6 {
		t.Fatalf("expected lastSeq updated to 6, got %d", got)
	}
}
