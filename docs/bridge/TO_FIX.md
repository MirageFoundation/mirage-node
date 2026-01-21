# Bridge Architecture Issues To Fix

This document captures issues identified in `docs/bridge/bridge_architecture.md`.

## High

- ~~Outbound confirmation is internally inconsistent: the flow requires 2/3+ voting power, but the `MsgBridgeAttestMinted` rules only describe per-attestation actions and fee payout, with no threshold enforcement described.~~ **FIXED**: Outbound now uses `BridgeMintAttestation` to accumulate validator attestations with 2/3 threshold enforcement. Fee payout only occurs when threshold is crossed.
- ~~`burn_sequence` is per-chain, but records are keyed only by `burn_id` (sequence). With multiple destination chains, identical sequences can collide and overwrite/mis-associate burns/mints.~~ **FIXED**: `BridgeBurnRecord` and `BridgeMintedRecord` keys now include destination chain: `bridge_burns/{dest_chain}/{burn_id}` and `bridge_mints/{dest_chain}/{burn_id}`.
- ~~Inbound `burn_id` is the external tx hash; a single Solana transaction can contain multiple burn instructions, which would share the same tx hash and collapse multiple burns into one attestation record.~~ **NOT AN ISSUE**: The Solana bridge program assigns unique sequence numbers to each burn. The orchestrator uses `event.BurnID` (a sequence from Solana bridge state), not the tx hash. Multiple burns in one tx get distinct sequences.

## Medium

- Finality/confirmation depth on Solana is not specified; orchestrators attest as soon as they detect burns. If a non-finalized tx is rolled back, Mirage could mint against a reverted event.
- `burn_id` semantics diverge between chain state (sequence) and indexer/API (Mirage tx hash), which is easy for clients and scripts to misuse when correlating records.
