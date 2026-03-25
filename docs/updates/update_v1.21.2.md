# Mirage v1.21.2 Release Notes

### Push Notifications

If you have the Mirage mobile app, you now get push notifications. When someone replies to your post, mentions you in a comment, or gives you an award, your device lights up with the notification. Tapping it takes you straight to the conversation. Notifications are tied to your inbox — you get up to three pushes per batch, and the counter resets every time you open your inbox, so you are never buried in alerts but you never miss what matters either. If you have not tried the app yet, grab it at mirage.foundation/app.

Because Mirage is decentralized, push delivery had to work regardless of which node processed the transaction. The backend runs a push listener that polls the indexer database for new on-chain events (posts, awards), so notifications fire even when the action originated from a different node. Token registration is cryptographically signed with your private key, so no one can register a push token on your behalf or hijack your notifications.

### Replay Protection — Start to Finish

What started in v1.18.0 as a new envelope nonce system is now fully shipped and cleaned up. Every relay message carries a unique nonce that the chain records and checks against duplicates, eliminating any window for transaction replay. The v1.19.0 release provided a temporary compatibility window so older mobile clients could keep working while updating. v1.20.0 closed that window — zero-nonce messages are now rejected outright. v1.21.0 stripped every remaining dead code path from the binary, so there is no ambiguity left in the codebase about what the chain accepts. Replay protection is unconditional, permanent, and covers every message type on the network.

### Simpler, Faster Backend

The backend no longer talks to the chain directly. All gRPC and RPC calls have been removed — every piece of chain state the backend needs now comes from the indexer's PostgreSQL database. Transaction broadcast goes directly to CometBFT's JSON-RPC endpoint with accurate gas estimation, removing the old queue-and-poll system entirely. The result is fewer moving parts, faster responses, and one less failure mode. If the indexer database is down, the backend returns a clear 503 instead of silently degrading.

### Security Hardening

Governance authority spoofing is now caught at the mempool gate. Before v1.21.0, someone could craft a regular transaction pretending to come from the governance module address — it would fail during execution, but it still consumed validator resources getting there. The new ante handler decorator rejects these immediately, before signature verification even runs. The subscription engine bug that let expired Agent-tier users keep their level indefinitely has been fixed with a one-time migration that re-evaluated every profile on the chain. Bridge confirmations are scoped to prevent first-writer poisoning, and the orchestrator is hard-disabled with a panic guard while the Solana bridge remains offline for the time being.

### Media and Quality of Life

Images and videos embedded in posts now carry dimension metadata, so the app can reserve the right amount of space before content loads — no more layout jumps as media pops in. Video uploads surface storage limit errors clearly instead of failing silently. Inbox notifications are deduplicated so a reply that also mentions you produces one notification, not two. Links in posts support Ctrl+click and middle-click to open in new tabs. Reply drafts are preserved when a submission fails due to a network error or proof-of-work timeout, so you do not lose what you typed. And if you visit Mirage from an iPhone browser, a download banner now points you to the iOS app.

### Node Operator Improvements

The status dashboard has been overhauled with disk usage breakdowns, validator payer balance warnings, snapshot retention info, and a cleaner layout. Log retention is now configurable via a single environment variable instead of growing unbounded. The CometBFT transaction index has been switched off and its on-disk store is automatically cleaned up during deploy, reclaiming significant disk space on long-running nodes. A new hot-swap statesync script lets operators rebuild a node from a snapshot without manual intervention. Failed transactions are now indexed so the backend can report clear errors instead of silent drops.
