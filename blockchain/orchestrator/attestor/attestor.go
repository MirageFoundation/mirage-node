package attestor

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync"
	"time"

	"mirage/orchestrator/chains"
	"mirage/orchestrator/config"
	"mirage/orchestrator/mirage"
	"mirage/orchestrator/chains/solana"
)

type Attestor struct {
	cfg      *config.Config
	mirage   *mirage.Client
	watchers []chains.ChainWatcher
	logger   *log.Logger

	// Sequence tracking for replay protection (per destination chain)
	lastSeqMu sync.RWMutex
	lastSeq   map[string]uint64
}

func New(cfg *config.Config, mirageClient *mirage.Client, logger *log.Logger) (*Attestor, error) {
	if cfg == nil {
		return nil, fmt.Errorf("config cannot be nil")
	}
	if mirageClient == nil {
		return nil, fmt.Errorf("mirage client cannot be nil")
	}
	if logger == nil {
		return nil, fmt.Errorf("logger cannot be nil")
	}

	watchers := []chains.ChainWatcher{}
	if cfg.Chains.Solana.Enabled {
		solanaWatcher, err := solana.NewWatcher(cfg.Chains.Solana, logger)
		if err != nil {
			return nil, err
		}
		watchers = append(watchers, solanaWatcher)
	}

	return &Attestor{
		cfg:      cfg,
		mirage:   mirageClient,
		watchers: watchers,
		logger:   logger,
		lastSeq:  make(map[string]uint64),
	}, nil
}

func (a *Attestor) Run(ctx context.Context) error {
	if len(a.watchers) == 0 {
		return fmt.Errorf("no enabled chain watchers")
	}

	// Initialize sequence tracking by querying each chain's bridge state
	for _, watcher := range a.watchers {
		lastSeq, err := watcher.GetLastSequence(ctx)
		if err != nil {
			a.logger.Printf("WARN failed to get last sequence for %s: %v (starting at 0)", watcher.ChainID(), err)
			lastSeq = 0
		}
		a.lastSeqMu.Lock()
		a.lastSeq[watcher.ChainID()] = lastSeq
		a.lastSeqMu.Unlock()
		a.logger.Printf("INFO  [REPLAY] initialized %s last_sequence=%d", watcher.ChainID(), lastSeq)
	}

	externalBurns := make(chan chains.ExternalBurnEvent, a.cfg.Attestor.BatchSize)
	mirageBurns := make(chan chains.MirageBurnEvent, a.cfg.Attestor.BatchSize)

	for _, watcher := range a.watchers {
		w := watcher
		go func() {
			if err := w.WatchBurns(ctx, externalBurns); err != nil {
				a.logger.Printf("ERROR chain watcher %s stopped: %v", w.ChainID(), err)
			}
		}()
	}

	go func() {
		if err := a.mirage.WatchBridgeBurns(ctx, mirageBurns); err != nil {
			a.logger.Printf("ERROR mirage burn watcher stopped: %v", err)
		}
	}()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case burn := <-externalBurns:
			if err := a.handleExternalBurns(ctx, burn, externalBurns); err != nil {
				return err
			}
		case burn := <-mirageBurns:
			if err := a.handleMirageBurns(ctx, burn, mirageBurns); err != nil {
				return err
			}
		}
	}
}

func (a *Attestor) handleExternalBurns(ctx context.Context, first chains.ExternalBurnEvent, ch <-chan chains.ExternalBurnEvent) error {
	batch := []chains.ExternalBurnEvent{first}
	for len(batch) < a.cfg.Attestor.BatchSize {
		select {
		case burn := <-ch:
			batch = append(batch, burn)
		default:
			return a.submitAttestationBatch(ctx, batch)
		}
	}
	return a.submitAttestationBatch(ctx, batch)
}

func (a *Attestor) handleMirageBurns(ctx context.Context, first chains.MirageBurnEvent, ch <-chan chains.MirageBurnEvent) error {
	batch := []chains.MirageBurnEvent{first}
	for len(batch) < a.cfg.Attestor.BatchSize {
		select {
		case burn := <-ch:
			batch = append(batch, burn)
		default:
			return a.executeMintBatch(ctx, batch)
		}
	}
	return a.executeMintBatch(ctx, batch)
}

