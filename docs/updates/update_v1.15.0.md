# Mirage v1.15.0 Release Notes

### Burn-only awards

You can now give awards to posts and comments. Awards are a pure signal of appreciation, not a payout — the MIRAGE cost is permanently burned rather than sent to the creator. There are four awards: Quality Post costs 10,000 MIRAGE, while Original Content, Based AF, and Receipts cost 5,000 MIRAGE each. When multiple people give the same award it stacks into a single count, and when different awards appear together they display as a tidy list so recognition stays readable instead of noisy.

### Giving awards

Tap the menu on any post or comment and hit "Give Award" to pick from the four award types. The confirmation dialog shows your current balance and greys out any award you can't afford. Once you confirm, the deduction and the new award badge show up instantly — no waiting for a block — and a success banner confirms the burn went through. One award per account per piece of content, and you can never award your own stuff.

### Award notifications

Awards now land in your inbox alongside replies and mentions. You'll see who gave the award, which type it was, and a preview of the post or comment that earned it. The inbox badge lights up immediately so you won't miss recognition even if you're not actively browsing.

### Smarter Magic feed

Awards feed into the Magic ranking model by counting how many distinct accounts recognized a post. Content that earns broad recognition from different users gets a clear visibility boost alongside votes, discussion, and personal relevance. The awards count now shows up in the Magic tooltip breakdown so you can see exactly how recognition factors into a post's score.

### Tighter Following feed

The Following feed now does what the name says — it only surfaces posts from people you actually follow (plus your own). Previously, a post could sneak in if it matched one of your followed topics even though you didn't follow the author. That loophole is closed; topic matching still powers the For You and Discover feeds, but Following is strictly your people.

### New-user highlight

Fresh accounts now stand out with a green username across the feed, post detail, inbox, and search results. Any account less than seven days old gets the highlight so the community can spot newcomers and welcome them in. Subscriber tier colors still take priority — if someone subscribes on day one, their tier color wins. The highlight window is server-configurable and can be turned off entirely if the community outgrows it.

### Burned (24h) network stat

The Server tab on the Network page now shows a "Burned (24h)" metric right alongside "Earned (24h)." Together these two numbers tell the full story of MIRAGE tokenomics. On the inflationary side, new tokens are minted every block and distributed to creators, subscribers, and node operators. On the deflationary side, awards permanently destroy tokens — every award burn removes MIRAGE from circulation forever. The minting rate is a governance parameter the community can adjust at any time, just like a central bank sets an interest rate: if too many tokens are entering circulation the community can vote to slow the mint, and if burns are outpacing issuance they can open the tap. The goal is equilibrium — mints and burns roughly in balance — which keeps MIRAGE supply stable and gives the token a predictable, durable value rather than an inflationary death spiral or a deflationary squeeze.

### Community-tuned awards

Award types and costs are governed by the community. The network can add new awards, remove old ones, or adjust costs through governance without waiting for another code release.