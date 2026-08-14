# Indexer Security Review — 2026-08-14

**Scope:** `indexer/` in full — `main.py`, `message_processor.py`, `database.py`, `chain_client.py`, `params.py`, `settings.py`, `address_utils.py` and all 14 migration modules (6,730 lines). The trust boundaries around it were read where a claim depended on them: the chain-side authorization for every relayed message type, `deploy/run_indexer_supervised.sh`, `deploy/templates/env/indexer.env`, and the backend's own handling of the fields it reads back out of `mirage_indexer`.
**Baseline:** `dev` at the `v1.35.0` tag (`922867c6`). Working tree clean under `indexer/`.
**Reporting bar:** all severities. This is a full review, not a Critical/High sweep.
**Method:** four parallel component audits plus an independent read by the reviewer, with every surviving candidate re-verified against source and, where it was cheap, executed. Three findings below were confirmed by running the actual code path rather than by reading it. A candidate that could not be traced end to end was dropped, and one candidate reported as High by a component audit was **disproven** and is recorded as such under H-1 rather than quietly omitted — the two audits disagreed about whether event attributes are base64, the question decides which of two files is the bug, and it was settled against the dependency's generated source.

**Prior state:** the [2026-08-07 indexer review](../2026-08-07/indexer-review.md) and its [retest](../2026-08-07/indexer-retest.md) closed 18 of 20 findings; the [2026-08-13 cross-component sweep](../2026-08-13/cross-component-review.md) fixed C-1 (permanent wedge via account self-delete) and the related unknown-message-type halt. **Per instruction, items already recorded as accepted decisions in [`open-items.md`](../open-items.md) are not re-reported here** — M-1 (pruned-history gaps), M-4 (no historical telemetry backfill), I-1 (owner derivation from unsigned content), I-4 (supervisor restart budget), L-4 (unrecorded content-derivation skips), the deliberate skip-don't-halt contract for unknown message types, absent profiles and missing vote/edit targets, and the deferred `--height` rebuild tooling. Those IDs are the 2026-08-07 review's; this document numbers its own findings from scratch, so where an older item is referenced below it is named with its date. Every previously fixed finding was re-checked for regression; none has regressed.

---

## Summary

**2 High, 3 Medium, 4 Low, 1 Informational. Nothing Critical.**

**Disposition, decided 2026-08-14 (same day):** nine of the ten were fixed on `dev` and are **unreleased**; **M-1 was accepted as risk** and will not be re-reported by future reviews. The Status column records each decision, and "Remediation" at the end of the document describes what shipped.

| ID | Finding | Severity | Status |
| :-- | :-- | :-- | :-- |
| **H-1** | Governance event attributes are base64-decoded on a guess; 11.6% of four-digit proposal IDs decode to garbage and permanently wedge the indexer | **High** | Fixed |
| **H-2** | Any admin level other than exactly `100` — which the chain explicitly permits — makes every post and vote by that account raise, permanently wedging the indexer | **High** | Fixed |
| **M-1** | Historical blocks are projected against present-day chain state, so moderation authority, vote weight and profile lists depend on when the replay runs | **Medium** | **Accepted as risk** |
| **M-2** | Startup reconciliation will soft-delete every profile and destroy the retained blocked-list history if the chain returns an empty profile inventory | **Medium** | Fixed |
| **M-3** | Deleting a post never retracts the topic standing it granted, so post-and-delete cycling buys downvote weight in a topic while leaving no visible content | **Medium** | Fixed |
| **L-1** | A swallowed exception inside the block transaction cannot do what its comment claims and buries the real error | **Low** | Fixed |
| **L-2** | Governance projects only a subset of the message types the indexer can handle, and drops the remainder silently | **Low** | Fixed |
| **L-3** | The per-block `chain_id` is written into the checkpoint without ever being compared to the node's own | **Low** | Fixed |
| **L-4** | Profile reads go over gRPC *inside* the block transaction, which the balance prefetch three lines earlier exists specifically to avoid | **Low** | Partially fixed |
| **I-1** | `unblock_topics_matching` treats a stored `%` as a wildcard where its sibling escapes it | **Informational** | Fixed |

**A fifth High candidate was reported and rejected.** One component audit filed the subscription `EndBlock` handler as High for reading event attributes *without* base64-decoding them. That is the exact opposite of H-1, and both could not be true. It was settled against CometBFT's generated source rather than by preferring one audit: `EventAttribute.Key/.Value` are Go `string`, so the attributes are plain text, the handler was right and the decoder was wrong. The full reasoning is under H-1, because which of the two files is the bug depends entirely on that answer.

Both High findings are the **same class as C-1**, the Critical fixed on 2026-08-13: a value that arrives with the block makes a required code path raise, the block rolls back, the checkpoint never advances, and every restart re-fails at the same height on every node — so the platform stops and the affected block becomes permanently unprojectable, defeating a rebuild as well. C-1 was the profile-absent instance of it. These are two more instances that the C-1 fix does not cover, in code C-1 never touched.

Neither is triggered by an ordinary user's transaction, which is the only reason they are High rather than Critical. **H-1 needs no attacker at all** — it arms itself as the global governance proposal counter advances, and the affected ranges begin at proposal 1400. H-2 needs one governance `MsgSetLevel` setting a level the chain documents as valid.

**M-3 is the only finding an ordinary user can trigger today**, and it is the one worth reading if you read only one Medium: two cheap transactions, repeated, buy real moderation influence and leave nothing behind to look at.

The rest of the indexer held up well under an audit that was specifically looking for the C-1 pattern. The atomic block transaction, the continuity verification, the fail-hard chain queries and the migration machinery are all intact, and the authorization boundary is genuinely tighter than it first reads — see "Checked and adequately guarded", which records the attacks that failed, because a clean result only means something if the attempts are visible.

---

## H-1 (High) — Permanent wedge: governance event attributes are base64-decoded on a guess

**Status: fixed 2026-08-14** (on `dev`, unreleased) — see Remediation.

**Component:** `indexer/message_processor.py`. **Privilege required:** none — this arms itself over time. **Effect:** indexing stops chain-wide, permanently, and the affected block becomes un-indexable.

### The bug

`decode_events` treats every event attribute key and value as *possibly* base64 and decodes it if it parses:

```2123:2131:indexer/message_processor.py
                        if val_b64:
                            try:
                                val = base64.b64decode(val_b64, validate=True).decode("utf-8")
                            except Exception:
                                if isinstance(val_b64, bytes):
                                    val = val_b64.decode("utf-8")
                                else:
                                    val = str(val_b64)
                            attrs[key] = val
```

**The attributes are not base64.** This is the load-bearing claim, and the proof is in the deployed dependency's own generated type — `Key` and `Value` are Go `string`, not `[]byte`:

```go
// cometbft@v0.39.3/abci/types/types.pb.go:3223
type EventAttribute struct {
	Key   string `protobuf:"bytes,1,opt,name=key,proto3" json:"key,omitempty"`
	Value string `protobuf:"bytes,2,opt,name=value,proto3" json:"value,omitempty"`
	Index bool   `protobuf:"varint,3,opt,name=index,proto3" json:"index,omitempty"`
}
```

