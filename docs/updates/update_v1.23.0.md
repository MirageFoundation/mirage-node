# Mirage v1.23.0 Release Notes

### State-Sync Pruning Fix

Nodes that joined the network via state-sync had a bug where old blockchain data was never cleaned up. The Cosmos SDK seeds the pruning snapshot list with height 0, but state-synced nodes start at a much higher block — say 450,000. That zero entry could never be evicted because the pruning manager expects a contiguous chain of heights, and the gap between 0 and 450,000 made it treat the entire history as unfinished. The result was unbounded disk growth even with pruning configured. This release detects the stale entry at startup and rewrites the list to contain only the valid contiguous tail. Pruning will resume normally and disk usage will stabilize.

### Startup Compaction

Every time a node container starts, PebbleDB databases are now compacted before the chain begins producing blocks. Pruning marks old data for deletion with tombstones, but PebbleDB does not always reclaim that space on its own schedule. The startup compaction forces a full sweep so tombstones are collapsed and disk space is freed immediately. This is non-fatal — if compaction fails for any reason, the node still starts normally. Operators should see a one-time drop in disk usage on the first restart after upgrading.

### Content Tag Normalization

The "porn" content tag has been renamed to "adult" across the chain, indexer, and frontend. Posts submitted with the old tag are automatically rewritten to "adult" before validation, so existing clients continue to work without changes. The old tag name will remain as an alias until all clients have migrated. The indexer migration renames existing data to match.

### Inbox Notifications for Donations and Follows

When someone sends you MIRAGE or follows your account, you now receive an inbox notification and a push alert. This works regardless of how the transaction was submitted — web wallet, CLI, or third-party tools. The indexer picks up every on-chain transfer and follow event and routes it through the same notification pipeline as replies and awards.

### Smaller Disk Footprint

Log retention has been reduced from 90 days to 30 days. Combined with the pruning fix and startup compaction, nodes should see a significant reduction in disk usage. The obsolete GoLevelDB-to-PebbleDB migration tool has been removed since all nodes now run PebbleDB. A new analyze-db diagnostic tool is included for operators who want to inspect the contents of their PebbleDB databases.

### Frontend Improvements

The bluemoon theme width cap has been removed and the content area expanded to 1500px. Post cards can now be expanded and collapsed inline. Gift subscription and donation buttons appear on profile pages in both themes. Font sizing, video player dimensions, and checkbox alignment have been cleaned up across mobile and desktop.

---

## Upgrade Instructions

The chain upgrade name is `v1.23.0` and the binary must be built from the `v1.23.0` tag. No on-chain state migration is required — the upgrade handler is a no-op. The pruning fix runs automatically at every startup, so it takes effect even without the governance upgrade proposal. All services (frontend, backend, indexer) should be updated simultaneously. The `compact-db` binary must be present in the Docker image for startup compaction to run.
