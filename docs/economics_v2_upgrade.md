# Economics v2.0 Upgrade

## Status

### ✅ Phase 1 Complete (2026-01-12)

| Step | Status | Details |
|------|--------|---------|
| Validator Minting | ✅ Proposal #46 | 5B MIRAGE × 4 validators = 20B |
| Fund Allocation | ✅ | 10B Founders + 20B Marketing + 50B Dev = 80B |
| Validator Self-Delegation | ✅ | All validators staked |
| User Compensation | ✅ | 10,000x multiplier, 76 users, ~10B MIRAGE |

**Total Minted in Phase 1:** ~110B MIRAGE

### ✅ Phase 2 Complete (2026-01-14)

Chain upgrade `v1.8.0-economics` deployed successfully.

---

## Target Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| minimum-gas-prices | 5000umirage | app.toml |
| RelayMinGasPrice | 5000 | No /1000 divisor |
| RelayMaxGasFee | 500,000,000 | 500 MIRAGE cap |
| SubscriptionReservePercent | 80 | 20% burned |
| MintQuantity | 350,000,000 | 350 MIRAGE per 10min |
| Tier1.PeriodFee | 100,000,000,000 | 100K MIRAGE ($1/mo) |
| Tier2.PeriodFee | 200,000,000,000 | 200K MIRAGE ($2/mo) |
| Tier3.PeriodFee | 300,000,000,000 | 300K MIRAGE ($3/mo) |

### Action Costs (at 5000 umirage/gas)

| Action | Gas | MIRAGE | USD |
|--------|-----|--------|-----|
| Vote | 10,000 | 50 | $0.0005 |
| Post | 22,000 | 110 | $0.0011 |
| Edit | 40,000 | 200 | $0.002 |
| Follow | 16,000 | 80 | $0.0008 |

### Subscriber Daily Allowance

| Tier | $/Month | Reserve | Actions/Day |
|------|---------|---------|-------------|
| Tier 1 | $1 | 80,000 MIRAGE | ~33 |
| Tier 2 | $2 | 160,000 MIRAGE | ~67 |
| Tier 3 | $3 | 240,000 MIRAGE | ~100 |

---

## User Balance Compensation (DONE)

10,000x multiplier applied to all user accounts with < 1M MIRAGE.

Old price:  ~$1/MIRAGE
New price:  $0.00001/MIRAGE
Ratio:      100,000x price drop

Compensation: 10,000x (users keep 10% of original USD value)

Example:
- User had 10 MIRAGE ($10 before)
- After: 100,000 MIRAGE ($1 at new price)

**Note:** Module accounts (bonded_tokens_pool, fee_collector, distribution, gov, core) 
do NOT need compensation - their balances are derived from user actions (staking, fees, etc.).

---

## Code Changes for v1.8.0

| File | Change |
|------|--------|
| x/core/module/module.go | Remove /1000 from deductRelayGasFee |
| app/ante_pow.go | Remove /1000 from checkReserveOrDowngrade |
| cmd/miraged/cmd/root.go | Add startup gas price check (≥5000) |
| app/upgrades.go | Add upgrade handler for param migration |

### deductRelayGasFee (module.go)

OLD: fee = (gasConsumed * minGasPrice + 999) / 1000
NEW: fee = gasConsumed * minGasPrice

### checkReserveOrDowngrade (ante_pow.go)

OLD: requiredReserve = (gasLimit * minGasPrice + 999) / 1000
NEW: requiredReserve = gasLimit * minGasPrice

### Startup Gas Price Check (root.go)

Fail startup if minimum-gas-prices < 5000umirage

### Upgrade Handler (upgrades.go)

V1_8_0_UpgradeName = "v1.8.0-economics"

Updates:
- params.RelayMinGasPrice = 5000
- params.RelayMaxGasFee = 500_000_000
- params.SubscriptionReservePercent = 80
- params.MintQuantity = 350_000_000
- params.Tiers[1].PeriodFee = 100_000_000_000
- params.Tiers[2].PeriodFee = 200_000_000_000
- params.Tiers[3].PeriodFee = 300_000_000_000

---

## Governance Params (MUST UPDATE)

Current gov params become meaningless after 10,000x multiplier:

| Parameter | Current | Problem | Suggested |
|-----------|---------|---------|-----------|
| min_deposit | 10 MIRAGE | $0.0001 - spam risk | 1,000,000 MIRAGE ($10) |
| expedited_min_deposit | 20 MIRAGE | $0.0002 - spam risk | 2,000,000 MIRAGE ($20) |

These should be updated in the v1.8.0 upgrade handler via gov module params.

---

## Rollback Plan

1. Stop node: sudo systemctl stop miraged
2. Restore binary: sudo cp miraged-v1.7.x /usr/local/bin/miraged
3. Restore config: cp ~/.mirage.backup.pre-v1.8.0/node/config/app.toml ~/.mirage/node/config/
4. Start node: sudo systemctl start miraged

---

## Review Before Upgrade (DONE)

### Governance (Cosmos SDK)
- [x] Update min_deposit to 500B umirage ($5)
- [x] Update expedited_min_deposit to 1T umirage ($10)
- [x] Review other gov params (voting_period, quorum, etc.)

### Chain Code
- [x] grep -rn "umirage" blockchain/ - find hardcoded amounts
- [x] grep -rn "000000" blockchain/ - find token amounts
- [x] Review Cosmos SDK module params we inherit

### Backend/Frontend
- [x] Hardcoded MIRAGE amounts in Python
- [x] Frontend subscription price display
- [x] PoW difficulty for free users

---

## Checklist

### Phase 1 - Minting ✅
- [x] Validator minting (Proposal #46)
- [x] Fund allocation proposal
- [x] Validator self-delegation
- [x] User balance compensation (10,000x)

### Phase 2 - Chain Upgrade ✅
- [x] Code: Remove /1000 divisors
- [x] Code: Startup gas price check (MUST validate minimum-gas-prices >= 5000umirage)
- [x] Code: Upgrade handler (core params + gov params)
- [x] Test on local testnet
- [x] Submit upgrade proposal
- [x] Coordinate validators
- [x] Execute upgrade
- [x] Verify all validators updated app.toml
