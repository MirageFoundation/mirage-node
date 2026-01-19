# Solana Bridge Program - Technical Specification

## Overview

This document describes the Solana program required to bridge MIRAGE tokens between the Mirage blockchain and Solana. The bridge uses a **validator-attested model** where Mirage validators run orchestrators that watch both chains and relay messages.

## Architecture

The bridge consists of three components:

1. **Mirage Chain** - Has a bridge module that burns/mints MIRAGE tokens
2. **Solana Program** (this spec) - Mints/burns MIRAGE tokens on Solana
3. **Orchestrators** - Background processes run by each Mirage validator that watch both chains and relay messages

### Outbound Flow (Mirage → Solana)

1. User submits `MsgBridgeBurn` on Mirage with their Solana destination address
2. Bridge module **burns** MIRAGE and emits an event
3. Orchestrators (run by validators) see the burn event
4. Each orchestrator calls the Solana program's `mint` instruction with an attestation
5. Once 66%+ of validator stake has attested, the Solana program mints MIRAGE to the user's Solana wallet

### Inbound Flow (Solana → Mirage)

1. User calls the Solana program's `burn` instruction, specifying their Mirage destination address
2. Solana program burns the MIRAGE and emits a `BurnInitiated` event
3. Orchestrators watch for burn events on Solana
4. Each orchestrator submits `MsgBridgeAttest` to the Mirage chain
5. Once 66%+ of validator stake has attested, the bridge module **mints** MIRAGE to the user

## Token Details

| Property | Value |
|----------|-------|
| Token Name | MIRAGE |
| Symbol | MIRAGE |
| Decimals | 6 (same as native MIRAGE on Mirage chain) |
| Type | SPL Token (Solana Program Library) |

The Solana program is the **mint authority** for MIRAGE on Solana.

---

## Program Instructions

### 1. `initialize`

**Purpose:** One-time setup to create the MIRAGE mint and configure the bridge.

**Accounts:**
| Account | Type | Description |
|---------|------|-------------|
| `authority` | Signer | Deployer (becomes program authority) |
| `mint` | PDA | MIRAGE token mint |
| `bridge_config` | PDA | Stores configuration |
| `system_program` | Program | System program |
| `token_program` | Program | SPL Token program |

**Data:**
```rust
pub struct InitializeParams {
    pub mirage_chain_id: String,      // Must be "mirage-1"
    pub attestation_threshold: u64,   // 6667 = 66.67% (matches Tendermint consensus threshold)
}
```

**Logic:**
1. Create MIRAGE mint with program as mint authority
2. Store config in bridge_config PDA

---

### 2. `mint` (Orchestrator → Solana)

**Purpose:** Mint MIRAGE to a user after they burned MIRAGE on Mirage chain. Called by orchestrators.

**Accounts:**
| Account | Type | Description |
|---------|------|-------------|
| `orchestrator` | Signer | Mirage validator's orchestrator key |
| `recipient` | Account | User's Solana wallet |
| `recipient_token_account` | Account | User's MIRAGE ATA |
| `mint` | PDA | MIRAGE token mint |
| `bridge_config` | PDA | Bridge configuration |
| `mint_record` | PDA | Tracks this specific mint (prevents duplicates) |
| `token_program` | Program | SPL Token program |

**Data:**
```rust
pub struct MintParams {
    pub burn_tx_hash: [u8; 32],       // Mirage tx hash of MsgBridgeBurn
    pub mirage_sender: String,         // mirage1... address that burned
    pub amount: u64,                   // Amount in smallest unit (umirage = 10^-6)
    pub orchestrator_signature: [u8; 64], // Signature over the attestation
}
```

**Logic:**
1. Verify `orchestrator` is a known Mirage validator (see Validator Registry below)
2. Check `mint_record` doesn't exist (prevents double-mint)
3. Verify signature is valid for this attestation
4. Track attestation: increment vote count for this `burn_tx_hash`
5. If attestation threshold reached (≥66% of validator stake):
   - Mint `amount` MIRAGE to `recipient_token_account`
   - Mark `mint_record` as completed