JSON marshalling base64-encodes `[]byte` and never `string`, so `/block_results` on `v0.39.3` (`blockchain/go.mod:36`) returns plain text. Two independent corroborations: `_process_subscription_events` reads the same `result_obj` with no decoding at all and raises if the value is missing (`indexer/main.py:398-401`), which would fail on every subscription event if attributes were encoded; and `scripts/submit_proposal.py:1105-1107` matches `attr.get("key") == "proposal_id"` with no decoding in the working proposal-submission path.

This deserves emphasis because **one of the parallel audits concluded the exact opposite** — that attributes *are* base64 and that `_process_subscription_events` is therefore the bug. Had that been right, the correct fix would have been to add decoding there rather than remove it here, so the two claims could not both be filed. The struct above settles it: the guess in `decode_events` is wrong and the plain read in `main.py` is right.

So the decode is not a compatibility shim that lies dormant — it is a guess applied to plain text, and it succeeds on any value that happens to be well-formed base64 whose bytes happen to be valid UTF-8.

**Three consumers of the same `result_obj` disagree about this**, which is the underlying defect: `_process_subscription_events` never decodes (correct), `decode_events` decodes with `validate=True` (H-1), and `_collect_touched_addresses` decodes with a bare `except: pass` (`main.py:479-486`). The third is **safe only by luck**: I tested every key and value it inspects and all of them fail to decode, so the raw value survives. `'receiver'` is the near miss — it is valid base64 by length and fails only on the UTF-8 step. The fix should normalise all three sites, not just the one that is currently fatal.

### Why that is fatal rather than cosmetic

The value it corrupts is a proposal ID, and the very next thing that touches it is an `int()`:

```2092:2097:indexer/message_processor.py
    def extract_proposal_id(attrs: dict) -> int | None:
        """Extract proposal_id from event attributes with multiple fallback names."""
        pid = attrs.get("proposal_id") or attrs.get("proposalID") or attrs.get("proposal-id") or attrs.get("proposalId")
        if pid is None:
            return None
        return int(pid)
```

Every link from there is unguarded:

1. `extract_passed_proposals` calls it for every decoded event (`message_processor.py:2142`) and does not catch.
2. `_process_governance_events` calls that at `indexer/main.py:429`, inside the block transaction opened at `indexer/main.py:321`.
3. `_process_block` wraps only per-transaction errors (`main.py:325-326`); the governance call sits outside that `try`, so the `ValueError` propagates and rolls the block back — `set_checkpoint` on line 336 never runs.
4. The catch-up loop has `try`/`finally` with **no** `except` (`main.py:766-782`), so the exception escapes `start()` and kills the process. The live path calls `sys.exit(1)` (`main.py:810-818`).
5. Restart resumes at the same height and fails identically. The supervisor burns its twelve restarts in about a minute and exits (`deploy/run_indexer_supervised.sh:69-73`).

The block is then permanently unprojectable — a fresh index build and a restore from an older `pg_dump` both die at the same height, which is exactly what made C-1 Critical.

### It is a time bomb, not an exploit

I ran the real decode against every plain proposal ID from 1 to 19,999. **1,040 of them are corrupted.** All one-, two- and three-digit IDs are safe (those lengths are not valid base64), so the first affected ID is **1400**, and from there the affected four-digit IDs fall in contiguous runs:

```
1400-1419, 1440-1459, 1480-1519, 1540-1559, 1580-1619, 1640-1659, 1680-1719,
1740-1759, 1780-1799,  and the same shape repeated through 2400-2799, 3400-3799,
4420-4769, 5420-5769, 6420-6769, 7420-7769  — 1,040 of 9,000 four-digit IDs (11.6%)
```

Proposal `1401` decodes to `'\u05cd5'`, and `int('\u05cd5')` raises `ValueError: invalid literal for int() with base 10`.

Any proposal whose ID lands in one of those runs wedges every indexer on the network when its voting period ends and the EndBlocker emits the status-change event — regardless of whether it passed, and regardless of who submitted it. Nobody has to attack anything; the counter simply has to reach 1400. An attacker who wanted to bring it forward could submit proposals to advance the counter, but that is the expensive way to cause something that is coming anyway.

### Fix

Stop guessing. The attributes are plain strings on the deployed CometBFT major version, and the file already has a function that treats them that way. The correct change is to remove the base64 attempt from `decode_events` so it matches `_process_subscription_events`. If byte-string tolerance must be kept for an older node, decode only when the attribute actually arrives as `bytes`, never as a shape test on a `str`.

Independently, `extract_proposal_id` should not hand an arbitrary string to a bare `int()` inside the block transaction — a non-numeric proposal ID is malformed input from the node, and the block-level failure it causes is out of all proportion to it.

---

## H-2 (High) — Permanent wedge: the indexer only understands admin level `100` exactly, but the chain accepts any level ≥ 100

**Status: fixed 2026-08-14** (on `dev`, unreleased) — see Remediation.

**Component:** `indexer/params.py`, reached from two handlers. **Privilege required:** one governance `MsgSetLevel`. **Effect:** the same permanent chain-wide wedge as H-1.

### The mismatch

The chain treats admin as a **range**. `LevelToTierIndex` maps anything at or above `LevelAdminMin` to the agent tier:

```70:83:blockchain/x/core/types/params.go
func LevelToTierIndex(level int) int {
	switch {
	case level == LevelFree:
		return 0
	case level == LevelSubscriber:
		return 1
	case level == LevelAgent:
		return 2
	case level >= LevelAdminMin:
		return 2 // admins get agent-tier capabilities
	default:
		return -1
	}
}
```

`SetLevel` validates against exactly that (`blockchain/x/core/module/module.go:3337-3340`) and its own error message tells the operator the accepted set: `"invalid level %d: must be 0, 1, 10, or >= 100"`. So `101`, `150` and `9999` are all valid on chain and are written to the profile.

The indexer builds a **point lookup** instead, with one hand-added key for `100`:

```95:98:indexer/params.py
    _idx_to_level = {0: 0, 1: 1, 2: 10}
    vote_weights = {_idx_to_level.get(i, i): float(t.get("vote_weight", 1.0)) for i, t in enumerate(tiers)}
    vote_weights[100] = vote_weights[10]  # admin = agent-tier weight
    result["vote_weights"] = vote_weights
```

and then raises on anything else:

```188:193:indexer/params.py
def get_vote_weight(level: int) -> float:
    """Get vote weight for tier level. Cached at startup."""
    weights = expect_params()["vote_weights"]
    if level not in weights:
        raise ValueError(f"Unknown tier level: {level}")
    return weights[level]
```

Reproduced against the chain's own `DefaultTiers`: levels `0`, `1`, `10` and `100` resolve; `101`, `110`, `150` and `999` all raise `ValueError: Unknown tier level: N`.

**The backend gets this right**, which is what makes it a defect rather than a design choice — `web/backend/routes/core.py:1806` and `:3936` both use `{0: 0, 1: 1, 10: 2}.get(level, 2 if level >= 100 else -1)`. Two components read the same column and only one handles the range.

### Exploit path

1. Governance passes `MsgSetLevel{target: victim_or_self, level: 101}`. Valid on chain; the profile is written.
2. The indexer projects it with no validation of its own — `_handle_set_level` writes the level straight through (`indexer/message_processor.py:1730`).
3. That account makes **one ordinary post**. `_handle_post` looks up the tier weight for the auto-upvote, outside any `try`:

