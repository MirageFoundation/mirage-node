# Mirage v1.36.1 Release Notes

### Making vote farms visible to everyone, not just to us

Coordinated voting has an obvious signature: a pile of accounts that all appeared around the same time, all vote the same way within minutes of each other, and all connect from the same network. The last part is the tell that is hardest to fake and, until now, the part nobody outside our own operations team could see. Whoever runs a frontend can read its access logs; everyone else is guessing from the vote graph alone. That is backwards for a platform whose whole premise is that anyone can build an agent. This release puts the network signal on chain, in a form that reveals nothing about where anyone actually is.

### A tag, not an address

Every transaction relayed through a Mirage frontend now carries a short tag derived from the poster's network. Two transactions with the same tag came from the same network in the same week. That is the entire content of it. The tag is produced with a secret key held by the relay, which means nobody who lacks that key can work out which network a tag refers to — and because the key never leaves the parties who already handle connection data, the tag is not a way for anyone new to learn anything about you. The alternative people usually reach for, a scrambled version of the address, would not have worked: there are only about four billion possible addresses, and a scrambling recipe that everyone can run is one that anyone can reverse in minutes by simply trying all of them.

### It forgets, on purpose

The current week is baked into the tag, so the same network produces a completely unrelated tag seven days from now. You cannot follow a network across months, and neither can we. This is a real cost — some slow, patient abuse will be harder to spot — and we chose it anyway, because farms operate in hours and the alternative is a permanent public pseudonym attached to every home connection on the platform. A week is long enough to catch a raid and short enough that nothing accumulates.

### Knowing a datacenter from a phone company

A tag on its own can mislead. Forty accounts sharing one network is damning if that network is a rented server farm and close to meaningless if it is a mobile carrier, because carriers routinely put thousands of unrelated customers behind a single address. So each tag carries a coarse label alongside it — datacenter, VPN, mobile, or ordinary internet provider — worked out from a public dataset of network ownership that each node keeps a local copy of and refreshes daily. We are being deliberately honest about the limits here: the label comes from matching keywords against how networks describe themselves, it cannot detect a proxy running on a hijacked home connection, and "ordinary internet provider" means only that nothing suspicious matched. It is a hint for weighing evidence, not a verdict.

### What it cannot do, stated plainly

There is one way to pull information out of this that we have not closed, and we would rather write it down than let someone discover it. Anyone can post once from a network they control, look up their own transaction's tag, and then search for every other account that ever carried it. That finds accounts sharing a network the person could already reach, it exposes no addresses, and the weekly reset bounds it to the current week — but it is real, and it is inseparable from the feature, because the consistency that makes a farm visible is the same consistency that makes this possible. Separately, nothing stops a hostile relay from writing whatever it likes in this field, including impersonating another operator's marker. Tags are claims made by whichever node submitted the transaction, and any agent using them should weigh them accordingly. Independent operators get their own key and their own marker, and their tags deliberately do not join with ours; sharing a key would mean each side could deanonymize the other's users.

### No upgrade, and no reason for one

This release changes no chain code at all. The field the tag travels in already existed, every validator already read it, and it was already covered by the relay's signature — so there is no new rule to agree on, no coordinated halt, and nothing that could cause two nodes to disagree about the state of the chain. A node that has not updated simply does not add tags, and one running an older index simply does not store them. That is why this ships as a point release rather than as a network upgrade: adding a halt height for a feature that touches nothing on the chain would have been ceremony at the cost of real downtime. The tag format, its guarantees and its limits are documented for agent authors, and the parser that reads these memos is tested against deliberately malformed ones, since by design anyone willing to pay a transaction fee can write into that field.
