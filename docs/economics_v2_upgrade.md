# Economics v2.0 Upgrade

## Status

### ✅ Done: Validator Minting (2026-01-12)
Proposal #46 - Minted 5B MIRAGE to each of 4 validators (20B total).

### ✅ Done: Fund Allocation
- 10B → Founders Fund
- 20B → Marketing Fund  
- 50B → Development Fund

### ✅ Done: Validator Self-Delegation

### 🔜 Next: User Balance Compensation
- 10,000x multiplier needed
- User with 10 MIRAGE → 100,000 MIRAGE ($1 at new price)
- Query accounts < 1M MIRAGE → mint to compensate

### 🔜 Then: Chain Upgrade (v1.8.0)
Code changes + param migration via governance proposal.

---

## Target Parameters

| Parameter | Value | Notes |
|-----------|-------|-------|
| `minimum-gas-prices` | `5000umirage` | app.toml |
| `RelayMinGasPrice` | 5000 | No /1000 divisor |
| `RelayMaxGasFee` | 500,000,000 | 500 MIRAGE cap |
| `SubscriptionReservePercent` | 80 | 20% burned |
| `MintQuantity` | 350,000,000 | 350 MIRAGE per 10min |
| `Tier1.PeriodFee` | 100,000,000,000 | 100K MIRAGE ($1/mo) |
| `Tier2.PeriodFee` | 200,000,000,000 | 200K MIRAGE ($2/mo) |
| `Tier3.PeriodFee` | 300,000,000,000 | 300K MIRAGE ($3/mo) |

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

## User Balance Compensation

10,000x multiplier for existing balances.

```
Old price:  ~$1/MIRAGE
New price:  $0.00001/MIRAGE
Ratio:      100,000x price drop

Compensation: 10,000x (users keep 10% of original USD value)

Example:
- User had 10 MIRAGE ($10 before)
- After: 100,000 MIRAGE ($1 at new price)
```

---

## Code Changes for v1.8.0

| File | Change |
|------|--------|
| `x/core/module/module.go` | Remove `/1000` from `deductRelayGasFee` |
| `app/ante_pow.go` | Remove `/1000` from `checkReserveOrDowngrade` |
| `cmd/miraged/cmd/root.go` | Add startup gas price check (≥5000) |
| `app/upgrades.go` | Add upgrade handler for param migration |

### deductRelayGasFee (module.go)
```go
// OLD
fee = (gasConsumed * minGasPrice + 999) / 1000

// NEW
fee = gasConsumed * minGasPrice
```

### checkReserveOrDowngrade (ante_pow.go)
```go
// OLD
requiredReserve = (gasLimit * minGasPrice + 999) / 1000

// NEW
requiredReserve = gasLimit * minGasPrice
```

### Upgrade Handler (upgrades.go)
```go
const V1_8_0_UpgradeName = "v1.8.0-economics"

func (app *App) registerV1_8_0Upgrade() {
    app.UpgradeKeeper.SetUpgradeHandler(
        V1_8_0_UpgradeName,
        func(ctx sdk.Context, plan upgradetypes.Plan, fromVM module.VersionMap) (module.VersionMap, error) {
            params := app.CoreKeeper.GetParams(ctx)
            
            params.RelayMinGasPrice = 5000
            params.RelayMaxGasFee = 500_000_000
            params.SubscriptionReservePercent = 80
            params.MintQuantity = 350_000_000
            
            if len(params.Tiers) >= 4 {
                params.Tiers[1].PeriodFee = 100_000_000_000
                params.Tiers[2].PeriodFee = 200_000_000_000
                params.Tiers[3].PeriodFee = 300_000_000_000
            }
            
            app.CoreKeeper.SetParams(ctx, params)
            return app.ModuleManager.RunMigrations(ctx, app.Configurator(), fromVM)
        },
    )
}
```

---

## Rollback Plan

```bash
sudo systemctl stop miraged
sudo cp miraged-v1.7.x /usr/local/bin/miraged
cp ~/.mirage.backup.pre-v1.8.0/node/config/app.toml ~/.mirage/node/config/
sudo systemctl start miraged
```

---

## Review Before Upgrade

### Governance (Cosmos SDK)
- [ ] `min_deposit` - currently 10 MIRAGE - WAY too low, spam risk
- [ ] `expedited_min_deposit` - currently 20 MIRAGE - same issue
- [ ] Review what values make sense with new economics

### Chain Code
- [ ] `grep -rn "umirage" blockchain/` - find hardcoded amounts
- [ ] `grep -rn "000000" blockchain/` - find token amounts
- [ ] Review Cosmos SDK module params we inherit

### Backend/Frontend
- [ ] Hardcoded MIRAGE amounts in Python
- [ ] Frontend subscription price display
- [ ] PoW difficulty for free users

---

## Checklist

### Phase 1 - Minting
- [x] Validator minting (Proposal #46)
- [x] Fund allocation proposal
- [x] Validator self-delegation
- [ ] User balance compensation (10,000x)

### Phase 2 - Chain Upgrade
- [ ] Code: Remove /1000 divisors
- [ ] Code: Startup gas price check - meaning there MUST BE A CHECK THAT A NODE HAS THE MINIMUM REQUIRED uMIRAGE AMOUNT FOR GAS!
- [ ] Code: Upgrade handler
- [ ] Test on local testnet
- [ ] Submit upgrade proposal
- [ ] Coordinate validators
- [ ] Execute upgrade
