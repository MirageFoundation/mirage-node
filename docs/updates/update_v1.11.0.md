# Mirage v1.11.0 Release Notes

### Overview

v1.11.0 overhauls the Proof-of-Work difficulty system from the ground up. The old mechanism used a leading-zero-bits approach where each integer increment — say from 10 to 11 — doubled the required hash work. That made the system overly aggressive: a single step-up punished legitimate users as much as it punished spammers. The new system treats difficulty as a work multiplier with a configurable fractional step, so adjustments are gradual and proportional instead of exponential.

Under the new model, difficulty starts at 1000 (representing 1.0x the base work) and each busy window multiplies it by 1.25 — a 25% increase instead of the old 100%. That step size is now a governable on-chain parameter (`pow_difficulty_step`), so validators can vote to make the ramp steeper or gentler without a code upgrade. PoW validation switches from counting leading zero bits to a target-based comparison: the Argon2 hash is treated as a 256-bit integer and checked against a dynamic threshold derived from the difficulty factor.

This release also converts two existing governance parameters from integers to proper floating-point fractions (`subscription_reserve_percent` and `bridge_attestation_threshold`), removing the need for basis-point arithmetic and making governance proposals more intuitive. All fallback defaults and legacy clamp logic have been stripped out in favor of hard failures — if a parameter is missing or invalid, the system surfaces the error immediately rather than silently recovering.

**Upgrade Name:** `v1.11.0`

---

### Target-Based PoW Difficulty

The core change: difficulty is now a **work multiplier** rather than a bit count.

- **Base difficulty**: `1000` (= 1.0x work). This is the floor; the network never goes below it.
- **Ramp up**: on a busy window, `new = difficulty * (1 + pow_difficulty_step)` — default 25% harder per step
- **Ramp down**: on a calm sequence, `new = difficulty / (1 + pow_difficulty_step)` — symmetric 25% easier per step
- **Validation**: `Argon2id(hash) <= base_target * 1000 / difficulty` where `base_target = 2^(256 - min_difficulty)`
- **Max cap**: difficulty factor capped at `2^53 - 1` for lossless JavaScript `Number` representation

**Difficulty ramp with default 0.25 step:**

| Step | Difficulty | Multiplier | vs Previous | Old system equivalent |
|------|-----------|------------|-------------|----------------------|
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

- New parameter: `pow_difficulty_step` (`double`, range `(0, 1]`)
- Default: `0.25` (25% increase/decrease per adjustment)
- Adjustable via governance proposal — no code upgrade needed to change the ramp rate
- Setting to `0.10` would mean 10% steps; `0.50` would mean 50% steps

---

### Parameter Type Conversions

Two existing governance parameters converted from integer encoding to `double` fractions for clarity:

| Parameter | Old Type | Old Value | New Type | New Value | Meaning |
|-----------|----------|-----------|----------|-----------|---------|
| `subscription_reserve_percent` | `uint64` (0–100) | `80` | `double` (0.0–1.0) | `0.80` | 80% of period fee to reserve |
| `bridge_attestation_threshold` | `uint64` (basis points) | `6667` | `double` (0.0–1.0) | `0.6667` | 66.67% voting power required |

Governance proposals can now set these as simple fractions (e.g., `0.75` for 75%) instead of integer percentages or basis points.

---

### Upgrade Migration

The `v1.11.0` upgrade handler performs:

1. **Raw protobuf extraction** — reads old `uint64` values from raw bytes before the wire type changes would break standard unmarshalling
2. **Parameter conversion** — `subscription_reserve_percent` divided by 100, `bridge_attestation_threshold` divided by 10000, both stored as `double`
3. **New parameter init** — `pow_difficulty_step` set to `0.25` if not already present
4. **Difficulty conversion** — old bit-count values (e.g., `10`) converted to factor format: `1000 * 2^(old - min_difficulty)`

---

### Fail-Hard Enforcement

All fallback defaults and silent recovery paths removed across the stack:

- **Go (chain)**: difficulty adjustment uses the configured `pow_difficulty_step` directly — no fallback to `0.25` if the parameter is zero
- **Go (ante handler)**: rejects any `difficulty < 1000` outright instead of clamping
- **JavaScript (PoW worker)**: requires valid `minDifficulty` and `difficulty` — returns a structured error object instead of ambiguous `0` on failure
- **JavaScript (TransactionHandler)**: `requireMinDifficulty()` and `requirePowDifficulty()` throw immediately on missing or invalid values instead of falling back to `10` or `0`
- **Python (backend/shared)**: `check_pow_target()` returns `False` for out-of-range inputs instead of silently clamping via `max(difficulty, 1000)`

---

### Frontend Changes

- PoW difficulty displayed as multiplier on the Network page: `1.25x` instead of `10 bits`
- PoW worker posts structured `{ error: 'invalid_params' }` / `{ error: 'pow_failed' }` on failure
- TransactionHandler validates worker responses and surfaces clear error messages to the user
- All `min_difficulty` and `pow_difficulty` values go through strict validation helpers

---

### New Query Fields

- `QueryDifficultyResponse` now includes `min_difficulty` (field 8) — the base difficulty bits parameter used to compute the PoW target
- `GET /api/get_parameters` returns `min_difficulty` alongside `pow_difficulty`

---

### Breaking Changes

- **Difficulty values**: on-chain `current_difficulty` changes from bit-count (~10) to factor (~1000+). Any tooling that reads raw difficulty must be updated.
- **Parameter types**: `subscription_reserve_percent` and `bridge_attestation_threshold` change wire type from varint to fixed64 (double). Direct protobuf consumers must regenerate bindings.
- **PoW validation**: hash comparison is now target-based (`hash <= target`) instead of leading-zero-bit counting. All PoW implementations (bots, clients) must update.
- **Worker protocol**: PoW web worker now posts error objects instead of `0` on failure. Frontend code consuming worker messages must handle the new format.

---

### Bot / Client Migration

Update your PoW implementation. The old `leading_zero_bits(hash) >= difficulty` check is replaced:

```python
def check_pow_target(digest: bytes, difficulty: int, min_difficulty: int) -> bool:
    if difficulty < 1000:
        return False
    base_target = 1 << (256 - min_difficulty)
    eff_target = base_target * 1000 // difficulty
    return int.from_bytes(digest, "big") <= eff_target
```

- Fetch `min_difficulty` from `GET /api/get_parameters` (new field)
- `pow_difficulty` is now a factor (1000 = base) instead of a bit count
- See `docs/bot-creation.md` for the full updated example

---

### Validator Requirements

**Before Upgrade Height:**
1. Update binary to v1.11.0
2. Restart node with new binary (it will halt at upgrade height)

**After Upgrade:**
1. Verify with `python3 scripts/verify_upgrade.py --phase post` which checks:
   - `current_difficulty >= 1000` (converted to factor format)
   - `subscription_reserve_percent` is a fraction in `[0, 1]`
   - `bridge_attestation_threshold` is a fraction in `[0, 1]`
   - `pow_difficulty_step = 0.25`

---

### Roadmap

- Galleries — multiple images and videos in a single post
- Block entire topics or keywords you don't want to see
- Push notifications for mentions and replies

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