6. Emit `MintCompleted` event

**PDA Seeds for `mint_record`:**
```rust
seeds = [b"mint_record", burn_tx_hash.as_ref()]
```

---

### 3. `burn` (User → Solana)

**Purpose:** User burns MIRAGE to redeem native MIRAGE on Mirage chain.

**Accounts:**
| Account | Type | Description |
|---------|------|-------------|
| `user` | Signer | User burning tokens |
| `user_token_account` | Account | User's MIRAGE ATA |
| `mint` | PDA | MIRAGE token mint |
| `burn_record` | PDA | Records this burn for orchestrators |
| `token_program` | Program | SPL Token program |

**Data:**
```rust
pub struct BurnParams {
    pub mirage_recipient: String,     // mirage1... address to receive MIRAGE
    pub amount: u64,                  // Amount to burn
}
```

**Logic:**
1. Validate `mirage_recipient` is valid bech32 with "mirage" prefix
2. Burn `amount` MIRAGE from `user_token_account`
3. Create `burn_record` PDA with burn details
4. Emit `BurnInitiated` event (critical - orchestrators watch this)

**PDA Seeds for `burn_record`:**
```rust
seeds = [b"burn_record", &burn_nonce.to_le_bytes()]
```

**Event (CRITICAL):**
```rust
#[event]
pub struct BurnInitiated {
    pub burn_id: u64,                 // Auto-incrementing nonce
    pub solana_sender: Pubkey,        // Who burned
    pub mirage_recipient: String,     // Where to send on Mirage
    pub amount: u64,                  // Amount burned
    pub timestamp: i64,               // Unix timestamp
}
```

Orchestrators parse this event to know when to submit attestations to Mirage.

---

### 4. `update_validators` (Governance)

**Purpose:** Update the set of authorized orchestrator keys (Mirage validator set changes).

**Accounts:**
| Account | Type | Description |
|---------|------|-------------|
| `authority` | Signer | Program authority (multisig recommended) |
| `bridge_config` | PDA | Bridge configuration |
| `validator_registry` | PDA | List of validators and their stake weights |

**Data:**
```rust
pub struct UpdateValidatorsParams {
    pub validators: Vec<ValidatorInfo>,
}

pub struct ValidatorInfo {
    pub orchestrator_pubkey: Pubkey,  // Solana pubkey of orchestrator
    pub mirage_validator: String,     // mirage1valoper... address
    pub voting_power: u64,            // Stake weight
}
```

**Logic:**
1. Verify signer is authority
2. Replace validator registry with new set
3. Recalculate total voting power

**Note:** This should be called whenever Mirage validator set changes significantly. Could be automated via orchestrator or done periodically.

---

## Data Structures

### BridgeConfig (PDA)
```rust
#[account]
pub struct BridgeConfig {
    pub authority: Pubkey,            // Can update config
    pub mint: Pubkey,                 // MIRAGE mint address
    pub mirage_chain_id: String,      // "mirage-1"
    pub attestation_threshold: u64,   // 6667 = 66.67%
    pub total_minted: u64,            // Lifetime minted
    pub total_burned: u64,            // Lifetime burned
    pub burn_nonce: u64,              // Auto-incrementing for burn IDs
    pub paused: bool,                 // Emergency pause
}
```

### ValidatorRegistry (PDA)
```rust
#[account]
pub struct ValidatorRegistry {
    pub validators: Vec<ValidatorInfo>,
    pub total_voting_power: u64,
}
```

### MintRecord (PDA per burn_tx_hash)
```rust
#[account]
pub struct MintRecord {
    pub burn_tx_hash: [u8; 32],
    pub recipient: Pubkey,
    pub amount: u64,
    pub attestations: Vec<Pubkey>,    // Orchestrators that attested
    pub attested_power: u64,          // Sum of attesting validator power
    pub completed: bool,              // True once threshold met and minted
    pub completed_at: Option<i64>,
}
```

