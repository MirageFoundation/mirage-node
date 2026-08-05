# Mirage v1.31.0 Release Notes

### Bridge Removed Permanently

The cross-chain Solana bridge and its off-chain orchestrator are gone. There is no bridge UI, no bridge API, and no orchestrator process on a Mirage node. Historical bridge transactions remain decodable on chain so past activity can still be read from the ledger, but new bridge messages cannot be submitted. If any historical burns never completed a mint on the other side, there is no redemption path in this release — those funds stay burned.

### Cleaner Failures When a Node Hits Trouble

When a validator hits a consensus-fatal condition, the process now exits cleanly instead of lingering in a half-alive state. That matters for everyone else on the network: fewer stretches where the app looks stuck on "Transaction failed" because one validator was answering RPC while no longer advancing consensus.

### Stronger Spam Resistance

Mempool admission checks the relay signature before doing expensive work. That cuts off a cheap way to burn validator CPU with unsigned junk while leaving ordinary posting and voting unchanged for users.

### Quieter Reliability Under the Hood

Supply accounting and a handful of paid-user edge cases got tighter handling so validators stay consistent and operators see fewer noisy false alarms mixed with real incidents. You should not notice a new product surface — the goal is steadier blocks and clearer operator signal when something is actually wrong.

### Security Review Follow-Through

This release also closes out findings from the latest blockchain security review cycle, including the permanent bridge removal called out there. The work is defensive infrastructure, not a new feature set — and the honest tradeoff is the same as above: dormant bridge risk is gone, and incomplete historical burns have no recovery path on-chain.
