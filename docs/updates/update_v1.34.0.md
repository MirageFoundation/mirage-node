# Mirage v1.34.0 Release Notes

### One node's bad disk can no longer split the chain

Mirage validators keep identical copies of the same state, and they stay identical because every node applies the same rules to the same data. The subtle way that breaks is not an attack — it is a storage read that fails on one machine. Until now a handful of those reads were treated as "nothing there": a follow count that could not be read looked like zero, an unreadable profile looked like a brand-new free account, a failed write was logged and forgotten. The node kept running and kept disagreeing with its peers, and the disagreement only surfaced later as a halt. This release removes that whole class of quiet divergence. Deterministic invalid data is rejected consistently, while a machine-specific storage or bank failure stops the affected validator before it can reject a transaction that healthy peers commit.

### Failing loudly is the feature

That trade is deliberate and worth stating plainly. A node that cannot read its own state now stops instead of guessing, so under a genuine storage fault you will see an error and a halted block rather than a validator that silently drifts. We think a loud failure you can diagnose in minutes beats a silent one that costs a day of forensics, and the recovery tooling already snapshots the diverged database before anything is wiped. Nothing about this changes normal operation: on healthy nodes the same transactions succeed exactly as before.

### Subscriptions that add up exactly

Part of every subscription payment is held back as a gas reserve and the remainder is burned. That split was computed in floating point, which meant the two halves could miss the total by a single unit — an invisible rounding difference that still has to come from somewhere. It is now computed in whole basis points and the reserve plus the burn always equals the fee paid, at every price and every reserve percentage. One-time subscriptions also expire properly now: when a plan is configured as a single purchase rather than a renewing one, reaching the end date burns any remaining reserve, returns the account to the free tier and announces the change, instead of leaving a paid badge on an account with nothing behind it.

### Governance can no longer set a parameter by accident

Chain parameters are changed by governance proposals, and proposals used to say "here are the parameters" and let the chain guess which of them the proposal actually meant to change. Anything left at zero was treated as "not specified", so a proposal that genuinely wanted to switch a limit off simply could not express that. Proposals now carry an explicit list of the fields they change. Setting a value to zero works because you named the field, while a proposal that names nothing, names an unsupported field, or leaves every selected value unchanged is rejected rather than applied as a no-op. Every proposal template in the repository has been updated to the new form.

### Parameters that cannot be voted into nonsense

Governance is trusted, but it is not infallible, and some parameters were unbounded in ways that would have made the chain do unbounded work or run arithmetic past the end of its number range. The proof-of-work window, the mint interval, the subscription period, profile-list limits, the accepted age of a signed request and the difficulty calm threshold now all have documented ceilings, and every conversion, multiplication, addition and expiry calculation that uses them is checked rather than allowed to wrap around. The upgrade itself verifies the values already stored on chain against the new ceilings and refuses to complete if any of them is out of range, so a bad parameter surfaces during the upgrade rather than during a block.

### Claiming rewards now always proves who you are

Claiming rewards has required a signature since v1.32.0, but a grace window kept serving claims whose proof was missing or did not verify, so that app builds shipped before the change kept working. That window was scheduled to close on 5 October; it closes now instead. Every reward claim must carry a signature that verifies for the address being claimed, and anything else is refused. Being direct about the cost: if you are running an older app build that signs the old way, claiming will fail until you update. We would rather ask you to update than keep an unauthenticated path open to the one endpoint that moves tokens.

### Tested where it matters, and coordinated

This release adds failure-injection tests that deliberately break storage reads and writes in the exact places this work touches, and proves each one now rejects instead of continuing, alongside new coverage for the message-routing registry, the recovery path for an account whose gas reserve ran out mid-flight, and the proof-of-work verification cost per message. Two guards were also added that fail the build rather than the chain: one requires every message carrying a signed envelope to have explicit signature and proof-of-work routing — proof-of-work is skipped only for subscribing and auto-renewal, which pay with tokens or reserve instead — and one requires every registered upgrade to be listed by name. Because consensus rules changed, this is a coordinated upgrade — all validators cross the same height on the v1.34.0 binary, and mixed versions will diverge.
