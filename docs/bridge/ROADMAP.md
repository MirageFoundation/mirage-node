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

## 2. (Add future items here)

**Status:** -

---

## Related Files

- `blockchain/orchestrator/chains/solana/minter.go` - Orchestrator mint logic
- `mirage-bridge-solana/programs/mirage-bridge/src/instructions/mint.rs` - Solana mint instruction
- `mirage-bridge-solana/programs/mirage-bridge/src/utils/bech32.rs` - Bech32 utilities
