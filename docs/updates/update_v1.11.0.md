# Mirage v1.11.0 Release Notes

### Overview

v1.11.0 overhauls the Proof-of-Work difficulty system from the ground up. The old mechanism used a leading-zero-bits approach where each integer increment — say from 10 to 11 — doubled the required hash work. That made the system overly aggressive: a single step-up punished legitimate users as much as it punished spammers. The new system treats difficulty as an integer step counter with a configurable fractional step size for the exponential factor, so adjustments are gradual and proportional instead of exponential.

Under the new model, difficulty is an integer step counter starting at `0` (base factor = 1000, i.e., 1.0x work). Each busy window increments difficulty by 1, each calm window decrements by 1, and the effective work factor is `1000 * (1 + pow_factor)^difficulty`. That step size is now a governable on-chain parameter (`pow_factor`), so validators can vote to make the ramp steeper or gentler without a code upgrade. PoW validation switches from counting leading zero bits to a target-based comparison: the Argon2 hash is treated as a 256-bit integer and checked against a dynamic threshold derived from the computed factor.

This release also converts two existing governance parameters from integers to proper floating-point fractions (`subscription_reserve_fraction` and `bridge_attestation_threshold`), removing the need for basis-point arithmetic and making governance proposals more intuitive. All fallback defaults and legacy clamp logic have been stripped out in favor of hard failures — if a parameter is missing or invalid, the system surfaces the error immediately rather than silently recovering.

**Upgrade Name:** `v1.11.0`

---

### Target-Based PoW Difficulty

The core change: difficulty is now an integer **step count** rather than a bit count or raw factor.

- **Base difficulty**: `difficulty = 0` steps (factor = `1000`, i.e., 1.0x work)
- **Ramp up**: on a busy window, `difficulty += 1`
- **Ramp down**: on a calm sequence, `difficulty -= 1` (floored at 0)
- **Effective factor**: `factor = 1000 * (1 + pow_factor)^difficulty`
- **Validation**: `Argon2id(hash) <= base_target * 1000 / factor` where `base_target = 2^(256 - pow_base_bits)`
- **Max cap**: factor capped at `2^53 - 1` for lossless JavaScript `Number` representation

**Difficulty ramp with default 0.25 step:**

| Difficulty (steps) | Factor | Multiplier | vs Previous | Old system equivalent |
|--------------------|--------|------------|-------------|----------------------|
| 0 | 1000 | 1.00x | baseline | baseline |
| 1 | 1250 | 1.25x | +25% | ~0.32 bits |
| 2 | 1562 | 1.56x | +25% | ~0.64 bits |
| 3 | 1952 | 1.95x | +25% | ~0.96 bits |
| 4 | 2440 | 2.44x | +25% | ~1.29 bits |
| 5 | 3050 | 3.05x | +25% | ~1.61 bits |
| 6 | 3812 | 3.81x | +25% | ~1.93 bits |
| 7 | 4765 | 4.77x | +25% | ~2.25 bits |
| 8 | 5956 | 5.96x | +25% | ~2.57 bits |
| 9 | 7445 | 7.45x | +25% | ~2.90 bits |
| 10 | 9306 | 9.31x | +25% | ~3.22 bits |

Under the old system, going from difficulty 10 to 11 was +1 bit = **2x harder** (100% jump). Now it takes ~4 steps to reach the same 2x, giving the network far more granularity to respond proportionally.

---

### Governable Difficulty Step

- New parameter: `pow_factor` (`double`, range `(0, 1]`)
- Default: `0.25` (25% increase/decrease per adjustment)
- Adjustable via governance proposal — no code upgrade needed to change the ramp rate
- Setting to `0.10` would mean 10% steps; `0.50` would mean 50% steps

---

### Parameter Type Conversions

Two existing governance parameters converted from integer encoding to `double` fractions for clarity:

| Parameter | Old Type | Old Value | New Type | New Value | Meaning |
|-----------|----------|-----------|----------|-----------|---------|
| `subscription_reserve_fraction` | `uint64` (0–100) | `80` | `double` (0.0–1.0) | `0.80` | 80% of period fee to reserve |
| `bridge_attestation_threshold` | `uint64` (basis points) | `6667` | `double` (0.0–1.0) | `0.6667` | 66.67% voting power required |

Governance proposals can now set these as simple fractions (e.g., `0.75` for 75%) instead of integer percentages or basis points.

