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
    SourceChain     string   // "solana"
    BurnID          string   // tx hash on external chain
    MirageRecipient string   // destination on Mirage
    Amount          uint64   // in umirage
    Attestors       []string // validator operator addresses
    AttestedPower   int64    // accumulated voting power
    Minted          bool     // threshold met, tokens minted
    CreatedAt       int64    // block height
}
```

**Key:** `source_chain + burn_id`

### BridgeMintedRecord (Outbound)

Tracks outbound mint confirmations from Mirage to external chains.

```go
type BridgeMintedRecord struct {
    BurnID           string   // Mirage burn tx hash (lowercase)
    DestinationChain string   // "solana"
    DestinationTx    string   // tx signature on Solana
    Attestors        []string // validator operator addresses
    AttestedPower    int64    // accumulated voting power
    Confirmed        bool     // 2/3 threshold met
}
```

**Key:** `burn_id` (lowercase Mirage tx hash)

### burn_sequence

Per-chain counter for replay protection. Incremented by each `MsgBridgeBurn`.

## Events

| Event | Emitted When | Key Attributes |
|-------|--------------|----------------|
| `bridge_burn` | User burns on Mirage | burn_id, owner, destination_chain, destination_address, amount, bridge_fee, sequence |
| `bridge_attest` | Validator attests inbound | source_chain, burn_id, validator, attested_power |
| `bridge_minted` | Validator attests outbound | burn_id, destination_chain, destination_tx, validator |

## Validation Rules

### MsgBridgeBurn
- Sender must have sufficient MIRAGE balance
- Destination chain must be enabled in params
- Amount must be > 0
- **Actions:** Burn tokens, emit event, increment sequence
- **No state record created** (event-only model)

### MsgBridgeAttestBurned (inbound)
- Signer must be active validator with voting power
- burn_id + source_chain must not already be minted
- Validator cannot double-attest same burn_id
- If attestation exists: recipient + amount must match
- **Threshold met →** Mint tokens to recipient, set `minted=true`

### MsgBridgeAttestMinted (outbound)
- Signer must be active validator with voting power
- Validator cannot double-attest same burn_id
- destination_tx must be consistent across attestations
- `mirage_tx_hash` must match an existing burn (via sequence validation)
- **Threshold met →** Set `confirmed=true`

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

- **v1.10.0**: Major bridge refactor
  - Renamed `MsgBridgeAttest` → `MsgBridgeAttestBurned`
  - Renamed `MsgBridgeMinted` → `MsgBridgeAttestMinted`
  - `MsgBridgeBurn` now event-only (no state record)
  - Added `mirage_tx_hash` field for outbound linking
  - Indexer-based status queries (single source of truth)
  - Full frontend implementation for Bridge In/Out
