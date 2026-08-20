# Mirage v1.38.5 Release Notes

### The morning the whole network stopped

This release exists because of an outage, and the honest version is worth telling. A community validator went offline. The chain noticed it had stopped signing, jailed it and took a slice of its stake as the penalty — all of it completely normal, and all of it working exactly as designed. But burning those tokens changed the total supply, and every other node ran a safety check that compared the supply against the mints and burns it knew about. The penalty was not on that list. Each node concluded its own accounting was broken, and each one did what it had been told to do when it cannot trust its own numbers: it stopped. Within seconds every validator on the network had halted itself over a penalty that was entirely legitimate.

### A safety check that no longer mistakes a penalty for a bug

The check itself was the right idea implemented too narrowly. It watched a running tally rather than the actual books, so anything that moved the supply without passing through that tally looked like corruption. It now does the obvious thing when the tally disagrees: it goes and adds up the real balances. If those reconcile, the tally was simply incomplete and the node carries on. Only when the full accounting genuinely fails to add up does a node stop, which is the situation the check was written for in the first place. Two related habits were fixed alongside it — a node that halts no longer misreads an old log line from earlier in the day as a reason to stay down, and the automatic recovery system now recognises this class of fault as one a human should look at rather than something to be solved by rebuilding the node's database.

### A node that is down can now update itself

The outage exposed something quietly worse than the bug. Once those validators had halted, the tool that installs new releases refused to run on them. It declined to swap in a new version whenever it could not reach the node it was updating, on the reasoning that it should not act blind — which sounds prudent until you notice that a node stopped by a fault is exactly the node that cannot answer, and exactly the node a new version would rescue. Operators were left holding a fix their machines would not accept. Updating a node that is already stopped cannot lose anything, so it now goes ahead and says so. The one genuine version of that concern is untouched: a node still in the middle of catching up will not be interrupted, because there the caution is real.

### Preparing a chain upgrade has its own command

Governance-driven chain upgrades are prepared with `mirage-upgrade` now, instead of a flag tacked onto the command for ordinary updates. Same behaviour, clearer name: `mirage-update` keeps a node current, `mirage-upgrade` arms it for a scheduled halt. The old spelling is gone rather than quietly aliased, so anyone typing it out of habit is told the new name instead of wondering why nothing happened.

### Earnings you can actually trust

The earnings panel on the node dashboard was doing something subtly wrong. It worked out what a node had earned by watching its balance rise and fall, which means it counted every incoming transfer as income and every outgoing one as an expense — and quietly lost any payout that arrived and was moved on before the next reading. It now counts the actual events: the rewards the chain pays this node and the fees this node pays out, tracked block by block as they happen. What you see is what the chain did, not an inference drawn from a balance that moves for a dozen unrelated reasons.

### What this means for your node

There is no governance halt and no upgrade vote here — this is an ordinary release you install whenever you like. Old and new nodes compute identical results from identical blocks, so nothing can fork over it. What a node running v1.38.4 will do is stop again the next time a validator is penalised, and there are validators on the network heading toward exactly that. If your node is currently stopped, its copy of the update tool still carries the refusal described above, so it needs `mirage-update --refresh-hosttools --image <digest from release/manifest.json>` once to take the corrected tooling, and a plain `mirage-update` after that. Every future update, including from a halted state, is a single command.