```358:362:indexer/message_processor.py
            community_weight = 1.0
            if WEIGHTED_VOTES:
                profile = self.db.get_profile(owner)
                level = profile[1] if profile else 0
                community_weight = get_vote_weight(level)
```

4. `ValueError` propagates through `process_core_message` and `_process_tx` into `_process_block`, which converts it to a block-level abort (`main.py:325-326`), and from there the H-1 chain applies verbatim: rollback, no checkpoint, restart re-fails, block permanently unprojectable.

A vote does the same thing through `_handle_vote` (`message_processor.py:620-625`), whose `except` re-raises (`:708-710`).

Note the shape: the account that wedges the network is an **admin**, and the transaction that does it is a normal post. The failure looks nothing like its cause.

### Fix

Make `get_vote_weight` mirror the chain's mapping and the backend's: resolve `level >= 100` to the agent-tier weight rather than looking for an exact key. `vote_weights[100] = vote_weights[10]` is the existing acknowledgement that admins take agent weight; it just needs to cover the range the chain actually accepts.

While there: `vote_weights[100] = vote_weights[10]` raises `KeyError` at param load if governance ever ships fewer than three tiers. That fails at startup rather than mid-block, so it is a much softer failure, but it is the same assumption.

---

## M-1 (Medium) — Historical blocks are projected against present-day chain state

**Status: ACCEPTED AS RISK 2026-08-14.** No fix intended; recorded in [`open-items.md`](../open-items.md). Future reviews should not re-report this. The analysis below stands as the record of what was accepted.

**Component:** `indexer/message_processor.py` + `indexer/main.py`. **Effect:** moderation actions and vote weights are decided by the level an account holds *when the replay runs*, not when the block was committed.

Startup reconciles every profile to **current** chain state before any historical block is replayed — `_sync_profiles_from_chain` (`main.py:887`, writing at `:1030`) runs before `_catch_up` (`main.py:891`). Three decisions then read that table while projecting old blocks:

| Decision | Site | Reads |
| :-- | :-- | :-- |
| Post delete authorization (`is_admin`) | `message_processor.py:1627-1628` | `get_user_level(owner)` — `database.py:2325-2331`, current `profiles.level` |
| Agent annotation authorization | `message_processor.py:963-966` | same |
| Vote weight ceiling (`tier_max`) | `message_processor.py:623-625`, and `:360-362` for the post auto-upvote | `get_profile(owner)` — current `profiles.level` |

`_handle_delete` is the one with teeth, because admin level is what separates "delete your own post" from "delete anybody's":

```1644:1646:indexer/message_processor.py
            elif is_admin:
                # Admin (level >= 100) can delete any post
                rows_affected = self.db.delete_post(target, None)
```

Three consequences, in decreasing order of how much they should worry you:

1. **Moderation silently reverses on rebuild.** An admin deletes abusive content at height H. The admin is later demoted, or their subscription-derived level changes. Any rebuild or restore that replays H now sees level `0`, takes the regular-user branch, and calls `delete_post(target, owner)` — which matches nothing, because the post is not theirs. **The deleted content comes back**, with no error and no log beyond a "not found or not owned by" warning.
2. **A delete can be pre-planted.** The chain accepts `MsgDelete` from anyone against any target and only charges gas; that is the documented boundary (`message_processor.py:1596-1604`). A user at level 0 can therefore write `MsgDelete` transactions against other people's posts today, have them correctly rejected by every indexer today, and have them **take effect on the next reindex** if they ever reach level ≥ 100. The transactions are already on chain and cannot be withdrawn.
3. **Vote weights are not reproducible.** A user who was free-tier at height H is credited at their present tier's `tier_max` on any rebuild, so `votes.user_weight` — and the community ranking built on it — differs between a live index and a rebuilt one. This is the same class the `v1_33_0_rebuild_derived_stats` and `v1_34_0_repair_topic_attribution` migrations exist to repair, one level up: those made the aggregates recomputable from the canonical rows, but the canonical `user_weight` itself is not reproducible.

This is not covered by the accepted 2026-08-07 I-1 boundary. That item accepts that *the indexer* enforces authorization the chain does not; it does not accept that the enforcement gives different answers on different runs over the same blocks.

**The same root cause has two further expressions**, both benign next to the delete path but worth fixing together because one change addresses all of them. The profile-list handlers do not apply the message's delta — they discard the stored list and refetch the account's **current** list over gRPC (`_refresh_followed_users` at `message_processor.py:1260-1263`, and the same shape at `:1163`, `:1236`, `:1284`, `:1773`), with no height pinning available on `query_profile_full` (`chain_client.py:194-201`). Replaying an old follow therefore writes today's follow list. And chain params are loaded once at startup from the head and only reloaded when a `MsgUpdateParams` appears in the replay stream (`params.py:109-137`, `main.py:458-461`), so a rebuild spanning a governance tier-weight change applies the new weights to blocks that predate it. Both converge once catch-up reaches the head, which is why they are not findings of their own; the delete path is the one that does not converge, because its output is a destructive write.

**Fix.** Decide authority from state as of the block, not as of now. The cheapest correct version is to persist the acting level alongside the projection at the time it is first indexed and reuse it on replay, so a rebuild reproduces the original decision. Pinning the profile query to the block height would be more principled but needs an at-height chain query the indexer does not currently make. At minimum, the delete path should record which level it used, so a rebuild that reaches a different verdict is detectable rather than silent.

---

## M-2 (Medium) — An empty profile inventory soft-deletes every user and destroys the blocked-list history

**Status: fixed 2026-08-14** (on `dev`, unreleased) — see Remediation.

**Component:** `indexer/main.py`. **Effect:** total, irreversible loss of the one dataset the indexer is the sole custodian of.

`_sync_profiles_from_chain` treats the chain's profile list as an authoritative inventory and deletes anything not in it:

```1055:1078:indexer/main.py
    def _soft_delete_absent_owners(self, chain_owners: set[str], now: int) -> int:
        """Soft-delete profiles the chain no longer has and drop their list rows."""
        with self.db._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT owner FROM profiles WHERE deleted_at IS NULL")
                db_owners = [str(r[0]) for r in cur.fetchall()]

        absent = [o for o in db_owners if o.strip().lower() not in chain_owners]
        if not absent:
            return 0

        for owner in absent:
            self.db.soft_delete_profile(owner, now)
            with self.db._connect() as conn:
                with conn.cursor() as cur:
                    for table in (
                        "enabled_agents",
                        "followed_users",
                        "followed_topics",
                        "blocked_users",
                        "blocked_posts",
                        "blocked_topics",
                    ):
                        cur.execute(f"DELETE FROM {table} WHERE LOWER(owner) = LOWER(%s)", (owner,))
```

`chain_owners` is built from whatever `list_profiles_paginated` returns (`main.py:1001-1012`). That function raises on a gRPC error (`chain_client.py:274-275`) and on a 120-second deadline (`:263-267`), but **an empty result is not an error**: a first page with zero profiles and an empty `next_key` breaks the loop at `chain_client.py:298-299` and returns `[]`. `chain_owners` is then the empty set, every profile is "absent", and the loop above runs over all of them.

