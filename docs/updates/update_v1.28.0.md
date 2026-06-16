# Mirage v1.28.0 Release Notes

### A foundation that stops failing

Every now and then a vote, follow, or post would come back with a blunt "Transaction failed," even though nothing was wrong with what you did. v1.28.0 is the release that goes after the root of that frustration. It is not a flashy feature drop; it is the structural fix that makes the whole chain steadier, so the actions you take land the first time instead of bouncing back for reasons no normal user should ever have to think about.

### What was actually going wrong

The failures traced back to a subtle timing problem deep inside the node software. While a node was finalizing a block, it could also be answering a read for the same data, and on rare occasions those two activities raced each other and produced a slightly different result on one machine than on the rest of the network. Because every node in a blockchain has to agree on the exact same state, a single node reading one value out of step was enough to wedge it and reject otherwise valid transactions. It was intermittent, hard to reproduce, and load-sensitive, which is exactly why it kept coming back.

### The fix, and where it comes from

Rather than paper over the symptom, v1.28.0 moves Mirage onto the next major version of the underlying blockchain framework, which ships the proper upstream fix for that exact race: the node now reads committed state and finalizes blocks in a strictly coordinated way, so the two can no longer step on each other. We also refreshed the storage engine to its latest patched line, which adds its own locking and consistency hardening, and we kept the earlier safeguard that forces every consensus read through the canonical state tree. Together these close the family of single-node divergences we have been chasing.

### A leaner node

While upgrading the foundation, we removed two modules that shipped with the framework but were never used on Mirage. They added surface area, dependencies, and in one case a licensing constraint, with no benefit to anyone here. Removing them makes the node simpler to build, audit, and reason about. No data you care about lived in them, and their unused storage is cleaned up automatically as part of the upgrade.

### How the upgrade happens

This is a coordinated, network-wide upgrade: validators agree on a single block height, and at that height every node switches to the new software together. Your balances, profiles, posts, and history carry over untouched because the on-disk format is unchanged, so there is no lengthy data migration and no snapshot to rebuild. We rehearse the whole sequence on a test network and on the staging environment before it touches the live chain.

### Honest about the tradeoffs

This kind of release is foundational rather than additive, so most of the work is invisible by design and the headline benefit is simply "things break less." It does require the whole validator set to move in lockstep at the upgrade height; a node that stays on the old software will stop following the chain until it updates, which is the normal cost of a coordinated upgrade. We also deliberately left the framework's brand-new experimental features switched off for this release, because stability is the entire point of v1.28.0 and unproven options have no place in a reliability fix. When those features have earned their keep elsewhere, we can revisit them on their own terms.
