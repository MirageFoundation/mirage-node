# Mirage v1.33.0 Release Notes

### The feed you read is now a verified record

Almost everything you see on Mirage — a profile, a vote tally, who blocked whom, what a topic looks like — is served from an index built by each node as blocks arrive. The chain is the authority, but the chain is also pruned, and the index deliberately keeps more history than the chain retains. That makes the index something closer to an archive than a cache, and this release treats it that way for the first time. A block's writes and the marker saying "we got this far" now land together or not at all, so a node can no longer record progress past work it only half finished.

### A node that drifted can no longer pretend otherwise

When a node has to recover, its database survives the recovery. That was quietly dangerous: if the node had briefly followed a different version of the chain, rows from that detour stayed in the index and kept being served as truth long after the node rejoined everyone else. Now a node checks, before it writes anything, that the history in its database is the same history the chain has — same network, same blocks, same hashes. If it does not match, the node refuses to start rather than serve you something that never happened. Nodes upgrading from an earlier version are checked against the block hashes they already recorded, so honest ones carry on and a drifted one is caught.

### Gaps are admitted instead of hidden

A node that was offline while the chain pruned past it can never recover those blocks. Previously it skipped ahead and looked perfectly healthy. Now the missing range is recorded and reported, and the node's health tells you its view of history is incomplete. This is the honest tradeoff: we would rather tell you a node has a hole in its record than let it quietly serve a partial view of moderation and feeds as though it were complete. Vote and topic statistics that earlier versions could miscount are rebuilt from the underlying votes when a node upgrades.

### One less thing pointed at the people running nodes

Link previews used to work by having the node fetch the URL in a post to see what was there. That meant anything you posted could make somebody else's server reach out to an address of your choosing. Previews are now worked out from the link itself, without contacting it. You may notice slightly fewer thumbnails on unusual links; we think that is the right price.

### Nothing a user posts can stop a node

There is a real tension in making a node stricter: the chain accepts some things the index has no natural shape for, such as a vote pointing at a post that was never made. Being strict about those would have meant one ordinary transaction could stop every node on the network from making progress. So nodes are strict about their own failures and forgiving about content the chain already accepted — those messages are logged and passed over. We caught this while testing the release against a copy of real data, which is exactly what that testing is for.

### Under the hood

Nodes now talk to the chain over a single interface rather than falling back to a second one, governance decisions are applied from the chain's own record of what passed rather than a cache that had quietly stopped working, and database credentials no longer appear in logs. Database upgrades refuse to run half-applied. The full backend, blockchain, and indexer suites pass against a node restored from a production-shaped backup.
