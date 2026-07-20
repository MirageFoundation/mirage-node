# Mirage v1.29.3 Release Notes

### The crashes stop here

This release closes out a stubborn reliability problem at its source. A small number of nodes had been crashing on a roughly weekly rhythm — never losing your data, and always recovering on their own, but crashing all the same and creating noise that made real problems harder to spot. We traced it the whole way down and fixed the actual cause, not just the symptom.

### What was actually going wrong

Two separate faults were stacking on top of each other. First, whenever a node shut down for routine maintenance, it was closing one of its internal databases twice and panicking on the second close — a clean shutdown turned into an ugly one. Second, and more importantly, the node cleans up old history in the background while it runs; if it was shut down at exactly the wrong moment, that background cleanup could be cut off mid-stride and leave a single tiny gap in its records. The node kept running fine until, days later, it walked back over that gap, correctly refused to continue on questionable data, and restarted itself from a healthy copy.

### The fix

We made shutdown clean and single-shot, so the double-close panic is gone. And we moved the history cleanup out of the background and into the node's normal step-by-step work, so it can no longer be interrupted halfway by a restart. No interrupted cleanup means no gap; no gap means no crash. The safety check that caught the problem in the first place stays in place as a permanent seatbelt — it just should never have anything to catch anymore.

### An honest note

Throughout this whole investigation the network stayed correct — every crash was a node protecting itself and recovering, never a wrong balance or a bad block, and the recent forensic snapshots are exactly what let us find and prove the root cause instead of guessing. This is the boring kind of fix we like: a specific bug, understood end to end, removed at the root. We have also reported the underlying issues upstream to the Cosmos SDK so the wider ecosystem benefits too.
