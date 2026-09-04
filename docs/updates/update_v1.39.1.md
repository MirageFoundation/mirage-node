# Mirage v1.39.1 Release Notes

### The front page, roughly six times faster

Opening Mirage used to mean staring at an empty shell for three and a half seconds while the server assembled your home feed. It now takes about half a second. Nothing about the feed itself changed — same posts, same ranking, same interleaving — we simply stopped doing an enormous amount of work nobody was ever going to see. The database was reading its way through every post and every upvote on the network to pick fifteen items for your screen, so we taught it to look only at recent candidates and to find them through purpose-built indexes rather than by scanning. The three sections of your home screen that have nothing to do with each other — your account status, who you follow, your communities — are now fetched at the same time instead of one after another.

### Posts that were there all along

The more uncomfortable half of this release is a bug we shipped with communities. If you sorted your home feed by newest, or looked at your own profile, posts were missing. Not hidden, not removed — they were being sorted to the back of the queue and then falling off the end of the page. The cause was that anywhere a community has a curation team, its posts had to make a second trip through the filter to see what the team had decided, and they rejoined the list at the bottom instead of where they belonged. In a busy community with a curation team, that was enough to push your newest post out of sight entirely. Order is now preserved exactly as the feed produced it, and there is a test that fails if it ever isn't.

### A curate menu that opens when you click it

Curators had to wait for a round trip every time they opened the menu on a post, because the app asked the server what the team had already decided about that one post. It now asks once for everything on screen and remembers the answer, so the menu opens instantly and clicking through a page of posts costs nothing at all. The answer is still signed and still checked against your team membership — we made it cheaper, not looser.

### Curator invites, finished properly

Inviting somebody to your curation team no longer means knowing their exact name: start typing and matching users appear, the same way mentioning somebody in a post does. If an invite fails, the reason now appears under the box you typed in rather than at the top of the page where you would have to go looking for it. The invitation card itself was restyled to match the rest of Mirage instead of looking like it arrived from somewhere else. And accepting an invitation, or leaving a team, now takes effect the moment your transaction is accepted — previously the card sat there unchanged, because the app was asking a database that hadn't caught up yet and getting the old answer back.

### Nodes that were doing everything right and still looked broken

A node with a domain name could serve the site perfectly and still be listed as unconfirmed on the network page. Nodes introduce themselves to each other by name, and unless an operator had set that name by hand it stayed at the factory default — so the network knew the node existed but had no idea where to reach it, and the one address that would have worked was never tried. If you have told your node its domain, that is now the name it publishes, and it confirms itself. Operators who deliberately chose a name keep it. Separately, the deploy step that updates that name used to give up in silence if the node was still starting; it now waits for it and says so if something is actually wrong.

### What this means for your node

This is an ordinary release. There is no governance vote, no scheduled halt, and nothing here changes how blocks are produced or validated, so nodes on the old and new versions agree completely and the network cannot split over it. Install it whenever suits you with a single `mirage-update`. The speed work is entirely in how the site reads its own database, so your node gets the new indexes when the release starts up. Worth knowing: the front page is fast now because it looks at recent posts when picking candidates, so a community that has been quiet for a fortnight contributes less to the mix than it used to — deliberate, and the reason your feed loads before you notice it loading.
