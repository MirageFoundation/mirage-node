# Mirage v1.14.1 Release Notes

### Account deletion

You can now delete your account from Settings. Type "DELETE," confirm, and the chain marks your profile for deletion — username, follows, blocks, subscription, everything. Your username frees up instantly, any remaining token balance flows back to the community pool, and the app clears your seed phrase and logs you out on the spot. One caveat worth being upfront about: Mirage is a decentralized network, and each node operator runs their own software. The deletion message goes out to every node and the default software honors it, but an operator *can* choose to ignore it or run modified code that keeps the data. Think of it as "marked for deletion" — the vast majority of nodes will comply, but we can't force every last one. That's the tradeoff of decentralization. Your historical posts stick around with your old username for context, but your profile and identity are gone from the canonical state.

### Governance deletion

The community can also delete accounts through governance. If a spam account, an impersonator, or a bad actor needs to go, anyone can propose it and the network votes — no user signature needed. When the vote passes, the same full cleanup runs automatically. The deletion flow is locked down where it matters: the chain rejects any attempt to delete someone else's account without a governance vote, and the full self-delete path is validated end to end with dedicated security tests.

### Feed interleaving

The Magic feed now interleaves fresh posts with top-ranked ones instead of just sorting by score. Every other slot in your feed pulls a random post from a 1-hour band — the first fresh slot draws from 0–1 hours ago, the next from 1–2 hours, then 2–3, and so on up to 7 days. New content gets a fair shot even when older posts have racked up more votes and engagement, and the linear hour-by-hour bands mean your feed stays consistently fresh rather than skipping big chunks of time.

### Rate limiting

All API and chain endpoints now enforce per-IP rate limiting — 10 requests per second on API routes, 5 on chain routes — with clean JSON errors instead of cryptic HTML when you hit the ceiling. Structured access logs, automatic Cloudflare IP trust, and smarter cache headers round out the hardening.
