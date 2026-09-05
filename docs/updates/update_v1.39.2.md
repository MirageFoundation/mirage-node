# Mirage v1.39.2 Release Notes

### An outage we should not have had

On the evening of September 4th, Mirage stopped accepting anything new for about eighteen hours. You could open the site and read what was already there, but posting, voting, following, subscribing and signing up all failed. The blockchain itself never stopped for a moment — it produced blocks the entire time, on every node, and no data was lost or rolled back. What stopped was the service that reads the chain and keeps the site's own copy of it up to date. Once that copy stopped moving forward, the site correctly refused to accept new actions rather than write them against state it knew was stale. That is the safe behaviour, and it is also why the front page kept loading normally while nothing on it worked.

### One wrong assumption about lapsed subscriptions

The cause was a single mistaken assumption about what a lapsed subscription looks like. Subscribers get a daily allowance of actions that do not cost them anything. If a subscription runs out partway through a day, the account drops back to free while the actions already taken that day remain on the record — so for the rest of that day the account has used more than its new allowance permits. That is ordinary and expected, and the blockchain reports it correctly. The service reading the chain, however, had been written to treat it as impossible, and when it finally met a real subscription lapsing on an empty balance it stopped rather than continue with what it thought was corrupted data. Because every node reads the same blocks in the same order, every node stopped at exactly the same one. It has now been taught what the chain has always known, and this release ships tests that reproduce the exact situation and fail if that assumption ever comes back.

### Being honest about the eighteen hours

The bug is a small one. The eighteen hours are the part worth explaining. Mirage already watches for a node that stops producing blocks and pages a human within minutes, and it deliberately stops restarting a service that is failing over and over rather than thrash forever. Both of those worked exactly as designed and both missed this. The nodes were healthy and never stopped producing blocks, so nothing looked wrong to the alarm, and the service that had genuinely stopped was one nothing was watching. So the network sat in a safe, correct, thoroughly broken state overnight until a human noticed. Nothing in this release fixes that gap, and we would rather say so plainly than let a one-line fix imply the problem is fully solved. Watching the readers as closely as we watch the nodes is the next piece of work.

### Curation that responds when you click it

Away from the outage, every remaining action on a curation team now takes effect the moment your transaction is accepted, instead of leaving the button looking untouched while the network caught up. Creating a team, inviting somebody, withdrawing an invitation, promoting a member, removing one, and pinning or unpinning a team all now respond immediately and show you where they are in the queue if there is a wait. This finishes the work started in the previous release, which had done the same for accepting an invitation and leaving a team, and it removes the last places where a click appeared to do nothing at all.

### What this means for your node

This is an ordinary release. There is no governance vote, no scheduled halt, and nothing here changes how blocks are produced or validated, so nodes running the old and new versions agree completely and the network cannot split over it. Install it whenever suits you with a single `mirage-update`. Operators who worked around the outage by hand should still install this one: the fix needs to be in the release to survive the next restart, and until it is, the same block content can stop the reader again. After installing, a node that fell behind catches up on its own and needs no further attention.
