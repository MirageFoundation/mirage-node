# Mirage v1.38.8 Release Notes

### A validator stopped signing because its disk was full

This release exists because of a failure worth describing in full. Installing a new version means downloading it first, and the download is a little over two gigabytes. On one of our servers that download ran onto a disk that had no room left for it, and filling the disk did not merely fail the update — it stopped the node. A blockchain node has to write every decision it makes to disk before it acts on it, so that a restart can never make it contradict something it already said. With nowhere to write, it could not take part at all. It stopped signing blocks at the height it was on while the rest of the network carried straight on without it.

### The cleanup existed. It had simply never run.

The uncomfortable part is that there was already a tool whose entire job was deleting old versions, and none of the things that were supposed to run it did. The fleet deploy ran it only once the new version was already installed and running, which is far too late to matter, because the download is what needs the space. It also skipped the step entirely unless the tool was present on the machine — and the fleet deploy never put it there, so on every server set up that way the cleanup was a silent no-op that had reported nothing wrong for months. The updater that public nodes use had the opposite half of the same bug: it installed the tool faithfully and then never called it, so every version a node had ever downloaded was still sitting on its disk. Ten gigabytes of dead versions had accumulated on the server that filled up.

### Cleaning up first, not last

Reclaiming space now happens before the download on every path that fetches a version, and it is no longer conditional on anything. The fleet deploy installs the tool and runs it as its first act. The updater does the same before it pulls, and again after a new version takes over, which is the moment the one it replaced becomes safe to remove. There is also a scheduled sweep, which matters more than it sounds: it is the only cleanup that is not a side effect of installing something, so it is the one that protects a node sitting idle, catching up, or waiting on a vote. It now runs before any of the checks that might cause it to stop early — a machine that is down or mid-upgrade is precisely the one that must not run out of room.

### Deleting the right things, and keeping the rest

Cleanup on a machine that has to stay running is a question of what you *keep*, and the answers are deliberate. The version currently running stays. So does the one before it, because that is what a node falls back to if a new version misbehaves, and deleting it to save space would trade a full disk for no way back. So does any version staged for an upcoming scheduled upgrade, which is referenced by nothing else and would leave a node unable to complete the upgrade it had already committed to. Everything else goes, including partial leftovers from downloads that were interrupted — those were invisible to the old cleanup, which only ever looked at fully-named versions, and they were three and a half gigabytes of what filled the disk. The blunt "delete everything unused" command is still not used anywhere, and it should not be: the rollback version is unused right up until the moment it is the only thing that saves you.

### Refusing to start rather than stopping halfway

Cleaning up more is not the same as guaranteeing there is room, so both the deploy and the updater now check for free space and refuse to begin without enough for the download plus headroom for the node's own writing. This is a deliberate trade-off in favour of a clear failure: you get an error naming the problem before anything is touched, instead of a download that runs for a while, fills the disk, and takes the node down with it. An update that declines to start leaves a working node running. Being honest about the limit, this protects the next download rather than the last one — a machine that is already full needs the cleanup to run once before it has room to update, which is now the first thing an update does.

### What this means for your node

This is an ordinary release with no governance vote and no scheduled halt, so install it whenever suits you with `mirage-update`. Nothing here changes how blocks are processed, so updated and not-yet-updated nodes agree on everything and the network can update at its own pace. Nothing needs configuring: if you run a public node, the cleanup and the space check apply from this version onwards, and a node set up with the one-line installer gets the scheduled sweep as part of its normal maintenance. If your node is short on space right now, updating is what clears it.
