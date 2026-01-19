# Mirage v1.9.0 Release Notes

### Overview

This release introduces comprehensive bridge documentation for cross-chain token transfers. The bridge supports two mechanisms: native IBC for Cosmos chains (Osmosis) and a validator-attested burn/mint model for non-IBC chains (Solana, Ethereum, etc.).

The validator-attested bridge uses the same security model as the chain itself—requiring 66.67% of validator stake to attest before minting tokens on the destination chain.

---

### Bridge Documentation

Two new technical documents in `docs/bridge/`:

**BRIDGE_IMPLEMENTATION_PLAN.md**
- Complete implementation roadmap for IBC and non-IBC bridges
- Message type specifications (`MsgIBCTransfer`, `MsgBridgeBurn`, `MsgBridgeAttest`)
- Orchestrator architecture for validator sidecars
- Frontend UI structure with network selector and direction tabs
- Phased implementation order

**SOLANA_BRIDGE_SPEC.md**
- Technical specification for Solana bridge program developers
- Program instructions: `initialize`, `mint`, `burn`, `update_validators`
- Data structures: `BridgeConfig`, `ValidatorRegistry`, `MintRecord`, `BurnRecord`
- Event definitions for orchestrator integration
- Security considerations and testing checklist

---

### Bridge Architecture

**IBC Chains (Osmosis):**
- Native IBC using existing infrastructure
- Trustless transfers via `MsgIBCTransfer`
- Inbound via Keplr deep link

**Non-IBC Chains (Solana, Ethereum):**
- Burn/mint model (no escrow)
- Validator orchestrators watch both chains
- 66.67% stake threshold for attestations
- Chain-agnostic message types

---

### Key Constants

| Constant | Value |
|----------|-------|
| Mirage → Osmosis channel | `channel-1` |
| Osmosis → Mirage channel | `channel-108698` |
| Attestation threshold | 66.67% (6667/10000) |
| Chain ID | `mirage-1` |

---

### For Developers

**New documentation:**
- `docs/bridge/BRIDGE_IMPLEMENTATION_PLAN.md` — Implementation roadmap
- `docs/bridge/SOLANA_BRIDGE_SPEC.md` — Solana program specification

**Planned message types (Phase 1-2):**
- `MsgIBCTransfer` — IBC transfers with envelope signing
- `MsgBridgeBurn` — Burn MIRAGE for external chain bridging
- `MsgBridgeAttest` — Validator attestation for inbound mints
