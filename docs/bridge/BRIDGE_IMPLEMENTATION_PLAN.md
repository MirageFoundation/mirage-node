# Mirage Bridge Implementation Plan

## Overview

The Mirage bridge supports two bridging mechanisms:

1. **IBC Chains** (Osmosis, other Cosmos chains): Native IBC using `MsgIBCTransfer` - trustless, uses existing IBC infrastructure
2. **Non-IBC Chains** (Solana, Ethereum, etc.): Validator-attested burn/mint model where 66.67% of validator stake must attest before minting

The non-IBC bridge is chain-agnostic - the same message types and orchestrator support any external chain via configuration.

---

## Part 1: IBC Bridge (Osmosis)

### How It Works

1. User signs canonical IBC transfer data in frontend
2. Backend builds `MsgIBCTransfer` with envelope fields
3. Transaction broadcast to Mirage chain
4. Ante handler (`ante_metasig.go`) verifies envelope signature
5. Handler calls `TransferKeeper.Transfer()` to initiate IBC transfer
6. IBC relayer (Hermes) delivers packet to Osmosis

### Message Type

**File:** `blockchain/proto/mirage/core/v1/tx.proto`

```protobuf
message MsgIBCTransfer {
  string authority = 1;
  
  // Envelope fields (standard)
  bytes envelope_pubkey = 2;
  bytes envelope_block_hash = 3;
  uint64 envelope_difficulty = 4;
  uint64 envelope_pow = 5;
  uint64 envelope_timestamp = 6;
  bytes envelope_signature = 7;
  
  // IBC transfer fields
  string receiver = 100;           // Destination address (e.g., osmo1...)
  uint64 amount = 101;             // Amount in umirage
  string source_channel = 102;     // IBC channel ID
  uint64 timeout_timestamp = 103;  // Timeout in nanoseconds (0 = default)
}

message MsgIBCTransferResponse {
  uint64 sequence = 1;  // IBC packet sequence number
}
```

### Implementation Files

| File | Changes |
|------|---------|
| `blockchain/proto/mirage/core/v1/tx.proto` | Add `MsgIBCTransfer` and response |
| `blockchain/app/ante_metasig.go` | Add case for `*coretypes.MsgIBCTransfer` |
| `blockchain/x/core/keeper/msg_server.go` | Add `IBCTransfer()` handler |
| `shared/datatypes.py` | Add `MsgIBCTransfer` class |
| `shared/canon.py` | Add `canon_base_ibc_transfer()` |
| `web/backend/routes/core.py` | Add `/api/core/ibc_transfer` endpoint |
| `web/frontend/src/utils/TransactionHandler.js` | Add `ibcTransfer()` method |
| `web/frontend/src/views/BridgeView.js` | Wire up Osmosis outbound tab |

### Key Constants

| Constant | Value |
|----------|-------|
| Chain ID | `mirage-1` |
| Token denom | `umirage` |
| Outbound channel (Mirage → Osmosis) | `channel-1` |
| Inbound channel (Osmosis → Mirage) | `channel-108698` |
| IBC denom on Osmosis | `ibc/3B6D9E089BECA458072D7624E67F0B84B8087E68B58CF0B9A65E0BA8E7818B54` |
| Default timeout | 10 minutes from block time |

### Inbound (Osmosis → Mirage)

Inbound IBC transfers don't require Mirage-side code changes. Users initiate from Osmosis using:
- Keplr wallet (deep link from our UI)
- Any IBC-compatible wallet

Frontend shows:
- User's `mirage1...` address with copy button
- "Open in Keplr" deep link
- Manual instructions with channel ID `channel-108698`

---

## Part 2: Non-IBC Bridge (Validator-Attested)

### Security Model

- Each Mirage validator runs an **orchestrator** (sidecar process)
- Orchestrator watches external chains for burn events
- Signs attestations using the **validator's consensus key**
- Minting triggers automatically when **≥66.67% of stake** attests (same as Tendermint consensus)
- Trust model identical to the chain itself

### Token Model

- **Outbound (Mirage → External):** MIRAGE is **burned** on Mirage, then **minted** on external chain
- **Inbound (External → Mirage):** MIRAGE is **burned** on external chain, then **minted** on Mirage
- No escrow or locking - pure burn/mint on both sides
- Total supply across all chains remains constant

