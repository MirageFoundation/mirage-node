# Mirage v1.37.0 Release Notes

### Your node, set up by asking you

Running a validator has always started with one command and one recovery phrase, and everything else was decided for you. That was fast, and it was also presumptuous: the name your validator carries in front of the whole network was quietly taken from your Mirage username, whether or not that is the name you want other operators to see. This release turns the silent decisions into three questions. What should your validator be called, does it have a domain, and should it accept media uploads. They are all asked in one go, right after your recovery phrase and before any of the slow work, so nothing interrupts a sync twenty minutes later to ask you something.

### Answers that stick

A name you chose used to be discarded the moment you also gave your node a domain, because a node with a domain silently renamed itself after its own website — and that name is what gets written to the chain when your node registers, where changing it later costs a transaction. Now your answer wins, and the website name is only the default for a node that was never given one. Every question has a sensible default and takes a single keystroke to accept, so the fast path stays fast: press Enter three times and you get your username, no domain, and uploads switched off.

### Honest defaults, including an uncomfortable one

Accepting uploads means users' images and video live on your disk, and nothing inspects them unless you have put a scanning service in front of your node. Rather than bury that in a config file, the installer says it and defaults to no. If you give a domain whose DNS is not pointing at your server yet, you are told immediately instead of discovering a website without a certificate later; the node keeps working on plain HTTP and retries the certificate on every restart. Fixing that warning also fixed something worse hiding behind it — a domain that did not resolve yet could abort the entire install with an unexplained error code, which is precisely the situation the warning exists to describe.

### Nodes that pick themselves back up

Nodes installed this way now repair themselves after falling out of step with the chain, rather than stopping and waiting for their operator to notice. For someone running a single node this is the difference between a short interruption and being offline until morning. It is worth being straight about the tradeoff: this kind of recovery replaces the node's local copy of the chain, which is destructive, and a version of it once wiped three of four validators after misreading a routine upgrade pause as a fault. That specific misreading has since been ruled out, recovery only proceeds when other healthy nodes are demonstrably further ahead, and the questionable data is always preserved for investigation before anything is replaced. If you would rather your node halt and wait for you, that remains one setting away.

### Automation without an interview

Every question can be answered ahead of time by an environment variable, which keeps the one-line install usable from a script or an image build. A variable that is set is never asked about, and an empty value counts as a real answer rather than a missing one — that is how an unattended install says "no domain" without being prompted. New operators' configuration also stopped shipping a setting that pointed at one of the foundation's own nodes; it never had any effect on a running node, but it read as though your node was a front end for somebody else's.

### No chain upgrade

Nothing here touches chain code. Transactions, consensus state, validator keys and the application hash are all untouched, so no governance halt is required and no node can fork because of this release. A version handler is registered so this release could be scheduled the way earlier feature releases were, but no proposal is being submitted and none is needed: nodes running v1.36.8 and v1.37.0 compute identical results from identical blocks.
