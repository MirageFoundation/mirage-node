# Bridge Architecture

This document describes the complete bridge architecture for transferring MIRAGE tokens between the Mirage blockchain and external chains (Solana, Osmosis/IBC).

## Overview

The bridge uses a **validator attestation model** where validators independently observe and attest to cross-chain events. When 2/3+ of validator voting power attests to an event, the bridge operation is confirmed and finalized.

```
┌──────────────────────────────────────────────────────────────────┐
│                      BRIDGE COMPONENTS                           │
├──────────────────────────────────────────────────────────────────┤
│  Frontend    │  Backend    │  Orchestrator  │  Chain   │  Indexer│
│  (React)     │  (Flask)    │  (Go daemon)   │  (x/core)│  (Py)   │
│              │             │                │          │         │
│  User UI  ───┼─→ API    ───┼─→ Watch/Submit ─┼─→ State  │         │
│              │             │                │    ↓     │         │
│              │  ← Query ───┼────────────────┼──────────┼─← Index │
└──────────────────────────────────────────────────────────────────┘
```

## Message Types

| Message | Direction | Purpose | Trigger |
|---------|-----------|---------|---------|
| `MsgBridgeBurn` | out | User burns MIRAGE on Mirage | User action |
| `MsgBridgeAttestBurned` | in | Validators attest external burn | Orchestrator detects Solana burn |
| `MsgBridgeAttestMinted` | out | Validators attest external mint | Orchestrator detects Solana mint |

## Bridge Flows

### Inbound: Solana → Mirage

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   User      │    │   Solana    │    │Orchestrators│    │   Mirage    │
│   Wallet    │    │   Program   │    │  (per val)  │    │   Chain     │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                  │                  │
       │  1. Burn MIRAGE  │                  │                  │
       │─────────────────▶│                  │                  │
       │                  │                  │                  │
       │                  │  2. Emit burn    │                  │
       │                  │     event        │                  │
       │                  │─────────────────▶│                  │
       │                  │                  │                  │
       │                  │                  │  3. Submit       │
       │                  │                  │  MsgBridgeAttest │
       │                  │                  │  Burned          │
       │                  │                  │─────────────────▶│
       │                  │                  │                  │
       │                  │                  │         4. Accumulate
       │                  │                  │            attestations
       │                  │                  │                  │
       │                  │                  │         5. 2/3 threshold
       │                  │                  │            → Mint tokens
       │                  │                  │                  │
       │◀─────────────────│──────────────────│──────────────────│
       │        6. MIRAGE arrives in Mirage wallet              │
```

**Steps:**
1. User connects Phantom wallet, enters amount, clicks "Bridge"
2. User burns MIRAGE on Solana via the bridge program
3. Orchestrators poll Solana, detect burn events
4. Each validator's orchestrator submits `MsgBridgeAttestBurned`
5. Chain accumulates attestations in `BridgeAttestation` state
6. When 2/3+ voting power attests → mint tokens to recipient, set `minted=true`

### Outbound: Mirage → Solana

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   User      │    │   Mirage    │    │Orchestrators│    │   Solana    │
│   Wallet    │    │   Chain     │    │  (per val)  │    │   Program   │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                  │                  │
       │  1. MsgBridgeBurn│                  │                  │
       │─────────────────▶│                  │                  │
       │                  │                  │                  │
       │                  │  2. Emit burn    │                  │
       │                  │     event (+seq) │                  │
       │                  │─────────────────▶│                  │
       │                  │                  │                  │
       │                  │                  │  3. Mint on      │
       │                  │                  │     Solana       │
       │                  │                  │─────────────────▶│
       │                  │                  │                  │
       │                  │  4. Submit       │                  │
       │                  │  MsgBridgeAttest │                  │
       │                  │  Minted          │                  │
       │                  │◀─────────────────│                  │
       │                  │                  │                  │
       │                  │  5. 2/3 threshold│                  │
       │                  │     → Confirmed  │                  │
       │                  │                  │                  │
       │◀─────────────────│──────────────────│──────────────────│
       │        6. MIRAGE arrives in Solana wallet              │
```

**Steps:**
1. User submits `MsgBridgeBurn` on Mirage (destination chain + recipient)
2. Chain emits `bridge_burn` event, increments sequence, burns tokens
3. Orchestrators detect event, mint MIRAGE on Solana
4. Each orchestrator submits `MsgBridgeAttestMinted` (includes `mirage_tx_hash` for linking)
5. When 2/3+ voting power attests → mark as confirmed
6. Frontend polls `/api/bridge/get_minted` to show completion