### Message Types

**File:** `blockchain/proto/mirage/core/v1/tx.proto`

#### MsgBridgeBurn (User Outbound)

User burns MIRAGE on Mirage to bridge out to an external chain.

```protobuf
message MsgBridgeBurn {
  string authority = 1;
  
  // Envelope fields (standard)
  bytes envelope_pubkey = 2;
  bytes envelope_block_hash = 3;
  uint64 envelope_difficulty = 4;
  uint64 envelope_pow = 5;
  uint64 envelope_timestamp = 6;
  bytes envelope_signature = 7;
  
  // Bridge fields
  string destination_chain = 100;   // "solana", "ethereum", "arbitrum", etc.
  string destination_address = 101; // Address on destination chain
  uint64 amount = 102;              // Amount in umirage
}

message MsgBridgeBurnResponse {
  string burn_id = 1;  // Unique identifier for this burn (tx hash)
}
```

#### MsgBridgeAttest (Validator Inbound)

Validator attests to a burn event on an external chain. When threshold is met, MIRAGE is minted to recipient.

```protobuf
message MsgBridgeAttest {
  string validator = 1;         // Validator operator address (signer)
  string source_chain = 2;      // "solana", "ethereum", etc.
  string burn_id = 3;           // Unique ID (tx hash from source chain where burn occurred)
  string mirage_recipient = 4;  // Mirage address to receive minted MIRAGE
  uint64 amount = 5;            // Amount in umirage
}

message MsgBridgeAttestResponse {
  bool minted = 1;              // True if this attestation triggered minting
  uint64 attested_power = 2;    // Total attested voting power so far
  uint64 required_power = 3;    // Power needed to mint
}
```

### Chain Parameters

```protobuf
message BridgeChainConfig {
  string chain_id = 1;          // "solana", "ethereum", etc.
  string contract_address = 2;  // Bridge contract address on that chain
  bool enabled = 3;             // Can be disabled via governance
}

message BridgeParams {
  repeated BridgeChainConfig chains = 1;
  uint64 attestation_threshold = 2;  // 6667 = 66.67%
}
```

New chains can be added via governance proposal without code changes.

### Bridge Keeper State

**Attestation tracking (per chain + burn_id) for inbound minting:**

```go
type BridgeMintAttestation struct {
    SourceChain     string
    BurnID          string           // Unique within chain (tx hash of burn on external chain)
    MirageRecipient string
    Amount          uint64
    Attestations    map[string]bool  // validator addr -> attested
    TotalPower      int64            // sum of attesting validator power
    Minted          bool
    CreatedAt       time.Time
    MintedAt        *time.Time
}
```

Storage key: `bridge/mint_attestation/{source_chain}/{burn_id}`

**Burn tracking (for outbound) - optional, for UI/history:**

```go
type BridgeBurn struct {
    BurnID             string
    Sender             string
    DestinationChain   string
    DestinationAddress string
    Amount             uint64
    CreatedAt          time.Time
}
```

Storage key: `bridge/burn/{burn_id}`

### Outbound Flow (Mirage → External Chain)

1. User submits `MsgBridgeBurn` with `destination_chain` and `destination_address`
2. Handler validates:
   - Chain is enabled in params
   - Amount > 0
   - User has sufficient balance
3. Handler **burns** MIRAGE from user's account (reduces total supply)
4. Handler emits event: `bridge_burn{chain, address, amount, burn_id}`
5. Orchestrators watch for `bridge_burn` events
6. Orchestrators call external chain's bridge contract to **mint** MIRAGE

### Inbound Flow (External Chain → Mirage)

1. User **burns** MIRAGE on external chain via bridge contract
2. External chain emits burn event with: `{burn_id, mirage_recipient, amount}`
3. Orchestrators watch external chain for burn events
4. Each orchestrator submits `MsgBridgeAttest` with:
   - `source_chain` = which chain (e.g., "solana")
   - `burn_id` = burn tx hash from source chain
   - `mirage_recipient` = destination on Mirage
   - `amount` = burned amount
