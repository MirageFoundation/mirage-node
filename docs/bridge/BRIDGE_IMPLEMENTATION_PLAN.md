# Mirage Bridge Implementation Plan

## Overview

The Mirage bridge supports two bridging mechanisms:

1. **IBC Chains** (Osmosis, other Cosmos chains): Native IBC using `MsgIBCTransfer` - trustless, uses existing IBC infrastructure
2. **Non-IBC Chains** (Solana, Ethereum, etc.): Validator-attested burn/mint model where 66.67% of validator stake must attest before minting

The non-IBC bridge is chain-agnostic - the same message types and orchestrator support any external chain via configuration.

### Implementation Status

| Component | Status |
|-----------|--------|
| Part 1: IBC Bridge (Go + Backend + Frontend) | ✅ Complete |
| Part 2: Non-IBC Bridge Messages (Go + Backend + Frontend) | ✅ Complete |
| Part 3: Orchestrator | ⏳ Not Started |
| Part 4: Solana Integration | ⏳ Not Started |
| Part 5: Additional Chains | ⏳ Not Started |

---

## Part 1: IBC Bridge (Osmosis) ✅ COMPLETE

### How It Works

1. User signs canonical IBC transfer data in frontend
2. Backend builds `MsgIBCTransfer` with envelope fields
3. Transaction broadcast to Mirage chain
4. Ante handler (`ante_metasig.go`) verifies envelope signature
5. Ante handler (`ante_pow.go`) validates PoW for non-subscribers
6. Handler calls `TransferKeeper.Transfer()` to initiate IBC transfer
7. IBC relayer (Hermes) delivers packet to Osmosis

### Message Type

**File:** `blockchain/proto/mirage/core/v1/tx.proto`

```protobuf
message MsgIBCTransfer {
  option (cosmos.msg.v1.signer) = "authority";
  
  string authority = 1;
  
  // Envelope fields (standard)
  bytes envelope_pubkey = 2;
  bytes envelope_block_hash = 3;
  uint64 envelope_difficulty = 4;
  uint64 envelope_pow = 5;
  uint64 envelope_timestamp = 6;
  // tags 7-9 reserved
  bytes envelope_signature = 10;
  
  // Payload
  string receiver = 100;           // destination address on target chain (e.g., osmo1...)
  uint64 amount = 101;             // amount in umirage to transfer
  string source_channel = 102;     // IBC channel ID (e.g., "channel-1")
  uint64 timeout_seconds = 103;    // timeout in seconds from now (default: 600 = 10 min)
}

message MsgIBCTransferResponse {
  uint64 sequence = 1;  // IBC packet sequence number
}
```

### Implementation Files ✅

| File | Status | Changes |
|------|--------|---------|
| `blockchain/proto/mirage/core/v1/tx.proto` | ✅ | Added `MsgIBCTransfer` and `MsgIBCTransferResponse` |
| `blockchain/app/ante_metasig.go` | ✅ | Added signature verification case for `*coretypes.MsgIBCTransfer` |
| `blockchain/app/ante_pow.go` | ✅ | Added PoW validation case and `buildCanonForIBCTransfer()` |
| `blockchain/x/core/module/module.go` | ✅ | Added `IBCTransfer()` handler calling `TransferKeeper.Transfer()` |
| `blockchain/x/core/module/cli_bridge.go` | ✅ | Added `bridge ibc-transfer` CLI command |
| `shared/datatypes.py` | ✅ | Added `MsgIBCTransfer` class with correct field numbers |
| `shared/canon.py` | ✅ | Added `canon_base_ibc_transfer()` matching Go canonical bytes |
| `web/backend/routes/bridge.py` | ✅ | Added `POST /api/bridge/ibc_transfer` endpoint |
| `web/frontend/src/utils/TransactionHandler.js` | ✅ | Added `ibcTransfer()` method with canonical signing |
| `web/frontend/src/views/BridgeView.js` | ✅ | Wired up Osmosis outbound with proper network config |

### Key Constants

| Constant | Value |
|----------|-------|
| Chain ID | `mirage-1` |
| Token denom | `umirage` |
| Outbound channel (Mirage → Osmosis) | `channel-1` |
| Inbound channel (Osmosis → Mirage) | `channel-108698` |
| IBC denom on Osmosis | `ibc/3B6D9E089BECA458072D7624E67F0B84B8087E68B58CF0B9A65E0BA8E7818B54` |
| Default timeout | 600 seconds (10 minutes) |
| Timeout bounds | 60s minimum, 86400s (24h) maximum |

### Backend Validation ✅

- **Receiver address**: Validated as proper bech32 with `osmo` HRP and 20-byte payload
- **Source channel**: Must be enabled in `params.bridge_chains` configuration
- **Amount**: Must be positive integer
- **Timeout**: Clamped to [60, 86400] seconds
- **PoW**: Required for non-subscribers, forbidden for subscribers

