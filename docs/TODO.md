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

### Node DB Compaction Strategy (goleveldb problem)
- **Problem:** goleveldb pruning deletes IAVL versions but disk never shrinks — compaction is lazy and there's no online `CompactRange` hook. The only way to reclaim space is offline `miraged prune` (causes downtime) or a full state-sync rebuild.
- **Current approach:** Stay on goleveldb. Run offline prune periodically or state-sync rebuild when disk gets too large.
- **PebbleDB (potential fix):** Already compiled into the binary (pure Go, no build changes needed). Would solve the disk bloat via continuous background compaction. Prior migration attempt (Jan 2026) failed for two reasons:
  1. CometBFT's `db_backend` does NOT support pebbledb (only `goleveldb`/`memdb`). Only the Cosmos SDK `app-db-backend` can use it.
  2. With `app-db-backend = "pebbledb"` + `db_backend = "goleveldb"`, state-sync snapshot restore corrupted staking params (`bond_denom` came back empty), causing a panic at the next block. Root cause never identified — could be a cosmos-db bug in the PebbleDB snapshot restore path.
  - **Untested path:** PebbleDB was never tested without state-sync (e.g., peer-restore with `restore_from_peer.sh` or syncing from genesis). The failure was specifically in snapshot restore, not normal block processing.
  - **Next step if revisiting:** Test `app-db-backend = "pebbledb"` on a non-critical node using peer-restore (not state-sync) to isolate whether the issue is PebbleDB itself or PebbleDB + snapshot restore.
- **RocksDB: Not viable without build changes.** Binary is built without CGO / `-tags rocksdb`. Would require Dockerfile changes, librocksdb install, and full rebuild pipeline update.

## Short-term cleanup (remove after March)
- Remove legacy handling of embedding image/media when the first line is a link. The `media` field already covers this.

## Performance
- Generally optimize website. Find bottlenecks. Use Firefox profiler.

## Moderation / Anti-botting
- Add relaying node into blockchain history so we can flag rogue relayers. A separate script can create a moderator that excludes posts from known spam-relayers.

## Content / UX
- Add blocking keywords (in topics or posts)?

## Security
- Full security audit for every module.

## Privacy
- Add all privacy-related quotes from Obsidian somewhere?

## Identity
- Should it remain possible to create msgs, participate, etc, without having a set username?