5. Handler validates:
   - Signer is active validator
   - Chain is enabled
   - Attestation not already submitted by this validator
   - If already minted, reject
6. Handler records attestation and calculates total attested power
7. If attested power ≥ 66.67% of total voting power:
   - **Mint** MIRAGE to recipient (increases total supply)
   - Mark attestation as minted
   - Emit `bridge_mint{chain, burn_id, recipient, amount}`

### Implementation Files

| File | Changes |
|------|---------|
| `blockchain/proto/mirage/core/v1/tx.proto` | Add `MsgBridgeBurn`, `MsgBridgeAttest`, params |
| `blockchain/proto/mirage/core/v1/params.proto` | Add `BridgeParams`, `BridgeChainConfig` |
| `blockchain/app/ante_metasig.go` | Add case for `*coretypes.MsgBridgeBurn` |
| `blockchain/x/core/keeper/bridge.go` | New file: bridge keeper logic (burn/mint) |
| `blockchain/x/core/keeper/msg_server.go` | Add `BridgeBurn()`, `BridgeAttest()` handlers |
| `shared/datatypes.py` | Add `MsgBridgeBurn`, `MsgBridgeAttest` classes |
| `shared/canon.py` | Add `canon_base_bridge_burn()` |
| `web/backend/routes/core.py` | Add `/api/bridge/burn` endpoint |
| `web/frontend/src/utils/TransactionHandler.js` | Add `bridgeBurn()` method |
| `web/frontend/src/views/BridgeView.js` | Wire up non-IBC chain tabs |

---

## Part 3: Orchestrator

The orchestrator is a Go binary that validators run alongside their node.

### Architecture

```
orchestrator/
├── cmd/
│   └── orchestrator/
│       └── main.go           # Entry point
├── config/
│   └── config.go             # Configuration loading
├── chains/
│   ├── interface.go          # ChainWatcher interface
│   ├── solana/
│   │   └── watcher.go        # Solana-specific implementation
│   └── evm/
│       └── watcher.go        # EVM-compatible chains
├── mirage/
│   ├── client.go             # Mirage chain client
│   └── events.go             # Watch for burn events
├── attestor/
│   └── attestor.go           # Sign and submit attestations
└── config.yaml               # Runtime configuration
```

### Configuration

```yaml
# orchestrator/config.yaml

mirage:
  rpc: "tcp://127.0.0.1:26657"
  grpc: "127.0.0.1:9090"
  validator_key: "/root/.mirage/node/config/priv_validator_key.json"
  chain_id: "mirage-1"

chains:
  solana:
    enabled: true
    rpc: "https://api.mainnet-beta.solana.com"
    ws: "wss://api.mainnet-beta.solana.com"
    contract: "<SOLANA_BRIDGE_PROGRAM_ID>"
    confirmations: 32  # Finalized
    poll_interval: "5s"
  
  ethereum:
    enabled: false
    rpc: "https://eth.llamarpc.com"
    contract: "<ETHEREUM_BRIDGE_CONTRACT>"
    confirmations: 12
    poll_interval: "15s"

attestor:
  batch_size: 10           # Max attestations per tx
  retry_interval: "30s"
  max_retries: 5
```

### ChainWatcher Interface

```go
// BurnEvent represents a burn on an external chain (triggers mint on Mirage)
type ExternalBurnEvent struct {
    TxHash          string
    MirageRecipient string
    Amount          uint64
    BlockHeight     uint64
    Timestamp       time.Time
}

// MirageBurnEvent represents a burn on Mirage (triggers mint on external chain)
type MirageBurnEvent struct {
    TxHash             string
    DestinationChain   string
    DestinationAddress string
    Amount             uint64
}

type ChainWatcher interface {
    // Watch external chain for burns (inbound to Mirage)
    WatchBurns(ctx context.Context, events chan<- ExternalBurnEvent) error
    
    // Execute mint on external chain (outbound from Mirage)
    ExecuteMint(ctx context.Context, burn MirageBurnEvent) error
    
    // Get chain identifier
    ChainID() string
}
```

### Responsibilities

**Inbound (External → Mirage):**
1. Watch external chain for burn events
2. For each burn, submit `MsgBridgeAttest` to Mirage (triggers mint when threshold met)
3. Handle retries if attestation fails

