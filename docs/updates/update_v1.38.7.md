# Mirage v1.38.7 Release Notes

### The network page now shows the whole network

Open /network and the Sites list is every active node on the chain, not just the handful your own node happens to be gossiping with at that moment. Those are different things, and the old list quietly answered the wrong one. Two nodes can both be running perfectly and never speak to each other directly, so whether a site appeared for you came down to the shape of the peer connections underneath — which is invisible, changes on its own, and has nothing to do with whether that site is worth visiting. The list is now drawn from the chain's own record of who is validating, which every node reads identically. Your view of the network and everyone else's finally agree.

### A fleet that counts itself

The same mistake was doing real damage behind the scenes. The admin growth dashboard combines figures from every server in the fleet, and it found those servers by reading a list an operator had typed in by hand. A list like that is out of date the moment anything changes, and it was: the dashboard cheerfully reported "1 server reporting" while four were running, so every visitor number it showed was a fraction of the real one, presented as if it were the whole. Nobody has to maintain that list anymore. A node is part of the fleet when the chain says it is validating, which means a new node starts contributing its numbers as soon as it joins, without anyone remembering to add it.

### Nodes that disappear, disappear

The flip side matters just as much. A node that is switched off for good used to linger on these lists forever, because nothing ever removed it. Now it removes itself: it stops signing blocks, the chain notices and sets it aside, and it drops off the network page and out of the statistics on its own. This is also what keeps the list honest at scale — you cannot pad it out with thousands of abandoned machines, because a node that is not signing does not count, and being counted in the first place requires a validator's own stake behind it.

### Only over a secure connection

A node advertises itself with a name it chooses, and that name is the address other nodes use to reach it. Since anyone can write anything there, we now insist on the one thing that can actually be checked: a proper domain served over https, whose certificate proves it is the site it claims to be. Names that point at a plain unencrypted address, or at a bare machine number, are skipped rather than shown or contacted. In practice this means a node needs a real domain to appear on the network page — which is the same thing as saying it needs one to be worth clicking.

### Being straight about the trust boundary

This is worth saying plainly, because it is a genuine trade-off rather than a pure improvement. When an administrator views the fleet-wide dashboard, their server asks the other nodes for their figures, and it proves who is asking with a signature — never a password, and never anything that would let another node act as them. But that proof stays valid for a few minutes, and it is now sent to nodes discovered from the chain rather than to a list we vetted by hand. An operator who runs a validator, and points its name at a machine they control, could catch a copy of that proof and use it to read another node's statistics before it expires. Doing so requires staking real funds as a validator, which is a considerably higher bar than the alternative arrangement it replaced, but it is not nothing. The complete fix binds each proof to the single node it was meant for, and that is queued as the next step on this surface.

### What this means for your node

This is an ordinary release with no governance vote and no scheduled halt, so install it whenever suits you with `mirage-update`. Nothing here changes how blocks are processed, so updated and not-yet-updated nodes agree on everything and the network can move at its own pace. If you run a public node, check that its advertised name is your https domain — that is what puts you on everyone else's network page.
