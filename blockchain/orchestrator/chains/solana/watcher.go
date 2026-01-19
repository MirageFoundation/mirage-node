package solana

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/binary"
	"fmt"
	"log"
	"strconv"
	"strings"
	"time"

	sdk "github.com/cosmos/cosmos-sdk/types"
	"github.com/gagliardetto/solana-go"
	"github.com/gagliardetto/solana-go/rpc"
	"github.com/gagliardetto/solana-go/rpc/ws"

	"mirage/orchestrator/chains"
	"mirage/orchestrator/config"
)

const (
	bridgeConfigSeed = "bridge_config"
	mintSeed         = "mint"
	mintRecordSeed   = "mint_record"
)

type Watcher struct {
	cfg        config.SolanaConfig
	logger     *log.Logger
	rpcClient  *rpc.Client
	wsClient   *ws.Client
	programID  solana.PublicKey
	lastSig    string
	seenSig    map[string]bool
	discBurn   [8]byte
	discMint   [8]byte
	ready      bool
}

func NewWatcher(cfg config.SolanaConfig, logger *log.Logger) (*Watcher, error) {
	if logger == nil {
		return nil, fmt.Errorf("logger cannot be nil")
	}
	programID, err := solana.PublicKeyFromBase58(cfg.ProgramID)
	if err != nil {
		return nil, fmt.Errorf("invalid solana program_id: %w", err)
	}
	wsClient, err := ws.Connect(context.Background(), cfg.WS)
	if err != nil {
		return nil, fmt.Errorf("failed to connect solana websocket: %w", err)
	}

	watcher := &Watcher{
		cfg:       cfg,
		logger:    logger,
		rpcClient: rpc.New(cfg.RPC),
		wsClient:  wsClient,
		programID: programID,
		seenSig:   make(map[string]bool),
		discBurn:  eventDiscriminator("BurnInitiated"),
		discMint:  instructionDiscriminator("mint"),
		ready:     true,
	}

	logger.Printf("DEBUG solana watcher ready program_id=%s", programID.String())
	return watcher, nil
}

func (w *Watcher) ChainID() string {
	return "solana"
}

// Close closes the WebSocket connection to Solana
func (w *Watcher) Close() error {
	if w.wsClient != nil {
		w.wsClient.Close()
	}
	return nil
}

func (w *Watcher) WatchBurns(ctx context.Context, events chan<- chains.ExternalBurnEvent) error {
	if !w.cfg.Enabled {
		return fmt.Errorf("solana watcher disabled")
	}
	if events == nil {
		return fmt.Errorf("events channel cannot be nil")
	}

	ticker := time.NewTicker(w.cfg.PollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if err := w.pollBurns(ctx, events); err != nil {
				w.logger.Printf("ERROR polling burns: %v", err)
				// Don't return on transient errors, just log and continue
			}
		}
	}
}

func (w *Watcher) pollBurns(ctx context.Context, events chan<- chains.ExternalBurnEvent) error {
	// Paginate through all signatures since lastSig to handle high volume
	var beforeSig solana.Signature
	allSigs := []*rpc.TransactionSignature{}

	for {
		opts := &rpc.GetSignaturesForAddressOpts{
			Limit: ptr(100),
		}
		if !beforeSig.IsZero() {
			opts.Before = beforeSig
		}

		sigs, err := w.rpcClient.GetSignaturesForAddressWithOpts(ctx, w.programID, opts)
		if err != nil {
			return fmt.Errorf("failed to fetch signatures: %w", err)
		}
		if len(sigs) == 0 {
			break
		}

		// Find where we should stop (lastSig or seen signatures)
		stopIndex := -1
		for i, sig := range sigs {
			sigStr := sig.Signature.String()
			if sigStr == w.lastSig || w.seenSig[sigStr] {
				stopIndex = i
				break
			}
		}

		if stopIndex >= 0 {
			// Only add signatures up to (but not including) the stop point
			for i := 0; i < stopIndex; i++ {
				allSigs = append(allSigs, sigs[i])
			}
			break
		}

		// Add all signatures from this batch
		for i := range sigs {
			allSigs = append(allSigs, sigs[i])
		}

		// If we got fewer than 100, we've reached the end
		if len(sigs) < 100 {
			break
		}

		// Set up pagination for next batch
		beforeSig = sigs[len(sigs)-1].Signature
	}

	if len(allSigs) == 0 {
		return nil
	}

	// Process in reverse chronological order (oldest first)
	for i := len(allSigs) - 1; i >= 0; i-- {
		sig := allSigs[i]
		sigStr := sig.Signature.String()
		if sigStr == "" || sig.Signature.IsZero() {
			continue
		}
		if w.seenSig[sigStr] {
			continue
		}

		burns, err := w.parseBurnsFromSignature(ctx, sigStr)
		if err != nil {
			w.logger.Printf("ERROR parsing burns from signature %s: %v", sigStr, err)
			// Mark as seen to avoid retrying bad transactions forever
			w.seenSig[sigStr] = true
			continue
		}
		for _, burn := range burns {
			select {
			case events <- burn:
				w.logger.Printf("DEBUG solana burn received burn_id=%s recipient=%s amount=%d", burn.BurnID, burn.MirageRecipient, burn.Amount)
			case <-ctx.Done():
				return ctx.Err()
			}
		}
		w.seenSig[sigStr] = true
	}

	// Update lastSig to the most recent signature
	if len(allSigs) > 0 {
		w.lastSig = allSigs[0].Signature.String()
	}

	// Prune seenSig map to prevent unbounded growth (keep last 10000)
	if len(w.seenSig) > 10000 {
		w.pruneSeenSigs()
	}

	return nil
}