**Why this is worse than it looks.** The soft-delete is recoverable — the next successful sync would not undelete the rows, but the profile data itself still exists on chain. The `DELETE FROM blocked_users / blocked_posts / blocked_topics` is not. The chain keeps only a small deque per user; the indexer deliberately retains up to `INDEXER_LIST_CAP = 100_000` entries (`database.py:16`) precisely because that history *cannot be reconstructed from chain state*. That retention is the stated justification for accepting the 2026-08-07 M-1 (pruned blocked history) in the first place — the retest argues against failing hard on pruned history because the workaround "would be worked around by wiping — losing the very blocked-list history the finding exists to protect." This code path wipes it directly, at startup, with no guard.

**Honest reachability.** I could not construct a trigger from source, and I am filing this on impact and the absence of any guard rather than on a demonstrated path. Continuity verification runs first and catches the obvious candidates: a wrong-network node fails on `chain_id` (`main.py:623-627`), a rolled-back node fails on `stored_height > current_height` (`main.py:630-634`), and a node with no comparable history is refused outright (`main.py:637-643`). What would be needed is a node that passes all of that and still serves an empty `GetProfiles`. That is a narrow window, and it may well be empty. But every other bulk operation in this file is guarded — `_process_block` checks block/result cardinality twice, `get_block_results_matching` refuses to proceed on a count mismatch, `list_profiles_paginated` rejects a profile with an empty owner — and this one, which is the most destructive of them, is not.

**Fix.** Two lines. Refuse to reconcile deletions against an empty inventory, and bound the blast radius: if a single sync would soft-delete more than a small fraction of known profiles, fail startup and make the operator look. Deleting the blocked-list rows at all deserves a second thought — the profile row is preserved "for historical post attribution" (`message_processor.py:1685`), and the same argument applies to the block history.

---

## M-3 (Medium) — Deleting a post never retracts the topic standing it granted

**Status: fixed 2026-08-14** (on `dev`, unreleased). Scoped to the author's own votes — see Remediation for why.

**Component:** `indexer/message_processor.py`, `indexer/database.py`. **Privilege required:** none — any user, on their own posts. **Effect:** cheap, invisible accumulation of downvote weight in a chosen topic.

This is the only finding in this review that an ordinary user can trigger with ordinary transactions today.

### The mechanism

Indexing a new root post credits its author with topic standing, and the write is a required projection — the comment says so:

```319:330:indexer/message_processor.py
        # Update user topic stats for new posts (not edits). Required projection: any
        # failure must abort the block rather than leave post_count silently short.
        # Auto-upvote also contributes +1 to net_votes so rebuild and live paths agree.
        if not existing and owner and root_topic:
            self.db.update_user_topic_stats(
                owner,
                root_topic,
                net_votes_delta=1,
                root_post_id=root_post_id,
                is_new_vote=True,
                post_increment=1,
            )
```

The post also gets an auto-upvote row in `votes` (`message_processor.py:355-363`). `delete_post` then soft-deletes the post row and its descendants and fixes ancestor comment counts (`database.py:2226-2283`) — but it **never touches `user_topic_stats`, and never removes the auto-upvote**. Nothing else does either. So each post-then-delete cycle leaves the standing behind permanently.

### Why the standing is worth stealing

`user_topic_stats` is exactly what gates downvote power. With `COMMUNITY_VOTE_BASELINE = 0.0`, an outsider's downvote is worth nothing, and full weight is reached only when four factors saturate (`message_processor.py:646-666`):

| Factor | Threshold (`indexer/settings.py`) | Inflated by a post/delete cycle? |
| :-- | :-- | :-- |
| `posts_factor` = `post_count / 3` | `COMMUNITY_VOTE_MAX_POSTS = 3` | **Yes** — `+1` per post, never decremented |
| `topic_factor` = `vote_count / 10` | `COMMUNITY_VOTE_MAX_TOPIC_VOTES = 10` | **Yes** — the auto-upvote counts |
| `root_factor` = `unique_root_posts / 3` | `COMMUNITY_VOTE_MIN_ROOT_POSTS = 3` | **Yes** — each cycle is a new root post |
| `age_factor` = `age_days / 7` | `COMMUNITY_VOTE_MATURITY_DAYS = 7` | No — real elapsed time |

Note that `COMMUNITY_VOTE_MIN_NET_VOTES` is **`-10`**, not a positive bar: the `net_votes` check is a floor that excludes heavily-downvoted accounts, and a new account already passes it. So `net_votes` is not the gate — the three activity counters are, and all three are inflatable.

**Exploit:** pick a topic, post and immediately delete, ten times. That saturates all three activity factors. After the account is seven days old, its downvotes in that topic carry full tier weight, and the topic shows **no posts from the account at all** — every one was deleted. The legitimate route to the same weight requires ten votes on other people's posts and three root posts that stay up and can be replied to, argued with, or downvoted in return. The attacker pays two PoW-priced transactions per cycle and leaves nothing to rebut.

### The code's own canonical definition says this is wrong

`_POST_STATS_FROM_CANONICAL` — the definition used by the rebuild migration and by live re-attribution, which the file states "must agree" (`database.py:1630-1632`) — **excludes deleted posts**:

```1661:1665:indexer/database.py
        FROM posts p
        WHERE LOWER(p.owner) = ANY(%s)
          AND LOWER(COALESCE(NULLIF(p.root_topic, ''), p.topic)) = ANY(%s)
          AND COALESCE(p.deleted, FALSE) = FALSE
        GROUP BY 1, 2
```

So the intended `post_count` does not count deleted posts, while the live path counts them forever. That is both the bug and a live-versus-rebuild divergence: a rebuild resets `post_count` to the honest value, so the two paths disagree — the same class of drift the v1.34.0 topic-attribution repair existed to fix.

The vote-derived counters are worse in a different way. `_VOTE_STATS_FROM_CANONICAL` (`database.py:1633-1652`) joins `votes` to `posts` with **no** `deleted` filter, so `vote_count`, `unique_root_posts` and `net_votes` count votes on deleted posts in the rebuild too. A full reindex therefore **reproduces** that part of the inflation rather than correcting it.

### Fix

Make deletion symmetric with creation. The cheapest correct version is to recompute `(owner, root_topic)` from the canonical tables after a successful `delete_post`, reusing the `reattribute_topic_stats` pattern (`database.py:1670-1733`) that already does exactly this for topic edits — it is the established idiom in this file and needs no schema change. That also forces the prior question, which is a product decision rather than a security one: whether a deleted post's auto-upvote should still count toward standing. Whichever way that lands, the live path and the canonical SQL have to agree on it.

---

## L-1 (Low) — A swallowed exception inside the block transaction cannot do what its comment claims

**Status: fixed 2026-08-14** (on `dev`, unreleased) — see Remediation.

```857:865:indexer/database.py
                        try:
                            cur.execute(
                                "UPDATE posts SET root_topic = %s, root_post_id = %s WHERE LOWER(txhash) = LOWER(%s)",
                                (final_topic, final_root_id, current_id),
                            )
                        except Exception:
                            # Best-effort backfill; do not fail caller if this update fails.
                            pass
                        return final_topic, final_root_id
```

