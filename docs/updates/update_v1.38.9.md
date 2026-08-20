# Mirage v1.38.9 Release Notes

### The cleanup we shipped yesterday deleted one thing too many

The previous release taught nodes to clear out old versions before downloading a new one, after a full disk stopped a validator signing. That was the right fix and it works — but the way it found things to delete was wrong in a way that only showed up on a real server, and this release corrects it before it can cost anyone anything.

### Why it went unnoticed

A version is identified either by a name or by an exact fingerprint of its contents. Mirage installs strictly by fingerprint, because a name can be moved to point at different code while a fingerprint cannot — that is what makes an install verifiable. The side effect is that installed versions have no name attached, and the cleanup asked Docker for everything unnamed. Docker's answer to that question is "everything installed by fingerprint", which on a Mirage node is every version it has. The cleanup was carefully written to spare three things, and that request went around all three of them.

### What could have been deleted

The version currently running was never at risk, because it is in use. The three that were are the ones a node needs precisely when something has gone wrong: the previous version, which is what a node falls back to if a new one misbehaves; a version downloaded and waiting to be switched on; and the version staged for an upcoming scheduled upgrade. The last is the serious one. A node that has committed to an upgrade, then loses the version it committed to, cannot complete it — it will not accept a substitute, and there is no way to know from the outside that it is now stuck. That exact failure was found and fixed once before, in v1.37.0; yesterday's cleanup quietly undid the protection.

### Identifying versions by what they are

The cleanup no longer asks Docker a question it answers too broadly. It now examines each installed version, reads the fingerprint that says which release it actually is, and compares that against the short list it must keep. This is the same form the node already records those decisions in, so the check and the record finally speak the same language. It also means the cleanup sees the versions it is supposed to be removing: because it had been matching on names, and installs have none, the sweep had genuinely never removed a single version in its entire existence — which is how a server came to be carrying ten gigabytes of them.

### Verified against a real server, not just in theory

This was caught by deploying to the test server rather than by reading the code, which is worth saying because the code looked correct. Both the old behaviour and the new one are now covered by tests that stand up a node's actual layout — a running version, a fallback, one waiting to be switched on, one staged for an upgrade — and confirm the three that must survive do, and that everything genuinely obsolete is still cleared out. The production server was deliberately left until after that check, so the only machine that ever ran yesterday's version is the test one.

### What this means for your node

This is an ordinary release with no governance vote and no scheduled halt, so install it whenever suits you with `mirage-update`. Nothing here changes how blocks are processed, so updated and not-yet-updated nodes agree on everything. If you installed v1.38.8, this replaces it and no action is needed beyond updating; if your node had a fallback version removed, updating restores a fresh one on the next release. The space reclaiming and the refusal to install without room, both introduced yesterday, are unchanged and still apply.
