# Mirage v1.38.1 Release Notes

### Signing up works again

Creating an account on Mirage requires your browser to solve a small puzzle first — that is what keeps the network free to use without drowning in spam. Since v1.36.0 the site had been telling browsers, in the same breath, that they were not allowed to run the engine that solves it. The result was a minute of "Preparing…" followed by a message about the puzzle taking too long, which was true but not the reason. Anyone who tried to sign up during that window, on any browser that enforces the rule, could not. The permission is now granted, narrowly: browsers may compile the puzzle engine and nothing else, which is a smaller allowance than most sites make and leaves the rest of the protection untouched. Sending anything as a free-tier user went through the same engine, so this was not only signup.

### A failure that says what it is

The puzzle runs in the background, and when the browser refused to start it, nothing said so — the page simply waited out its full minute. It now checks whether it is permitted before it begins, and if it is not, it tells you immediately and by name instead of leaving you watching a spinner. Being honest about this one: the file carrying that check is held in browser and edge caches for up to thirty days, so returning visitors may keep the old silent version for a while. The fix itself does not depend on it. The permission travels with the page, which is never cached, so signup works everywhere the moment this release is deployed.

### Nothing tagged when you are not signed in

A post carrying a content tag should not greet someone who has not signed in, and one did. Two separate things had to be true for that, and both were. Tags applied by the moderation agents that run for everyone were being skipped for signed-out visitors, so a post an agent had marked was judged as though it carried no mark at all. And the server was treating "show me sensitive content" as the default for everyone rather than a signed-in preference. Signed out now means nothing tagged, in the feeds, in topics, in search and on profiles. Signed in, sensitive content is still shown by default and the stricter categories still stay hidden until you ask for them, all of it yours to change in settings. The decision is now made by the server rather than requested by the app, so a months-old cached copy of the app cannot ask for tagged content on a visitor's behalf.

### A front page that is computed once

The page a signed-out visitor sees is the same page for every signed-out visitor: no blocks, no reading history, no votes of their own. It was being built from scratch on every single request anyway, which made it the most expensive thing the site does and the least necessary. It is now built once and shared for thirty seconds, and answered before a database connection is even opened. The verification of which moderation agents run for everyone — a fixed piece of configuration that was being re-checked on every request from every visitor, signed in or not — is now checked once every five minutes. The tradeoff is plain: a brand-new post can take up to thirty seconds to appear for someone who is not signed in. Signed-in feeds are personal and are not shared or delayed.

### No chain upgrade

Nothing here touches chain code. Consensus, transactions, validator keys and the application hash are untouched, so no governance halt is required and no node can fork because of this release. Nodes running v1.38.0 and v1.38.1 compute identical results from identical blocks; this is a web and site update that every node can take at its own pace.
