# Solana Bridge - Orchestrator Integration Guide

This document describes how the Mirage orchestrator interacts with the Solana bridge program. It explains the exact data formats, event structures, and instruction layouts that the orchestrator expects.

## Overview

The orchestrator is a Go process that runs alongside each Mirage validator. It has two jobs:

1. **Inbound (Solana → Mirage)**: Watch for `BurnInitiated` events on Solana, then submit attestations to Mirage. Once 66.67% of validator stake attests, MIRAGE is minted on Mirage chain.

2. **Outbound (Mirage → Solana)**: Watch for `bridge_burn` events on Mirage, then call the Solana program's `mint` instruction to mint MIRAGE on Solana.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              INBOUND FLOW                                   │
│                          (Solana → Mirage)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   User burns MIRAGE        Orchestrators see          Mirage mints          │
│   on Solana program   →    BurnInitiated event   →    when 66.67%           │
│                            and submit attestations    validators attest     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                              OUTBOUND FLOW                                  │
│                          (Mirage → Solana)                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   User burns MIRAGE        Orchestrators see          Orchestrators call    │
│   on Mirage chain     →    bridge_burn event     →    Solana mint           │
│                                                       instruction           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Inbound Flow - `BurnInitiated` Event

When a user burns MIRAGE on Solana to receive native MIRAGE on Mirage chain, the Solana program must emit a `BurnInitiated` event that the orchestrator can parse.

### How Orchestrator Watches Burns

The orchestrator polls `getSignaturesForAddress` on the bridge program, then fetches each transaction and parses `Program data:` log lines for events.

```go
// Polling flow (simplified)
1. Call getSignaturesForAddress(programID)
2. For each new signature:
   a. Call getTransaction(signature)
   b. Parse tx.Meta.LogMessages for "Program data: <base64>"
   c. Decode base64, check discriminator, parse BurnInitiated event
```

### Event Format

The event must be emitted using Anchor's `emit!` macro (or equivalent), which produces a log line like:

```
Program data: <base64-encoded-event>
```

### Event Discriminator

Anchor uses the first 8 bytes as a discriminator, computed as:

```rust
sha256("event:BurnInitiated")[0..8]
```

In Go, this is:

```go
hash := sha256.Sum256([]byte("event:BurnInitiated"))
discriminator := hash[0:8]  // [228, 69, 165, 46, 81, 203, 154, 45]
```

### Event Data Layout (Borsh Serialization)

After the 8-byte discriminator, the event fields are serialized using Borsh (little-endian):

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0 | 8 | bytes | discriminator | `sha256("event:BurnInitiated")[0..8]` |
| 8 | 8 | u64 | burn_id | Auto-incrementing nonce |
| 16 | 32 | Pubkey | solana_sender | User who burned |
| 48 | 4 + N | String | mirage_recipient | Borsh string: 4-byte length + UTF-8 bytes |
| 48+4+N | 8 | u64 | amount | Amount in smallest unit (same decimals as Mirage) |
| 56+4+N | 8 | i64 | timestamp | Unix timestamp |

### Borsh String Encoding

Borsh encodes strings as:
1. 4-byte little-endian length prefix (u32)
2. UTF-8 bytes (no null terminator)

Example for `"mirage1abc...xyz"` (44 chars):
```
[44, 0, 0, 0]  // length = 44 as u32 LE
[0x6d, 0x69, 0x72, 0x61, 0x67, 0x65, 0x31, ...]  // "mirage1..."
```

### Rust Event Definition

```rust
use anchor_lang::prelude::*;

#[event]
pub struct BurnInitiated {
    pub burn_id: u64,              // Auto-incrementing nonce for unique identification
    pub solana_sender: Pubkey,     // Who burned the tokens
    pub mirage_recipient: String,  // Where to mint on Mirage (e.g., "mirage1abc...")
    pub amount: u64,               // Amount burned (6 decimals, same as Mirage)
    pub timestamp: i64,            // Unix timestamp of the burn
}
```

### Orchestrator Parsing Code

This is how the orchestrator decodes the event (from `watcher.go`):

```go
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
    // Check discriminator matches
    if !bytes.Equal(data[:8], discriminator[:]) {
        return nil, false, nil  // Not a BurnInitiated event
    }
    
    reader := bytes.NewReader(data[8:])
    
    // Read burn_id (u64 LE)
    burnID, err := readU64(reader)
    
    // Read solana_sender (32 bytes)
    senderBytes := make([]byte, 32)
    reader.Read(senderBytes)
    
    // Read mirage_recipient (Borsh string: u32 length + bytes)
    recipient, err := readString(reader)
    
    // Read amount (u64 LE)
    amount, err := readU64(reader)
    
    // Read timestamp (i64 LE)
    timestamp, err := readI64(reader)
    
    return &burnInitiatedEvent{...}, true, nil
}
```