`get_root_topic_for_post` runs inside the block transaction (`_connect()` joins the active connection — `database.py:55-66`). In PostgreSQL a statement that errors inside a transaction puts the whole transaction into an aborted state, and every subsequent statement fails with `InFailedSqlTransaction` until rollback. So swallowing this exception does not keep the caller alive; it just means the block dies a few statements later with an error that names the wrong statement.

The comment describes behaviour the database will not provide. Either wrap the backfill in a `SAVEPOINT`, which makes the "best-effort" claim true, or drop the `try` and let the real error surface at its own site. Given that the backfill is a legacy-data convenience, the savepoint is the better of the two.

---

## L-2 (Low) — Governance projects only a subset of the message types the indexer can handle, and drops the rest silently

**Status: fixed 2026-08-14** (on `dev`, unreleased) — see Remediation.

`_process_governance_events` resolves a passed proposal's messages through `TYPE_URL_TO_PROTO` (`main.py:437`), and `_filter_trackable_anys` keeps only the types in that map (`chain_client.py:379-386`). But the map is **not** the set of messages the indexer can project. `TYPE_URL_TO_PROTO` has 26 entries (`message_processor.py:112-138`) and `MsgAnnotate` is not among them, while `process_core_message` dispatches `MsgAnnotate` to a full handler (`message_processor.py:184-185`, `944-1056`). The two lists are maintained independently with nothing tying them together.

The failure is quiet in both shapes, and the more dangerous one is quieter:

- If *every* message is filtered out, `fetch_proposal_messages` raises "no trackable messages" (`chain_client.py:342-345`), which `main.py:439-445` downgrades to a warning and `continue`s — the checkpoint still advances.
- If *some* are filtered out, there is no exception and no warning at all. The count difference appears only in a `logger.debug` line (`chain_client.py:330-335`). The proposal is recorded as applied while part of it was never projected.

**Honest reachability.** I did not demonstrate this end to end. The chain's `Annotate` handler derives its actor from `envelope_pubkey` and is agent-gated (`blockchain/x/core/module/module.go:1749-1793`) with no governance-authority branch, so a governance-delivered `MsgAnnotate` is contrived at best. I am filing it as the structural defect rather than as an exploit: the trackable set is a hand-maintained subset of the projectable set, the mismatch is invisible, and the failure mode is a checkpoint that claims a governance action was applied when it was not. That contract is what the "fails closed" comment at `main.py:420-423` promises and does not deliver.

**Fix.** Derive the governance map from the same dispatch table `process_core_message` uses so the two cannot drift, and treat `len(raw_messages) != len(trackable)` as a block-level failure rather than a debug line.

---

## L-3 (Low) — The per-block `chain_id` is written into the checkpoint without ever being compared

**Status: fixed 2026-08-14** (on `dev`, unreleased) — see Remediation.

`_process_block` reads `chain_id` out of the block header, requires only that it be non-empty (`main.py:297-299`), and hands it to `set_checkpoint` (`main.py:336`), which overwrites `meta.chain_id` on every block (`database.py:754-773`). Nothing compares it to `self.chain.get_chain_id()` or to the value already stored.

Startup continuity verification does check `chain_id` (`main.py:613-627`), so the gap is confined to a change that happens *while the indexer is running* — a node restarted onto a different network, or repointed by configuration. The indexer would keep indexing and silently rewrite the stored identity that the next startup check depends on, destroying the evidence that would have caught it.

This sits close to the accepted "co-located node is trusted" boundary, and I am not claiming a remote attacker; the realistic case is operator error. **Fix:** compare against the node's chain ID (or the stored value once set) and refuse the block on mismatch. One comparison, in the function that already has both values.

---

## L-4 (Low) — Profile reads go over gRPC inside the block transaction

**Status: PARTIALLY fixed 2026-08-14** (on `dev`, unreleased). The amplification is gone; the gRPC call is still inside the transaction — see Remediation.

`_process_block` deliberately hoists balance reads out of the transaction, and says why:

```316:319:indexer/main.py
        # Prefetch required balance reads BEFORE opening the block transaction so
        # a slow/failed gRPC call cannot hold row locks against other DB users.
        touched = self._collect_touched_addresses(result_obj)
        balances = self.chain.get_balances_batch(sorted(touched)) if touched else None
```

Three lines later the transaction opens, and the profile-list handlers call `query_profile_full` over gRPC from *inside* it — `_refresh_followed_users` (`message_processor.py:1260-1263`) and the same pattern at `:1163`, `:1236`, `:1284`, `:1773`. Each call can block for `GRPC_TIMEOUT = 3` seconds (`settings.py:39`, applied at `chain_client.py:201`), holding the block transaction and its row locks for the sum across every profile-mutating transaction in the block.

A block packed with follow/unfollow transactions therefore stalls the indexer and the backend readers contending on those tables. It is self-limiting — the block completes or fails, and it costs the attacker one PoW-priced transaction per call — so this is a latency and availability nuisance rather than a wedge. It is filed because the codebase states the rule and then breaks it in the same function. **Fix:** prefetch the profiles before opening the transaction, exactly as the balances are.

---

## I-1 (Informational) — `unblock_topics_matching` treats a stored `%` as a wildcard where its sibling escapes it

**Status: fixed 2026-08-14** (on `dev`, unreleased) — see Remediation.

```2216:2223:indexer/database.py
                cur.execute(
                    """
                    DELETE FROM blocked_topics
                    WHERE LOWER(owner) = LOWER(%s)
                      AND LOWER(%s) LIKE LOWER(REPLACE(target, '*', '%%'))
                    """,
                    (owner, t),
                )
```

`target` is stored user content, converted into a `LIKE` pattern with only `*` translated. A blocked-topic entry containing a literal `%` or `_` therefore behaves as a SQL wildcard, so following any topic can clear more blocks than it should. Twenty lines up, `unfollow_topics_matching` handles the same problem correctly by escaping first (`database.py:2112`).

Not a vulnerability: both the pattern and the rows are scoped to a single owner by `LOWER(owner) = LOWER(%s)`, so a user can only over-unblock their own list, and they had to block the `%`-bearing topic themselves. Recorded because the two adjacent functions disagree, and the next person to copy one of them has a 50% chance of copying the wrong one.

---

## Minor and operational

Recorded so they are not lost. These came out of the parallel component audits; I confirmed each exists in source but did not build an exploit path for any of them, and none is a security finding on its own.

| Item | Note |
| :-- | :-- |
| `_update_ancestor_comment_counts` walks the parent chain with one `UPDATE` per level and no depth cap (`database.py:2297-2323`), so a linear thread of depth *D* costs O(*D²*) updates inside block transactions | `get_root_topic_for_post` caps its own walk at 100 (`database.py:821`); the same cap belongs here |
| `v1_33_0_rebuild_derived_stats` manages its own transaction, but its completion marker is written afterwards on a separate autocommit connection (`migrations/__init__.py:116-124`, `253-258`) | A crash in between re-runs the full rebuild. It is idempotent, so correctness is fine. `v1_34_0` already uses the atomic `run_db_migration()` |
| `--height` on an empty DB skips the blocks below it without recording a `history_gaps` row (`main.py:741-754`) | The backend defaults `history_complete` to true when the meta key is absent, so an incomplete index reports as complete |
| `get_balances_batch` bounds each gRPC call but not the batch (`chain_client.py:517-530`) | A block touching many distinct addresses has no overall deadline |
| The signal handler exits 0 when interrupted mid-block (`main.py:251-261`) | A supervisor reading exit 0 as a clean stop will not restart. The in-flight transaction rolls back correctly, so no data is at risk |
| `INDEXER_ENABLED=false` still launches the supervisor, which crash-loops until the restart budget is spent (`deploy/entrypoint.sh:581-582`, `main.py:152-153`) | Misconfiguration is noisy instead of a clean skip |