### IBC Bridge (Osmosis)

IBC transfers to Osmosis use the standard Cosmos IBC protocol:

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Mirage    │    │     IBC     │    │   Osmosis   │
│   Chain     │───▶│   Relayer   │───▶│   Chain     │
└─────────────┘    └─────────────┘    └─────────────┘
```

No attestation required - IBC handles finality via light client verification.

## State Records

### BridgeAttestation (Inbound)

Tracks inbound attestations from external chains to Mirage.

```go
type BridgeAttestation struct {
    SourceChain     string           // "solana"
    BurnID          string           // tx hash on external chain
    MirageRecipient string           // destination on Mirage
    Amount          uint64           // in umirage
    Attestors       map[string]int64 // validator operator address -> voting power at attestation
    AttestedPower   int64            // accumulated voting power
    Minted          bool             // threshold met, tokens minted
    CreatedAt       int64            // block height
}
```

**Key:** `source_chain + burn_id`

### BridgeBurnRecord (Outbound)

Tracks outbound burns for fee payout and auditing.

```go
type BridgeBurnRecord struct {
    BurnID             string // Sequence number as string
    Owner              string // Mirage sender address
    DestinationChain   string // "solana"
    DestinationAddress string // Recipient on external chain
    Amount             uint64 // Gross amount (includes fee)
    BridgeFee          uint64 // Fee escrowed for validator
    Sequence           uint64 // Per-chain sequence number
    CreatedAt          int64  // Block height
}
```

**Key:** `burn_id` (sequence number)

### BridgeMintAttestation (Outbound)

Tracks validator attestations for outbound mint confirmations (before threshold is met).

```go
type BridgeMintAttestation struct {
    BurnID           string            // Sequence number (as string)
    DestinationChain string            // "solana"
    DestinationTx    string            // tx signature on Solana (from first attestor)
    Attestors        map[string]int64  // validator operator address -> voting power at attestation
    AttestedPower    int64             // accumulated voting power
    Confirmed        bool              // threshold met
    CreatedAt        int64             // block height
}
```

**Key:** `destination_chain + burn_id`

### BridgeMintedRecord (Outbound)

Tracks final outbound mint confirmations (written only when threshold is met).

```go
type BridgeMintedRecord struct {
    BurnID           string // Sequence number (matches BridgeBurnRecord)
    DestinationChain string // "solana"
    DestinationTx    string // tx signature on Solana
    CreatedAt        int64  // Block height
}
```

**Key:** `burn_id` (sequence number)

### burn_sequence

Per-chain counter for replay protection. Incremented by each `MsgBridgeBurn`.

## Events

| Event | Emitted When | Key Attributes |
|-------|--------------|----------------|
| `bridge_burn` | User burns on Mirage | burn_id, owner, destination_chain, destination_address, amount, bridge_fee, sequence |
| `bridge_attest` | Validator attests inbound | source_chain, burn_id, validator, power, attested_power, required_power, **minted** |
| `bridge_attest_minted` | Validator attests outbound | burn_id, destination_chain, destination_tx, validator, power, attested_power, required_power, **minted**, mirage_tx_hash |

**Note:** The `minted` attribute is `true` when the attestation triggers the 2/3 threshold. The indexer watches for this to update the database. For outbound, `mirage_tx_hash` links the attestation to the original burn transaction.

## Validation Rules

### MsgBridgeBurn
- Sender must have sufficient MIRAGE balance (amount includes fee)
- Destination chain must be enabled in params
- Amount must be > bridge fee
- **Fee Handling:**
  - `amount` is the gross amount (what user enters)
  - `burn_amount = amount - bridge_fee` is burned from user
  - `bridge_fee` is escrowed in the core module account (paid to validator on confirmation)
- **Actions:** Burn net amount, escrow fee, store `BridgeBurnRecord`, emit event, increment sequence
- **State:** `BridgeBurnRecord` stored (keyed by sequence) for fee payout on confirmation

### MsgBridgeAttestBurned (inbound)
- Signer must be active validator with voting power
- burn_id + source_chain must not already be minted
- Validator cannot double-attest same burn_id
- If attestation exists: recipient + amount must match
- **Threshold met →** Mint tokens to recipient, set `minted=true`

### MsgBridgeAttestMinted (outbound)
- Signer must be active validator with voting power
- Validator cannot double-attest same burn_id
- burn_id must be a valid sequence number (≤ current sequence)
- destination_chain must match the original burn record
- destination_tx must match the first attestor's value (consistency check)
- **Actions:** Accumulate attestation in `BridgeMintAttestation`, emit `bridge_attest_minted` event
- **Threshold met →** Set `confirmed=true`, store `BridgeMintedRecord`, distribute bridge fee proportionally
- **Fee Payout:** The `bridge_fee` from `BridgeBurnRecord` is distributed ONCE when threshold is met:
  - Each attestor receives `fee * their_power / total_attested_power`
  - Rounding dust (if any) goes to the validator that crossed the threshold

## Orchestrator Architecture

Each validator runs an orchestrator daemon that:

```
┌─────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐   │
│  │  Solana     │     │   Mirage    │     │   Attestor  │   │
│  │  Watcher    │────▶│   Signer    │◀────│   Logic     │   │
│  └─────────────┘     └─────────────┘     └─────────────┘   │
│        │                    │                   │          │
│        ▼                    ▼                   ▼          │
│  Poll burns/mints    Sign & broadcast    Retry failed     │
│  on Solana           to Mirage chain     attestations     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key files:**
- `orchestrator/chains/interface.go` - Chain interface definitions
- `orchestrator/chains/solana.go` - Solana burn/mint detection
- `orchestrator/mirage/events.go` - Mirage event watching
- `orchestrator/mirage/signer.go` - Tx signing and submission
- `orchestrator/attestor/attestor.go` - Main attestation loop

