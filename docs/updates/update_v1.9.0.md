# Mirage v1.9.0 Release Notes

## Overview

v1.9.0 introduces **cross-chain bridge functionality**, enabling token transfers between Mirage and external blockchains. This release includes the Solana bridge (attested) with infrastructure ready for IBC bridges (Osmosis, Cosmos Hub).

**Upgrade Name:** `v1.9.0-bridge`

---

## Major Features

### Cross-Chain Bridge

- **Attested Bridge** for non-IBC chains (Solana, future Ethereum support)
  - Validators run orchestrators that watch external chains for burns
  - Attestations require 66.67% of voting power to mint tokens
  - Per-chain bridge fee (100 MIRAGE for Solana) paid to validator who confirms mint

- **Bridge Orchestrator** - new component for validators
  - Watches Solana for burn events
  - Submits attestations to Mirage chain
  - Configurable via `orchestrator.env`

### New Chain Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `bridge_chains` | `[{chain_id: "solana", enabled: true, fee: 100000000}]` | Enabled bridge chains with per-chain fees |
| `bridge_attestation_threshold` | `6667` (66.67%) | Voting power required for attestation |

### New CLI Commands

```bash
# Query bridge status
miraged q bridge status

# Query bridge configuration  
miraged q bridge config

# Submit attestation (validators only)
miraged tx bridge attest <source_chain> <burn_id> <recipient> <amount>

# Initiate bridge out
miraged tx bridge send <dest_chain> <dest_address> <amount>
```

---

## Security Improvements

### Rate Limiting

- **P2P Rate Limiting** via iptables (deploy migration `v1_9_0_p2p_rate_limiting`)
  - Max 5 concurrent connections per IP to port 26656
  - Max 10 new connections per minute per IP

- **Caddy Rate Limiting** reduced from 100 to 30 req/s per IP

### Authorization Fixes

- Fixed Delete message authorization to require governance for indexed content
- Security hardening in core module message handlers

---

## Infrastructure Changes

### Environment Variables

- **Renamed**: `MIRAGE_INDEXER_*` → `INDEXER_*`
  - `INDEXER_ENABLED` (was `MIRAGE_INDEXER_ENABLED`)
  - `INDEXER_DB_URL` (was `MIRAGE_INDEXER_DB_URL`)
  - Migration `v1_9_0_indexer_env_rename` handles existing deployments

- **Removed**: `MIRAGE_MODE` from `backend.env` (unused)

- **New**: `orchestrator.env` for bridge orchestrator configuration
  - `ORCHESTRATOR_ENABLED`
  - `ORCHESTRATOR_SOLANA_PROGRAM_ID`
  - `ORCHESTRATOR_SOLANA_RPC` / `ORCHESTRATOR_SOLANA_WS`
  - `ORCHESTRATOR_SOLANA_KEYPAIR`

### Deploy Migrations (v1.9.0)

| Migration | Description |
|-----------|-------------|
| `v1_9_0_indexer_env_rename` | Renames MIRAGE_INDEXER_* to INDEXER_* |
| `v1_9_0_p2p_rate_limiting` | Adds iptables rules for P2P rate limiting |

---

## Validator Requirements

### Before Upgrade Height

1. **Update binary** to v1.9.0
2. **Restart node** with new binary (it will halt at upgrade height)

### After Upgrade (Optional but Recommended)

1. **Set up orchestrator** if participating in bridge attestations:
   ```bash
   # Generate Solana wallet
   python3 deploy/setup_orchestrator.py
   
   # Fund wallet with ~0.1 SOL for fees
   # Configure orchestrator.env
   # Restart container
   ```

2. **Verify upgrade** with verification script:
   ```bash
   python3 scripts/verify_upgrade.py --phase post
   ```

---

## Breaking Changes

- None for standard node operators
- Orchestrator is optional (only needed for bridge attestation participation)

---

## File Changes Summary

### New Files
- `blockchain/orchestrator/` - Bridge orchestrator implementation
- `deploy/templates/env/orchestrator.env` - Orchestrator configuration template
- `deploy/migrations/v1_9_0_indexer_env_rename.py`
- `deploy/migrations/v1_9_0_p2p_rate_limiting.py`
- `deploy/setup_orchestrator.py` - Orchestrator setup script

### Modified Files
- `blockchain/x/core/` - Bridge message handlers and queries
- `blockchain/proto/mirage/core/v1/` - Bridge proto definitions
- `deploy/entrypoint.sh` - Orchestrator startup, env var renames
- `deploy/templates/env/indexer.env` - Renamed variables
- `shared/config.py` - Updated env var names
- Various scripts updated for new env var names

---

## Verification Checklist

Run `python3 scripts/verify_upgrade.py --phase post` which checks:

- [ ] Node health and sync status
- [ ] Upgrade applied at correct height
- [ ] All core params set correctly
- [ ] All 4 tiers configured with correct values
- [ ] Solana bridge chain enabled with fee = 100,000,000 (100 MIRAGE)
- [ ] Bridge attestation threshold = 6667
- [ ] Bridge queries working (status, config)
- [ ] Gov params unchanged
- [ ] Local config valid (app.toml, genesis.json)
- [ ] Deploy migrations applied

---

## Rollback

If issues occur, the upgrade cannot be rolled back without a coordinated hard fork. Ensure thorough testing on devnet before mainnet deployment.