---

## Checked and adequately guarded

A clean result is only meaningful if the attempts are visible. These were the attacks worth constructing; each died on a specific guard.

**Attributing an action to another account through the `target` field.** Five handlers prefer an unsigned `target` over the envelope signer — `_handle_set_username` (`message_processor.py:1155`), `_handle_set_biography` (`:1209`), and the three agent handlers (`:1312`, `:1328`, `:1344`). That is the inverse of the envelope-first precedence the 2026-08-07 I-1 fix established, and it looked like the highest-value finding in the review. **It is not exploitable, because the chain closes it first:** every one of these handlers requires `derived != target → reject` on the non-governance path — `SetUsername` (`blockchain/x/core/module/module.go:2008-2020`), `SetBiography` (`:2122-2137`), `EnableAgent` (`:2207-2222`), `DisableAgent` (`:2297-2312`), `SetAgents` (`:2355-2370`). A transaction with a foreign `target` never reaches `code == 0`, and the indexer only projects successful transactions. The precedence is still fragile — it depends on a chain-side invariant that nothing in the indexer states — but there is no exploit today.

**Granting yourself a level, and with it admin delete and agent annotation.** `_handle_set_level` (`message_processor.py:1714-1755`) performs **no authorization check at all** and writes the level straight from the message. It is safe for two independent reasons: the chain rejects any authority that is not the gov module (`module.go:3313-3315`), and `MsgSetLevel` is deliberately excluded from the relay registry so it can only route through `stdAnte`, which is pinned by a test that asserts it must never be added (`blockchain/app/relay_messages_test.go:35-38`, `blockchain/app/ante_metasig.go:857-859`). A user cannot produce a successful `MsgSetLevel`.

**Duplicate or replayed awards.** `_handle_award` relies on `ON CONFLICT (LOWER(owner), LOWER(target)) DO NOTHING` (`message_processor.py:1092`). Postgres raises `InvalidColumnReference` when no matching unique index exists, which inside the block transaction would be another permanent wedge — one per award. The matching index is present: `uniq_awards_owner_target` (`database.py:280`).

**A database write escaping the block transaction.** This was H-1 in the 2026-08-07 review. `_connect()` joins the active transaction connection through a contextvar rather than opening its own (`database.py:24-28`, `:55-66`), so all 70+ call sites are inside the block transaction automatically — including the ones in `_soft_delete_absent_owners` and `_handle_award` that open connections explicitly. Nesting is rejected outright (`:71-72`), `set_checkpoint` refuses to run outside a transaction (`:756-757`), and `set_last_height` is hard-forbidden with an explanatory error (`:788-793`). No regression.

**SQL injection.** Five f-string SQL sites in 2,536 lines. Two interpolate `table`/`value_col` in `_evict_oldest` (`database.py:876`, `:883-891`), both supplied by internal callers from literals; two build `%s` placeholder lists from a count (`:1097-1103`, `:1150-1154`); one interpolates a fixed table name in the loop at `main.py:1078`. Every value is bound. `unfollow_topics_matching` escapes `%` and `_` before building its `LIKE` (`:2112`) — see I-1 for the sibling that does not, which is still not injectable.

**Persisting a query failure as truth.** This was M-2 in the 2026-08-07 review. `get_balance` and `get_balances_batch` raise on any error rather than returning zero (`chain_client.py:501-502`, `:529-530`), and balances are prefetched outside the block transaction so a slow gRPC call cannot hold row locks (`main.py:316-319`). `query_profile_full` maps **only** `NOT_FOUND` to `None`; every other status re-raises (`chain_client.py:202-206`). No other client method converts an error into an empty result.

**Processing a transaction whose result has not arrived.** This was H-3. Enforced twice now: `get_block_results_matching` retries until the count matches under a 15-second deadline (`chain_client.py:116-168`), and `_process_block` asserts equality again before touching the database (`main.py:308-311`).

**Overwriting the evidence of a divergence.** Every retained `recent_blocks` hash is compared against the node *before* any startup upsert (`main.py:658-675`), adoption of a provenance-less database requires the node to confirm the checkpoint hash (`:677-700`), and a checkpoint below the node's earliest retained block is recorded as `unverified_pruned_gap` rather than claimed verified (`:644-656`). Migrations run only after all of this (`:881-883`).

**Migrations.** Import failure, a missing `MIGRATION_KEY`/`run`, and a duplicate key are all fatal (`migrations/__init__.py:82-95`); the advisory lock is held on a dedicated connection for the whole run and refuses to wait (`:227-237`); checksums are pinned on first sight and mismatches are fatal (`:178-198`); `run_db_migration` writes the completion marker in the same transaction as the work (`:143-153`). Naming is consistent with the release-tag rule — the newest is `v1_34_0_repair_topic_attribution.py` and `v1.35.0` adds none.

**Outbound network access from post content.** None. `discover_post_thumbnail` is a pure deterministic URL transform (`message_processor.py:2027-2074`), and no `requests`/HTTP call exists anywhere in the message path. The H-5 removal holds.

**gRPC-only policy.** No reference to port `1317` anywhere in `indexer/`. Governance resolution is gov v1 gRPC with a v1beta1 content fallback for legacy proposals (`chain_client.py:313-374`), and an unresolvable tracked proposal still fails the block (`main.py:435-446`).

**Vote arithmetic.** `net_votes_delta` is computed as `new_direction - prev_direction` (`message_processor.py:690`), the cleared-vote path reverses the prior contribution (`:534-541`), and re-votes do not increment `vote_count` (`database.py:1582-1583`). The topic-edit reattribution added in v1.34.0 recomputes both affected topics from the canonical rows rather than guessing a delta (`database.py:1670-1700`). The vote and edit paths are sound — **but deletion is not, which is M-3**: every other mutation that invalidates a stats delta was taught to recompute, and deletion was missed.

**Supervisor input handling.** `run_indexer_supervised.sh` validates both numeric env inputs against anchored regexes and exits non-zero on a bad value (`:22-23`), checks the entry point exists (`:24`), and passes `"$@"` through without re-splitting. No unvalidated input reaches a shell construct.

---

## Test coverage gaps

As found, none of the wedge paths had any coverage — nothing in the suite referenced `get_vote_weight` or `decode_events` at all. **Closed as part of the remediation**, in the existing `indexer_hardening` category, stub-level so they need no docker and no chain:

| Gap | State |
| :-- | :-- |
| `get_vote_weight` for admin levels other than `100` | **Closed.** `admin_levels_resolve_to_agent_tier` pins `101`, `110`, `150`, `999`; `unknown_levels_still_rejected` keeps `2` and `50` rejected so the range check did not become a catch-all |
| `decode_events` against plain-string attributes, including base64-shaped values | **Closed.** `event_attrs_not_base64_decoded` runs the real decoder over `1400`, `1401`, `1412`, `2400`, `7768`, and `attr_text_decodes_bytes_only` pins the `bytes`/`None` behaviour |
| A governance event whose `proposal_id` is not parseable | **Closed.** `proposal_id_parses_after_decode` end to end, plus `proposal_id_unparseable_fatal` asserting it still raises rather than skipping |
| `user_topic_stats` after a post is deleted, and agreement with the canonical SQL | **Closed.** `deleted_posts_grant_no_standing` pins both canonical predicates and `delete_recomputes_topic_stats` pins the wiring. The retraction itself was additionally executed against PostgreSQL |
| Profile reconciliation against an empty chain inventory, and bulk soft-delete limiting | **Closed.** `profile_sync_guarded` covers both guards |
| A governance proposal carrying a message type the indexer handles but does not track | **Closed.** `untracked_core_message_fatal`, plus `cosmos_messages_still_ignored` to prove the new failure did not swallow legitimate cosmos proposals, plus `annotate_is_governance_trackable` |
| L-1, L-3, I-1 and the minor guards | **Closed.** `legacy_backfill_uses_savepoint`, `chain_id_checked_per_block`, `unblock_pattern_escaped`, `ancestor_walk_bounded`, `signal_exit_nonzero` |
| Replay of a delete/annotate block after the actor's level changed | **Still absent — M-1**, which was accepted as risk. Recorded here because accepting the risk does not make the untested behaviour tested |
| Vote weight reproducibility between live indexing and rebuild | **Still absent — M-1**, same reason |

**The source-level assertions were subsequently replaced with behavioural ones**, because a guard that is present but broken would have satisfied a string match. The SQL-level fixes now run against a real PostgreSQL in a throwaway schema that the real `DatabaseManager` populates via `search_path`, so nothing touches live rows: the `SAVEPOINT` is proven by forcing only the backfill `UPDATE` to fail with a CHECK constraint and asserting the surrounding transaction still works, the escaping and the depth cap are executed, and the M-3 retraction is driven through the real `delete_post`. The chain-id latch, the signal exit code and the profile-sync guards are driven against bare instances and a stub DB. The remaining string match is on the canonical SQL predicates themselves, where the text *is* the definition.

**The assertions were mutation-tested.** Reverting the M-3 vote predicate and the walk depth cap in the source made exactly the expected three fail, with useful messages — the M-3 one reporting `(3, 3, 3, 0)`, which is the live-versus-rebuild divergence described above showing through: `post_count` correctly dropped to zero while the vote-derived counters kept the standing. A regression test that cannot fail is not evidence, so this was checked rather than assumed.

---

## Verification performed

- Read all 6,730 lines of `indexer/` plus the 14 migration modules; cross-read the chain-side handler for every message type whose indexer handler makes an authorization or identity decision.
- **Executed the H-1 decode** against every plain proposal ID from 1 to 19,999 using the exact `base64.b64decode(v, validate=True).decode("utf-8")` call from `decode_events`: 1,040 corrupted, first at 1400, and `int()` confirmed to raise on the result.
- **Executed the H-2 lookup**: rebuilt `vote_weights` from the chain's `DefaultTiers` and confirmed `101`, `110`, `150` and `999` raise while `0`, `1`, `10` and `100` resolve.
- **Settled the base64 question against the dependency source**, because a parallel audit reached the opposite conclusion and only one fix direction could be right: `EventAttribute.Key`/`.Value` are Go `string` in `cometbft@v0.39.3/abci/types/types.pb.go:3223-3227`, so JSON never base64-encodes them. Corroborated by two working consumers that do not decode (`main.py:398-401`, `scripts/submit_proposal.py:1105-1107`).
- **Executed the tolerant decoder in `_collect_touched_addresses`** against every key and value it inspects (`sender`, `recipient`, `spender`, `receiver`, `transfer`, `coin_spent`, `coin_received`, a sample bech32 address, and `umir` amounts): all fail to decode, so the raw value survives and there is no finding — but `'receiver'` is valid base64 and fails only on UTF-8, so the safety is incidental.
- **Traced M-3 through the canonical SQL**: confirmed `delete_post` (`database.py:2226-2283`) touches no stats table, that `_POST_STATS_FROM_CANONICAL` filters `deleted = FALSE` while `_VOTE_STATS_FROM_CANONICAL` does not, and read the four gating factors and their thresholds in `settings.py:17-23` — including that `COMMUNITY_VOTE_MIN_NET_VOTES` is `-10`, so `net_votes` is a floor rather than the gate the counter's name suggests.
- Confirmed `MsgAnnotate` is absent from `TYPE_URL_TO_PROTO` (26 entries, `message_processor.py:112-138`) while `process_core_message` dispatches it (`:184-185`), and that the chain's `Annotate` handler is envelope/agent-gated with no governance branch (`module.go:1749-1793`).
- Confirmed `uniq_awards_owner_target` exists, so the `ON CONFLICT` in `_handle_award` is not a latent wedge.
- Confirmed `LevelAdminMin = 100` and that `LevelToTierIndex` accepts the whole range above it.
- Traced every `_connect()` call site (70+ in `database.py`, 3 in `main.py`, 1 in `message_processor.py`, 9 in migrations) against the contextvar to confirm no write escapes the block transaction.
- Swept every f-string / `.format()` / `%`-built SQL string in `database.py` and classified what each interpolates.
- Diffed `indexer/` and `shared/` from `v1.33.2` to `v1.35.0` (8 commits) and re-checked each previously fixed finding for regression.
- **Measured H-1's fuse on both fleets** (read-only): UAT (`val2`) and prod (`val1`) both report governance proposal **108** against a first corrupting ID of **1400** — roughly 1,290 proposals of runway. The two returned byte-identical responses, including the same `v1.35.0` upgrade plan at height 6805312, so they front the same chain rather than two independently-counting ones.
- **Validated the remediation against a real PostgreSQL 16** rather than by reading the SQL: the M-3 retraction (attacker `(3,3,3,3)` → no row; honest voter `(1,1,1)` retained), the I-1 escaping (literal `%` and `_` inert, `*` still globs), and that the recursive-CTE cascade `UPDATE … RETURNING` is valid and returns the descendant owners.
- **Re-ran every fix as a standalone assertion suite** (18 checks) covering the poisoned proposal IDs end to end, admin levels `101`/`110`/`150`/`999`, the canonical SQL predicates, the governance filter's three categories, and each guard's presence.

**Not run:** `tests/test_backend.py` and `tests/test_blockchain.py`. Both submit real transactions and may only run inside local docker after raising the PoW limit. Nothing in this review depends on their output; the checks above were run standalone.

---

## Assumptions

- Honest node operators run the reviewed indexer. The accepted ability of an operator to serve a modified index is not reclassified as a vulnerability.
- The chain-side guards cited under "Checked and adequately guarded" are load-bearing for those non-findings. If any of them is relaxed, the corresponding indexer handler becomes exploitable immediately — most sharply `_handle_set_level`, which has no defence of its own.
- The items under "Minor and operational" are reported at lower confidence than the numbered findings: they were confirmed to exist in source but not traced to an impact, and they came from the component audits rather than from my own read.