func (a *Attestor) submitAttestationBatch(ctx context.Context, burns []chains.ExternalBurnEvent) error {
	for _, burn := range burns {
		burn.BurnID = strings.ToLower(strings.TrimSpace(burn.BurnID))
		if err := a.retry(ctx, func() error {
			return a.mirage.SubmitBridgeAttest(ctx, burn)
		}); err != nil {
			// Log but don't exit - continue processing other burns
			a.logger.Printf("ERROR attestation failed for burn_id=%s: %v (continuing)", burn.BurnID, err)
			continue
		}
	}
	return nil
}

func (a *Attestor) executeMintBatch(ctx context.Context, burns []chains.MirageBurnEvent) error {
	for _, burn := range burns {
		// Replay protection: validate sequence before processing
		a.lastSeqMu.RLock()
		lastSeq := a.lastSeq[burn.DestinationChain]
		a.lastSeqMu.RUnlock()

		if burn.Sequence <= lastSeq {
			a.logger.Printf("WARN [REPLAY] rejecting stale sequence: burn_id=%s chain=%s seq=%d last_seq=%d",
				burn.BurnID, burn.DestinationChain, burn.Sequence, lastSeq)
			continue // Skip this burn, don't return error
		}

		// Execute mint on destination chain - each orchestrator mints independently
		// The Mirage chain accepts all attestations; first destination_tx becomes canonical
		watcher, err := a.findWatcher(burn.DestinationChain)
		if err != nil {
			a.logger.Printf("ERROR no watcher for chain=%s burn_id=%s: %v (skipping)", burn.DestinationChain, burn.BurnID, err)
			continue
		}
		var sig string
		if err := a.retry(ctx, func() error {
			var execErr error
			sig, execErr = watcher.ExecuteMint(ctx, burn)
			return execErr
		}); err != nil {
			// Log but don't exit - continue processing other burns
			a.logger.Printf("ERROR mint failed for burn_id=%s chain=%s: %v (continuing)", burn.BurnID, burn.DestinationChain, err)
			continue
		}

		if sig != "" {
			// Update last sequence after successful mint
			a.lastSeqMu.Lock()
			if burn.Sequence > a.lastSeq[burn.DestinationChain] {
				a.lastSeq[burn.DestinationChain] = burn.Sequence
				a.logger.Printf("DEBUG [REPLAY] updated %s last_sequence=%d", burn.DestinationChain, burn.Sequence)
			}
			a.lastSeqMu.Unlock()

			if err := a.retry(ctx, func() error {
				return a.mirage.SubmitBridgeMinted(ctx, burn.BurnID, burn.DestinationChain, sig, burn.TxHash)
			}); err != nil {
				a.logger.Printf("WARN failed to submit bridge minted burn_id=%s: %v", burn.BurnID, err)
			}
		}
	}
	return nil
}

func (a *Attestor) findWatcher(chainID string) (chains.ChainWatcher, error) {
	for _, watcher := range a.watchers {
		if watcher.ChainID() == chainID {
			return watcher, nil
		}
	}
	return nil, fmt.Errorf("no watcher for destination chain: %s", chainID)
}

func (a *Attestor) retry(ctx context.Context, fn func() error) error {
	var lastErr error
	for attempt := 1; attempt <= a.cfg.Attestor.MaxRetries; attempt++ {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		if err := fn(); err != nil {
			// Don't retry permanent errors
			if isPermanentError(err) {
				a.logger.Printf("INFO  permanent error (no retry): %v", err)
				return nil // Return nil to skip this burn and continue
			}
			lastErr = err
			a.logger.Printf("DEBUG retry attempt=%d err=%v", attempt, err)
			timer := time.NewTimer(a.cfg.Attestor.RetryInterval)
			select {
			case <-ctx.Done():
				timer.Stop()
				return ctx.Err()
			case <-timer.C:
			}
			continue
		}
		return nil
	}
	return fmt.Errorf("max retries exceeded: %w", lastErr)
}

// isPermanentError returns true for errors that should not be retried
func isPermanentError(err error) bool {
	errStr := err.Error()
	// Solana program errors that indicate already processed or invalid data
	// Note: AlreadyMinted (6021) is now handled gracefully in the minter and returns success
	permanentPatterns := []string{
		"TransactionTooOld",            // Sequence too old
		"error: 6020",                  // TransactionTooOld error code
		"bridge mint already recorded", // Duplicate mint confirmation on Mirage
	}
	for _, pattern := range permanentPatterns {
		if strings.Contains(errStr, pattern) {
			return true
		}
	}
	return false
}
