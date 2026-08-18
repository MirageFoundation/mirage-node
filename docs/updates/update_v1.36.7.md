# Mirage v1.36.7 Release Notes

### The one-command install works for real accounts

Until now, the single command that turns a fresh server into a Mirage validator would stop just after you typed your recovery phrase, complaining that the network's public endpoints disagreed about your account. Nothing was wrong with the server, the phrase or the account. The installer was asking a question it did not need answered, and then refusing to continue because two honest nodes gave two honest answers.

### Why it asked two nodes in the first place

Before an install commits to anything, it checks your account against more than one independent node and stops if they disagree. That safeguard is the point: a single node should never be able to talk an operator into an install by misreporting their balance or their name. The mistake was in how much of the answer counted. Each node's reply also carries that node's own private bookkeeping about you, including how many unread items are waiting in your inbox — a number that lives only on that machine and legitimately differs everywhere. The installer compared the entire reply, so it treated a difference in unread mail as evidence that the network could not be trusted. In practice that meant it worked only for accounts nobody had ever used.

### What changed, and what deliberately did not

The account check now compares only the piece of the answer it actually acts on: the username tied to your address. The two checks that guard real money and real risk were left exactly as strict as they were, comparing every byte of the answer across every endpoint. That includes the check that refuses to continue if your validator key is already signing somewhere else, which is the one mistake in running a validator that cannot be undone.

### Chosen so it cannot come back

We had a choice between listing the per-node details to ignore and listing the details that matter. Ignoring is easier to write and quietly wrong: the next time someone adds another piece of per-node bookkeeping to that reply, installs would break again and nobody would connect the two changes. So each check now names what it compares, and a test pins the behaviour from both directions — a difference in unread mail must not stop an install, and a genuine disagreement about your username still must.

### Where this came from

This was found by an operator running the published command on a new server, not by us. Our tests exercised the comparison with invented accounts that happened to agree on everything, so they passed while the real network could not. The new test uses accounts that differ the way real ones do. Existing validators are unaffected — this is entirely about preparing a new host, and nothing about it reaches the chain.

### No chain upgrade

This release changes the installer only. Transactions, consensus state, validator keys and the application hash are untouched, so no governance halt is required and nodes running v1.36.6 and v1.36.7 cannot fork because of this update.
