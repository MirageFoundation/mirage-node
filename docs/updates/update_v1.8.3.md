# Mirage v1.8.3 Release Notes

### Overview

This release completes the Economics v2.0 overhaul—a fundamental rebalancing of Mirage's token economics. The 10,000x token multiplier means everyday actions like voting and posting now cost fractions of a cent instead of dollars. Subscribers get 80% of their fees held in reserve for gas, with only 20% burned. The math is simpler, the costs are clearer, and the chain is ready for mainstream adoption.

Deployment got a major upgrade too. Registry-first deploys push images to GitHub Container Registry and pull them on servers—build once, deploy everywhere in seconds. Hash-based detection skips unnecessary rebuilds. The Dockerfile layer order was fixed so frontend changes don't trigger full rebuilds. Multi-node deployments that used to take 20 minutes now take 2.

The chain endpoints have been reorganized under `/chain/rpc` and `/chain/rest` for clarity. A new status dashboard provides real diagnostic power—validating actual response data, checking block heights, and surfacing exactly what's wrong when something breaks.

---

### Economics v2.0 (Chain Upgrade)

**Upgrade handler:** `v1.8.0-economics`

- **Gas pricing simplified:** Removed /1000 divisor from fee calculations
- **RelayMinGasPrice:** 25 → 5000 umirage/gas
- **RelayMaxGasFee:** 5000 → 500,000,000 (500 MIRAGE cap)
- **SubscriptionReservePercent:** 40% → 80% (only 20% burned now)
- **MintQuantity:** 100,000 → 350,000,000 (350 MIRAGE per 10min)
- **Tier fees:** 10/20/30M → 100/200/300B umirage ($1/$2/$3 per month)
- **Gov min_deposit:** 10M → 500B umirage ($5)
- **Startup validation:** Node fails to start if minimum-gas-prices ≠ 5000umirage

**Action costs at new pricing:**
| Action | Gas | MIRAGE | USD |
|--------|-----|--------|-----|
| Vote | 10,000 | 50 | $0.0005 |
| Post | 22,000 | 110 | $0.0011 |
| Edit | 40,000 | 200 | $0.002 |
| Follow | 16,000 | 80 | $0.0008 |

---

### Registry-First Deploys

- Default to GHCR push/pull instead of tarball upload
- Auto-skip proto-gen and Go build when inputs unchanged (hash-based detection)
- Fix Dockerfile layer order so frontend only rebuilds when frontend changes
- Remove `docker system prune` by default (add `--prune` flag if needed)
- Use `--file` flag for legacy tarball flow when needed

---

### Chain Endpoint Restructuring

- `/rpc/*` → `/chain/rpc/*` (CometBFT RPC, includes WebSocket)
- `/lcd/*` → `/chain/rest/*` (Cosmos REST API)
- Old paths remain functional until 2026-02-20 for backwards compatibility
- Migration `v1_8_3_caddy_chain_paths` auto-updates Caddyfile on deploy

---

### Status Dashboard

- Renamed from `check_status.py` to `status_dashboard.py`
- New Endpoints card validates actual response data (block height, network, params)
- Improved error display: truncated messages, ASCII-safe output
- Better formatting: heights with commas, stake in millions
- HTTP connection refused shows green when HTTPS is working

---

### Frontend Improvements

- MIRAGE balance formatting improved (thousands separators)
- Costs displayed in MIRAGE instead of raw umirage
- Recovery flow redirects to account creation when no account found
- "Immediately hide downvoted posts" now defaults to off

---

### Unified Magic Feed Algorithm

The "magic" sort mode now uses a single scoring function across all feeds (home, following, topic/global). No more inconsistent ranking between feeds.

**Formula:** `(√S + √V + √U + √P) × R`

| Component | Description |
|-----------|-------------|
| S | Similarity sum — how many similar users upvoted this post |
| V | Net votes — signed sqrt so downvotes hurt the score |
| U | Unique commenters — discussion activity |
| P | Your prefs — signed sqrt so disliked topics/authors rank lower |
| R | Recency decay — `1 / (1 + (age_hours/24)^1.585)` |

**Key changes:**
- All components use sqrt scaling with equal weight (no arbitrary 0.5x or 0.3x multipliers)
- V and P use signed sqrt: negative values actively hurt the score instead of clamping to 0
- Following feed now uses the same scorer (P=0 since prefs don't apply)
- Topic/global feeds use the same scorer (S=0, P=0 for non-personalized ranking)
- Feed debug tooltip simplified: shows raw input values that match the formula
- Removed dead code (`_score_home_post` bucketed scorer)

---

### Bug Fixes

- Fix gas estimation: increased per-byte gas cost to 100, include indentation
- Fix Hermes config for v1.8.0 economics (gas_price = 5000)
- Fix IBC denom in Hermes config
- Fix local testnet reset: preserve .migrations file, prevent indexer log spam
- `letsencrypt_register.sh` now renders from template instead of hardcoding paths
- Status dashboard tile alignment fixed for consistent card layout
- ProxyJump support restored in `deploy_all_prod.sh`

---

### For Developers

**Migrations:**
- `v1_8_0_economics` - Updates app.toml minimum-gas-prices
- `v1_8_1_hermes_gas_price` - Regenerates Hermes config for new gas price
- `v1_8_3_caddy_chain_paths` - Updates Caddyfile with new endpoint paths

**Code changes:**
- Removed /1000 divisor from `deductRelayGasFee` in `module.go`
- Extracted `calculateRelayFee` helper for fee math
- Startup validation enforces `minimum-gas-prices = 5000umirage`
- All Go test files removed (tests run via integration scripts)

**Script renames:**
- `check_status.py` → `status_dashboard.py`

**Deprecated endpoints (remove after 2026-02-20):**
- `/rpc/*` → use `/chain/rpc/*`
- `/lcd/*` → use `/chain/rest/*`