### What Orchestrator Does With Burns

When a `BurnInitiated` event is detected:

1. Validate `mirage_recipient` is a valid bech32 address with "mirage" prefix
2. Submit `MsgBridgeAttest` to Mirage chain:
   ```
   MsgBridgeAttest {
       Validator:       "miragevaloper1...",  // This orchestrator's validator
       SourceChain:     "solana",
       BurnId:          "<burn_id as string>",  // e.g., "12345"
       MirageRecipient: "mirage1...",
       Amount:          <amount>,
   }
   ```
3. When 66.67%+ of validator stake has attested, Mirage chain mints tokens

### Important: burn_id Format

The orchestrator uses `burn_id` as the unique identifier for attestations. It converts the u64 to a string:

```go
burn.BurnID = strconv.FormatUint(event.BurnID, 10)  // "12345"
```

This must be deterministic across all orchestrators watching the same burn event.

---

## Part 2: Outbound Flow - `mint` Instruction

When a user burns MIRAGE on Mirage chain to receive wrapped MIRAGE on Solana, each orchestrator calls the Solana program's `mint` instruction.

### Mint Instruction Accounts

| Index | Account | Signer | Writable | Description |
|-------|---------|--------|----------|-------------|
| 0 | orchestrator | ✓ | ✓ | Orchestrator's Solana keypair (pays fees) |
| 1 | recipient | | | User's Solana wallet |
| 2 | recipient_token_account | | ✓ | User's MIRAGE ATA |
| 3 | mint | | ✓ | MIRAGE token mint PDA |
| 4 | bridge_config | | ✓ | Bridge config PDA |
| 5 | mint_record | | ✓ | Mint record PDA (keyed by burn_tx_hash) |
| 6 | token_program | | | SPL Token program |
| 7 | associated_token_account_program | | | ATA program |
| 8 | system_program | | | System program |

### PDA Seeds

```rust
// MIRAGE token mint
mint_pda = find_program_address([b"mint"], program_id)

// Bridge config
bridge_config_pda = find_program_address([b"bridge_config"], program_id)

// Mint record (prevents double-mint)
mint_record_pda = find_program_address([b"mint_record", burn_tx_hash], program_id)
```

### Mint Instruction Discriminator

```rust
sha256("global:mint")[0..8]
```

### Mint Instruction Data Layout

| Offset | Size | Type | Field | Description |
|--------|------|------|-------|-------------|
| 0 | 8 | bytes | discriminator | `sha256("global:mint")[0..8]` |
| 8 | 32 | [u8; 32] | burn_tx_hash | Mirage tx hash where burn occurred |
| 40 | 4 + N | String | mirage_sender | Borsh string: who burned on Mirage |
| 40+4+N | 8 | u64 | amount | Amount to mint |
| 48+4+N | 64 | [u8; 64] | orchestrator_signature | Ed25519 signature |

### Orchestrator Signature

Each orchestrator signs an attestation payload using Ed25519:

```go
// Payload format (what gets signed)
payload := []byte{}
payload = append(payload, burn_tx_hash[:]...)           // 32 bytes
payload = append(payload, borshString(mirage_sender)...) // 4 + len(sender)
payload = append(payload, uint64LE(amount)...)          // 8 bytes
payload = append(payload, recipient[:]...)              // 32 bytes (Solana pubkey)

signature := ed25519.Sign(orchestrator_private_key, payload)
```

**Security note**: The recipient is included in the signed payload to prevent redirection attacks. Without this binding, a malicious actor could intercept a valid attestation and redirect minted tokens to their own address.

### Rust Mint Params

```rust
#[derive(AnchorDeserialize)]
pub struct MintParams {
    pub burn_tx_hash: [u8; 32],        // Mirage tx hash (hex decoded)
    pub mirage_sender: String,          // Who burned on Mirage chain
    pub amount: u64,                    // Amount to mint
    pub orchestrator_signature: [u8; 64], // Ed25519 signature over attestation
}
```

### burn_tx_hash Format

The `burn_tx_hash` is the Mirage transaction hash where `MsgBridgeBurn` was executed. It's a 32-byte hex string from Mirage, passed as raw bytes:

```go
// Mirage burn event provides burn_id as hex string like:
// "a1b2c3d4e5f6...64 hex chars total"

// Orchestrator decodes to bytes:
burnHash := hex.DecodeString(burn.BurnID)  // [32]byte
```

### ATA Creation

The orchestrator will create the recipient's Associated Token Account if it doesn't exist:

```go
// Check if ATA exists
ataExists := accountExists(recipientATA)

if !ataExists {
    // Prepend CreateAssociatedTokenAccount instruction
    instructions = append(instructions, createATAInstruction)
}

// Then add mint instruction
instructions = append(instructions, mintInstruction)
```

### What Solana Program Should Do

When `mint` is called:

