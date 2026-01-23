# Mirage v1.9.0 Release Notes

### Overview

Mirage goes multi-chain. v1.9.0 delivers **native bridge support for Solana and Osmosis**, bringing MIRAGE tokens to two of the most active ecosystems in crypto. Transfer seamlessly between chains with the security guarantees you'd expect from a decentralized network—no centralized multisigs, no trusted third parties. Every bridge transfer is secured by the same validator set that runs the Mirage chain itself, requiring 2/3 of stake to confirm before tokens move.

**Solana** gets a custom validator-attested bridge with an on-chain Anchor program. Validators run orchestrators that watch for burns on either chain and submit cryptographic attestations. When supermajority consensus is reached, tokens mint automatically. **Osmosis** connects via native IBC—the battle-tested Inter-Blockchain Communication protocol that powers the Cosmos ecosystem. The Hermes relayer handles packet forwarding with light client verification, no attestation needed.

The architecture is built for expansion. Adding new chains—whether EVM-compatible like Ethereum and Arbitrum, or entirely different architectures—requires only a new orchestrator module and chain-specific program. The core attestation logic, fee distribution, and replay protection are chain-agnostic by design. Solana and Osmosis are just the beginning.

This release also ships **enterprise-grade disaster recovery** for validators. Full node backups stream directly to your local machine, and restores work with or without the original mnemonic depending on your recovery scenario. One command to backup, one command to restore.

**Upgrade Name:** `v1.9.0-bridge`

---

### Cross-Chain Bridge

- **Attested Bridge** for non-IBC chains (Solana, future Ethereum support)
  - Validators run orchestrators that watch external chains for burns
  - Attestations require 66.67% of voting power to mint tokens
  - Per-chain bridge fee (500 MIRAGE) distributed proportionally among attestors

- **IBC Bridge** for Cosmos ecosystem chains (Osmosis)
  - Uses native IBC transfer protocol with MsgIBCTransfer
  - Per-chain bridge fee (500 MIRAGE for Osmosis)
  - Auto-configured channel for Osmosis (channel-0)

- **Bidirectional attestation model**
  - Inbound: burn on external chain → attestations → mint on Mirage
  - Outbound: burn on Mirage → attestations from external chain → confirmation

- **Fee distribution**: bridge fees split proportionally among all validators who attested

---

### Solana Bridge Program (mirage-bridge-solana)

A new **Anchor-based Solana program** deployed at `ghcr.io/miragefoundation/mirage-node` provides the on-chain component for Solana↔Mirage transfers.

**Architecture:**
- Ed25519 signatures verified on-chain
- 2/3 validator stake threshold for mints
- Sequence-based replay protection via sliding window bitmap (1024 sequences)
- Zero marginal cost—rent is fully refunded after mint completion

**PDAs:**

| PDA | Seeds | Description |
|-----|-------|-------------|
| Bridge Config | `["bridge_config"]` | Global settings |
| Bridge State | `["bridge_state"]` | Replay protection bitmap |
| Validator Registry | `["validator_registry"]` | Validators + stake |
| Token Mint | `["mint"]` | MIRAGE SPL token |
| Mint Record | `["mint_record", burn_tx_hash]` | Temporary attestation tracking |
| Burn Record | `["burn_record", nonce_le_bytes]` | Burn records |

**Scripts:**

| Command | Description |
|---------|-------------|
| `bun run bridge:init` | Initialize bridge (one-time) |
| `bun run bridge:validators` | Update validator registry |
| `bun run bridge:status` | View bridge status |
| `bun run bridge:pause` | Pause bridge (emergency) |
| `bun run bridge:unpause` | Unpause bridge |

---

### IBC Bridge (Osmosis)

The Osmosis bridge uses standard **Inter-Blockchain Communication (IBC)** protocol, requiring no validator attestation—finality is handled via light client verification.

**How it works:**
```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Mirage    │    │   Hermes    │    │   Osmosis   │
│   Chain     │───▶│   Relayer   │───▶│   Chain     │
└─────────────┘    └─────────────┘    └─────────────┘
```

1. User initiates transfer with `MsgIBCTransfer` on Mirage
2. Hermes relayer (run by validators) relays the packet
3. Osmosis receives and credits the IBC-wrapped MIRAGE

**Hermes relayer setup:**
```bash
python3 deploy/setup_hermes.py
```

The setup script:
- Installs Hermes v1.13.2 binary
- Generates config from `deploy/templates/hermes/config.toml`
- Imports relayer keys for both chains (same mnemonic)
- Finds existing IBC channel or creates new one
- Starts relayer in tmux window

