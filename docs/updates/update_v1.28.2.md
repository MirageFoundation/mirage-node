# Mirage v1.28.2 Release Notes

### A Steadier Network

This release is all about reliability under the hood. Over the past weeks a small number of nodes occasionally fell out of step with the rest of the network and had to be recovered — never losing your data, but causing brief hiccups. We have hardened the parts of the node most likely to be responsible. The shared in-memory cache that sits between blocks, the single most likely source of an inconsistent read, is now switched off across the fleet, and several internal read paths now stop immediately and loudly if they ever hit a storage error instead of quietly guessing a value. A clean stop is something we can detect and recover from automatically; a quiet wrong guess is not.

### Keeping Disk Usage Honest

We tracked down why node databases were ballooning far faster than the actual chain data justified. A piece of bookkeeping that the underlying Cosmos SDK writes on every block was never being cleaned up, so it grew without limit — on our nodes it had quietly become the overwhelming majority of the database while the real state stayed tiny. This release reclaims that space gradually and safely as old history is pruned, so disk growth now tracks real usage rather than runaway bookkeeping.

### Faster, Safer Recovery

When a node does need to recover, it now always preserves a forensic snapshot of the diverged state before anything is wiped, so we can actually diagnose what went wrong rather than losing the evidence in the rush to get back online. We also added an independent watchdog that pages a human if a node silently freezes, running in its own isolated process so it keeps working even if the main monitor is the thing that failed. The alerting is optional and ships switched off by default.

### Giving Back Upstream

The database-bloat bug is not unique to Mirage — it affects every Cosmos chain that prunes history, it is just usually hidden on chains whose state dwarfs the bookkeeping. We have reported it upstream to the Cosmos SDK team along with a proposed fix so the wider ecosystem benefits, not just us.

### An Honest Note

We want to be straight about this: while we have shipped meaningful hardening and ruled several theories out, we have not yet proven the single definitive root cause of the original divergences. These changes remove the most probable culprits and dramatically improve our ability to catch and diagnose the next occurrence if there is one. This is steady, evidence-driven progress, not a victory lap — and the new forensic snapshots mean that if it happens again, we will finally have what we need to close the case for good.
