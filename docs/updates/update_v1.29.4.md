# Mirage v1.29.4 Release Notes

### The crash loop, fixed at the true root

Our last release (v1.29.3) took an honest swing at a recurring node crash and moved the cleanup work into the node's normal step-by-step flow. It wasn't enough — the crashes came back, and this time two nodes went down close enough together that the network briefly paused between blocks before recovering. We went all the way back down, and this time we found the actual culprit. It was subtle, and it was ours.

### What was actually going wrong

The node periodically tidies up old history. During that tidy-up it occasionally has to rewrite one internal bookkeeping record — remove the old one, write the replacement. Those two steps share a buffer that automatically saves to disk once it fills up, and once in a while the save landed *between* the two steps: for a split second on disk the old record was gone and its replacement hadn't been written yet. Our own safety check would glance at disk in exactly that split second, see the record "missing," and slam on the brakes — and slamming the brakes threw away the not-yet-written replacement, turning a harmless split-second into a real, permanent gap. The safety net was accidentally creating the very thing it was built to catch.

### The fix

Two independent changes, either of which alone closes the door:

- **Write the replacement first, then remove the old record** — so at no instant is the record ever actually missing from disk.
- **The safety check now double-checks before acting** — it finishes saving to disk and re-reads before ever halting, so a split-second buffer state heals itself instead of tripping the alarm. A genuine problem still stops the node loudly, exactly as intended.

We reproduced the failure deterministically in a test that fails on the old code and passes on the new — so we know this is the mechanism, not another guess.

### An honest note

As before, the network stayed correct the entire time: every halt was nodes refusing to run on questionable data and recovering, never a wrong balance or a bad block. The forensic snapshots we added earlier are exactly what let us pin this down for real. We're also preparing a report of the underlying issue upstream to the Cosmos SDK, since it affects any chain built the same way.