**Relayer addresses need funding:**
- Mirage: at least 100 MIRAGE
- Osmosis: at least 100 OSMO

**IBC channel:** `channel-0` (Mirage) ↔ `channel-108698` (Osmosis)

**IBC denom on Osmosis:**
```
ibc/E132A35DC380C8D68E99F46BC7A5083602F171D00E3BE9471541FB1AA62D8BE2
```

**Test transfer:**
```bash
miraged tx ibc-transfer transfer transfer channel-0 <OSMO_ADDR> 1000000umirage \
  --from validator --chain-id mirage-1 --fees 50000umirage
```

**Key difference from Solana:** No orchestrator needed—the Hermes relayer handles everything. However, the relayer must run continuously to keep IBC clients alive (trusting period ~13 days).

---

### Bridge Orchestrator

- New component for validators to participate in bridge attestations
- Watches Solana for burn events and submits attestations to Mirage
- Configurable via `orchestrator.env`
- **Replay protection**: validates sequences against chain state before processing
- **Idempotent minting**: handles "AlreadyMinted" gracefully for crash recovery
- **Gas simulation**: dynamically calculates tx fees via RPC simulation
- **Unordered transactions**: uses 5-minute timeout for replay protection
- **Fee logging**: `[FEES]` logs show gas fees, bridge fees received, and net profit
- **Auto-detects Solana cluster** from RPC URL (devnet/testnet/mainnet)
- **Startup banner** shows validator and Solana addresses

---

### Disaster Recovery (Backup/Restore)

New `scripts/backup_restore.py` provides full node backup and restore capabilities.

**Backup:**
```bash
python3 scripts/backup_restore.py backup --source mirage.vote
```

- Streams tar directly to local machine (no remote disk space needed)
- Progress bar via `pv` shows download progress
- Backups organized per-server: `~/.mirage/backups/{server}/{server}-{timestamp}.tgz`
- Includes blockchain data, config, keys, PostgreSQL dump, orchestrator files

**Restore (same server):**
```bash
python3 scripts/backup_restore.py restore --target mirage.vote --latest
```

- **No mnemonic required**—identity files restored from backup
- `--latest` automatically finds the most recent backup for that server
- Docker image name saved in backup metadata

**Restore (different server / migrate):**
```bash
python3 scripts/backup_restore.py restore --target 139.59.9.96 --file ~/.mirage/backups/mirage.vote/mirage.vote-20260123.tgz --migrate
```

- Requires mnemonic to derive new identity
- Deletes backup's identity files and re-derives from mnemonic
- Hermes and orchestrator must be set up manually afterward

**What gets backed up:**
- `~/.mirage/node/data/` - Full blockchain data and state
- `~/.mirage/node/config/` - Node configuration, genesis, validator keys
- `~/.mirage/node/keyring-*` - Keyring (validator account key)
- `~/.mirage/postgres/` - PostgreSQL data directory
- `~/.mirage/env/` - Environment files
- `~/.mirage/orchestrator/` - Orchestrator files (Solana keypair)
- PostgreSQL SQL dump - Clean dump for easy restore

---

### PebbleDB Migration

New `scripts/switch_to_pebbledb.py` migrates nodes from GoLevelDB to PebbleDB:

- 40-60% faster block processing
- Better memory efficiency
- State-sync based migration (fresh state download)
- Shows before/after disk usage comparison
- Updates config templates and re-renders app.toml/config.toml

```bash
python3 scripts/switch_to_pebbledb.py --target mirage.vote
```

---

### Security Improvements

**Rate Limiting:**
- **P2P Rate Limiting** via iptables (deploy migration `v1_9_0_p2p_rate_limiting`)
  - Max 5 concurrent connections per IP to port 26656
  - Max 10 new connections per minute per IP
- **Caddy Rate Limiting** reduced from 100 to 30 req/s per IP

**Authorization Fixes:**
- Fixed Delete message authorization to require governance for indexed content
- Security hardening in core module message handlers
- Governance messages forced through standard ante handler (prevents relay bypass)

**Bridge Replay Protection (Defense-in-Depth):**

| Layer | Check | Result |
|-------|-------|--------|
| **Orchestrator** | `sequence <= lastSeq` | Logged & skipped |
| **Solana Program** | Sliding window bitmap (1024 sequences) | `AlreadyMinted` or `TransactionTooOld` |

- Orchestrator queries Solana bridge state on startup to initialize sequence tracking
- Prevents processing of stale/malicious burn events
- Integer overflow protection in fee distribution calculations

---

### Frontend Changes

