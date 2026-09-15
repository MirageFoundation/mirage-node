# Mirage v1.39.3 Release Notes

### A subscription that ended should not look like a broken post

When a paid subscription runs out, Mirage already treats that account as free on the chain. Posting is still allowed, but it has to prove a small amount of work, the same way a free account always has. What broke was the site's own copy of that fact. The chain recorded the lapse immediately. The reader that feeds the site did not, so the composer still showed paid limits and sent a zero-fee post the chain would not accept. The only thing you saw was "Transaction rejected." This release teaches the reader to catch the lapse as it happens, so the site and the chain agree again.

### An honest error instead of a shrug

If your browser still thinks you are subscribed for a moment after the lapse, the site now says your subscription status changed and asks you to try again, instead of hiding the real reason behind a generic failure. That retry is the free path: proof of work, then the post goes through. We are not pretending a lapsed account keeps its paid allowance. The chain never did.

### What this means for your node

This is an ordinary release. There is no governance vote, no scheduled halt, and nothing here changes how blocks are produced or validated, so nodes on the old and new versions agree completely and the network cannot split over it. Install it with a single `mirage-update`. Until a node installs this, a lapsed subscriber on that node can still see the paid composer and get a useless rejection. After install, the reader corrects itself on startup and from then on, and the clearer error is what you get if the browser is still a step behind.
