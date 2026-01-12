# MIRAGE Economics v2.0 - Complete Upgrade Plan

## Executive Summary

This document outlines the complete plan to restructure MIRAGE tokenomics to achieve:
- **Meme token psychology**: Target price $0.00001/MIRAGE so users hold millions of tokens
- **Sustainable economics**: $1-3/month subscriptions with meaningful gas fees
- **Server viability**: Validators/servers compensated via minting to cover operational costs
- **Deflationary pressure**: Burns exceed minting at scale

The upgrade is executed in two phases:
1. **Phase 1**: Mint tokens to validators to establish proper stake levels
2. **Phase 2**: Chain upgrade to change gas pricing, subscriptions, and minting params

---

## Target Economics

### Core Targets

| Metric | Target Value |
|--------|--------------|
| MIRAGE Price | $0.00001/MIRAGE |
| Gas Price | 5,000 umirage/gas |
| Subscription Reserve | 80% (20% burned) |
| Tier 1 Subscription | $1/month (100,000 MIRAGE) |
| Tier 2 Subscription | $2/month (200,000 MIRAGE) |
| Tier 3 Subscription | $3/month (300,000 MIRAGE) |
| Minting Rate | 350 MIRAGE per 10 minutes |
| Validator Stake Target | $50,000 each (5,000,000,000 MIRAGE) |

### Action Costs (at 5,000 umirage/gas)

| Action | Gas Used | Cost (MIRAGE) | Cost (USD) |
|--------|----------|---------------|------------|
| Vote | 10,000 | 50 | $0.0005 |
| Post | 22,000 | 110 | $0.0011 |
| Edit | 40,000 | 200 | $0.002 |
| Follow | 16,000 | 80 | $0.0008 |
| Username | 24,000 | 120 | $0.0012 |
| Delete | 10,000 | 50 | $0.0005 |

### Subscriber Daily Allowance

| Tier | USD/Month | MIRAGE Reserve | Actions/Day |
|------|-----------|----------------|-------------|
| Tier 1 | $1 | 80,000 | ~33 |
| Tier 2 | $2 | 160,000 | ~67 |
| Tier 3 | $3 | 240,000 | ~100 |

### Minting Economics (4 Validators)

| Metric | Value |
|--------|-------|
| MintQuantity | 350 MIRAGE per interval |
| MintInterval | 200 blocks (~10 minutes) |
| Total minted/day | 50,400 MIRAGE ($0.504) |
| Per validator/day | 12,600 MIRAGE ($0.126) |
| Per validator/month | 378,000 MIRAGE ($3.78) |

### Supply Dynamics (Estimated at 1K Subscribers)

| Flow | MIRAGE/Month |
|------|--------------|
| Minted | +1,512,000 |
| Subscription burns (20%) | -2,000,000 |
| Relay gas burns | -1,125,000 |
| **Net** | **-1,613,000 (deflationary)** |

---

## Parameter Changes

### Node Config (app.toml)

```toml
minimum-gas-prices = "5000umirage"
```

### Chain Parameters (Governance)

```
# Gas Pricing
RelayMinGasPrice = 5000              # 5000 umirage/gas (full precision, no /1000)
RelayMaxGasFee = 500000000           # 500 MIRAGE cap per tx

# Subscriptions
SubscriptionReservePercent = 80      # 80% to reserve, 20% burned
Tier1.PeriodFee = 100000000000       # 100,000 MIRAGE ($1/month)
Tier2.PeriodFee = 200000000000       # 200,000 MIRAGE ($2/month)
Tier3.PeriodFee = 300000000000       # 300,000 MIRAGE ($3/month)

# Minting
MintQuantity = 350000000             # 350 MIRAGE per interval
```

### Code Changes Required

| File | Change |
|------|--------|
| `blockchain/x/core/module/module.go` | Remove `/1000` divisor from `deductRelayGasFee` |
| `blockchain/app/ante_pow.go` | Remove `/1000` divisor from `checkReserveOrDowngrade` |
| `blockchain/cmd/miraged/cmd/root.go` | Add startup check for minimum gas price |
| `blockchain/app/upgrades.go` | Add upgrade handler for param migration |

---

## Phase 1: Mint Tokens to Validators

### Objective

Increase validator stakes from ~600 MIRAGE to 5,000,000,000 MIRAGE each ($50,000 equivalent at target price).

### Calculation

```
Current stake per validator:     600 MIRAGE
Target stake per validator:      5,000,000,000 MIRAGE
Tokens to mint per validator:    4,999,999,400 MIRAGE

Number of validators:            4
Total tokens to mint:            ~20,000,000,000 MIRAGE (20B)
```

### Execution Options

**Option A: Governance Mint Proposal**
- Submit proposal to mint tokens to validator addresses
- Requires governance vote
- Most decentralized approach

**Option B: Admin/Authority Mint**
- If chain has mint authority, execute directly
- Faster but more centralized

**Option C: Script-based Mint**
- Use existing minting mechanism with modified params temporarily
- Requires temporary param change

### Steps