- **Bidirectional bridge UI**: supports both Bridge In (to Mirage) and Bridge Out (from Mirage)
- **Solana wallet integration**: connect Phantom/Solflare for Bridge In transactions
- **Dynamic bridge fees**: fetched from `/api/bridge/config` per chain
- **Multi-step progress UI**: shows burn → attestation → confirm stages with real-time polling
- **Balance display**: shows both Mirage and external chain balances
- **Chain icons**: SVG icons for Solana and Osmosis in `/public/bridges/`

---

### Infrastructure Changes

**Environment Variables:**

- **Renamed**: `MIRAGE_INDEXER_*` → `INDEXER_*`
  - `INDEXER_ENABLED` (was `MIRAGE_INDEXER_ENABLED`)
  - `INDEXER_DB_URL` (was `MIRAGE_INDEXER_DB_URL`)
  - Migration `v1_9_0_indexer_env_rename` handles existing deployments

- **Removed**: `MIRAGE_MODE` from `backend.env` (unused)

- **New**: `orchestrator.env` for bridge orchestrator configuration
  - `ORCHESTRATOR_ENABLED` - must be explicitly set
  - `ORCHESTRATOR_SOLANA_PROGRAM_ID`
  - `ORCHESTRATOR_SOLANA_RPC` / `ORCHESTRATOR_SOLANA_WS` - cluster auto-detected from URL
  - `ORCHESTRATOR_SOLANA_KEYPAIR`

**Build Changes:**
- Blockchain binaries now built to `blockchain/bin/` directory
- New build targets: `make build-orchestrator`, `make build-all`, `make test-fast`

**Deploy Migrations:**

| Migration | Description |
|-----------|-------------|
| `v1_9_0_indexer_env_rename` | Renames MIRAGE_INDEXER_* to INDEXER_* |
| `v1_9_0_p2p_rate_limiting` | Adds iptables rules for P2P rate limiting |

**Setup Scripts (converted from bash to Python):**
- `deploy/setup_orchestrator.py` - generates Solana wallet, configures orchestrator
- `deploy/setup_letsencrypt.py` - SSL certificate setup
- `deploy/setup_hermes.py` - IBC relayer configuration

---

### New Chain Parameters

| Parameter | Value | Description |
|-----------|-------|-------------|
| `bridge_chains` | Solana + Osmosis enabled | Per-chain config with fees and IBC channels |
| `bridge_attestation_threshold` | `6667` (66.67%) | Voting power required for attestation |

**Bridge chain configs in genesis:**
- Solana: `{chain_id: "solana", enabled: true, fee: 500000000}`
- Osmosis: `{chain_id: "osmosis", enabled: true, fee: 500000000, ibc_channel: "channel-0"}`

---

### New CLI Commands

```bash
# Query bridge status
miraged q bridge status

# Query bridge configuration  
miraged q bridge config

# Query attestations for a burn
miraged q bridge attestations <chain> <burn_id>

# Submit attestation (validators only)
miraged tx bridge attest-burned <source_chain> <burn_id> <recipient> <amount>

# Confirm external mint (validators only)
miraged tx bridge attest-minted <dest_chain> <burn_id> <external_tx_hash>

# Initiate bridge out (burn on Mirage)
miraged tx bridge burn <dest_chain> <dest_address> <amount>
```

---

### Validator Requirements

**Before Upgrade Height:**
1. Update binary to v1.9.0
2. Restart node with new binary (it will halt at upgrade height)

**After Upgrade (Optional but Recommended):**

1. Set up Solana orchestrator if participating in Solana bridge attestations:
   ```bash
   # Run setup script (generates wallet, registers validator)
   python3 deploy/setup_orchestrator.py
   
   # Fund Solana wallet with ~0.1 SOL for fees
   # Restart container to start orchestrator
   ```

2. Set up Hermes relayer if participating in IBC relaying:
   ```bash
   python3 deploy/setup_hermes.py
   
   # Fund relayer addresses:
   #   Mirage: at least 100 MIRAGE
   #   Osmosis: at least 100 OSMO
   ```

3. Verify upgrade with verification script:
   ```bash
   python3 scripts/verify_upgrade.py --phase post
   ```

**Orchestrator Verification:**
After starting, check logs for:
- `[REPLAY] initialized solana last_sequence=<N>` - replay protection active
- `solscan: https://solscan.io/tx/...` - correct cluster URL
- Startup banner showing validator and Solana addresses

**Hermes Verification:**
After starting, check tmux window `hermes`:
- `tmux select-window -t mirage:hermes`
- Look for `spawned packet worker` messages
- Run `hermes query channel end --chain mirage-1 --port transfer --channel channel-0` to verify channel is Open

---

### API Changes

