# Mirage Token Burns

This document explains where burned tokens come from in the Mirage blockchain.

## Overview

Mirage is deflationary by design. All transaction fees are **burned** (destroyed) rather than paid to validators. Validators earn only from block rewards (minting).

## Burn Sources

### 1. Gas Fees (fee_collector burns)

**Who pays**: Anyone submitting a transaction with a gas fee (typically validators paying for PoW users)

**Flow**:
```
Tx submitter pays fee → fee_collector module → BeginBlock burns it
```

**When it happens**: Every block in `BeginBlock`, the entire `fee_collector` balance is transferred to the `core` module and burned.

**Typical amounts**: 200-600 umirage per transaction (varies by gas consumed)

**Code path**: `blockchain/x/core/module/module.go` → `BeginBlock()` → `BurnAllFromModuleName(fee_collector)`

### 2. Subscriber Relay Gas (core module burns)

**Who pays**: Paid subscribers (level 1+) from their escrowed reserve

**Flow**:
```
User subscribes → 40% of period fee escrowed in core module as "reserve"
User posts/votes → relay gas deducted from reserve → burned from core module
```

**When it happens**: After each subscriber transaction, in the message handler via `deductRelayGasFee()`

**Typical amounts**: 263-1000+ umirage per transaction (based on gas consumed, capped at `relay_max_gas_fee`)

**Code path**: `blockchain/x/core/module/module.go` → `deductRelayGasFee()` → `BurnFromModuleAmount()`

### 3. Subscription Period Fee Burns

**Who pays**: Users when subscribing or renewing

**Flow**:
```
User pays period_fee (e.g., 1 MIRAGE)
├── 40% → escrowed as reserve (for future relay gas)
└── 60% → burned immediately
```

**When it happens**:
- On initial subscription (`MsgUpgradeLevel`)
- On auto-renewal (processed in `EndBlock` when subscription expires)

**Code path**: 
- `blockchain/x/core/module/module.go` → `UpgradeLevel()` → `BurnFromAccount()`
- `blockchain/x/core/module/module.go` → `processSubscriptions()` → `BurnFromAccount()`

### 4. Leftover Reserve Burns

**Who pays**: Subscribers whose subscription expires or changes tier

**Flow**:
```
Subscription expires/renews → any remaining reserve is burned before processing
```

**When it happens**: In `EndBlock` subscription processing, or when upgrading/downgrading tier

**Code path**: `blockchain/x/core/module/module.go` → `processSubscriptions()` → `BurnFromModuleAmount()`

## Module Addresses

| Module | Address | Purpose |
|--------|---------|---------|
| `fee_collector` | `mirage17xpfvakm2amg962yls6f84z3kell8c5lxzd6yx` | Collects SDK transaction fees |
| `core` | `mirage1p4zltl2x9wx8p0lmzqpp4sdulul43u5m96x969` | Holds subscriber reserves, executes burns |

## Who Pays for PoW Transactions?

PoW (Proof-of-Work) users don't pay fees directly. Instead:

1. User submits PoW-signed message to backend
2. Backend/validator wraps it in a Cosmos SDK transaction
3. **Validator pays the gas fee** from their own balance
4. Fee goes to `fee_collector` → burned in `BeginBlock`

This means **validators subsidize PoW users**. Validators recoup this cost through block rewards (minting).

## Burn Event Types

When analyzing chain events, burns appear as:

```json
{"type": "burn", "attrs": {"burner": "<module_address>", "amount": "263umirage"}}
```

The `burner` is always a module address (usually `core`), not a user address. User funds are first transferred to the module, then burned.

## Monitoring Burns

Use the `scripts/list_burns.py` script to analyze burn activity:

```bash
python3 scripts/list_burns.py --days 7
```

This outputs JSONL with categorized burns:
- `fee_collector_burn`: Gas fees from tx submitters (validators for PoW)
- `subscriber_reserve_burn`: Relay gas from subscriber reserves  
- `subscription_fee_burn`: Period fee burns on subscribe/renew
- `leftover_reserve_burn`: Unused reserve burned on expiry/renewal

