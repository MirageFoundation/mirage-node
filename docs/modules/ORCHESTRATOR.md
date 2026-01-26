# Mirage Cross-Chain Orchestrator

This document provides a comprehensive technical overview of the Mirage orchestrator, the off-chain service responsible for monitoring and executing cross-chain bridge operations. It is intended for senior engineers and project managers who need to understand the system's design philosophy, operational model, and the rationale behind key implementation choices.

For protocol-level details (message types, state records, API endpoints), see [Bridge Architecture](../bridge/bridge_architecture.md).

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Component Structure](#component-structure)
4. [Attestor: The Core Coordination Layer](#attestor-the-core-coordination-layer)
5. [Chain Watcher Pattern](#chain-watcher-pattern)
6. [Solana Integration](#solana-integration)
7. [Error Handling and Reliability](#error-handling-and-reliability)
8. [Security Model](#security-model)
9. [Observability and Debugging](#observability-and-debugging)
10. [Operational Considerations](#operational-considerations)

---

## Overview

The orchestrator is a Go daemon that runs alongside each validator node. Its primary responsibilities are:

1. **Watch External Chains**: Detect burn events on connected chains (e.g., Solana)
2. **Submit Attestations**: Report detected burns to the Mirage chain
3. **Execute Mints**: When Mirage burns occur, mint tokens on destination chains
4. **Confirm Mints**: Report successful mints back to Mirage

### Why an Orchestrator?

Blockchains are isolated systems. A Cosmos SDK chain cannot directly observe events on Solana, Ethereum, or other networks. The orchestrator bridges this gap by:

- **Observing** events on external chains
- **Translating** them into Mirage transactions
- **Executing** actions on external chains when triggered by Mirage events

### Trust Model

The orchestrator implements a **validator attestation model**:

- Each validator runs their own orchestrator independently
- Orchestrators do NOT coordinate with each other
- The Mirage chain accumulates attestations from multiple validators
- When 2/3+ of voting power attests to an event, it becomes finalized

This design ensures:
- No single validator can forge bridge transactions
- Byzantine validators cannot disrupt honest validators
- The security threshold matches the consensus threshold

---

## Architecture Philosophy

### Why Not a Centralized Relayer?

Many bridges use centralized relayers or multi-sig schemes. Mirage chose decentralized attestation because:

1. **Censorship Resistance**: No single party can block bridge operations
2. **Liveness**: The bridge remains operational as long as 2/3+ validators are online
3. **Alignment**: Bridge security inherits from chain consensus security
4. **Simplicity**: Each validator runs identical software, no coordination required

### Event-Driven Architecture

The orchestrator is fundamentally event-driven:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          ORCHESTRATOR EVENT FLOW                             │
└─────────────────────────────────────────────────────────────────────────────┘

                  ┌──────────────┐
                  │   Attestor   │
                  │  (main loop) │
                  └──────┬───────┘
                         │
           ┌─────────────┴─────────────┐
           │                           │
           ▼                           ▼
┌─────────────────────┐    ┌─────────────────────┐
│  externalBurns      │    │    mirageBurns      │
│  channel            │    │    channel          │
└──────────┬──────────┘    └──────────┬──────────┘
           │                           │
           ▼                           ▼
┌─────────────────────┐    ┌─────────────────────┐
│  Chain Watchers     │    │  Mirage Watcher     │
│  (Solana, etc.)     │    │  (WebSocket/gRPC)   │
└─────────────────────┘    └─────────────────────┘
           │                           │
           ▼                           ▼
   [External Chain]            [Mirage Chain]
```

Two parallel event streams feed the attestor:
- **External Burns**: Detected on Solana, trigger attestations to Mirage
- **Mirage Burns**: Detected on Mirage, trigger mints on external chains

### Batching for Efficiency

Events are processed in batches (configurable `batch_size`) to:
- Reduce RPC round-trips
- Amortize transaction costs
- Handle burst traffic gracefully

---

## Component Structure

### Directory Layout

```
orchestrator/
├── attestor/
│   └── attestor.go      # Main coordination logic
├── chains/
│   ├── interface.go     # ChainWatcher interface
│   └── solana/
│       ├── watcher.go   # Burn detection
│       └── minter.go    # Mint execution
├── config/
│   └── config.go        # Configuration structures
└── mirage/
    ├── client.go        # Mirage chain client
    ├── events.go        # Event parsing
    └── signer.go        # Transaction signing
```

### Dependency Graph

```
┌──────────────────────────────────────────────────────────────────┐
│                     ORCHESTRATOR DEPENDENCIES                     │
└──────────────────────────────────────────────────────────────────┘

                        ┌─────────────┐
                        │   Attestor  │
                        └──────┬──────┘
                               │
               ┌───────────────┼───────────────┐
               │               │               │
               ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │  Config  │    │  Mirage  │    │ Watchers │
        │          │    │  Client  │    │          │
        └──────────┘    └────┬─────┘    └────┬─────┘
                             │               │
                             │       ┌───────┴───────┐
                             │       │               │
                             ▼       ▼               ▼
                      [Mirage Chain] [Solana]   [Future Chains]
```

---

## Attestor: The Core Coordination Layer

The `Attestor` struct is the central coordinator that:
- Manages chain watcher lifecycle
- Routes events to appropriate handlers
- Maintains replay protection state
- Implements retry logic

### Initialization

```go
func New(cfg *config.Config, mirageClient *mirage.Client, logger *log.Logger) (*Attestor, error) {
    watchers := []chains.ChainWatcher{}
    if cfg.Chains.Solana.Enabled {
        solanaWatcher, err := solana.NewWatcher(cfg.Chains.Solana, logger)
        if err != nil {
            return nil, err
        }
        watchers = append(watchers, solanaWatcher)
    }
    // ... additional chains
}
```

The attestor is chain-agnostic. Adding a new chain requires:
1. Implementing the `ChainWatcher` interface
2. Registering it in the attestor initialization

### Main Event Loop

The `Run` method establishes event channels and enters the main loop:

```go
func (a *Attestor) Run(ctx context.Context) error {
    // Initialize sequence tracking for replay protection
    for _, watcher := range a.watchers {
        lastSeq, _ := watcher.GetLastSequence(ctx)
        a.lastSeq[watcher.ChainID()] = lastSeq
    }

    // Create event channels
    externalBurns := make(chan chains.ExternalBurnEvent, a.cfg.Attestor.BatchSize)
    mirageBurns := make(chan chains.MirageBurnEvent, a.cfg.Attestor.BatchSize)

    // Start watchers
    for _, watcher := range a.watchers {
        go watcher.WatchBurns(ctx, externalBurns)
    }
    go a.mirage.WatchBridgeBurns(ctx, mirageBurns)

    // Process events
    for {
        select {
        case burn := <-externalBurns:
            a.handleExternalBurns(ctx, burn, externalBurns)
        case burn := <-mirageBurns:
            a.handleMirageBurns(ctx, burn, mirageBurns)
        }
    }
}
```

### Two Distinct Flows

**Inbound Flow (External → Mirage):**
1. Chain watcher detects burn on Solana
2. `ExternalBurnEvent` sent to channel
3. Attestor calls `submitAttestationBatch`
4. `MsgBridgeAttestBurned` submitted to Mirage

**Outbound Flow (Mirage → External):**
1. Mirage watcher detects `bridge_burn` event
2. `MirageBurnEvent` sent to channel
3. Attestor calls `executeMintBatch`
4. Mint executed on destination chain
5. `MsgBridgeAttestMinted` submitted to Mirage

---

## Chain Watcher Pattern

### Interface Definition

All chain integrations implement a common interface:

```go
type ChainWatcher interface {
    // ChainID returns the unique identifier (e.g., "solana")
    ChainID() string

    // WatchBurns monitors for burn events and sends them to the channel
    WatchBurns(ctx context.Context, events chan<- ExternalBurnEvent) error

    // ExecuteMint mints tokens on the external chain
    ExecuteMint(ctx context.Context, burn MirageBurnEvent) (signature string, err error)

    // GetLastSequence returns the last processed sequence for replay protection
    GetLastSequence(ctx context.Context) (uint64, error)

    // Close releases resources
    Close() error
}
```

### Why This Interface?

The interface abstracts away chain-specific details:

| Method | Purpose |
|--------|---------|
| `ChainID()` | Routing and logging identification |
| `WatchBurns()` | Long-running goroutine for event detection |
| `ExecuteMint()` | Stateless mint execution (may be called multiple times) |
| `GetLastSequence()` | Enables replay protection without chain-specific logic |
| `Close()` | Resource cleanup (connections, files) |

### Event Structures

```go
// ExternalBurnEvent represents a burn detected on an external chain
type ExternalBurnEvent struct {
    SourceChain     string // "solana"
    BurnID          string // Unique identifier on source chain
    MirageRecipient string // Destination address on Mirage
    Amount          uint64 // Amount in umirage
    BlockHeight     uint64 // For ordering and debugging
}

// MirageBurnEvent represents a burn detected on Mirage
type MirageBurnEvent struct {
    BurnID             string // Sequence number as string
    Owner              string // Mirage sender address
    DestinationChain   string // "solana"
    DestinationAddress string // Recipient on external chain
    Amount             uint64 // Gross amount
    BridgeFee          uint64 // Fee portion
    Sequence           uint64 // For replay protection
    TxHash             string // Mirage tx hash for linking
}
```

---

## Solana Integration

### Watcher: Detecting Burns

The Solana watcher polls for burn events using a signature-based approach:

**Why Polling Instead of WebSocket?**

While Solana offers WebSocket subscriptions, polling is more reliable for production:
- WebSocket connections can drop silently
- Polling with `lastSig` tracking ensures no missed events
- Enables graceful recovery from restarts

**Signature Tracking:**

```go
func (w *Watcher) pollBurns(ctx context.Context, events chan<- ExternalBurnEvent) error {
    // Fetch signatures since lastSig
    sigs, err := w.rpcClient.GetSignaturesForAddressWithOpts(ctx, w.programID, opts)

    // Process in reverse chronological order (oldest first)
    for i := len(allSigs) - 1; i >= 0; i-- {
        burns, _ := w.parseBurnsFromSignature(ctx, sigStr)
        for _, burn := range burns {
            events <- burn
        }
        w.seenSig[sigStr] = true
    }

    // Persist state for restart recovery
    w.lastSig = allSigs[0].Signature.String()
    w.saveState()
}
```

**Event Discriminator:**

Solana programs use Anchor's event discriminator pattern:
```go
func eventDiscriminator(name string) [8]byte {
    hash := sha256.Sum256([]byte("event:" + name))
    var out [8]byte
    copy(out[:], hash[:8])
    return out
}
```

The watcher looks for `BurnInitiated` events in transaction logs.

### Minter: Executing Mints

The mint process is more complex because it must:
1. Construct a valid Solana transaction
2. Include cryptographic proof of authorization
3. Handle idempotency (same burn may be processed multiple times)

**Transaction Structure:**

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SOLANA MINT TRANSACTION                                 │
└─────────────────────────────────────────────────────────────────────────────┘

Instruction 0: Ed25519 Signature Verification
├── Pubkey: Orchestrator's Ed25519 public key
├── Message: Attestation payload (burn details)
└── Signature: Orchestrator's signature over payload

Instruction 1: Bridge Program Mint
├── Accounts:
│   ├── orchestrator (signer, writable)
│   ├── recipient
│   ├── recipient_token_account (writable)
│   ├── token_mint (writable)
│   ├── bridge_config (writable)
│   ├── bridge_state (writable)
│   ├── mint_record (writable)
│   ├── validator_registry
│   ├── instructions_sysvar
│   └── ... (programs)
└── Data: burn_hash, mirage_sender, amount, sequence
```

**Why Ed25519 Verification?**

The Solana program needs to verify that an authorized validator submitted the mint. Instead of storing validator keys on-chain, we use Solana's native Ed25519 program:

1. Orchestrator signs the attestation payload off-chain
2. Ed25519 instruction verifies the signature on-chain
3. Bridge program checks the instruction sysvar to confirm verification passed

This is cheaper and more flexible than on-chain signature storage.

**Attestation Payload:**

```go
func buildMintAttestationPayload(burnHash [32]byte, mirageSender string, amount uint64, 
                                  recipient solana.PublicKey, destinationChain string) []byte {
    buf := bytes.NewBuffer(nil)
    buf.Write(burnHash[:])              // 32 bytes - prevents double-mint
    writeBorshString(buf, mirageSender) // Mirage sender for auditing
    binary.Write(buf, binary.LittleEndian, amount)
    buf.Write(recipient[:])             // 32 bytes - prevents redirection attacks
    writeBorshString(buf, destinationChain) // Prevents cross-chain replay
    return buf.Bytes()
}
```

**Idempotency:**

If a mint was already executed (e.g., orchestrator restarted mid-operation), the Solana program returns `AlreadyMinted` (error code 6021). The orchestrator recovers the canonical signature from the `mint_record` account history:

```go
if strings.Contains(errStr, "AlreadyMinted") || strings.Contains(errStr, "6021") {
    recoveredSig, err := w.findMintRecordSignature(ctx, mintRecordPDA)
    if err != nil {
        return "", fmt.Errorf("mint already exists but failed to recover signature: %w", err)
    }
    return recoveredSig, nil
}
```

This keeps attestation idempotent without submitting a placeholder destination_tx.

---

## Error Handling and Reliability

### Retry Strategy

The attestor implements exponential backoff for transient errors:

```go
func (a *Attestor) retry(ctx context.Context, fn func() error) error {
    for attempt := 1; attempt <= a.cfg.Attestor.MaxRetries; attempt++ {
        if err := fn(); err != nil {
            if isPermanentError(err) {
                return nil  // Skip this burn, continue processing
            }
            time.Sleep(a.cfg.Attestor.RetryInterval)
            continue
        }
        return nil
    }
    return fmt.Errorf("max retries exceeded")
}
```

### Permanent vs. Transient Errors

The orchestrator distinguishes between error types:

**Permanent Errors (no retry):**
- `TransactionTooOld` - Sequence already processed
- `AlreadyMinted` - Mint already executed
- `bridge mint already recorded` - Duplicate attestation

**Transient Errors (retry):**
- Network timeouts
- RPC rate limiting
- Temporary node unavailability

### Replay Protection

The orchestrator maintains per-chain sequence tracking:

```go
type Attestor struct {
    lastSeqMu sync.RWMutex
    lastSeq   map[string]uint64  // chain_id -> last processed sequence
}
```

Before processing a `MirageBurnEvent`:

```go
if burn.Sequence <= lastSeq {
    logger.Printf("WARN [REPLAY] rejecting stale sequence: burn_id=%s seq=%d last_seq=%d",
        burn.BurnID, burn.Sequence, lastSeq)
    continue  // Skip without error
}
```

This prevents:
- Processing the same burn twice after restart
- Handling out-of-order events from the Mirage watcher
- Replay attacks from malicious event injection

### State Persistence

The Solana watcher persists `lastSig` to disk:

```go
func (w *Watcher) saveState() error {
    // Atomic write: temp file + rename
    tmpPath := w.stateFilePath() + ".tmp"
    os.WriteFile(tmpPath, []byte(w.lastSig), 0600)
    os.Rename(tmpPath, w.stateFilePath())
}
```

On startup, the watcher loads this state to resume from where it left off.

---

## Security Model

### Validator Key Protection

Each orchestrator requires access to:
- **Mirage validator key**: Signs attestation messages
- **Solana keypair**: Signs mint transactions

These keys must be protected with the same rigor as validator consensus keys.

### Attack Vectors and Mitigations

**Forged Burns:**
- External chain programs have their own authentication
- Orchestrator only reads finalized events
- Mirage requires 2/3+ validator attestations

**Double Mints:**
- Solana program tracks `mint_record` per burn
- `AlreadyMinted` error prevents duplicate execution
- Sequence tracking in orchestrator adds defense-in-depth

**Replay Attacks:**
- Attestation payload includes `destinationChain`
- Sequence numbers are monotonic per chain
- `envelope_timestamp` on Mirage messages adds temporal bounds

**Byzantine Validators:**
- Individual validators cannot forge events (need 2/3+)
- Conflicting attestations are rejected (amount/recipient must match)
- Voting power is verified against staking state

### Finality Requirements

The orchestrator only acts on finalized events:

**Solana:**
- Uses `CommitmentFinalized` (32+ confirmations)
- Configuration enforces minimum confirmation count

**Mirage:**
- Events are only emitted after block finalization
- WebSocket subscriptions wait for confirmed blocks

---

## Observability and Debugging

### Log Levels

The orchestrator uses structured logging with prefixes:

```
INFO   - Significant state changes (mints, attestations)
DEBUG  - Detailed operation flow
WARN   - Recoverable issues (retries, skipped events)
ERROR  - Failures requiring attention
```

### Key Log Points

**Startup:**
```
INFO  [REPLAY] initialized solana last_sequence=42
DEBUG solana watcher ready program_id=9rMS8...
```

**Burn Detection:**
```
DEBUG polling solana burns
DEBUG solana burn received burn_id=123 recipient=mirage1abc... amount=1000000
```

**Mint Execution:**
```
DEBUG solana mint submitted burn_id=456 signature=5xYz...
INFO  solscan: https://solscan.io/tx/5xYz...
INFO  [FEES] solana_mint solana_fee=~0.000005 SOL mint_amount=1.00 MIRAGE
```

**Replay Protection:**
```
WARN  [REPLAY] rejecting stale sequence: burn_id=789 chain=solana seq=41 last_seq=42
```

**Errors:**
```
INFO  permanent error (no retry): already minted
ERROR chain watcher solana stopped: connection timeout
```

### Metrics to Monitor

- **Events processed**: Count by chain and direction
- **Attestations submitted**: Success/failure rate
- **Mints executed**: Success/failure rate
- **Retry count**: Indicator of network health
- **Sequence lag**: Gap between chain sequence and processed sequence

---

## Operational Considerations

### Deployment Requirements

Each validator should run:
- One orchestrator instance
- Access to validator's signing key
- Network access to external chain RPCs
- State directory for persistence

### Configuration

Key configuration parameters:

```yaml
attestor:
  batch_size: 10        # Events per batch
  max_retries: 5        # Retry attempts
  retry_interval: 5s    # Wait between retries

chains:
  solana:
    enabled: true
    rpc: "https://api.mainnet-beta.solana.com"
    ws: "wss://api.mainnet-beta.solana.com"
    program_id: "9rMS8JEHCM5UTGjwKoXV7V32tzkgM9b16LZcbVdPAMdp"
    keypair: "/path/to/solana-keypair.json"
    confirmations: 32
    poll_interval_min: 10s
    poll_interval_max: 30s
    state_dir: "/var/lib/orchestrator"
```

### Startup Checklist

1. Verify validator key access
2. Verify Solana keypair access
3. Test Solana RPC connectivity
4. Test Mirage gRPC connectivity
5. Ensure CometBFT tx indexing is enabled (`tx_index = "on"`)
6. Verify state directory is writable
7. Check sequence initialization logs

### Failure Modes

**Orchestrator Down:**
- Bridge operations continue (other validators still attesting)
- Catch-up happens automatically on restart
- No manual intervention required if state persisted

**Solana RPC Unavailable:**
- Watcher enters retry loop
- Events accumulate until connectivity restored
- May need to increase batch size temporarily

**Mirage Node Unavailable:**
- Attestation submission fails
- Mints may execute but attestations queued
- Resume automatically when node recovers

### Upgrading

The orchestrator is stateless except for:
- `lastSig` file (Solana watcher)
- In-memory sequence tracking

Safe upgrade process:
1. Stop orchestrator gracefully (SIGTERM)
2. State is persisted on shutdown
3. Deploy new version
4. Start orchestrator
5. Verify sequence initialization logs

---

## Appendix: File Reference

| File | Purpose |
|------|---------|
| `orchestrator/attestor/attestor.go` | Main coordination logic, event routing |
| `orchestrator/chains/interface.go` | ChainWatcher interface definition |
| `orchestrator/chains/solana/watcher.go` | Solana burn detection, signature tracking |
| `orchestrator/chains/solana/minter.go` | Solana mint execution, Ed25519 signing |
| `orchestrator/config/config.go` | Configuration structures and defaults |
| `orchestrator/mirage/client.go` | Mirage chain gRPC client |
| `orchestrator/mirage/events.go` | Event parsing and subscription |

---

*Document Version: 1.0*  
*Last Updated: January 2026*