**Backend Endpoints (New):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/bridge/config` | GET | Returns bridge chain configs with per-chain fees |
| `/api/bridge/get_minted` | GET | Query mint confirmation by burn_id |
| `/api/bridge/attestations` | GET | Query attestations for a burn |

**Query RPC Changes:**
- All query RPCs renamed to use `Get` prefix for consistency
- Example: `Params` → `GetParams`, `Profile` → `GetProfile`

**New Messages:**
- `MsgIBCTransfer` - IBC token transfer with envelope signature
- `MsgBridgeBurn` - Burn tokens for outbound bridge
- `MsgBridgeAttestBurned` - Validator attestation for inbound burns
- `MsgBridgeAttestMinted` - Validator confirmation for outbound mints

All bridge endpoints use `/api/bridge/` prefix.

---

### Breaking Changes

- **API**: `/api/get_bridge_minted` renamed to `/api/bridge/get_minted`
- **Query RPCs**: All renamed to use `Get` prefix
- **Build path**: `blockchain/miraged` → `blockchain/bin/miraged`
- **Env vars**: `MIRAGE_INDEXER_*` → `INDEXER_*`

Orchestrator is optional (only needed for bridge attestation participation).

---

### Documentation

New comprehensive module documentation in `docs/modules/`:
- `BACKEND.md` - Python Flask backend architecture
- `BLOCKCHAIN_CORE.md` - Go blockchain and core module
- `DEPLOYMENT.md` - Deploy scripts, Docker, migrations
- `FRONTEND.md` - React frontend architecture
- `INDEXER.md` - Indexer service and database schema
- `ORCHESTRATOR.md` - Bridge orchestrator operation
- `SHARED_MODULES.md` - Shared Python libraries

---

### File Changes Summary

**New Files:**
- `blockchain/orchestrator/` - Bridge orchestrator (Go)
- `blockchain/cmd/orchestrator/main.go` - Orchestrator binary entry
- `blockchain/app/ante_canon_test.go` - Canonical serialization tests
- `deploy/setup_orchestrator.py` - Orchestrator setup
- `deploy/setup_letsencrypt.py` - SSL setup
- `deploy/setup_hermes.py` - IBC relayer setup
- `deploy/enable_rate_limiting.sh` - P2P rate limiting
- `deploy/templates/env/orchestrator.env` - Orchestrator config
- `deploy/migrations/v1_9_0_*.py` - Deploy migrations
- `scripts/backup_restore.py` - Disaster recovery backup/restore
- `scripts/switch_to_pebbledb.py` - Database migration script
- `scripts/status_dashboard.py` - Node status monitoring
- `web/backend/routes/bridge.py` - Bridge API endpoints
- `web/frontend/src/utils/solanaBridge.js` - Solana wallet integration
- `web/frontend/public/bridges/*.svg` - Chain icons
- `docs/modules/*.md` - Module documentation

**New Repository:**
- `mirage-bridge-solana/` - Anchor-based Solana program for bridge

**Modified:**
- `blockchain/x/core/` - Bridge handlers, queries, tests
- `blockchain/proto/mirage/core/v1/` - Bridge proto definitions
- `blockchain/app/upgrades.go` - v1.9.0-bridge, v1.9.1-seq-fix, v1.10.0-bridge-refactor
- `blockchain/Makefile` - New build targets
- `deploy/deploy.sh` - Improved UX, --no-cache flag
- `indexer/message_processor.py` - Bridge message handlers
- `web/frontend/src/views/BridgeView.js` - Complete bridge UI

---

### Verification Checklist

Run `python3 scripts/verify_upgrade.py --phase post` which checks:

- [ ] Node health and sync status
- [ ] Upgrade applied at correct height
- [ ] All core params set correctly
- [ ] All 4 tiers configured with correct values
- [ ] Solana bridge chain enabled with fee = 500,000,000 (500 MIRAGE)
- [ ] Osmosis bridge chain enabled with fee = 500,000,000 (500 MIRAGE)
- [ ] Bridge attestation threshold = 6667
- [ ] Bridge queries working (status, config)
- [ ] Gov params unchanged
- [ ] Local config valid (app.toml, genesis.json)
- [ ] Deploy migrations applied

---

### Rollback

If issues occur, the upgrade cannot be rolled back without a coordinated hard fork. Ensure thorough testing on devnet before mainnet deployment.

---

### Upgrade Handlers

| Handler | Description |
|---------|-------------|
| `v1.9.0-bridge` | Main bridge upgrade - enables Solana + Osmosis |
| `v1.9.1-seq-fix` | Advances Solana sequence to 100 (recovery hack) |
| `v1.10.0-bridge-refactor` | Bridge attestation model refactor |