### MirageBurnEvent Structure

```go
type MirageBurnEvent struct {
    BurnID           string // Sequence number as string
    Sender           string // Mirage sender address
    DestinationChain string // "solana"
    Recipient        string // Solana address
    Amount           uint64 // in umirage
    BridgeFee        uint64 // Fee in umirage
    TxHash           string // Original Mirage tx hash (hex)
}
```

The `TxHash` field is passed to `MsgBridgeAttestMinted.mirage_tx_hash` for indexer linking.

## Indexing

The indexer watches all Mirage blocks and indexes bridge transactions:

### bridge_transactions Table

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| tx_hash | TEXT | Mirage transaction hash |
| direction | TEXT | "in" or "out" |
| msg_type | TEXT | "burn", "attest_burned", "attest_minted" |
| burn_id | TEXT | Unique burn identifier |
| source_chain | TEXT | Source chain (inbound) |
| destination_chain | TEXT | Destination chain (outbound) |
| recipient | TEXT | Destination address |
| amount | BIGINT | Amount in umirage |
| validator | TEXT | Attesting validator |
| destination_tx | TEXT | External chain tx |
| minted | BOOLEAN | Confirmation status |
| height | BIGINT | Block height |
| created_at | BIGINT | Unix timestamp |

### Linking Outbound Transactions

For outbound bridges, the `burn_id` column uses the Mirage tx hash (from `mirage_tx_hash` field in `MsgBridgeAttestMinted`) to link attestations to the original burn.

### Minted Status Updates

For inbound bridges (Solana → Mirage), the indexer updates `minted=true` by processing tx events:

1. When `MsgBridgeAttestBurned` is processed, the record is inserted with `minted=false`
2. The indexer also processes tx events for each transaction
3. When a `bridge_attest` event has `minted=true`, the indexer calls `update_bridge_attestation_minted()`
4. This flips `minted=true` in the database, allowing the frontend to show completion

This event-driven approach ensures the UI reflects the actual chain state.

## API Endpoints

### GET /api/bridge/get_minted

Query bridge status from indexer database.

**Inbound (Solana → Mirage):**
```http
GET /api/bridge/get_minted?burn_id=<solana_tx_signature>&chain=solana
```

Response:
```json
{
  "found": true,
  "confirmed": true,
  "mint_tx": "ABC123DEF456...",
  "recipient": "mirage1abc...",
  "amount": 1000000
}
```

**Outbound (Mirage → Solana):**
```http
GET /api/bridge/get_minted?burn_id=<mirage_tx_hash>
```

Response:
```json
{
  "found": true,
  "confirmed": true,
  "destination_chain": "solana",
  "destination_tx": "5xYzABC...",
  "amount": 1000000
}
```