### Inbound (Osmosis → Mirage)

Inbound IBC transfers don't require Mirage-side code changes. Users initiate from Osmosis using:
- Keplr wallet (deep link from our UI)
- Any IBC-compatible wallet

Frontend shows:
- User's `mirage1...` address with copy button
- "Open in Keplr" deep link
- Manual instructions with channel ID `channel-108698`

---

## Part 2: Non-IBC Bridge (Validator-Attested) ✅ COMPLETE

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

### Bridge Fee

- **Per-chain fee** configured in `bridge_chains[].fee` parameter
- Solana: 500 MIRAGE (500,000,000 umirage)
- Fee is **paid to the validator** who confirms the mint on the destination chain
- Incentivizes validators to run bridge orchestrators
- Applies regardless of subscriber status

### Message Types

**File:** `blockchain/proto/mirage/core/v1/tx.proto`

#### MsgBridgeBurn (User Outbound) ✅

User burns MIRAGE on Mirage to bridge out to an external chain.

```protobuf
message MsgBridgeBurn {
  option (cosmos.msg.v1.signer) = "authority";
  
  string authority = 1;
  
  // Envelope fields (standard)
  bytes envelope_pubkey = 2;
  bytes envelope_block_hash = 3;
  uint64 envelope_difficulty = 4;
  uint64 envelope_pow = 5;
  uint64 envelope_timestamp = 6;
  // tags 7-9 reserved
  bytes envelope_signature = 10;
  
  // Payload
  string destination_chain = 100;    // target chain identifier (e.g., "solana", "ethereum")
  string destination_address = 101;  // recipient address on target chain
  uint64 amount = 102;               // amount in umirage to burn and bridge
}

message MsgBridgeBurnResponse {
  string burn_id = 1;  // unique burn identifier (tx hash)
}
```

#### MsgBridgeAttest (Validator Inbound) ✅

Validator attests to a burn event on an external chain. When threshold is met, MIRAGE is minted to recipient.

```protobuf
message MsgBridgeAttest {
  option (cosmos.msg.v1.signer) = "validator";
  option (amino.name) = "mirage/x/core/MsgBridgeAttest";

  string validator = 1;         // Validator operator address (signer)
  string source_chain = 2;      // "solana", "ethereum", etc.
  string burn_id = 3;           // Unique ID (tx hash from source chain where burn occurred)
  string mirage_recipient = 4;  // Mirage address to receive minted MIRAGE
  uint64 amount = 5;            // Amount in umirage
}

message MsgBridgeAttestResponse {
  bool minted = 1;              // True if this attestation triggered minting
  int64 attested_power = 2;     // Total attested voting power so far
  int64 required_power = 3;     // Power needed to mint
}
```

**Note:** `MsgBridgeAttest` does NOT use envelope fields - it's signed directly by the validator's consensus key.

### Chain Parameters ✅

Added to `blockchain/proto/mirage/core/v1/params.proto`:

```protobuf
message BridgeChainConfig {
  string chain_id = 1;      // "solana", "osmosis", etc.
  bool enabled = 2;         // Can be disabled via governance
  uint64 fee = 3;           // Per-chain fee in umirage (e.g., 500000000 = 500 MIRAGE for Solana)
  string ibc_channel = 4;   // IBC channel ID, empty for attested chains
}

// In Params message:
repeated BridgeChainConfig bridge_chains = 50;
uint64 bridge_attestation_threshold = 51;  // 6667 = 66.67%
```

New chains can be added via governance proposal without code changes.

### Attestation Storage ✅

**File:** `blockchain/x/core/types/bridge.go`

```go
type BridgeAttestation struct {
    SourceChain     string          `json:"source_chain"`
    BurnID          string          `json:"burn_id"`
    MirageRecipient string          `json:"mirage_recipient"`
    Amount          uint64          `json:"amount"`
    Attestors       map[string]bool `json:"attestors"`  // validator addr -> attested
    AttestedPower   int64           `json:"attested_power"`
    Minted          bool            `json:"minted"`
    CreatedAt       int64           `json:"created_at"` // block height
}
```

Storage key: `bridge_attestations/{source_chain}/{burn_id}`

**Key behavior:**
- Attestations persist across blocks until threshold is met
- Same `(source_chain, burn_id)` key = same attestation record
- Multiple validators can attest over multiple blocks
- Once minted, further attestations are rejected
- Duplicate attestations from same validator are rejected

**Important:** `burn_id` should be canonicalized (e.g., lowercase hex) by orchestrators to prevent duplicate attestation records from case differences.

### Implementation Files ✅