---

## Remediation — 2026-08-14

Everything except M-1 was fixed the same day. **All of it is on `dev` and unreleased.** Each fix carries a stub-level regression test in the `indexer_hardening` category (18 new assertions, no docker or chain required), and the changed SQL was validated against a real PostgreSQL 16 rather than reasoned about.

| ID | What changed |
| :-- | :-- |
| **H-1** | The base64 attempt is gone. A new `attr_text` helper decodes only genuine `bytes`, and **all four** readers of the same `result_obj` now share it: `decode_events`, `_process_subscription_events`, `_collect_touched_addresses`, and `_synthesize_raw_log` — the last of which was not in the original finding and still carried a comment asserting the attributes were base64-encoded. An unparseable proposal id now raises a named `RuntimeError` rather than a bare `int()` traceback, and deliberately stays fatal: skipping it would advance the checkpoint past a governance action that was never projected |
| **H-2** | `level_to_tier_index` mirrors the chain's `LevelToTierIndex` as a range check. The level-keyed `vote_weights` dict was replaced by a tier-indexed list, which also removes the `KeyError` that would have fired at param load if governance ever shipped fewer than three tiers |
| **M-3** | `delete_post` collects the affected `(owner, topic)` pairs via `RETURNING` on both the post and cascade updates, then rebuilds them from canonical through a new shared `_recompute_topic_stats` helper — the same helper `reattribute_topic_stats` now uses, so there is one definition rather than two. The canonical vote SQL excludes an author's own vote on their own deleted post. Migration `v1_36_0_repair_deleted_post_standing` applies the new definition to rows written before the fix, scoped to owners with deleted posts, and asserts agreement afterwards |
| **M-2** | `_soft_delete_absent_owners` refuses an empty chain inventory against a populated index, and aborts if a sync would soft-delete more than `PROFILE_SYNC_MAX_ABSENT_FRACTION` (10%) of known profiles. A genuinely fresh chain still starts, because the guard compares against the local row count rather than assuming profiles must exist |
| **L-1** | The legacy backfill runs inside a `SAVEPOINT`, so "best-effort" is now true instead of aspirational |
| **L-2** | `MsgAnnotate` added to `TYPE_URL_TO_PROTO`. An untracked `/mirage.core.v1.` message inside a proposal is now fatal instead of silently filtered, while cosmos messages stay deliberately ignored — the same prefix rule `_process_tx` already applies. This is the durable half: a handler added without a map entry now fails loudly rather than dropping a governance action |
| **L-3** | The expected `chain_id` is latched from the first block and compared on every subsequent one. Latched rather than queried per block, so it costs no network round-trip during catch-up |
| **I-1** | Escaped in SQL with an explicit `ESCAPE '#'`. The sibling's Python-side escaping does not transfer because here the pattern is a column rather than a parameter. Verified against PostgreSQL that a literal `%` and `_` no longer match anything else and that `*` still globs |
| Minor | Ancestor comment-count walk bounded by `MAX_ANCESTOR_WALK_DEPTH = 100`, matching the root walk beside it; `--height` on an empty database now records the `[1, start-1]` history gap, so a partial index no longer reports itself complete; the signal handler exits `128+signum` instead of `0`, so an interruption is not read as a clean shutdown; `get_balances_batch` gained an overall `BALANCE_BATCH_DEADLINE` of 30s, since per-call timeouts bounded each request but let *N* addresses cost *N* × 3s; `INDEXER_ENABLED=false` now exits the supervisor cleanly instead of crash-looping until the restart budget is spent, so an operator's own setting no longer produces a crash-loop ACTION ITEM. Only an explicit `false` skips — an absent or malformed value still falls through to the config layer's hard failure |

**M-3 retracts standing from the author only, and that is a deliberate narrowing.** The chosen disposition was "deleted posts grant no standing", which turned out to be ambiguous once written: it can mean the author loses what their own deleted post granted, or that *everyone* who voted on it loses it too. The second reading creates a griefing lever — an author could strip a chosen voter's topic standing by deleting their own popular content — which trades one abuse path for another. Only the author's own vote on their own deleted post is excluded; other voters keep what they earned by participating. Confirmed against PostgreSQL: an attacker's `(vote_count, net_votes, unique_root_posts, post_count)` of `(3,3,3,3)` drops to no row at all after deleting, while an honest voter on the same posts keeps `(1,1,1)`.

**L-4 is mitigated, not fixed, and the remainder was accepted as risk.** A per-block memo collapses repeated profile reads of the same address, which removes the amplification from packing a block with transactions from one account. The gRPC call still happens inside the block transaction. Eliminating it needs prefetching, prefetching needs the addresses before the transaction opens, and deriving those addresses ahead of time means duplicating the owner-derivation precedence across five handlers — the exact logic the 2026-08-07 I-1 fix consolidated into one chokepoint. Reintroducing a closed finding to close a latency nuisance is a bad trade, so the residue is recorded in [`open-items.md`](../open-items.md) as accepted and should not be re-reported.

**Two items under "Minor and operational" were also accepted as risk** and should not be re-reported: the L-4 residue above, and `v1_33_0`'s completion marker being written outside its own transaction. The latter is effectively unfixable rather than merely unimportant — applied migration files are checksum-pinned, so editing `v1_33_0` is a hard startup failure on every existing deployment. Its rebuild is idempotent, so a crash between the work and the marker costs time and not correctness, and `v1_34_0` onward already use the atomic helper.

**M-1 was accepted as risk** and is recorded in [`open-items.md`](../open-items.md) under accepted decisions. Future reviews should not re-report it. The impact stands as described below — a rebuild after an admin is demoted un-deletes that admin's moderation, and pre-planted deletes can activate on a later reindex — and was accepted with that understood, because the only correct fix persists the acting level alongside the projection and therefore needs a schema column.

**Migration version:** `v1_36_0_*` per the repo rule that migrations match the current tag, which this release makes `v1.36.0`. The already-applied `v1_33_0` and `v1_34_0` migrations were deliberately left untouched: applied migration files are checksum-pinned, and editing one is a hard startup failure on every existing deployment. `v1_33_0` therefore keeps its own frozen copy of the older canonical SQL and the new migration supersedes it.

---

## Recommended order

Superseded — everything here is dispositioned. Retained because the reasoning explains the sequencing that was used.

1. **H-2 first.** A four-line change with an already-correct reference implementation in the backend, and until it lands the operator cannot safely use any admin level except exactly `100`.
2. **H-1 next.** Also small, but it should normalise every attribute reader rather than only the fatal one, and come with the missing `decode_events` test. In the event there were four readers, not three.
3. **M-3.** The only finding a user can exploit today, using an idiom already in the file. Ahead of M-2 despite M-2's more severe failure, because M-2 has no demonstrated trigger and this one needs none.
4. **M-2.** Two guards, no schema change, and the failure it prevents is unrecoverable.
5. **M-1.** The largest and the only one touching the schema. **Accepted as risk instead.**
6. **L-1 through L-4 and I-1** in passing.