**Outbound (Mirage → External):**
1. Watch Mirage for `bridge_burn` events
2. Call external chain's bridge contract to mint
3. Optionally update burn record on Mirage when minted

---

## Part 4: Frontend UI

### Chain Configuration

```javascript
// web/frontend/src/views/BridgeView.js

const BRIDGE_NETWORKS = {
  osmosis: {
    type: 'ibc',
    name: 'Osmosis',
    symbol: 'OSMO',
    channel: 'channel-1',
    inboundChannel: 'channel-108698',
    addressPrefix: 'osmo',
    canDerive: true,  // Can derive from Mirage key
    deepLinkBase: 'https://wallet.keplr.app/chains/osmosis',
    ibcDenom: 'ibc/3B6D9E089BECA458072D7624E67F0B84B8087E68B58CF0B9A65E0BA8E7818B54'
  },
  solana: {
    type: 'attested',
    name: 'Solana',
    symbol: 'SOL',
    addressRegex: /^[1-9A-HJ-NP-Za-km-z]{32,44}$/,
    canDerive: false,
    explorerUrl: 'https://solscan.io/tx/',
    instructions: 'Burn MIRAGE on Solana. Validators will automatically mint to your Mirage address within ~2 minutes.'
  }
};
```

### UI Structure

1. **Network Selector**: Dropdown to choose destination/source chain
2. **Direction Tabs**: OUTBOUND / INBOUND
3. **Dynamic Form**: Changes based on network type

**OUTBOUND (Mirage → External):**
- Amount input with max button
- Destination address:
  - IBC chains: Auto-derived from Mirage key, option for different address
  - Non-IBC chains: Manual entry with validation
- Fee display (free for subscribers, 1 MIRAGE for non-subscribers)
- Submit button

**INBOUND (External → Mirage):**
- Network selector
- Display user's `mirage1...` address with copy button
- For IBC chains: "Open in Keplr" button with deep link
- For non-IBC chains: Instructions to burn on that chain

---

## Part 5: Implementation Order

### Phase 1: IBC Bridge (Osmosis)

Ship first - well-understood, uses existing infrastructure.

1. Add `MsgIBCTransfer` to protobuf, regenerate
2. Add ante handler case
3. Implement handler calling `TransferKeeper.Transfer()`
4. Add Python datatypes and canon function
5. Add backend endpoint
6. Add frontend transaction handler
7. Wire up BridgeView with Osmosis tabs

### Phase 2: Non-IBC Message Types

Prepare the chain for attested bridges.

1. Add `MsgBridgeBurn`, `MsgBridgeAttest` to protobuf
2. Add `BridgeParams` with chain configs
3. Implement bridge keeper (burn/mint, attestation tracking)
4. Add ante handler for `MsgBridgeBurn`
5. Implement handlers for both message types
6. Add Python datatypes and backend endpoints
7. Update frontend for non-IBC chains

### Phase 3: Orchestrator Core

Build the validator sidecar.

1. Set up Go project structure
2. Implement config loading
3. Implement Mirage client (watch events, submit attestations)
4. Implement ChainWatcher interface
5. Build attestor logic with batching and retries

### Phase 4: Solana Integration

First external chain.

1. Deploy Solana bridge program (see `SOLANA_BRIDGE_SPEC.md`)
2. Implement Solana watcher in orchestrator
3. Test full round-trip (Mirage → Solana → Mirage)
4. Enable Solana in chain params via governance

### Phase 5: Additional Chains

Add more chains as needed.

1. Deploy bridge contract on new chain
2. Add watcher module to orchestrator
3. Enable chain in params via governance
4. Update frontend `BRIDGE_NETWORKS` config

Each new chain requires:
- Bridge contract deployment (external)
- Watcher module (~200-500 lines of Go)
- Governance proposal to enable
- Frontend config update

---

## Related Documents

- `SOLANA_BRIDGE_SPEC.md` - Technical spec for Solana program developer
- `blockchain/proto/mirage/core/v1/tx.proto` - Protobuf definitions
- `web/frontend/src/views/BridgeView.js` - Frontend implementation