| File | Status | Changes |
|------|--------|---------|
| `blockchain/proto/mirage/core/v1/tx.proto` | ✅ | Added `MsgBridgeBurn`, `MsgBridgeAttest`, responses |
| `blockchain/proto/mirage/core/v1/params.proto` | ✅ | Added `BridgeChainConfig`, bridge params |
| `blockchain/proto/mirage/core/v1/query.proto` | ✅ | Added `BridgeStatus`, `BridgeAttestation`, `BridgeConfig` queries |
| `blockchain/x/core/types/bridge.go` | ✅ | `BridgeAttestation` type with threshold logic |
| `blockchain/x/core/keeper/keeper.go` | ✅ | `GetOrCreateBridgeAttestation`, `SetBridgeAttestation`, `MintToAccount` |
| `blockchain/app/ante_metasig.go` | ✅ | Signature verification for `MsgBridgeBurn` (not `MsgBridgeAttest`) |
| `blockchain/app/ante_pow.go` | ✅ | PoW validation and `buildCanonForBridgeBurn()` |
| `blockchain/x/core/module/module.go` | ✅ | `BridgeBurn()`, `BridgeAttest()` handlers + query handlers |
| `blockchain/x/core/module/cli_bridge.go` | ✅ | `bridge burn`, `bridge attest`, `bridge status` CLI commands |
| `shared/datatypes.py` | ✅ | Added `MsgBridgeBurn` class |
| `shared/canon.py` | ✅ | Added `canon_base_bridge_burn()` |
| `web/backend/routes/bridge.py` | ✅ | `POST /api/bridge/burn`, `GET /api/bridge/config` endpoints |
| `web/frontend/src/utils/TransactionHandler.js` | ✅ | Added `bridgeBurn()` method |
| `web/frontend/src/views/BridgeView.js` | ✅ | Wired up Solana outbound |

### Backend Validation ✅

For `POST /api/bridge/burn`:
- **Destination chain**: Must be enabled in params AND must be non-IBC
- **Destination address**: Validated per chain (Solana: valid base58, 32 bytes decoded)
- **Amount**: Must be positive integer
- **PoW**: Required for non-subscribers, forbidden for subscribers

### Outbound Flow (Mirage → External Chain)

1. User submits `MsgBridgeBurn` with `destination_chain` and `destination_address`
2. Handler validates:
   - Chain is enabled in params and is non-IBC
   - Amount + chain fee fits in balance
   - User has sufficient balance
3. Handler **burns** amount from user's account (for minting on destination)
4. Handler **escrows** bridge_fee in module account (paid to validator on confirmation)
5. Handler emits event: `bridge_burn{chain, address, amount, burn_id, bridge_fee}`
6. Orchestrators watch for `bridge_burn` events
7. Orchestrators call external chain's bridge contract to **mint** MIRAGE
8. Orchestrator submits `MsgBridgeMinted` with destination tx proof
9. Handler **pays** escrowed bridge_fee to the validator who confirmed

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
   - Signer is active bonded validator
   - Chain is enabled and non-IBC
   - Attestation not already submitted by this validator
   - If already minted, return early (no error)
   - Recipient and amount match existing attestation (if any)
6. Handler records attestation and calculates total attested power
7. If attested power ≥ 66.67% of total voting power:
   - **Mint** MIRAGE to recipient (increases total supply)
   - Mark attestation as minted
   - Emit `bridge_mint{chain, burn_id, recipient, amount}`

---

## Part 3: Orchestrator ⏳ NOT STARTED

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

## Part 4: Frontend UI ✅ COMPLETE

### Chain Configuration

```javascript
// web/frontend/src/views/BridgeView.js

const NETWORKS = {
    osmosis: {
        id: 'osmosis',
        name: 'Osmosis',
        icon: '/bridges/osmosis.svg',
        addressPrefix: 'osmo',
        addressPlaceholder: 'osmo1...',
        canDerive: true,
        minAmount: 1,
        estimatedTime: '~30 seconds',
        isIbc: true,
        ibcChannel: 'channel-0',
    },
    solana: {
        id: 'solana',
        name: 'Solana',
        icon: '/bridges/solana.svg',
        addressPlaceholder: 'Solana address',
        canDerive: false,
        minAmount: 10,
        estimatedTime: '~2 minutes',
        isIbc: false,
    },
};
```

### UI Structure

1. **Network Selector**: Cards to choose destination chain
2. **Dynamic Form**: Changes based on network type

**OUTBOUND (Mirage → External):**
- Amount input with max button and thousands separators
- Destination address:
  - IBC chains: Auto-derived from Mirage key, option for different address
  - Non-IBC chains: Manual entry with chain-specific validation
- Fee display (per-chain fee from /api/bridge/config, paid to validator)
- "Receive on {Chain}" display
- Submit button with loading state and success/error feedback

