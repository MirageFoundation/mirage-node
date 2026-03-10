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

	// Initialize with retries - the node may not be ready immediately after container start
	if err := a.initializeWithRetry(ctx); err != nil {
		return err
	}

	externalBurns := make(chan chains.ExternalBurnEvent, a.cfg.Attestor.BatchSize)
	mirageBurns := make(chan chains.MirageBurnEvent, a.cfg.Attestor.BatchSize)
	errCh := make(chan error, len(a.watchers)+1)

	for _, watcher := range a.watchers {
		w := watcher
		go func() {
			if err := w.WatchBurns(ctx, externalBurns); err != nil {
				a.logger.Printf("ERROR chain watcher %s stopped: %v", w.ChainID(), err)
				errCh <- fmt.Errorf("chain watcher %s: %w", w.ChainID(), err)
			}
		}()
	}

	go func() {
		if err := a.mirage.WatchBridgeBurns(ctx, mirageBurns); err != nil {
			a.logger.Printf("ERROR mirage burn watcher stopped: %v", err)
			errCh <- fmt.Errorf("mirage burn watcher: %w", err)
		}
	}()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case err := <-errCh:
			return err
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

// initializeWithRetry performs initialization with retries.
// This handles the case where the orchestrator starts before the Mirage node is fully synced.
// It will keep retrying for up to 10 minutes before giving up.
func (a *Attestor) initializeWithRetry(ctx context.Context) error {
	const (
		maxInitDuration = 10 * time.Minute
		retryInterval   = 10 * time.Second
	)

	deadline := time.Now().Add(maxInitDuration)
	attempt := 0

	for {
		attempt++
		if ctx.Err() != nil {
			return ctx.Err()
		}

		if time.Now().After(deadline) {
			return fmt.Errorf("initialization failed: timed out after %v", maxInitDuration)
		}

		err := a.initialize(ctx)
		if err == nil {
			return nil
		}

		remaining := time.Until(deadline).Round(time.Second)
		a.logger.Printf("WARN initialization attempt %d failed: %v (retrying for %v more)", attempt, err, remaining)

		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(retryInterval):
		}
	}
}

// initialize performs the one-time startup initialization.
func (a *Attestor) initialize(ctx context.Context) error {
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

	// Replay pending burns before starting live subscription
	if err := a.mirage.RequireTxIndex(ctx); err != nil {
		return err
	}
	if err := a.replayPendingBurns(ctx); err != nil {
		return err
	}

	return nil
}

// replayPendingBurns queries for outbound burns that haven't been minted yet and processes them.
// This ensures burns that failed due to temporary issues (e.g., low SOL balance) are retried on startup.
func (a *Attestor) replayPendingBurns(ctx context.Context) error {
	a.logger.Printf("INFO  [REPLAY] checking for pending outbound burns...")

	// Query bridge status to get per-chain sequences
	status, err := a.mirage.QueryBridgeStatus(ctx)
	if err != nil {
		return fmt.Errorf("failed to query bridge status: %w", err)
	}

	totalPending := 0
	for _, chainStatus := range status.ChainStatus {
		chainID := chainStatus.ChainId
		currentSeq := chainStatus.CurrentSequence

		if currentSeq == 0 {
			continue // No burns on this chain
		}

		// Find the watcher for this chain
		watcher, err := a.findWatcher(chainID)
		if err != nil {
			a.logger.Printf("DEBUG [REPLAY] skipping chain %s: %v", chainID, err)
			continue
		}

		// Get last minted sequence from destination chain
		a.lastSeqMu.RLock()
		lastMintedSeq := a.lastSeq[chainID]
		a.lastSeqMu.RUnlock()

		// Check each sequence from lastMintedSeq+1 to currentSeq
		pendingCount := 0
		for seq := lastMintedSeq + 1; seq <= currentSeq; seq++ {
			burnIDStr := fmt.Sprintf("%d", seq)

			// Check if already minted
			mintedResp, err := a.mirage.QueryBridgeMint(ctx, chainID, burnIDStr)
			if err != nil {
				a.logger.Printf("DEBUG [REPLAY] failed to query minted status for %s/%d: %v", chainID, seq, err)
				continue
			}
			if mintedResp.Minted {
				continue // Already minted, skip
			}

			// Get burn record details
			burnResp, err := a.mirage.QueryBridgeBurn(ctx, chainID, burnIDStr)
			if err != nil {
				a.logger.Printf("DEBUG [REPLAY] failed to query burn record for %s/%d: %v", chainID, seq, err)
				continue
			}
			if !burnResp.Found {
				a.logger.Printf("DEBUG [REPLAY] burn record not found for %s/%d", chainID, seq)
				continue
			}

			// Search for the tx hash
			txHash, err := a.mirage.SearchBurnTxHash(ctx, chainID, seq)
			if err != nil {
				a.logger.Printf("DEBUG [REPLAY] failed to find tx hash for %s/%d: %v", chainID, seq, err)
				continue
			}

			a.logger.Printf("INFO  [REPLAY] found pending burn: chain=%s seq=%d amount=%d dest=%s",
				chainID, seq, burnResp.Amount, burnResp.DestinationAddress)

			// Create burn event and process it
			burn := chains.MirageBurnEvent{
				BurnID:             burnIDStr,
				DestinationChain:   chainID,
				DestinationAddress: burnResp.DestinationAddress,
				Amount:             burnResp.Amount,
				BridgeFee:          burnResp.BridgeFee,
				Owner:              burnResp.Owner,
				Sequence:           seq,
				TxHash:             txHash,
			}

			// Execute mint on destination chain
			var sig string
			if err := a.retry(ctx, func() error {
				var execErr error
				sig, execErr = watcher.ExecuteMint(ctx, burn)
				return execErr
			}); err != nil {
				a.logger.Printf("ERROR [REPLAY] mint failed for burn_id=%s chain=%s: %v", burn.BurnID, chainID, err)
				pendingCount++
				continue
			}

			if sig != "" {
				// Update last sequence
				a.lastSeqMu.Lock()
				if seq > a.lastSeq[chainID] {
					a.lastSeq[chainID] = seq
				}
				a.lastSeqMu.Unlock()

				// Submit bridge_minted confirmation
				if err := a.retry(ctx, func() error {
					return a.mirage.SubmitBridgeMinted(ctx, burn.BurnID, chainID, sig, txHash)
				}); err != nil {
					a.logger.Printf("WARN [REPLAY] failed to submit bridge minted burn_id=%s: %v", burn.BurnID, err)
				} else {
					a.logger.Printf("INFO  [REPLAY] successfully replayed burn_id=%s chain=%s sig=%s", burn.BurnID, chainID, sig)
				}
			}
		}

		if pendingCount > 0 {
			a.logger.Printf("WARN [REPLAY] %d pending burns remaining for %s (may need manual intervention)", pendingCount, chainID)
			totalPending += pendingCount
		}
	}

	if totalPending == 0 {
		a.logger.Printf("INFO  [REPLAY] no pending burns found")
	}
	return nil
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
