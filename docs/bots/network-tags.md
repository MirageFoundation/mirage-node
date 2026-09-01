# Network tags

Every relayed transaction can carry a pseudonymous tag for the network it came
from, published in the transaction memo. Two transactions with the same tag came
from the same network in the same week. No IP address is disclosed, and nobody
without the relay's secret can work out which network a tag refers to.

This exists so that anyone can build a vote-farm detector. Collusion has an
obvious signature — many accounts, one network, lockstep voting — but until now
that signature was only visible to whoever ran the frontend and could read the
access logs. The tag puts it on chain, where anyone can see it.

## Reading a tag

The memo is JSON, namespaced under `nettag` so other things can share the field:

```json
{"nettag":{"v":1,"n":"4Ylxthnthic","e":"2026-W34","f":4,"t":"laUZK8YgCAQTRm8rYQolSw","c":"isp"}}
```

| Field | Meaning |
| --- | --- |
| `v` | Format version. Currently `1`. Ignore a memo whose version you do not know. |
| `n` | Namespace: which trust domain produced this tag. 8 bytes, unpadded base64url. |
| `e` | Epoch, as ISO year and ISO week (`YYYY-Www`). |
| `f` | Address family: `4` or `6`. |
| `t` | The tag itself. 16 bytes, unpadded base64url. |
| `c` | Network class. Optional — see below. |

Two tags are comparable only when `n`, `e` and `f` all match. A tag says
nothing about a different week, a different family, or a different trust domain.

If you would rather query than parse, a node's indexer projects all of this into
a `net_tags` table keyed by transaction hash, which joins to `posts.txhash` and
`votes.txhash`.

## Network class

`c` is a coarse classification of the network, and it changes how much a cluster
means:

- `hosting` — a datacenter or cloud provider. Ordinary users do not post from
  these, so a cluster here is the strongest signal available.
- `vpn` — a commercial VPN or proxy exit.
- `cellular` — a mobile carrier. Carrier-grade NAT puts large numbers of
  unrelated subscribers behind one address, so a cluster here is weak evidence.
- `isp` — none of the above matched. A weak negative signal, not a clean bill of
  health: it cannot detect residential proxies at all.
- `unknown` — the relay had classification data and this address was not in it.

**`c` absent is not the same as `c: "unknown"`.** Absent means the relay had no
dataset at all and is declining to guess. `unknown` means it looked and found
nothing. Treating them as the same will make you read confident silence as an
answer.

## What the tag is not

**It is not an identity.** It identifies a network for one week. Everyone behind
one home router shares a tag; so does everyone behind one CGNAT block, which can
be thousands of unrelated people on a mobile carrier. Use `c` before you draw a
conclusion from a cluster.

**It is not authenticated.** Any relayer that pays a fee can write anything in a
memo, including copying a namespace that is not theirs. Every tag is a *claim by
the relayer that submitted it*. Scope your analysis to relayers you have reason
to trust — the `relayer` column, or the `authority` field on the message, tells
you which one it was. A namespace match is not proof of trust-domain membership.

**It does not survive the week.** The epoch is an input to the tag, so the same
network gets an unrelated tag next week. You cannot follow a network through
time, by design. Farms operate in hours, so this costs detection almost nothing.

**Absence means nothing.** A transaction with no memo may come from a relay that
has not deployed tags, or from a direct RPC submission. It is not a signal.

## How a tag is produced

```
tag = HMAC-SHA256(SECRET, domain || iso_year || iso_week || family || ip)[:16]
```

For IPv4 the full address is used. For IPv6 only the `/64` prefix is, because
that is the per-subscriber allocation and it is unaffected by RFC 4941 privacy
addressing, which rotates the interface identifier and leaves the prefix alone.

A keyed MAC rather than a salted hash because IPv4 has only 2^32 addresses: any
function of an address that the public can evaluate is invertible by brute force
in minutes, so a published salt would be equivalent to publishing the address
itself. Without the key the tag cannot be evaluated at all.

The secret belongs to a trust domain. Whoever holds it can compute the tag for
every address on the internet, so it is shared only as far as the parties that
already handle raw client IPs. Officially operated frontends share one value, so
a user gets the same tag whichever door they come through. An independent
operator's node generates its own and is its own namespace.

There is one deanonymization path the design does not close, and it is worth
stating plainly: anyone can post once from a network they control, read their
own transaction's tag off the chain, and then find every account that carried
that tag. That reveals accounts sharing a network the attacker can already reach
— it does not reveal any address — and the weekly epoch bounds it to the current
week. Consistency within an epoch is exactly the property that makes tags useful
for detection, so this cannot be removed without removing the feature.

## Running your own relay

Your node generates its own key on deploy and publishes its own namespace. Your
tags will not join with anyone else's, which is correct: you have made no trust
arrangement with them. Never accept a secret from another operator, and never
send yours — a shared key lets each side deanonymize the other's users.
