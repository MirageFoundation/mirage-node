# Bridge Roadmap

Future enhancements and improvements for the Mirage-Solana bridge.

---

## 1. Dual-Signature Verification

**Status:** Planned

### Problem

Currently, when minting on Solana (Mirage → Solana flow), the Solana program only verifies the `orchestrator_pubkey` signature. It trusts that whoever controls this key is the legitimate validator operator.

If an orchestrator's Solana key is compromised, an attacker could submit fraudulent mint attestations.

### Solution

Require orchestrators to sign Solana mint attestations with **both** keys:

1. **Solana signature** from `orchestrator_pubkey` (current behavior)
2. **Mirage signature** from the key corresponding to `mirage_validator`

The `mirage_validator` bech32 address encodes the same 20-byte pubkey as `mirage1...`:
```
miragevaloper1... → decode bech32 → 20 bytes ← decode bech32 ← mirage1...
```

Since both Solana and Cosmos use ed25519, signatures are compatible.

### Implementation

**Orchestrator changes (`minter.go`):**
```go
// Sign payload with BOTH keys
solanaSignature := ed25519.Sign(solanaPrivKey, payload)
mirageSignature := ed25519.Sign(miragePrivKey, payload)
```

**Solana program changes (`mint.rs`):**
```rust
// 1. Verify Solana signature (current)
verify_ed25519(payload, solana_signature, orchestrator_pubkey)?;

// 2. Decode mirage_validator bech32 to get pubkey bytes
let mirage_pubkey = decode_bech32_pubkey(&validator_info.mirage_validator)?;

// 3. Verify Mirage signature (new)
verify_ed25519(payload, mirage_signature, mirage_pubkey)?;
```

### Benefits

- Defense in depth: attacker must compromise both keys
- Cryptographic cross-chain verification
- No additional trust assumptions

---

## 2. Automatic Validator Set from Chain Stakers

**Status:** Planned

### Problem

Currently, bridge authorities must be manually added to the Solana program via `add_validator` instructions. This creates:

1. **Redundant registration** - Validators already stake on the Mirage chain; re-adding them to the bridge is duplicate work
2. **Sync issues** - The bridge validator set can drift from the actual chain validator set
3. **Administrative overhead** - Every new validator requires a separate bridge registration transaction
4. **Stake mismatch** - Bridge authority weights must be manually kept in sync with chain stake

### Solution

Derive the bridge authority set directly from the Mirage chain's active validator set:

- **No manual addition** - Any staked validator on Mirage automatically becomes a bridge authority
- **Stake-weighted voting** - Authority weight equals their staked amount on the chain
- **Dynamic set** - Validator joins/exits/stake changes automatically reflected in bridge consensus

### Implementation Considerations

1. **State proof verification** - Solana program verifies Mirage chain state proofs to determine validator set
2. **Epoch boundaries** - Validator set changes at epoch boundaries for predictability
3. **Minimum stake threshold** - Only validators above a minimum stake participate in bridge consensus

### Benefits

- Zero administrative overhead for validator onboarding
- Perfect alignment between chain security and bridge security
- Stake-weighted consensus matches chain's economic security model
- Single source of truth for validator set

---

## Related Files

- `blockchain/orchestrator/chains/solana/minter.go` - Orchestrator mint logic
- `mirage-bridge-solana/programs/mirage-bridge/src/instructions/mint.rs` - Solana mint instruction
- `mirage-bridge-solana/programs/mirage-bridge/src/utils/bech32.rs` - Bech32 utilities