func ptr[T any](v T) *T {
	return &v
}

func (w *Watcher) pruneSeenSigs() {
	// Simple strategy: clear the map and rely on lastSig for deduplication
	// This is safe because lastSig ensures we don't re-process old signatures
	w.seenSig = make(map[string]bool)
}

func (w *Watcher) parseBurnsFromSignature(ctx context.Context, signature string) ([]chains.ExternalBurnEvent, error) {
	sig, err := solana.SignatureFromBase58(signature)
	if err != nil {
		return nil, fmt.Errorf("invalid signature %s: %w", signature, err)
	}
	tx, err := w.rpcClient.GetTransaction(ctx, sig, &rpc.GetTransactionOpts{
		Encoding:   solana.EncodingBase64,
		Commitment: w.commitment(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to fetch transaction %s: %w", signature, err)
	}
	if tx == nil || tx.Meta == nil {
		return nil, fmt.Errorf("transaction %s missing metadata", signature)
	}

	burns := []chains.ExternalBurnEvent{}
	for _, line := range tx.Meta.LogMessages {
		line = strings.TrimSpace(line)
		if !strings.HasPrefix(line, "Program data: ") {
			continue
		}
		payload := strings.TrimPrefix(line, "Program data: ")
		raw, err := base64.StdEncoding.DecodeString(payload)
		if err != nil {
			return nil, fmt.Errorf("failed to decode program data: %w", err)
		}
		event, ok, err := decodeBurnInitiated(raw, w.discBurn)
		if err != nil {
			return nil, err
		}
		if !ok {
			continue
		}
		if _, err := sdk.AccAddressFromBech32(event.MirageRecipient); err != nil {
			return nil, fmt.Errorf("invalid mirage_recipient in burn event: %w", err)
		}
		burns = append(burns, chains.ExternalBurnEvent{
			SourceChain:     "solana",
			BurnID:          strconv.FormatUint(event.BurnID, 10),
			MirageRecipient: event.MirageRecipient,
			Amount:          event.Amount,
			BlockHeight:     uint64(tx.Slot),
		})
	}
	return burns, nil
}

func (w *Watcher) commitment() rpc.CommitmentType {
	if w.cfg.Confirmations >= 32 {
		return rpc.CommitmentFinalized
	}
	return rpc.CommitmentConfirmed
}

type burnInitiatedEvent struct {
	BurnID          uint64
	SolanaSender    solana.PublicKey
	MirageRecipient string
	Amount          uint64
	Timestamp       int64
}

func decodeBurnInitiated(data []byte, discriminator [8]byte) (*burnInitiatedEvent, bool, error) {
	if len(data) < 8 {
		return nil, false, nil
	}
	if !bytes.Equal(data[:8], discriminator[:]) {
		return nil, false, nil
	}
	reader := bytes.NewReader(data[8:])
	burnID, err := readU64(reader)
	if err != nil {
		return nil, false, fmt.Errorf("failed to read burn_id: %w", err)
	}
	senderBytes := make([]byte, 32)
	if _, err := reader.Read(senderBytes); err != nil {
		return nil, false, fmt.Errorf("failed to read solana_sender: %w", err)
	}
	recipient, err := readString(reader)
	if err != nil {
		return nil, false, fmt.Errorf("failed to read mirage_recipient: %w", err)
	}
	amount, err := readU64(reader)
	if err != nil {
		return nil, false, fmt.Errorf("failed to read amount: %w", err)
	}
	timestamp, err := readI64(reader)
	if err != nil {
		return nil, false, fmt.Errorf("failed to read timestamp: %w", err)
	}
	return &burnInitiatedEvent{
		BurnID:          burnID,
		SolanaSender:    solana.PublicKeyFromBytes(senderBytes),
		MirageRecipient: recipient,
		Amount:          amount,
		Timestamp:       timestamp,
	}, true, nil
}

func readU64(r *bytes.Reader) (uint64, error) {
	var value uint64
	if err := binary.Read(r, binary.LittleEndian, &value); err != nil {
		return 0, err
	}
	return value, nil
}

func readI64(r *bytes.Reader) (int64, error) {
	var value int64
	if err := binary.Read(r, binary.LittleEndian, &value); err != nil {
		return 0, err
	}
	return value, nil
}

func readString(r *bytes.Reader) (string, error) {
	var length uint32
	if err := binary.Read(r, binary.LittleEndian, &length); err != nil {
		return "", err
	}
	if length == 0 {
		return "", fmt.Errorf("string length cannot be zero")
	}
	buf := make([]byte, length)
	if _, err := r.Read(buf); err != nil {
		return "", err
	}
	return string(buf), nil
}

func eventDiscriminator(name string) [8]byte {
	hash := sha256.Sum256([]byte("event:" + name))
	var out [8]byte
	copy(out[:], hash[:8])
	return out
}

func instructionDiscriminator(name string) [8]byte {
	hash := sha256.Sum256([]byte("global:" + name))
	var out [8]byte
	copy(out[:], hash[:8])
	return out
}
