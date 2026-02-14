# Mirage Blockchain Core Architecture

This document provides a comprehensive technical overview of the Mirage blockchain application layer. It is intended for senior engineers, architects, and project managers who need to understand the system's design philosophy, architectural decisions, and the rationale behind key implementation choices.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture Philosophy](#architecture-philosophy)
3. [Transaction Processing Model](#transaction-processing-model)
4. [Custom AnteHandler Pipeline](#custom-antehandler-pipeline)
5. [Core Module (x/core)](#core-module-xcore)
6. [User Tier System](#user-tier-system)
7. [Tokenomics Design](#tokenomics-design)
8. [Block Lifecycle Events](#block-lifecycle-events)
9. [Observability and Debugging](#observability-and-debugging)
10. [Security Model](#security-model)

---

## Overview

Mirage is a decentralized social platform built on **Cosmos SDK** with **CometBFT** consensus. The blockchain serves as the authoritative source of truth for user-generated content (posts, votes, comments), user profiles, subscriptions, and token transfers.

### Key Design Goals

1. **Gas-less User Experience**: End users should not need to hold tokens or pay gas fees to interact with the platform (for free tier users)
2. **Spam Prevention Without Fees**: Use Proof-of-Work as an alternative to economic barriers for free-tier users
3. **Tiered Feature Access**: Paid subscriptions unlock additional platform capabilities
4. **Deflationary Economics**: Burn mechanisms reduce supply over time
5. **Cross-Chain Interoperability**: Support bridging to external chains (Solana)

### Technology Stack

- **Cosmos SDK v0.53**: Application framework with depinject-based dependency injection
- **CometBFT**: Byzantine fault-tolerant consensus engine
- **Protobuf**: Message serialization for both Go and Python services
- **Argon2id**: Memory-hard hash function for Proof-of-Work
- **secp256k1**: Elliptic curve cryptography for signatures

---

## Architecture Philosophy

### Why Cosmos SDK?

The decision to build on Cosmos SDK stems from several architectural needs:

1. **Modular Design**: Custom application logic (`x/core`) integrates cleanly with standard SDK modules (auth, bank, staking, governance)
2. **Sovereignty**: Full control over transaction processing, fee models, and consensus parameters
3. **Bridge Support**: Attested bridge for external chain transfers
4. **Governance**: On-chain parameter updates through proposal/voting mechanisms

### Why Not a Traditional Backend?

A traditional database-backed system would be simpler, but Mirage requires:

- **Censorship Resistance**: No single party can delete or modify content
- **Transparency**: All state transitions are publicly auditable
- **Decentralization**: Multiple validators prevent single points of failure
- **Cryptographic Authenticity**: Every action is signed by the user's private key

### The Dual-Layer Architecture

Mirage employs a dual-layer architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                     Frontend (React)                        │
│         - User interaction, PoW computation (optional)      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   Backend (Python Flask)                    │
│    - Transaction building, PoW computation, API serving     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Blockchain (Cosmos SDK)                     │
│        - Consensus, state machine, authoritative truth      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Indexer (Python)                         │
│        - Denormalized view for efficient queries            │
└─────────────────────────────────────────────────────────────┘
```

The blockchain is the **authoritative source** of truth, but its on-chain state is optimized for consensus, not queries. The indexer denormalizes this state into PostgreSQL for efficient retrieval by the backend.

---

## Transaction Processing Model

### The Problem: Gas Fees Destroy UX

Traditional blockchains require users to:
1. Acquire native tokens
2. Manage gas estimation
3. Pay fees for every interaction

This creates massive friction for a social platform where users expect to post, vote, and comment freely.

### The Solution: Relay Transactions with Meta-Signatures

Mirage implements a **relay transaction model** where:

1. **Users sign messages** with their private key (creating a "meta-signature")
2. **The validator/node pays gas** on behalf of the user
3. **User identity is proven** through the embedded signature, not the transaction signer

This is conceptually similar to EIP-712 meta-transactions in Ethereum, but implemented natively in the Cosmos SDK ante handler chain.

### Transaction Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Transaction Flow                                   │
└─────────────────────────────────────────────────────────────────────────────┘

User Device                    Backend/Node                    Blockchain
    │                              │                               │
    │  1. Create message           │                               │
    │     (MsgPost, MsgVote, etc.) │                               │
    │                              │                               │
    │  2. Sign canonical bytes     │                               │
    │     with private key         │                               │
    │                              │                               │
    │  3. Compute PoW (if free)    │                               │
    │     OR skip (if paid tier)   │                               │
    │                              │                               │
    │ ─────────────────────────────>                               │
    │     Send signed message      │                               │
    │                              │                               │
    │                              │  4. Build Cosmos tx           │
    │                              │     (validator signs outer)   │
    │                              │                               │
    │                              │  5. Set fee payer to node     │
    │                              │                               │
    │                              │ ─────────────────────────────>│
    │                              │     Broadcast transaction     │
    │                              │                               │
    │                              │                               │  6. AnteHandler:
    │                              │                               │     - Verify meta-sig
    │                              │                               │     - Validate PoW
    │                              │                               │     - Deduct gas
    │                              │                               │
    │                              │                               │  7. Execute message
    │                              │                               │     handler
    │                              │                               │
    │                              │ <─────────────────────────────│
    │                              │     Result (success/fail)     │
    │ <─────────────────────────────                               │
    │     Response to user         │                               │
```

### Two Transaction Paths

The ante handler detects transaction type and routes accordingly:

**Path A: Standard SDK Transactions**
- Used for: staking, governance, validator ops
- Full Cosmos SDK signature verification
- Standard gas/fee model

**Path B: Relay Transactions (Core Messages)**
- Used for: MsgPost, MsgVote, MsgSetUsername, etc.
- Meta-signature embedded in message fields
- PoW validation OR reserve-based gas payment
- Validator pays outer transaction fees

---

## Custom AnteHandler Pipeline

The ante handler is the gatekeeper for all transactions. Mirage implements a custom pipeline that diverges from the standard SDK flow for relay transactions.

### Why Custom Ante Handlers?

The standard Cosmos SDK ante handler assumes:
- Every transaction has a valid outer signature from the signer
- Gas fees are paid by the transaction signer
- No alternative spam prevention mechanisms

Mirage needs:
- Signature-less outer transactions (validator signs, not user)
- User identity proven through embedded meta-signatures
- Proof-of-Work as alternative to gas fees for free users
- Gas fees deducted from escrowed reserves for paid users

### Decorator Chain

The relay ante handler chain executes in this order:

```
1. SetUpContextDecorator     │ Initialize gas meter, context
2. TxTimeoutHeightDecorator  │ Reject expired transactions
3. ConsumeGasForTxSizeDecorator │ Charge gas for tx bytes
4. LoggingDecorator          │ Debug logging (development)
5. PowDecorator              │ Validate Proof-of-Work (free users)
6. EnsureAccountsDecorator   │ Create accounts if needed
7. RelayGasFeeDecorator      │ Verify/deduct SDK-level fees
8. RelayAccountingDecorator  │ Track usage statistics
9. DisableDelegatorStakingDecorator │ Prevent delegator staking attacks
10. RelaySigDecorator        │ Verify meta-signatures
```

### PowDecorator: Spam Prevention Without Fees

The `PowDecorator` enforces Proof-of-Work for free-tier users. This is the key innovation that enables gas-less transactions while preventing spam.

**Why Argon2id?**
- Memory-hard: Resists GPU/ASIC optimization
- OWASP recommended: Same algorithm used for password hashing
- Tunable: Parameters can be adjusted via governance

**PoW Validation Process:**
1. Extract `envelope_block_hash`, `envelope_difficulty`, `envelope_pow` from message
2. Build canonical bytes (deterministic serialization of message fields)
3. Compute `hash = Argon2id(canonical || ":" || pow, salt=block_hash)`
4. Treat hash as a 256-bit integer and compare against target threshold
5. Reject if `hash > base_target * 1000 / difficulty` (where `base_target = 2^(256 - min_difficulty)`)

**Dynamic Difficulty Adjustment:**
- Difficulty is a work-multiplier factor (1000 = base 1.0x, 1250 = 1.25x harder, etc.)
- Monitored in sliding window (`pow_message_window` blocks)
- If message count >= `pow_message_limit`: multiply difficulty by `(1 + pow_difficulty_step)`
- If message count < `pow_calm_period_definition` for `pow_calm_sequence_threshold` consecutive windows: divide difficulty by `(1 + pow_difficulty_step)`
- Bounded by base difficulty floor (1000) and max safe difficulty ceiling (2^53 - 1)

**Tier-Based PoW Bypass:**
- Free users (level 0): Must provide valid PoW
- Paid users (level 1-3): Skip PoW, pay from escrowed reserve
- Admins (level >= 100): Pay from on-chain balance

### RelaySigDecorator: Meta-Signature Verification

The `RelaySigDecorator` verifies that the user actually authorized the action by checking the embedded signature.

**Canonical Byte Construction:**
```
prefix = "mirage.core.v1:" + MsgName + 0x00
for each field (sorted by proto field number):
    write field_tag (1 byte)
    write length-prefixed value (uvarint + bytes)
```

This ensures:
- Deterministic serialization across platforms (Go, Python, JavaScript)
- Signature covers all semantic fields
- Replay attacks prevented via `envelope_timestamp` + `envelope_block_hash`

**Timestamp Validation:**
- `envelope_timestamp` must be within `max_envelope_age` seconds of block time
- Prevents replay of old signed messages
- Small future skew allowed (half of max age) for clock drift

### RelayGasFeeDecorator: Fee Management

For relay transactions, the node/validator pays SDK-level gas fees. This decorator:
1. Validates the fee payer has sufficient balance
2. Deducts fees during `ExecModeFinalize` (not during check/prepare)
3. Fees go to `fee_collector` module account (then burned in BeginBlock)

---

## Core Module (x/core)

The `x/core` module contains all Mirage-specific application logic. It is the heart of the platform.

### Message Types

**Content Messages:**
- `MsgPost`: Create a post or comment
- `MsgVote`: Upvote or downvote content
- `MsgEdit`: Edit existing content (within time window)
- `MsgDelete`: Mark content as deleted (enforced by indexer)

**Profile Messages:**
- `MsgSetUsername`: Claim or change username
- `MsgFollowModerator`, `MsgUnfollowModerator`: Manage trusted moderators
- `MsgFollowUser`, `MsgUnfollowUser`: Manage followed users
- `MsgFollowTopic`, `MsgUnfollowTopic`: Manage followed topics
- `MsgBlockUser`, `MsgUnblockUser`: Personal blocking
- `MsgBlockPost`, `MsgUnblockPost`: Personal post hiding

**Financial Messages:**
- `MsgSendTokens`: Transfer MIRAGE tokens
- `MsgUpgradeLevel`: Subscribe to paid tier
- `MsgSetAutoRenewal`: Toggle subscription auto-renewal

**Bridge Messages:**
- `MsgBridgeBurn`: Burn for external chain bridge
- `MsgBridgeAttestBurned`: Validator attestation for inbound bridge
- `MsgBridgeAttestMinted`: Validator attestation for outbound bridge

**Governance Messages:**
- `MsgUpdateParams`: Update chain parameters
- `MsgSetLevel`: Set user level (admin assignment)
- `MsgPunishValidator`: Slash/jail validator
- `MsgMintTokens`: Mint tokens to address
- `MsgBurnTokens`: Burn tokens from address

### State Storage

The module stores state under prefixed keys in the KV store:

| Prefix | Purpose |
|--------|---------|
| `profile/` | Core profile data (JSON serialized) |
| `profile_mods/` | Followed moderators list |
| `profile_users/` | Followed users list |
| `profile_topics/` | Followed topics list |
| `profile_blocked_users/` | Blocked users list |
| `profile_blocked_posts/` | Blocked posts list |
| `profile_quality_posts/` | Quality-marked posts list |
| `username/` | Username → address mapping |
| `difficulty/` | Current PoW difficulty |
| `pow_window/` | Per-block message counts |
| `subscription/` | Subscription expiry index |
| `bridge/` | Bridge attestation state |

### Message Handler Philosophy

Each message handler follows a consistent pattern:

1. **Authority Check**: Is this governance or relay path?
2. **Owner Derivation**: Extract user address from `envelope_pubkey`
3. **Validation**: Check field constraints (lengths, formats, ownership)
4. **Tier Limits**: Apply tier-based restrictions
5. **State Mutation**: Update KV store
6. **Gas Fee Deduction**: Deduct from reserve (paid users) or skip (free users)
7. **Event Emission**: Emit events for indexer consumption

**Important Design Decision: Minimal On-Chain Validation**

The blockchain intentionally performs minimal authorization checks for some operations (e.g., `MsgDelete`). The philosophy is:
- On-chain storage is expensive
- Complex authorization requires storing ownership mappings
- The indexer can enforce authorization rules at query time
- Users who submit unauthorized deletions simply waste gas

This is documented in the `MsgDelete` handler:
```go
// SECURITY MODEL (enforced by indexer, NOT here):
// The blockchain accepts Delete messages from anyone - they just pay gas.
// Authorization is enforced by the INDEXER.
```

---

## User Tier System

### Why Tiers?

The tier system serves multiple purposes:

1. **Sustainable Economics**: Paid users fund validator operations
2. **Spam Resistance**: Higher tiers = more trust = more features
3. **Feature Segmentation**: Premium features incentivize subscriptions
4. **Gas Reserve Model**: Paid users pre-pay for gas, improving UX

### Tier Definitions

| Level | Name | Monthly Fee | Key Features |
|-------|------|-------------|--------------|
| 0 | Free | 0 | PoW required, limited content length, "Anon-" username prefix |
| 1 | Trusted | 100K MIRAGE | No PoW, custom username, biography, avatar |
| 2 | Established | 200K MIRAGE | Moderator eligibility, quality posts, longer content |
| 3 | Distinguished | 300K MIRAGE | Maximum limits, highest vote weight |
| 100+ | Admin | N/A | Governance-assigned, special privileges |

### Subscription Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Subscription Lifecycle                                │
└─────────────────────────────────────────────────────────────────────────────┘

User calls MsgUpgradeLevel(level=1)
           │
           ▼
┌─────────────────────────────────────────┐
│  1. Validate user has sufficient balance │
│  2. Burn non-reserve portion of fee      │
│  3. Escrow reserve portion to module     │
│  4. Set level, expiry, auto_renew=true   │
│  5. Index subscription for renewal       │
└─────────────────────────────────────────┘
           │
           │  (subscription period passes)
           ▼
┌─────────────────────────────────────────┐
│  EndBlock: processSubscriptions()        │
│  - Find expired subscriptions            │
│  - If auto_renew && balance sufficient:  │
│      → Renew (deduct fee, set new expiry)│
│  - If auto_renew && balance insufficient:│
│      → Downgrade to free tier            │
│  - If !auto_renew:                       │
│      → Downgrade to free tier            │
└─────────────────────────────────────────┘
```

### Reserve Fund Model

**Why Escrow?**

When a user subscribes, a portion of their fee (default 80%) is escrowed to the `core` module account as a "reserve fund". This reserve pays for gas fees on relayed transactions.

Benefits:
- **Predictable Costs**: Users know their monthly cost upfront
- **No Per-Transaction Fees**: Users don't see gas deductions
- **Automatic Downgrade**: When reserve exhausts, user gracefully falls back to free tier

**Gas Fee Calculation:**
```
fee = min(gasConsumed * relayMinGasPrice, relayMaxGasFee)
```

If reserve is insufficient for even one transaction, the user is immediately downgraded to free tier and must provide PoW.

---

## Tokenomics Design

### Token: MIRAGE (umirage)

- Base denomination: `umirage` (micro-MIRAGE)
- Display denomination: MIRAGE = 1,000,000 umirage
- Bond denomination: `umirage`

### Minting

**Schedule:**
- Mint occurs every `mint_interval` blocks (default: 200 blocks ≈ 10 minutes)
- Fixed `mint_quantity` per interval (default: 350 MIRAGE)
- Minted to `fee_collector` module account

**Dynamic Minting Credit:**
- Validators earn "credits" for including relay transactions
- Credits allow claiming portion of dynamic mint allocation
- Incentivizes validators to include user transactions

### Burning

**Fee Burning:**
- All fees collected in `fee_collector` are burned in `BeginBlock`
- Subscription fees (non-reserve portion) burned immediately
- Reserve fees burned as consumed or at subscription end

**Bridge Fees:**
- External bridge transfers include fees
- Bridge fees are burned (deflationary)

### Economic Equilibrium

The system is designed to reach equilibrium:

```
Inflows:  Minting (fixed per interval)
Outflows: Fee burning, bridge fees, subscription burns

If usage ↑ → more fees burned → supply ↓ → token value ↑
If usage ↓ → less fees burned → supply ↑ → token value ↓ → cheaper to use
```

---

## Block Lifecycle Events

### BeginBlock

Executed at the start of each block:

1. **Burn Fee Collector**: Any fees from previous block are burned
2. **Daily Minting**: If `mint_interval` blocks passed, mint to fee collector
3. **Difficulty Initialization**: Set initial difficulty if not present
4. **Module Account Profiles**: Ensure reserved usernames exist
5. **Counter Cleanup**: Periodically clean old PoW counters

### EndBlock

Executed at the end of each block:

1. **PoW Difficulty Adjustment**: Analyze message window, adjust difficulty
2. **Subscription Processing**: Renew or expire subscriptions

### Why These Boundaries?

- **BeginBlock for burns**: Ensures fees from previous block are processed before new transactions
- **EndBlock for difficulty**: Uses current block's message count for next block's threshold
- **EndBlock for subscriptions**: Ensures consistent expiry timing

---

## Observability and Debugging

### Key Log Points

**Transaction Processing:**
```
ctx.Logger().Info("SetUsername: username changed", "owner", owner, "old_username", prevUsername, "new_username", username)
ctx.Logger().Error("PoW: validation failed", "msg", "MsgPost", "err", err.Error())
ctx.Logger().Warn("relay insufficient fee", "offered", offered.String(), "required", required.String())
```

**Subscription Events:**
```
ctx.Logger().Info("processSubscriptions: subscription renewed", "address", sub.Address, "level", core.Level)
ctx.Logger().Info("deductRelayGasFee: reserve exhausted, downgrading to free", "owner", owner)
```

**Difficulty Adjustment:**
```
ctx.Logger().Info("Increased PoW difficulty due to busy window", "old_difficulty", currentDifficulty, "new_difficulty", newDifficulty)
ctx.Logger().Debug("PoW difficulty status", "block", sdkCtx.BlockHeight(), "current_difficulty", currentDifficulty)
```

### Events for Indexer

The module emits events that the indexer consumes:

- `subscription_renewed`: Subscription successfully renewed
- `subscription_expired`: Subscription ended (with reason)
- `bridge_burn`: External bridge burn initiated

### Query Endpoints

gRPC query endpoints for debugging:

- `/mirage.core.v1.Query/GetParams`: Current chain parameters
- `/mirage.core.v1.Query/GetDifficulty`: Current PoW difficulty and stats
- `/mirage.core.v1.Query/GetProfile`: User profile data
- `/mirage.core.v1.Query/GetBridgeStatus`: Bridge operational status

---

## Security Model

### Trust Assumptions

1. **Validators are honest**: 2/3+ voting power is honest
2. **User keys are secure**: Private keys are not compromised
3. **Timestamps are reasonable**: Node clocks are within acceptable skew

### Attack Vectors and Mitigations

**Spam Attacks:**
- Free tier: PoW requirement makes spam computationally expensive
- Paid tier: Reserve exhaustion leads to automatic downgrade
- Dynamic difficulty: Increases during high-volume periods

**Replay Attacks:**
- `envelope_timestamp` must be recent
- `envelope_block_hash` must match recent blocks
- Signatures include all message fields

**Unauthorized Actions:**
- Meta-signatures prove user intent
- Address derived from pubkey, not claimed
- Indexer enforces ownership for deletions/edits

**Economic Attacks:**
- Subscription fees burned (not redistributed)
- Reserve funds escrowed (not user-controlled)
- Validators cannot steal user funds

### Governance Controls

All critical parameters are governance-controlled:
- PoW difficulty bounds and adjustment rates
- Subscription periods and fees
- Tier configurations
- Bridge parameters

This allows the community to respond to attacks or economic issues without code changes.

---

## Appendix: File Reference

| File | Purpose |
|------|---------|
| `blockchain/app/app.go` | Application bootstrap, ante handler setup |
| `blockchain/app/ante_pow.go` | Proof-of-Work validation decorator |
| `blockchain/app/ante_metasig.go` | Meta-signature verification decorator |
| `blockchain/x/core/module/module.go` | Message handlers, block hooks |
| `blockchain/x/core/types/params.go` | Parameter definitions and defaults |
| `blockchain/x/core/keeper/keeper.go` | State access methods |

---

*Document Version: 1.0*  
*Last Updated: January 2026*
