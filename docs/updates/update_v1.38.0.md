# Mirage v1.38.0 Release Notes

### Running a node now pays for itself

Until now, what a validator earned came down almost entirely to how much it had staked. A node with five million MIRAGE behind it and a node with five billion did the same work — same machine, same bandwidth, same uptime, same blocks signed — and the smaller one took home roughly a thousandth as much. That is not a reward for participation, it is a reward for capital, and it made a modest node not worth switching on. From this release a fifth of everything minted is paid out equally to every validator holding up the network, regardless of stake. Show up, stay bonded, and you earn.

### Twenty, ten, seventy

Each minting round now divides three ways. Twenty percent is the floor: split evenly among every bonded, non-jailed validator, so your share depends on being there rather than on your balance. Ten percent pays for work — the traffic your node actually relayed for users, capped per round so one busy node cannot take the pool. The remaining seventy percent is still weighted by stake, because stake is what secures the chain and it should stay the largest single reason to hold MIRAGE. The amount minted per round has not changed at all; only how it is divided.

### Work that means work

The work share used to be weighted by traffic multiplied by stake, which quietly made it a second stake pool. Two nodes serving identical traffic were paid wildly differently, so relaying was never really what you were being paid for. That multiplication is gone. Equal traffic now earns equal pay, full stop, which is the only version of a work reward that means anything. If nobody relayed anything in a round, that slice falls back to stake weighting rather than being folded into the floor, so an idle network does not quietly change what the floor is.

### What this costs you, honestly

If you are a large staker, your share of each round goes down. That is the deliberate point of the change and it is worth stating plainly rather than dressing up: seventy percent of the mint still follows stake, but the thirty percent that no longer does used to be mostly yours. The floor also thins as the network grows, since it is split among all bonded validators — twenty percent shared four ways is very different from twenty percent shared four hundred ways, and a node that joins later earns a smaller floor than one that joined today. Jailed and unbonded validators earn nothing from any of the three pools, exactly as before. And restaking your earnings still grows your holdings without letting you out-earn the floor that everyone else receives.

### This one stops the chain

Unlike recent releases, this genuinely changes consensus. A node still running v1.37.0 computes a different payout from the very same block, so a network on mixed versions would not merely disagree about rewards, it would split in two. Every validator therefore stops at one scheduled block and returns on the new version. Nothing is downloaded in the background: before the proposal is submitted, each operator explicitly verifies, downloads and prepares the signed release. The node then switches to that exact prepared version automatically when it reaches the matching halt. A validator that was not prepared stays safely halted on the old version until its operator acts; it never guesses or silently crosses the boundary.

### Adjustable from here

Both shares are ordinary chain parameters from now on, readable by anyone querying the node and changeable by governance vote. This release had to be a new version because the floor did not exist to point a vote at; the next adjustment will not. If the community decides twenty percent is too generous or too thin, that is a proposal rather than a release, and the chain refuses any combination that would pay out more than a round actually mints. The split was rehearsed end to end against a copy of live chain state before shipping, and the payout arithmetic is covered down to the last unit — every round distributes exactly what it mints, with nothing lost or invented in the rounding.
