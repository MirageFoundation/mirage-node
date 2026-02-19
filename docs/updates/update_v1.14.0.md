v1.14.0 brings **account deletion** to Mirage. Your data, your choice — head to Settings, type "DELETE," and your entire presence is wiped from the chain: profile, username, follows, blocks, subscription, everything. Your username is freed up instantly for anyone else to claim, and any remaining token balance flows back to the community pool.

Mirage is built on a blockchain, so deletion works a bit differently than what you're used to. When you delete your account, the network broadcasts a deletion request to every node. The vast majority will honor it immediately, but because each node is independently operated, we can't promise that every last copy disappears from every corner of the network. Your historical posts stick around with your old username for context — but your profile and identity are gone for good.

For cases where the community needs to step in, account deletion can also happen through **governance**. If a spam account, an impersonator, or a bad actor needs to go, the community can propose and vote on it — no user signature needed. When the vote passes, the same full cleanup runs automatically.

We've also tightened up the infrastructure in this release. All API and chain endpoints now enforce **per-IP rate limiting** — 10 requests per second on API routes, 5 on chain routes — with clean JSON errors instead of cryptic HTML when you hit the ceiling. Structured access logs, automatic Cloudflare IP trust, and smarter cache headers round out the hardening.

The deletion experience is designed to be final. Once you confirm, the app **clears your seed phrase, wipes local data, and logs you out** on the spot. No cooldown period, no "we'll keep your data for 30 days just in case." When you say delete, we mean it.

Every layer of the deletion flow is battle-tested: the chain rejects any attempt to delete someone else's account, the API enforces the same ownership check, and the full self-delete path is validated end to end with dedicated security tests.
