# Mirage v1.38.3 Release Notes

### A brand-new node now finishes its own installation

Setting up a fresh node had a flaw worth stating plainly: the install completed, the node joined the network and synced perfectly, and then the site never came up. The node's database creates its own tables during that first sync, and the account the site reads them with was only granted access to tables that existed beforehand — of which, on a brand-new machine, there were none. So the site could not read the chain, held its "coming online" page, and waited. Forever. The install script reported no error because nothing had actually errored, which is the worst way for something to break.

The permission is now granted for the tables the node is about to create rather than only the ones already there, so a first install reaches the end on its own. This never affected a running node: any node that had been restarted even once had already picked up the missing access as a side effect, which is exactly why it stayed hidden for so long. If you are running a node that has been up since its first boot and has never served traffic, restarting it once resolves it on any version.

### Failures that describe themselves

The same wait exposed a habit worth correcting. The site retries for a full hour on startup, which is right when it is waiting for the node to finish indexing, and wrong when it has been told it lacks permission — that answer will never change, no matter how long you wait. A refused permission now stops immediately and says which account needs which access, instead of logging the same warning sixty-five times while an operator watches a holding page. Elsewhere, error messages that were fragments of internal diagnostics now say what happened in words.

### The status board tells you what is happening

Running the status board on a node that was still catching up was genuinely misleading: it reported four failures and a stalled chain, with no hint that the node was working exactly as intended. A node replaying weeks of history and a node that has stopped dead look identical if you only check when the last block arrived — the difference is whether the count is still climbing, which the board now checks. A catching-up node says so, tells you how far behind it is and roughly how long it has left, and explains that its public addresses are held until then. A node that has genuinely stopped still turns red, and a node sitting at the tip whose site still will not answer stays red too, because that one is broken and no amount of patience fixes it.

The board also lines up properly now. Every panel is the same height regardless of how much it has to report, and the storage panel shows the four largest directories rather than stretching its row to fit a fifth.

### No chain upgrade

Nothing here touches chain code. Consensus, transactions, validator keys and the application hash are untouched, so no governance halt is required and no node can fork because of this release. Nodes running v1.38.2 and v1.38.3 compute identical results from identical blocks.
