# Mirage v1.36.6 Release Notes

### Requirements you can actually meet

The installer used to demand 80 GiB of free disk space, which was not a strict rule so much as an impossible one: an 80 GB cloud disk already has Ubuntu on it, so it can never present 80 GiB free, and the check rejected the exact machines the requirement was written for. The floor is now 20 GiB, with a warning below 40 GiB that tells you about long-term growth without blocking the install.

### The numbers come from the running network

Rather than round the requirements up and hope, we measured the validators that have been carrying Mirage for months. Each runs on a 4 GB, 2-core plan with a 24 GB disk. The whole system — the container image, both databases, the pruned chain data and the logs — occupies about 15 GiB, and memory peaked at 38 percent over nine days without ever dropping below 1.9 GiB available. The published requirements now describe that machine, and the guide shows the measurements so you can check our arithmetic instead of taking our word for it.

### The swapfile is gone, and so is the story behind it

Every Mirage host used to get a 2 GB swapfile, justified by the belief that memory pressure had caused a state divergence in June and that swap was what stood between a validator and silent corruption. That belief was wrong, and our own investigation had already said so: the node diverged while the machine was idle, on a host that already had swap, with no process ever running out of memory. The real cause was a database pruning race, and it was fixed months ago. Measurement confirmed the swapfile was carrying nothing — under 50 MB in use, with paging activity indistinguishable from zero. New hosts no longer create one.

### Honest about what we kept

Existing validators keep the swapfile they already have. Removing live swap from a running node is the kind of change that should be made deliberately by an operator watching it, not silently by an upgrade script, so we document how to do it and leave the decision with you. The setting that keeps Linux biased against swapping also stays, precisely because those older hosts still have swap to be biased about.

### A correction where it matters most

The same refuted memory explanation had also settled into the incident-recovery runbook, which is the document someone reads at speed when a validator is misbehaving. It told them to suspect memory. That has been corrected to point at the real cause and the fix that shipped for it, because a runbook that sends you after the wrong thing costs more during an incident than at any other time.

### No chain upgrade

This release changes host preparation and documentation only. Transactions, consensus state, validator keys and the application hash are untouched, so no governance halt is required and validators running v1.36.4, v1.36.5 or v1.36.6 cannot fork because of this update.