1. Identify all validator operator addresses
2. Calculate exact mint amounts per validator
3. Submit mint transaction(s)
4. Validators self-delegate newly minted tokens
5. Verify new stake amounts on-chain
6. Wait for delegation to be active

### Verification

```bash
# Check validator stakes after minting
miraged query staking validators
miraged query bank balances <validator-address>
```

---

## Phase 2: Chain Upgrade

### Objective

Deploy new binary with:
- Removed `/1000` divisor from RelayMinGasPrice
- Startup gas price validation
- New default parameters

### Pre-Upgrade Preparation

#### 2.1 Code Changes

**Remove /1000 Divisor (module.go)**

Find in `deductRelayGasFee`:
```go
// OLD
fee = (gasConsumed * minGasPrice + 999) / 1000

// NEW  
fee = gasConsumed * minGasPrice
```

**Remove /1000 Divisor (ante_pow.go)**

Find in `checkReserveOrDowngrade`:
```go
// OLD
requiredReserve = (gasLimit * minGasPrice + 999) / 1000

// NEW
requiredReserve = gasLimit * minGasPrice
```

**Add Startup Gas Price Check**

In `cmd/miraged/cmd/root.go` or app initialization:
```go
func validateMinGasPrice(appOpts servertypes.AppOptions) error {
    minGasPrices := cast.ToString(appOpts.Get(server.FlagMinGasPrices))
    coins, err := sdk.ParseDecCoins(minGasPrices)
    if err != nil {
        return fmt.Errorf("invalid minimum-gas-prices: %w", err)
    }
    
    for _, coin := range coins {
        if coin.Denom == "umirage" {
            required := sdk.NewDec(5000)
            if coin.Amount.LT(required) {
                return fmt.Errorf(
                    "FATAL: minimum-gas-prices=%s is below required 5000umirage for v1.8.0+\n"+
                    "Update app.toml: minimum-gas-prices = \"5000umirage\"",
                    minGasPrices,
                )
            }
        }
    }
    return nil
}
```

**Add Upgrade Handler (upgrades.go)**

```go
const V1_8_0_UpgradeName = "v1.8.0-economics"

func (app *App) registerV1_8_0Upgrade() {
    app.UpgradeKeeper.SetUpgradeHandler(
        V1_8_0_UpgradeName,
        func(ctx sdk.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
            // Update core params
            params := app.CoreKeeper.GetParams(ctx)
            
            params.RelayMinGasPrice = 5000
            params.RelayMaxGasFee = 500_000_000
            params.SubscriptionReservePercent = 80
            params.MintQuantity = 350_000_000
            
            // Update tier pricing
            if len(params.Tiers) >= 4 {
                params.Tiers[1].PeriodFee = 100_000_000_000  // Tier 1: 100K MIRAGE
                params.Tiers[2].PeriodFee = 200_000_000_000  // Tier 2: 200K MIRAGE
                params.Tiers[3].PeriodFee = 300_000_000_000  // Tier 3: 300K MIRAGE
            }
            
            app.CoreKeeper.SetParams(ctx, params)
            
            ctx.Logger().Info("v1.8.0 economics upgrade complete",
                "RelayMinGasPrice", params.RelayMinGasPrice,
                "RelayMaxGasFee", params.RelayMaxGasFee,
                "SubscriptionReservePercent", params.SubscriptionReservePercent,
                "MintQuantity", params.MintQuantity,
            )
            
            return app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
        },
    )
}
```

#### 2.2 Build & Test

```bash
# Build new binary
cd blockchain && make build

# Test on local testnet
python scripts/reset_local_testnet.py

# Verify changes work:
# - New subscription at new price
# - Relay tx deducts correct fee
# - Minting distributes correctly
# - Startup fails with low gas price
```

#### 2.3 Release Binary

```bash
# Tag release
git tag v1.8.0
git push origin v1.8.0

# Build release binaries
make release
```

### Upgrade Execution

#### Timeline

| Day | Action |
|-----|--------|
| D-14 | Announce upgrade, publish plan |
| D-7 | Release candidate binary available |
| D-3 | Final binary release |
| D-1 | Submit upgrade governance proposal |
| D0 | Proposal passes, upgrade height set |
| D+1 | Upgrade height reached, chain halts |
| D+1 | All validators swap binary + config |
| D+1 | Chain resumes with new economics |

#### Validator Upgrade Procedure

Each validator must execute:

```bash
# 1. Wait for chain to halt at upgrade height
# (chain will stop automatically)

# 2. Stop the node service
sudo systemctl stop miraged

# 3. Backup current state
cp -r ~/.mirage ~/.mirage.backup.pre-v1.8.0

# 4. Replace binary
sudo cp miraged-v1.8.0 /usr/local/bin/miraged
miraged version  # verify v1.8.0

# 5. Update app.toml (CRITICAL!)
sed -i 's/minimum-gas-prices = .*/minimum-gas-prices = "5000umirage"/' \
    ~/.mirage/node/config/app.toml

# 6. Verify config
grep minimum-gas-prices ~/.mirage/node/config/app.toml
# Should show: minimum-gas-prices = "5000umirage"

# 7. Restart node
sudo systemctl start miraged

# 8. Check logs
journalctl -u miraged -f

# 9. Verify sync
miraged status | jq .SyncInfo.catching_up
# Should be false once synced
```