1. **Verify discriminator** matches `sha256("global:mint")[0..8]`
2. **Verify orchestrator** is in the ValidatorRegistry
3. **Verify signature** is valid Ed25519 over the attestation payload:
   - Reconstruct payload: `burn_tx_hash || borsh_string(mirage_sender) || amount || recipient_pubkey`
   - The `recipient_pubkey` comes from the `recipient` account (index 1)
   - This ensures orchestrators cannot redirect mints to different addresses
4. **Check mint_record** PDA doesn't exist (prevents double-mint)
5. **Track attestation**: increment attested power for this `burn_tx_hash`
6. **If threshold reached** (≥66.67% of total validator voting power):
   - Mint `amount` MIRAGE to `recipient_token_account`
   - Create/mark `mint_record` as completed
7. **Emit** `MintCompleted` event (optional, for monitoring)

---

## Part 3: Testing

### Test Inbound (Solana → Mirage)

1. Deploy your Solana program to devnet
2. Call the `burn` instruction with a test `mirage_recipient` address
3. Verify `BurnInitiated` event is emitted in transaction logs
4. Check orchestrator logs for:
   ```
   DEBUG solana burn received burn_id=1 recipient=mirage1... amount=1000000
   DEBUG attestation submitted burn_id=1 txhash=...
   ```

### Test Outbound (Mirage → Solana)

1. Submit `MsgBridgeBurn` on Mirage (via CLI or frontend):
   ```bash
   miraged tx core bridge burn solana <your-solana-address> 1000000 --from mykey
   ```
2. Check orchestrator logs for:
   ```
   DEBUG bridge burn received burn_id=<txhash> dest_chain=solana amount=1000000
   DEBUG solana mint submitted burn_id=<txhash> signature=<solana-sig>
   ```
3. Verify tokens appear in Solana wallet

### Devnet Configuration

For testing, update the orchestrator config:

```env
ORCHESTRATOR_SOLANA_RPC=https://api.devnet.solana.com
ORCHESTRATOR_SOLANA_WS=wss://api.devnet.solana.com
ORCHESTRATOR_SOLANA_PROGRAM_ID=<your-devnet-program-id>
```

---

## Part 4: Data Types Reference

### Token Details

| Property | Value |
|----------|-------|
| Token Name | MIRAGE |
| Symbol | MIRAGE |
| Decimals | 6 (same as native MIRAGE: 1 MIRAGE = 1,000,000 umirage) |
| Mint Authority | Bridge program PDA |

### Discriminator Calculation

```rust
// For events
fn event_discriminator(name: &str) -> [u8; 8] {
    let hash = sha256(format!("event:{}", name).as_bytes());
    hash[0..8].try_into().unwrap()
}

// For instructions
fn instruction_discriminator(name: &str) -> [u8; 8] {
    let hash = sha256(format!("global:{}", name).as_bytes());
    hash[0..8].try_into().unwrap()
}
```

### Discriminator Values

| Name | Type | Prefix | SHA256 Input | First 8 Bytes (Hex) |
|------|------|--------|--------------|---------------------|
| BurnInitiated | Event | `event:` | `event:BurnInitiated` | `e445a52e51cb9a2d` |
| mint | Instruction | `global:` | `global:mint` | (compute locally) |
| burn | Instruction | `global:` | `global:burn` | (compute locally) |

---

## Part 5: Error Handling

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "invalid mirage_recipient in burn event" | Bad bech32 address | Validate address format before emitting |
| "failed to fetch transaction" | RPC timeout | Orchestrator will retry |
| "transaction failed" | Mint instruction rejected | Check mint_record, validator registry |

### Orchestrator Retry Behavior

- Default: 5 retries with 30s interval
- Transient RPC errors don't stop the orchestrator
- Permanent errors (bad address format) mark transaction as processed to avoid infinite retries

---

## Part 6: Security Checklist

- [ ] `BurnInitiated` event includes all required fields
- [ ] `burn_id` is unique (auto-incrementing nonce)
- [ ] `mirage_recipient` is validated as proper bech32 before burning
- [ ] `mint` instruction verifies Ed25519 signature **including recipient binding**
- [ ] `mint` instruction checks orchestrator is in ValidatorRegistry
- [ ] `mint_record` PDA prevents double-minting
- [ ] Threshold logic requires ≥66.67% of validator stake
- [ ] Emergency pause flag can halt all operations

---

## Questions?

Contact the Mirage team for questions about:
- Orchestrator behavior and logs
- Mirage chain RPC/gRPC endpoints
- Validator registry updates
- Testing on devnet

**Mirage Chain Endpoints (for testing):**
- RPC: `tcp://127.0.0.1:26657` (local) or `tcp://mirage.vote:26657` (testnet)
- gRPC: `127.0.0.1:9090` (local) or `mirage.vote:9090` (testnet)
- Chain ID: `mirage-1`
