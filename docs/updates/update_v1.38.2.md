# Mirage v1.38.2 Release Notes

### Fixes to the sign-up engine can now actually reach you

Yesterday's release improved the puzzle engine that guards free accounts, and almost nobody would have received it. The engine is served from an address that never changes, and browsers and the network's edge servers had been told to keep their copy for a month, so a returning visitor would have kept running the old one until September. The address now carries the build it belongs to, which makes it a different address with every release, and the site tells caches to check for a newer copy rather than assume there isn't one. The practical effect is that improvements and fixes to signing up, posting and voting arrive when they are published instead of a month later.

### The kind of mistake worth naming

Nothing set out to cache that engine for a month. Every other part of the site says how long its files may be kept — the app's own code is fingerprinted and kept for a year, the page itself is never kept, the build marker is never stored — and this one directory said nothing at all. Silence is not the same as "do not cache": the network's edge substituted its own default of thirty days, and that default became the delivery schedule for the most security-sensitive code in the browser. Every release now checks that this directory declares a policy, so the gap cannot reopen quietly.

### No chain upgrade

Nothing here touches chain code. Consensus, transactions, validator keys and the application hash are untouched, so no governance halt is required and no node can fork because of this release. Nodes running v1.38.1 and v1.38.2 compute identical results from identical blocks.
