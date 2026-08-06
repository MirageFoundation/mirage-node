# Backend Trust Model

**Status:** Accepted
**Date:** 2026-08-05
**Related:** Backend security review 2026-08-05 (H-3, C-1)

## The rule

**The chain's ante handlers are the only enforcement boundary. Every check the
backend performs on a chain write is advisory.**

If you are adding a validation to a relay endpoint in `web/backend/routes/core.py`,
assume an attacker will skip it. The question to answer is not "does the backend
reject this?" but "does the chain reject this?" If the answer to the second
question is no, the validation you are adding is cosmetic.

## Why

`/chain/rest/*` and `/chain/rpc/*` are proxied to the public internet by
`deploy/templates/caddy/Caddyfile`, with only a per-IP rate limit in front. Any
client can construct a relay transaction and broadcast it directly to the chain,
never touching the backend. This is deliberate: a node operator cannot be the
gatekeeper of a decentralized network, and third-party clients need chain access.

Since v1.32.0 that bypass is no longer free — the attacker must sign the outer
transaction and fund their own gas — but it is still open, and the location of
enforcement is unchanged.

## What this means in practice

- **PoW prechecks are a UX fast-fail.** They exist so an honest client with a
  short proof gets a fast, cheap 400 instead of paying gas for a chain rejection.
  The chain's `PowDecorator` is what actually enforces difficulty. A precheck
  that throws must not reject the request: see `_log_pow_precheck_error` in
  `routes/core.py`, which logs `pow.precheck_error` and lets the request through.
  Alert on that tag — a sustained rate means the precheck is broken and every
  proof is reaching the chain unscreened.
- **Backend signature verification is not uniform, and that is recorded, not
  accidental.** 13 relay endpoints verify the envelope signature before relaying;
  16 do not. The chain's `RelaySigDecorator` verifies all of them. The split is an
  accepted inconsistency (H-3 item 2, accepted risk) rather than an oversight —
  do not read the presence of a check on one endpoint as a guarantee on another.
- **Never synthesize a value the user signed over.** Canonical bytes are the
  contract between client and chain. If the client omits `timestamp`, forward 0
  and log it (`_client_timestamp`); substituting `now` produces an envelope whose
  signature cannot verify, which is a bug that only appears once verification is
  switched on.
- **`authority` is always the validator or governance address**, never a value
  from the request. The acting user is derived from `envelope_pubkey`.

## What would change this

Withholding `broadcast_tx` at the edge would make the backend a real boundary and
give every check above enforcement value. That was considered and declined: it
would break third-party clients and contradict the public-chain design. If it is
ever revisited, this document and the advisory framing of every precheck must be
revisited with it.

## History

C-1 (unauthorized fee deduction from any account) survived review partly because
this model was undocumented. A reader tracing `authority` and `fee.payer` through
`web/backend/tx.py` reasonably assumed the outer transaction was signed, because
the surrounding code looked like an enforcement boundary. It was not. Write the
model down so the next reader does not have to infer it.
