## Review Notes: Suggested Order and Rationale

These notes are meant to turn the themes below into an execution order with explicit rationale, risks, and dependency flow.

### 0. Baseline: measure and confirm intent (short, 1-2 days)
- Confirm the intended outcomes for each effort: why we are doing it, and what success looks like.
- For each item below, list expected wins (bug surface reduction, deploy simplicity, runtime performance) and clear exit criteria.
- This prevents large refactors from drifting without a finish line.

### 1. SDK bloat removal ✅ COMPLETED (v1.10.3-sdk-bloat)
- Rationale: lowest coupling to application logic; reduces attack surface, binary size, build time, and upgrade complexity.
- **Status: DONE** — Merged to prod, tagged v1.10.4
- Removed modules: authz, feegrant, group, epochs, vesting, mint, circuit, evidence
- Changes:
  - `app_config.go`: removed module configs, BeginBlockers, EndBlockers, InitGenesis entries
  - `app.go`: removed keepers and depinject bindings
  - `genesis.json`: removed genesis state for all 8 modules
  - `upgrades.go`: added `v1.10.3-sdk-bloat` upgrade handler with store deletion
  - `verify_upgrade.py`: added SDK bloat removal verification
- Outcome: leaner binary, fewer upgrade paths, fewer config knobs

### 2. Protobuf code generation in Python (reduce schema drift)
- Rationale: this is the largest current source of subtle correctness drift.
- Dependency flow:
  - Introduce generated Python types for protobufs (buf/protoc).
  - Replace `datatypes.py` dynamic definitions with generated types.
  - Verify parity via a small set of serialization tests (same message bytes for Go/Python).
- Expected outcome: a single schema source of truth and fewer manual edits.

### 3. Clarify chain vs indexer enforcement (delete, ownership semantics)
- Rationale: security and correctness semantics are user-facing and need clarity.
- Options (choose one and document clearly):
  - Enforce ownership on-chain and reject invalid deletes.
  - Keep on-chain permissive but mark as "request" and surface state clearly to users.
- Expected outcome: users cannot misunderstand a "successful" on-chain tx that becomes a no-op.

### 4. Indexer event sourcing (if we need long-term audit/replay)
- Rationale: enables replay/rebuild, simplifies debugging, and improves recovery.
- This is larger than it looks: impacts schema, storage, backfill tooling, and query layer.
- Only start after protobuf generation is stable, so we don't create duplicated systems.

### 5. Language consolidation (Go indexer and backend)
- Rationale: big architectural change, but also the biggest disruption.
- Prereq: protobuf generation is in place and the SDK bloat is already resolved.
- Sequence:
  - Start with one service (indexer or backend), not both at once.
  - Define cross-service API contracts first.
  - Port in thin slices and keep data models mirrored until the cutover.
- Expected outcome: reduce cross-language serialization drift and improve type safety.

---

1. Language Consistency: Go Everywhere
Current: Go (chain, orchestrator) + Python (indexer, backend) + JavaScript (frontend)
The problem: The canonical serialization must be byte-identical across Go, Python, and JavaScript. This is a maintenance nightmare and a source of subtle bugs. Three separate implementations of uvarint, encStr, encBytes, field ordering...
What I'd do instead:
Write indexer in Go (consume protobuf natively, no datatypes.py mirroring)
Write backend in Go (single binary, shared types with chain)
Keep JS on frontend (unavoidable)
This reduces the cross-language surface area from 3 languages to 2.




2. Use Protobuf Code Generation, Not Dynamic Message Building
Current: datatypes.py manually builds protobuf descriptors at runtime:
msg = file_proto.message_type.add()msg.name = "MsgPost"add_f(msg, "authority", 1, TYPE_STRING)add_f(msg, "envelope_pubkey", 2, TYPE_BYTES)# ... 50+ fields across 20+ message types
The problem: Every time you add a field in Go, you must manually mirror it in Python. Field numbers are duplicated. There's no compile-time verification.
What I'd do instead: Use buf generate with Python output. The .proto files are the single source of truth; generated code ensures consistency. Yes, this adds a build step, but it eliminates an entire class of bugs.



3. Rethink the "Chain Accepts, Indexer Enforces" Pattern
Current: MsgDelete is accepted from anyone on-chain; the indexer checks ownership.
// SECURITY MODEL (enforced by indexer, NOT here):// The blockchain accepts Delete messages from anyone - they just pay gas.
The problem: This is conceptually confusing and creates a weird trust model. Users might think their delete "worked" when the chain accepted it, but it's actually a no-op because the indexer ignores it.
What I'd do instead: Either:
Store post ownership on-chain (it's just a mapping, not that expensive)
Return an error from the chain if ownership doesn't match
OR make this explicitly a "soft delete request" that gets queued for indexer processing
The current hybrid approach saves some gas but creates unclear semantics.





6. Event Sourcing for the Indexer
Current: The indexer processes blocks and directly mutates PostgreSQL.
What I'd do instead: Store raw block events first (event sourcing), then derive views. Benefits:
Can rebuild any view without re-syncing from chain
Easier debugging (replay specific events)
Cleaner separation between "what happened" and "current state"



## Cosmos SDK Bloat Analysis ✅ COMPLETED

### Pure Bloat (0 actual usage) - ✅ REMOVED in v1.10.3-sdk-bloat
- ~~`authz`~~ - permission delegation, never used
- ~~`feegrant`~~ - fee payment delegation, never used  
- ~~`group`~~ - on-chain DAO/multisig, never used
- ~~`epochs`~~ - scheduled hooks, never used
- ~~`vesting`~~ - token lockups, never used
- ~~`mint`~~ - SDK inflation minting, never used (we do custom minting via bank)
- ~~`circuit`~~ - emergency shutdown, never used
- ~~`evidence`~~ - double-sign evidence, never used

### Actually Needed (kept)
- `auth` - accounts, signatures
- `bank` - balances, mint/burn (heavily used)
- `staking` - validator set (delegation disabled via ante)
- `gov` - admin operations (params, setlevel, punish, mint)
- `upgrade` - chain upgrades (13+ handlers)
- `genutil` - genesis init
- `consensus` - required by SDK

### Partially Used (infrastructure only, kept)
- `params` - legacy, only for subspaces
- `slashing` - only in export.go and PunishValidator
- `distribution` - only in export.go

### Summary
- ~~8 modules are pure bloat~~ → All removed
- ~7 modules actually needed → Kept

