# Mirage v1.37.0 Release Notes

### One command, one recovery phrase

Running a validator takes a single command and the twelve words you already have. Nothing else is asked. Your validator is named after your Mirage username, it serves on the machine's IP address, and it does not accept media uploads — the three answers that are right for a new public node. The install tells you each decision as it makes it, so you finish knowing exactly what your node is, and every one of them can be changed afterwards without reinstalling. If you want different answers from the start, each one reads an environment variable, which is also what makes a scripted install possible.

### A name that sticks

The name your node carries is written to the chain when it registers, and changing it later costs a transaction, so it should not move on its own. It used to: a node given a domain quietly renamed itself after its own website. Your username is now the name, and the website name is only a default for a node that never had one. Names are stored as text rather than as shell, so a space no longer aborts startup and a crafted one cannot run as a command inside the container after keys are already on disk.

### Adding a domain when you are ready

A domain gives your node HTTPS and a public web address, and it needs DNS pointing at your server before it can work. Rather than ask for one during an install, when the DNS record often does not exist yet, the node starts on its IP and you add the domain whenever you like with a single command that requests the certificate and binds the name. Media uploads are the same kind of decision: they put users' images and video on your disk and nothing inspects them unless you run a scanning service in front of the node, so they stay off until you turn them on deliberately.

### Installs that survive their first hour

A first install now behaves like a first install. The setup steps a release carries exist to move older nodes forward, and on brand-new hardware they were being run anyway, against an empty database and freshly written configuration — one of them queried a table the node had not created yet and took the whole startup down with it, leaving the container restarting in a loop. A node with no chain history now skips that historical work entirely, and an install interrupted partway through is still recognised as new when you run it again. Joining also no longer feeds years-old parameter names from the network's immutable genesis into a binary that has since renamed them; the genesis is still verified byte for byte before the installer applies the current parameter shape needed to begin state sync. The one-line installer also no longer trips over how current Ubuntu images run SSH, which stopped hardening before the firewall was configured.

### Nodes that pick themselves back up

Nodes installed this way now repair themselves after falling out of step with the chain, rather than stopping and waiting for their operator to notice. For someone running a single node this is the difference between a short interruption and being offline until morning. It is worth being straight about the tradeoff: this kind of recovery replaces the node's local copy of the chain, which is destructive, and a version of it once wiped three of four validators after misreading a routine upgrade pause as a fault. That specific misreading is ruled out: a scheduled network upgrade that stops the binary is not treated as a broken chain, recovery only proceeds when other healthy nodes are demonstrably further ahead, the validator will not lower the height it has already signed or rewrite that watermark while it is still catching up, and the questionable data is always preserved for investigation before anything is replaced. If you would rather your node halt and wait for you, that remains one setting away.

### Updates that do not strand you

A node used to be allowed to install a new version only if it was already running the one immediately before it. On a node that was switched off for a fortnight, or whose updater was paused, that was a dead end: the version it insisted you install first was no longer offered anywhere, because only the newest release is ever published. That requirement is gone. The one-time setup steps a release carries are applied by looking at which ones this particular node has never run, so a node that missed three releases performs all of their setup steps in order the first time it starts the new version. A new version is parked by the hourly check; the tools on the machine itself are replaced only when you activate. Nodes whose existing updater still expects the old rule will decline this release until those tools are replaced once; new installs are unaffected.

### No chain upgrade

Nothing here touches chain code. Transactions, consensus state, validator keys and the application hash are all untouched, so no governance halt is required and no node can fork because of this release. A version handler is registered so this release could be scheduled the way earlier feature releases were, but no proposal is being submitted and none is needed: nodes running v1.36.8 and v1.37.0 compute identical results from identical blocks.
