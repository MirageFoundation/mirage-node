# Bridge Architecture - Items to Consider

This document captures issues and improvements identified in the bridge architecture.

## Completed

- ~~Outbound confirmation is internally inconsistent: the flow requires 2/3+ voting power, but the `MsgBridgeAttestMinted` rules only describe per-attestation actions, with no threshold enforcement described.~~ **FIXED**: Outbound now uses `BridgeMintAttestation` to accumulate validator attestations with 2/3 threshold enforcement. Bridge fee is burned during `MsgBridgeBurn` (v1.9.3+).

- ~~`burn_sequence` is per-chain, but records are keyed only by `burn_id` (sequence). With multiple destination chains, identical sequences can collide and overwrite/mis-associate burns/mints.~~ **FIXED**: `BridgeBurnRecord` and `BridgeMintedRecord` keys now include destination chain: `bridge_burns/{dest_chain}/{burn_id}` and `bridge_mints/{dest_chain}/{burn_id}`.

- ~~Inbound `burn_id` is the external tx hash; a single Solana transaction can contain multiple burn instructions, which would share the same tx hash and collapse multiple burns into one attestation record.~~ **NOT AN ISSUE**: The Solana bridge program assigns unique sequence numbers to each burn. The orchestrator uses `event.BurnID` (a sequence from Solana bridge state), not the tx hash. Multiple burns in one tx get distinct sequences.

- ~~Finality/confirmation depth on Solana is not specified; orchestrators attest as soon as they detect burns. If a non-finalized tx is rolled back, Mirage could mint against a reverted event.~~ **FIXED**: Orchestrator now enforces Solana finalized commitment only (requires `ORCHESTRATOR_SOLANA_CONFIRMATIONS >= 32`).

- ~~`burn_id` semantics diverge between chain state (sequence) and indexer/API (Mirage tx hash), which is easy for clients and scripts to misuse when correlating records.~~ **FIXED**: API now uses explicit fields `burn_sequence` and `burn_tx_hash` and disallows ambiguous query parameters.

- ~~Attestation payload did not bind destination_chain, allowing potential cross-chain replay if multiple destination chains share validators.~~ **FIXED**: Both orchestrator (`minter.go`) and Solana program (`ed25519.rs`, `mint.rs`) now include `destination_chain` in the signed payload.

- ~~`MAX_VALIDATORS` and `MAX_ATTESTORS` in Solana program limited to 10.~~ **FIXED**: Raised to 100 in `constants.rs`. **Note:** This increases account sizes; ensure sufficient rent is allocated when initializing accounts.

## Future Considerations

### Automatic Validator Set Sync

**Current approach:** Validators are manually registered on Solana via the `update_validators` instruction, which requires the bridge `authority` to sign. The authority sets each validator's orchestrator pubkey and voting power.

**Why this is not trustless:** Solana has no way to verify that the registered validators/power actually match Mirage chain state. The authority could lie about who the validators are or what their stake is.

#### Why trustless is hard

Solana cannot read Mirage state directly. For Solana to *know* the Mirage validator set, one of these must happen:

| Approach | Trust Model | Complexity |
|----------|-------------|------------|
| **Single authority** (current) | Trust one party completely | Simple |
| **2/3 signed updates** | Trust that 2/3 of *current* registry is honest | Medium |
| **Light client on Solana** | Cryptographic verification of Mirage blocks | Very complex |

#### Option: 2/3 Signed Updates

Validators sign a snapshot of the validator set, and Solana verifies that 2/3+ of the *current* registry signed before accepting the update.

**Flow:**
1. Mirage chain computes validator snapshot (via `MsgCreateValidatorSnapshot` or similar)
2. Snapshot is stored on-chain with a hash
3. Validators sign the snapshot hash off-chain
4. Orchestrator collects signatures and submits to Solana
5. Solana verifies 2/3+ signatures from current registry
6. Registry updated

**Variant: On-chain aggregation (per-validator submissions)**
- Each validator submits its own signed snapshot to Solana (no off-chain signature collection).
- Solana stores a per-snapshot attestation record, tracks signing power, and finalizes once 2/3+ is reached.
- Requires adding a `submit_validator_signature` instruction and an on-chain record (similar to the existing mint attestation pattern).

**Limitations:**
- Still requires off-chain signature collection
- Bootstrap problem: first validator set must still be trusted
- Stake changes require periodic updates (e.g., daily at 00:00 UTC)

**Cost estimate (Solana fees):**
- On-chain aggregation costs one Solana transaction per validator signature.
- Base fee is ~5000 lamports per transaction signature (subject to network changes), plus optional priority fees.
- Example: 67 signatures/day (2/3 of 100) ≈ 335,000 lamports/day (~0.000335 SOL/day) + priority fees.
- Example: 100 signatures/day ≈ 500,000 lamports/day (~0.0005 SOL/day) + priority fees.

#### Option: Light Client on Solana

Implement a CometBFT light client inside the Solana program that:
- Verifies Mirage block headers (checking 2/3+ validator signatures)
- Verifies Merkle proofs for staking module state
- Trustlessly knows the current validator set

**Why this is hard:**
- Many Ed25519 signature verifications per update (expensive on Solana)
- ICS-23 Merkle proof verification in BPF
- Significant engineering effort (months of work)

This is out of scope for now.

#### Current Decision

**Keep it simple:** Use manual authority-based updates for now.

- The bridge is new and validator set is small/stable
- Manual updates are acceptable during early operation
- Can always upgrade to 2/3 signed updates later without breaking changes
- The attestation model (2/3 threshold for mints) still provides security for individual transfers

#### Key Architecture Notes

**Orchestrator keys:** Each validator runs an orchestrator with a separate Solana ed25519 keypair. This is distinct from:
- Consensus key (`priv_validator_key.json`) - ed25519, signs blocks
- Cosmos account key (keyring) - secp256k1, signs Mirage transactions

All three can be derived from the same mnemonic but use different derivation paths and (for the account key) different curves.

**Why separate Solana keys:** The Solana keypair uses derivation path `m/44'/501'/0'/0'` (Solana coin type), while the consensus key uses `m/44'/118'/1'/0'`. This could be simplified in the future to reuse the consensus key directly, since both are ed25519.

**Bridge participation:** Currently assumes all validators participate. If a validator doesn't want to run the orchestrator, they simply don't register their pubkey on Solana. However, if validators with >33% of power opt out, the bridge cannot reach the 2/3 threshold.
