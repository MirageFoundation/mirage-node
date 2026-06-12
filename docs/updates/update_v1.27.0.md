# Mirage v1.27.0 Release Notes

### Why This Upgrade Exists

This release targets one problem: recurring single-node divergence under production load. Mirage has already hardened recovery, but recovery is only the safety net. v1.27.0 hardens the consensus path itself so nodes stop trusting advisory cache reads in places where correctness matters more than speed.

### What Changed In Consensus

The chain now treats canonical IAVL state as the only authority for consensus reads. Fast-node data can still exist as a performance index, but it no longer decides consensus outcomes on its own. In practical terms, this closes the stale-read class that produced app-hash mismatches on busy nodes while quieter validators stayed healthy.

### New Invariant Protection

v1.27.0 also adds a strict supply invariant check at the end of every block. If a node ever reaches a state where recorded supply does not match account balances, that node now halts immediately with an explicit error instead of silently committing a divergent hash. This is intentionally strict because silent divergence is harder to detect and slower to recover from.

### Runtime Hardening

Node runtime configuration now enforces `iavl-disable-fastnode=true` so operators do not have to remember a manual toggle during incidents. Existing nodes pick this up through deploy migration, and new nodes pick it up from templates by default. The goal is to make the safe path the default path everywhere.

### Rollout Expectations

This is a coordinated software-upgrade release. There is no chain state migration and no new governance parameter, but the behavior is consensus-critical, so validators must switch at one planned upgrade height. Mixed binaries can run for short operational windows, but they are not a steady-state target for this release.
