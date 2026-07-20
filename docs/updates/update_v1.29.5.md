# Mirage v1.29.5 Release Notes

### Smoother housekeeping, no more synchronized pauses

v1.29.4 fixed the crash at its root, and it's held — no crashes since. This follow-up removes the *last* rough edge that came with it: a brief, occasional pause where the whole network would catch its breath at the same moment.

### What was happening

The node periodically cleans up old history. In the previous couple of releases that cleanup ran "in-line" — right in the middle of finalizing a block. Normally that's instant, but once in a while a larger-than-usual cleanup would take a minute or two, and because every node does it at the exact same height, they'd all pause together. The network stayed perfectly correct and picked right back up on its own, but for a few minutes blocks would pause instead of flowing every three seconds.

### The fix

We moved the cleanup back off to the side, so it runs quietly in the background instead of in the middle of block production. Now if a cleanup ever takes a moment, a single node just does its housekeeping and catches up — the rest of the network never notices. This was only ever run in-line as a workaround for a problem we've since fixed properly (in v1.29.4), so there's no downside to moving it back.

### An honest note

The safety checks and the clean-shutdown fixes from the last two releases all stay exactly where they are. This is purely a smoothness improvement: same correctness, same crash-free behavior, minus the synchronized pauses.