---

### Upgrade Migration

The `v1.11.0` upgrade handler performs:

1. **Raw protobuf extraction** — reads old `uint64` values from raw bytes before the wire type changes would break standard unmarshalling
2. **Parameter conversion** — `subscription_reserve_fraction` divided by 100, `bridge_attestation_threshold` divided by 10000, both stored as `double`
3. **New parameter init** — `pow_factor` set to `0.25` if not already present
4. **Difficulty conversion** — old bit-count values (e.g., `10`) converted to factor format: `1000 * 2^(old - pow_base_bits)`, then converted to steps via `round(log(factor/1000) / log(1 + pow_factor))`

---

### Fail-Hard Enforcement

All fallback defaults and silent recovery paths removed across the stack:

- **Go (chain)**: difficulty adjustment uses the configured `pow_factor` directly — no fallback to `0.25` if the parameter is zero
- **Go (ante handler)**: rejects invalid step counts and invalid `pow_factor` instead of silently clamping
- **JavaScript (PoW worker)**: requires valid `powBaseBits` and `difficulty` — returns a structured error object instead of ambiguous `0` on failure
- **JavaScript (TransactionHandler)**: `requirePowBaseBits()` and `requirePowDifficulty()` throw immediately on missing or invalid values instead of falling back to `10` or `0`
- **Python (backend/shared)**: `check_pow_target()` returns `False` for out-of-range inputs instead of silently clamping

---

### Frontend Changes

- PoW difficulty displayed as multiplier on the Network page using `pow_factor`
- PoW worker posts structured `{ error: 'invalid_params' }` / `{ error: 'pow_failed' }` on failure
- TransactionHandler validates worker responses and surfaces clear error messages to the user
- All `pow_base_bits` and `pow_difficulty` values go through strict validation helpers

---

### New Query Fields

- `QueryDifficultyResponse` now includes `pow_base_bits` (field 8) — the base difficulty bits parameter used to compute the PoW target
- `GET /api/get_parameters` returns `pow_base_bits` and `pow_factor` alongside `pow_difficulty`

---

### Breaking Changes

- **Difficulty values**: on-chain `current_difficulty` is now a step count (0, 1, 2, …). Any tooling that treated it as a factor must be updated.
- **Parameter types**: `subscription_reserve_fraction` and `bridge_attestation_threshold` change wire type from varint to fixed64 (double). Direct protobuf consumers must regenerate bindings.
- **PoW validation**: hash comparison is now target-based (`hash <= target`) instead of leading-zero-bit counting. All PoW implementations (bots, clients) must update.
- **Worker protocol**: PoW web worker now posts error objects instead of `0` on failure. Frontend code consuming worker messages must handle the new format.

---

### Bot / Client Migration

Update your PoW implementation. The old `leading_zero_bits(hash) >= difficulty` check is replaced:

```python
import math

BASE_FACTOR = 1000

def _round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))

def _difficulty_factor(steps: int, step: float) -> int:
    return _round_half_up(BASE_FACTOR * (1 + step) ** steps)

def check_pow_target(digest: bytes, difficulty_steps: int, pow_base_bits: int, pow_factor: float) -> bool:
    if difficulty_steps < 0 or pow_factor <= 0 or pow_factor > 1:
        return False
    base_target = 1 << (256 - pow_base_bits)
    factor = _difficulty_factor(difficulty_steps, pow_factor)
    eff_target = base_target * BASE_FACTOR // factor
    return int.from_bytes(digest, "big") <= eff_target
```

- Fetch `pow_base_bits` and `pow_factor` from `GET /api/get_parameters`
- `pow_difficulty` is now a step count (0 = base) instead of a bit count or factor
- See `docs/bot-creation.md` for the full updated example

---

### Validator Requirements

**Before Upgrade Height:**
1. Update binary to v1.11.0
2. Restart node with new binary (it will halt at upgrade height)

**After Upgrade:**
1. Verify with `python3 scripts/verify_upgrade.py --phase post` which checks:
   - `current_difficulty >= 0` (step count)
   - `subscription_reserve_fraction` is a fraction in `[0, 1]`
   - `bridge_attestation_threshold` is a fraction in `[0, 1]`
   - `pow_factor = 0.25`

---

### Roadmap

- Galleries — multiple images and videos in a single post
- Block entire topics or keywords you don't want to see
- Push notifications for mentions and replies

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
