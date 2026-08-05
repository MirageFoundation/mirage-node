# Mirage v1.32.0 Release Notes

### Gas payer proof

Every free-user action on Mirage is relayed by a validator that pays the gas. That was always the design — proof-of-work for the user, gas for the node — and it is how spam stays expensive for anyone who spins up their own node. What was missing was a simple proof: the account named as the gas payer never had to show it agreed. A crafted transaction could name someone else's account, leave a placeholder where the outer signature belongs, and the chain would still take the gas from that account. In the worst case that drained a balance in a single shot; in the everyday case it let a spammer push traffic while someone else paid.

### What changed

Relay transactions now require a real outer signature from the gas payer, using unordered transactions so validators still never have to track sequence numbers. The gas payment itself is unchanged: the validator still pays for free users, paid users still burn from reserve, and a hostile node still pays its own gas per message. The only difference is that naming an account as the payer now means holding that account's key. An upper bound on the gas payment closes the drain path even if something else goes wrong later.

### Honest limits

This is a consensus-breaking upgrade. Every validator must cross the same height on the same binary; mixed versions will diverge. Public chain RPC and REST endpoints remain reachable, so an attacker can still talk to the chain directly — they just cannot make someone else pay for it anymore. Closing that broadcast surface is separate hardening, not part of this release.
