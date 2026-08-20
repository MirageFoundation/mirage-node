# Mirage v1.38.10 Release Notes

### The network page shows the whole network again

Open the network page and you now see every node that is actually running. Until
this release it showed two, while four were carrying the chain. The other two
were there the whole time — signing blocks, staying in sync, doing the work — and
the page simply refused to name them.

### Why half the network was invisible

The list is built from the validator set, which is the chain's own answer to who
is running right now, and each node is found by the address in its name. That
part was right. The mistake was insisting every address be an `https://` one. Two
of the four nodes have no domain, and nobody can issue a certificate for a bare
IP address, so those nodes serve plain `http` — which made them unlistable, even
though anyone could open them in a browser. Being reachable and being reachable
over TLS are not the same question, and the page was asking the wrong one.

### Listed is not the same as trusted

There was a reason for the original rule, and it still holds: when an operator
opens the private stats dashboard, their signed credential is forwarded to the
other nodes to collect numbers from each. That is a credential leaving this
machine, so it may only go somewhere whose certificate proves it is the host it
claims to be — which rules out plain `http` and rules out a bare address, since a
certificate cannot vouch for one. So the two questions are now answered
separately. The page lists every node you can reach; the dashboard still only
talks to the ones it can authenticate. Widening the first can no longer widen the
second, and the tests now assert that the trusted set stays a strict subset.

### A silent failure, three months long

The two invisible nodes were named `mirage-node-3` and `mirage-node-4` — labels,
not addresses, so there was nowhere to send a visitor even after the rule was
relaxed. Deploys were supposed to keep those names pointed at each node's real
address, and every attempt for months had been rejected by the chain for paying
no transaction fee. The failure was discarded and the deploy reported success. It
now takes its fee from the node's own configuration, treats a rejection as fatal,
and confirms against the chain that the name actually changed before calling it
done. A rename that quietly failed used to be indistinguishable from one that was
never needed; it isn't any more.

### One node still won't appear, and that's not a bug

A third-party validator called `EuroServer` remains unlisted, because its
operator has not published an address anyone can visit. Nothing here invents one.
On a chain anyone can join, the honest answer to "where is this node" is whatever
its operator chose to publish, and if that is a nickname then it stays a nickname.
Any operator wanting to appear can set their moniker to the address they serve —
a domain, or `http://` and their IP if they have no domain — and the page will
pick it up on its own within the minute.
