# TODO

## Architecture

### Language Consistency: Go Everywhere
- Current: Go (chain, orchestrator) + Python (indexer, backend) + JavaScript (frontend)
- Problem: Canonical serialization must match across Go/Python/JS. This is a maintenance nightmare and a source of subtle bugs (uvarint, encStr, encBytes, field ordering).
- Recommendation: Write indexer in Go, write backend in Go, keep JS on frontend. Reduce cross-language surface from 3 languages to 2.

### Use Protobuf Code Generation (No Dynamic Building)
- Current: `datatypes.py` manually builds protobuf descriptors at runtime:
  ```
  msg = file_proto.message_type.add()
  msg.name = "MsgPost"
  add_f(msg, "authority", 1, TYPE_STRING)
  add_f(msg, "envelope_pubkey", 2, TYPE_BYTES)
  # ... 50+ fields across 20+ message types
  ```
- Problem: Every Go field change must be manually mirrored in Python. Field numbers are duplicated. No compile-time verification.
- Recommendation: Use `buf generate` with Python output so `.proto` files are the single source of truth.

### Event Sourcing for the Indexer
- Current: Indexer processes blocks and directly mutates PostgreSQL.
- Recommendation: Store raw block events first, then derive views.
  - Rebuild any view without re-syncing
  - Easier debugging (replay specific events)
  - Cleaner separation between "what happened" and "current state"

## Infrastructure / Ops

### Node DB Compaction Strategy — RESOLVED
- **PebbleDB migration (Feb 2026) succeeded.** All nodes now run `app-db-backend = "pebbledb"` + `db_backend = "pebbledb"`. Compaction is working: application.db SST files are actively created and deleted (e.g., file numbers up to 13k with only ~1.5k files remaining).
- **Disk growth was NOT from PebbleDB.** The real culprits were:
  1. **CometBFT consensus WAL (`cs.wal/`)**: Rotated segments (`wal.NNN`) were never cleaned. ~200MB/day of unbounded growth. Fixed in `entrypoint.sh` — periodic cleanup now deletes rotated WAL segments older than 1 day.
  2. **Node logs**: 43MB/day with 30-day retention = ~1.3GB steady state. Acceptable.
  3. **tx_index.db**: `indexer = "kv"` grows forever. Consider switching to `null` on non-query nodes if disk becomes a concern again.

## Short-term cleanup (remove after March)
- Remove legacy handling of embedding image/media when the first line is a link. The `media` field already covers this.

## Performance
- Generally optimize website. Find bottlenecks. Use Firefox profiler.

## Moderation / Anti-botting
- Add relaying node into blockchain history so we can flag rogue relayers. A separate script can create an agent that excludes posts from known spam-relayers.

## Content / UX
- Add blocking keywords (in topics or posts)?

## Security
- Full security audit for every module.


# CLEANUP!!!
- now that we're fully moved from GoLevelDB to PebbleDB, remove everything related to the pebbledb converter (the go project, etc)

# Other Ideas:
- Allow only 3 new profiles (set_username) per minute