### BurnRecord (PDA per burn_nonce)
```rust
#[account]
pub struct BurnRecord {
    pub burn_id: u64,
    pub solana_sender: Pubkey,
    pub mirage_recipient: String,
    pub amount: u64,
    pub timestamp: i64,
    pub minted_on_mirage: bool,       // Updated by orchestrator (optional, for UI tracking)
}
```

---

## Events

Events are critical for orchestrators to watch. Use Anchor's `#[event]` macro.

### BurnInitiated
```rust
#[event]
pub struct BurnInitiated {
    pub burn_id: u64,
    pub solana_sender: Pubkey,
    pub mirage_recipient: String,
    pub amount: u64,
    pub timestamp: i64,
}
```

### MintCompleted
```rust
#[event]
pub struct MintCompleted {
    pub burn_tx_hash: [u8; 32],
    pub recipient: Pubkey,
    pub amount: u64,
    pub timestamp: i64,
}
```

### MintAttested
```rust
#[event]
pub struct MintAttested {
    pub burn_tx_hash: [u8; 32],
    pub orchestrator: Pubkey,
    pub current_power: u64,           // Attested power so far
    pub threshold: u64,               // Required power
}
```

---

## Security Considerations

### 1. Duplicate Prevention
- `MintRecord` PDA keyed by `burn_tx_hash` prevents double-minting
- `BurnRecord` PDA keyed by auto-incrementing `burn_nonce` ensures unique IDs

### 2. Attestation Threshold
- Require ≥66.67% of Mirage validator stake to approve mints
- Matches Tendermint consensus threshold
- Single compromised orchestrator cannot mint tokens

### 3. Validator Registry Sync
- Must stay in sync with Mirage validator set
- Consider automated sync via orchestrator
- Stale registry = security risk

### 4. Emergency Pause
- `paused` flag in BridgeConfig
- Authority can pause all mints/burns
- Use for security incidents

### 5. Amount Validation
- Verify amounts are reasonable (not zero, not overflow)
- Consider maximum single-transfer limits

---

## Integration with Orchestrator

The Mirage orchestrator will interact with this program:

### Watching Burns (Solana → Mirage)
```
1. Subscribe to program logs via Solana RPC
2. Parse BurnInitiated events
3. For each burn:
   - Construct MsgBridgeAttest
   - Sign with validator key
   - Submit to Mirage chain
```

### Executing Mints (Mirage → Solana)
```
1. Watch Mirage for MsgBridgeBurn events
2. For each burn:
   - Construct mint instruction
   - Sign with orchestrator key
   - Submit to Solana
3. If attestation threshold not met, wait for other orchestrators
```

### RPC Requirements
- `getSignaturesForAddress` - find program transactions
- `getTransaction` - parse logs for events
- `getProgramAccounts` - query mint/burn records
- WebSocket subscription for real-time events

---

## Testing Checklist

- [ ] Initialize bridge and mint
- [ ] Mint with single orchestrator (should not complete)
- [ ] Mint with threshold orchestrators (should complete)
- [ ] Prevent double-mint with same burn_tx_hash
- [ ] Burn tokens, verify event emitted
- [ ] Prevent burn with invalid mirage_recipient
- [ ] Update validator registry
- [ ] Pause/unpause bridge
- [ ] Edge cases: zero amount, overflow, invalid signatures

---

## Deployment

1. Deploy program to devnet first
2. Initialize with test validator set
3. Test full round-trip (Mirage → Solana → Mirage)
4. Deploy to mainnet
5. Initialize with real validator set
6. Monitor closely during initial operation

---

## Contact

For questions about the Mirage side of the bridge, the orchestrator interface, or validator set management, contact the Mirage core team.

**Mirage Chain Resources:**

- RPC: `https://mirage.vote/chain/rpc` (CometBFT RPC via proxy)
- Direct RPC: `tcp://mirage.vote:26657`
- Chain ID: `mirage-1`
- Token denom: `umirage` (1 MIRAGE = 1,000,000 umirage)
- Bridge Module Docs: See `docs/bridge/` in mirage-node repo
