# Mirage v1.29.9 Release Notes

### Housekeeping, and an early-warning light

A quiet maintenance release. No consensus changes, no crash fixes needed — the network has been running clean since v1.29.5. This one is about disk space and about noticing things sooner.

### What we found

While checking in on storage, we measured exactly what was using the disk on our busiest node — and the answer was a pleasant surprise. The blockchain database itself is now **40 MB**. Not gigabytes: megabytes. Earlier this month that same database was over 1.8 GB, and the cleanup work from the last several releases is what shrank it. Every part of the chain that's supposed to be trimmed is now trimmed to exactly its configured limit, right down to the block.

So the disk wasn't filling up with chain data at all. It was ordinary log files — including the system's own diagnostic journal, which by default is allowed to grow to a tenth of the entire disk.

### What we changed

We capped the system journal and shortened how long routine log files are kept, from 30 days to 14. Together that returns a comfortable chunk of space and keeps it from creeping back. Two weeks is still plenty of history for diagnosing anything — and the logs that matter most for investigating a real incident are kept separately, on their own longer schedule, completely untouched by this.

We also added an early-warning light: nodes now raise a clear warning when a disk crosses 80% full, well before it could become a problem.

### One deliberate choice

That warning only warns. It will never delete anything on its own. It's tempting to have a machine tidy up automatically when space runs low, but deleting large amounts of data under pressure is precisely how we caused ourselves trouble earlier this month, and databases need free space available in order to compact and reclaim it — so an automatic purge at 90% full could make things worse before better. A human decides, with the full picture in hand. The one thing the software should never do under stress is get creative.

### An honest note

Nothing was wrong here. There was no incident, no urgency, and months of headroom remained. This is the housekeeping you do while things are calm, precisely so you're not doing it while they aren't.