### Post-Upgrade Verification

```bash
# Verify new params active
miraged query core params

# Expected output:
# relay_min_gas_price: 5000
# relay_max_gas_fee: 500000000
# subscription_reserve_percent: 80
# mint_quantity: 350000000
# tiers:
#   - period_fee: 0
#   - period_fee: 100000000000
#   - period_fee: 200000000000
#   - period_fee: 300000000000

# Check minting is working
miraged query bank balances <validator-address>
# Balance should increase every ~10 min

# Test new subscription (from backend/test)
# Verify correct MIRAGE amount deducted
```

---

## Existing User Migration

### Approach: Natural Expiration

Existing subscriptions will naturally expire as their (now tiny) reserves deplete.

| User State | What Happens |
|------------|--------------|
| Active sub with old reserve | Reserve depletes quickly, downgrades to free |
| Free user | No change, still free |
| User with MIRAGE balance | Balance unchanged, can subscribe at new rates |

### User Communication

```
Subject: MIRAGE Economics Update - Action Required

Dear MIRAGE User,

We're updating MIRAGE tokenomics to improve sustainability:

- Subscription prices: Now $1-3/month (paid in MIRAGE)
- More actions: 33-100 actions per day depending on tier
- Better value: Cleaner pricing, predictable costs

Your current subscription will expire at [DATE]. 
To continue, please re-subscribe at the new rates.

New Pricing:
- Tier 1: 100,000 MIRAGE/month ($1)
- Tier 2: 200,000 MIRAGE/month ($2)  
- Tier 3: 300,000 MIRAGE/month ($3)

[Subscribe Now Button]
```

---

## Rollback Plan

If the upgrade fails:

```bash
# 1. Stop node
sudo systemctl stop miraged

# 2. Restore old binary
sudo cp miraged-v1.7.x /usr/local/bin/miraged

# 3. Restore old config
cp ~/.mirage.backup.pre-v1.8.0/node/config/app.toml ~/.mirage/node/config/

# 4. Restore state (if needed)
cp -r ~/.mirage.backup.pre-v1.8.0/* ~/.mirage/

# 5. Restart
sudo systemctl start miraged
```

---

## Checklist Summary

### Phase 1 Checklist
- [ ] Calculate exact mint amounts per validator
- [ ] Execute mint transaction(s)
- [ ] Validators self-delegate new tokens
- [ ] Verify stake amounts on-chain
- [ ] Confirm all validators at ~5B MIRAGE stake

### Phase 2 Checklist
- [ ] Code: Remove /1000 divisor from module.go
- [ ] Code: Remove /1000 divisor from ante_pow.go
- [ ] Code: Add startup gas price check
- [ ] Code: Add upgrade handler
- [ ] Test: Local testnet deployment
- [ ] Test: New subscription flow
- [ ] Test: Relay tx gas deduction
- [ ] Test: Minting distribution
- [ ] Test: Startup fails with low gas price
- [ ] Release: Tag and build v1.8.0
- [ ] Announce: Publish upgrade timeline
- [ ] Coordinate: All validators ready
- [ ] Execute: Submit upgrade proposal
- [ ] Execute: Upgrade height reached
- [ ] Verify: All validators online
- [ ] Verify: New params active
- [ ] Verify: Block production normal
- [ ] Communicate: User migration instructions

---

## Appendix: Quick Reference

### All Parameter Changes (Copy-Paste Ready)

**app.toml:**
```toml
minimum-gas-prices = "5000umirage"
```

**Chain Params (JSON for governance):**
```json
{
  "relay_min_gas_price": 5000,
  "relay_max_gas_fee": 500000000,
  "subscription_reserve_percent": 80,
  "mint_quantity": 350000000,
  "tiers": [
    {"period_fee": 0},
    {"period_fee": 100000000000},
    {"period_fee": 200000000000},
    {"period_fee": 300000000000}
  ]
}
```

### Key Numbers

| Item | umirage | MIRAGE | USD |
|------|---------|--------|-----|
| 1 Vote | 50,000,000 | 50 | $0.0005 |
| 1 Post | 110,000,000 | 110 | $0.0011 |
| 1 Edit | 200,000,000 | 200 | $0.002 |
| Tier 1/month | 100,000,000,000 | 100,000 | $1 |
| Tier 2/month | 200,000,000,000 | 200,000 | $2 |
| Tier 3/month | 300,000,000,000 | 300,000 | $3 |
| Max fee cap | 500,000,000 | 500 | $0.005 |
| Mint/10min | 350,000,000 | 350 | $0.0035 |
| Validator stake | 5,000,000,000,000 | 5,000,000,000 | $50,000 |



------


We need to think about a fuckton of stuff that gets affected too, like minimum price for proposals. 10 mirage is obviously nothing. Review the entire code, especially the Go code, any search online for CosmosSDK to see if there are any important things we are not covering here.