**INBOUND (External → Mirage):**
- Network selector
- Display user's `mirage1...` address with copy button
- For IBC chains: "Open in Keplr" button with deep link
- For non-IBC chains: Instructions to burn on that chain

### Address Validation ✅

- **Osmosis**: Valid bech32 with `osmo` HRP and 20-byte payload (checksum verified)
- **Solana**: Valid base58, decodes to exactly 32 bytes

---

## Part 5: Implementation Order

### Phase 1: IBC Bridge (Osmosis) ✅ COMPLETE

- [x] Add `MsgIBCTransfer` to protobuf, regenerate
- [x] Add ante handler cases (signature + PoW)
- [x] Implement handler calling `TransferKeeper.Transfer()`
- [x] Add bridge fee deduction and burning
- [x] Add Python datatypes and canon function
- [x] Add backend endpoint with validation
- [x] Add frontend transaction handler
- [x] Wire up BridgeView with Osmosis

### Phase 2: Non-IBC Message Types ✅ COMPLETE

- [x] Add `MsgBridgeBurn`, `MsgBridgeAttest` to protobuf
- [x] Add `BridgeChainConfig` params with chain configs
- [x] Implement bridge keeper (burn/mint, attestation tracking)
- [x] Add attestation persistence across blocks
- [x] Add ante handler for `MsgBridgeBurn` (signature + PoW)
- [x] Implement handlers for both message types
- [x] Add CLI commands (`bridge burn`, `bridge attest`, `bridge status`)
- [x] Add query handlers (`BridgeStatus`, `BridgeAttestation`, `BridgeConfig`)
- [x] Add Python datatypes and backend endpoints
- [x] Add destination address validation (bech32, base58)
- [x] Add chain/channel whitelist validation
- [x] Update frontend for non-IBC chains

### Phase 3: Orchestrator Core ⏳ NOT STARTED

- [ ] Set up Go project structure
- [ ] Implement config loading
- [ ] Implement Mirage client (watch events, submit attestations)
- [ ] Implement ChainWatcher interface
- [ ] Build attestor logic with batching and retries
- [ ] Add burn_id canonicalization (lowercase hex)

### Phase 4: Solana Integration ⏳ NOT STARTED

- [ ] Deploy Solana bridge program (see `SOLANA_BRIDGE_SPEC.md`)
- [ ] Implement Solana watcher in orchestrator
- [ ] Test full round-trip (Mirage → Solana → Mirage)
- [ ] Enable Solana in chain params via governance

### Phase 5: Additional Chains ⏳ NOT STARTED

- [ ] Deploy bridge contract on new chain
- [ ] Add watcher module to orchestrator
- [ ] Enable chain in params via governance
- [ ] Update frontend `NETWORKS` config

Each new chain requires:
- Bridge contract deployment (external)
- Watcher module (~200-500 lines of Go)
- Governance proposal to enable
- Frontend config update

---

## CLI Commands ✅

```bash
# Query bridge status
miraged q core bridge-status

# Query attestation for a specific burn
miraged q core bridge-attestation solana <burn_id>

# Query bridge configuration
miraged q core bridge-config

# Submit a bridge burn (outbound to external chain)
miraged tx core bridge burn <destination_chain> <destination_address> <amount> --from <key>

# Submit attestation (validators only)
miraged tx core bridge attest <source_chain> <burn_id> <mirage_recipient> <amount> --from <validator_key>

# IBC transfer (outbound to IBC chain)
miraged tx core bridge ibc-transfer <receiver> <amount> <source_channel> [timeout_seconds] --from <key>
```

---

## Security Considerations ✅

1. **Canonical bytes**: Go, Python, and JavaScript implementations produce identical canonical bytes for signature verification
2. **Attestation uniqueness**: `burn_id` should be canonicalized (lowercase) by orchestrators to prevent duplicate records
3. **Threshold safety**: Uses `cosmossdk.io/math` for safe integer arithmetic, no overflow
4. **Duplicate prevention**: Same validator cannot attest twice; already-minted attestations are rejected
5. **Chain validation**: Destination/source chain must be enabled in params
6. **Address validation**: Chain-specific validation (bech32 for Cosmos, base58 for Solana)
7. **PoW/Reserve**: Non-subscribers must provide valid PoW; subscribers use reserve

---

## Related Documents

- `SOLANA_BRIDGE_SPEC.md` - Technical spec for Solana program developer
- `blockchain/proto/mirage/core/v1/tx.proto` - Protobuf definitions
- `blockchain/x/core/types/bridge.go` - Attestation types and logic
- `web/frontend/src/views/BridgeView.js` - Frontend implementation
- `web/backend/routes/bridge.py` - Backend API endpoints