### GET /api/bridge/config

Returns bridge configuration including enabled chains and token addresses.

```json
{
  "chains": {
    "solana": {
      "enabled": true,
      "token_address": "BH8J5cEBvvzHJLehBa2EkN2XHteE7v6rWtEF585JGai2",
      "program_id": "9rMS8JEHCM5UTGjwKoXV7V32tzkgM9b16LZcbVdPAMdp"
    }
  }
}
```

## Frontend Integration

The bridge UI (`BridgeView.js`) provides:

### Bridge Out (Mirage → Solana)
1. User enters amount and Solana recipient address
2. Transaction summary shows fees and expected receive amount
3. 3-step progress: Confirm on Mirage → Orchestrator detection → Mint on Solana
4. Polls `/api/bridge/get_minted` until confirmed

### Bridge In (Solana → Mirage)
1. User connects Phantom wallet
2. Shows MIRAGE and SOL balances
3. Transaction summary with estimated Solana fees
4. 3-step progress: Confirm on Solana → Orchestrator detection → Mint on Mirage
5. Polls `/api/bridge/get_minted?chain=solana` until confirmed

## Configuration

### Environment Variables

```bash
# Orchestrator
ORCHESTRATOR_SOLANA_RPC=https://api.devnet.solana.com
ORCHESTRATOR_SOLANA_PROGRAM_ID=9rMS8JEHCM5UTGjwKoXV7V32tzkgM9b16LZcbVdPAMdp
ORCHESTRATOR_SOLANA_TOKEN_ADDRESS=BH8J5cEBvvzHJLehBa2EkN2XHteE7v6rWtEF585JGai2

# Backend
SOLANA_PROGRAM_ID=9rMS8JEHCM5UTGjwKoXV7V32tzkgM9b16LZcbVdPAMdp
SOLANA_TOKEN_ADDRESS=BH8J5cEBvvzHJLehBa2EkN2XHteE7v6rWtEF585JGai2
```

### Chain Parameters

```protobuf
message Params {
  // Bridge fee percentage (basis points, e.g. 100 = 1%)
  uint64 bridge_fee_bps = 10;
  // Enabled destination chains
  repeated string bridge_enabled_chains = 11;
}
```

## Security Considerations

1. **2/3 Threshold**: Requires supermajority of validator power to confirm
2. **Replay Protection**: burn_sequence prevents double-minting from same burn
3. **Double-Attestation Prevention**: Validators cannot attest twice to same burn_id
4. **Amount/Recipient Consistency**: All attestations must agree on amount and recipient
5. **Validator-Only**: Only active validators with voting power can attest

## Version History

- **v1.10.3**: Proportional fee distribution
  - `Attestors` map changed from `map[string]bool` to `map[string]int64` to store voting power
  - Bridge fee is now distributed proportionally among all attestors based on their voting power
  - Added `GetAttestorPower()` method to retrieve individual attestor's power contribution
  - Rounding dust from integer division goes to the threshold-crossing validator

- **v1.10.2**: Outbound 2/3 threshold enforcement
  - Added `BridgeMintAttestation` state record to accumulate validator attestations for outbound bridges
  - `MsgBridgeAttestMinted` now requires 2/3 voting power threshold before confirming
  - `bridge_attest_minted` event now includes `attested_power`, `required_power`, and `minted` attributes
  - Indexer updated to flip `minted=true` on threshold-crossing event
  - Frontend shows attestation progress during "Validator confirmations" step
  - Added `/api/bridge/attestation_status` endpoint for polling attestation progress

- **v1.10.1**: Fee handling and indexer fixes
  - `MsgBridgeBurn` now stores `BridgeBurnRecord` for fee payout
  - Bridge fee is escrowed (not burned) and paid to attesting validator on confirmation
  - Indexer processes tx events to update `minted=true` from `bridge_attest` events
  - Fixed "Orchestrator detection" UI getting stuck on inbound bridges

- **v1.10.0**: Major bridge refactor
  - Renamed `MsgBridgeAttest` → `MsgBridgeAttestBurned`
  - Renamed `MsgBridgeMinted` → `MsgBridgeAttestMinted`
  - `MsgBridgeBurn` now event-only (no state record)
  - Added `mirage_tx_hash` field for outbound linking
  - Indexer-based status queries (single source of truth)
  - Full frontend implementation for Bridge In/Out
