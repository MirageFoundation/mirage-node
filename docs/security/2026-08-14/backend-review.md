# Backend Security Review — 2026-08-14

**Scope:** `web/backend/` — all 34 tracked Python files (~26,110 lines), all 87 registered HTTP routes plus the four `/api/rewards/debug/*` handlers, quest and reward accounting, relay transaction construction, media upload and proxy, push delivery, analytics, and the data layer. `blockchain/`, `indexer/`, `shared/` and `deploy/` were read only where they define a backend trust, configuration, or input boundary.
**Baseline:** `dev` at the `v1.35.0` tag (`922867c6`), clean working tree.
**Reporting bar:** all severities. This is a full audit, not a diff review or a remediation retest.
**Method:** six parallel subsystem audits, each required to produce a concrete exploit chain rather than a pattern match, followed by independent re-verification of every surviving candidate against source by the reviewer. Candidates that could not be traced end to end were dropped, and two were corrected during re-verification — see "Corrections made during verification".

**Prior state:** every Critical and High from the 2026-08-04 → 2026-08-13 rounds is closed; see [`open-items.md`](../open-items.md). Items already recorded there as accepted decisions were excluded from scope by instruction and are not re-reported. Nothing below is a re-report of a known item.

> **Retest guidance.** Nothing here is fixed. This document records findings only; no code was modified during the audit.

---

## Summary

**1 Critical, 3 High, 5 Medium, 2 Low.**

**Disposition (v1.36.0):** ten of the eleven findings are fixed and covered by
regression tests; **M-5 is accepted as a risk** and will not be raised again. All
nine sub-threshold observations were also fixed. See [Remediation](#remediation).

| ID | Area | Finding | Severity |
| :-- | :-- | :-- | :-- |
| **C-1** | Feeds / push | One on-chain blocked-topic pattern wedges the backend: exponential regex backtracking, ~24 s of CPU per row, and it also kills push delivery fleet-wide with no further attacker action | **Critical** |
| **H-1** | Feeds | `page` is unbounded and multiplied into the SQL `LIMIT`, so one unauthenticated GET fetches the whole `posts` table into a worker | **High** |
| **H-2** | Stats fan-out | `/api/admin/stats/aggregate` sends a live admin proof to any host named by an unauthenticated P2P peer | **High** |
| **H-3** | Quests | Quest completion is an unlocked read-modify-write; the only guard is a same-second unique index | **High** |
| **M-1** | Push | Push delivery ignores the recipient's block list and the post's deleted state, both of which the in-app inbox enforces | **Medium** |
| **M-2** | Push | Mention fan-out is uncapped; a few posts silently destroy every queued notification platform-wide | **Medium** |
| **M-3** | Upload | `/api/upload_media` parses the entire body before the per-kind size cap, so a 15 MiB image cap is really ~1.5 GiB | **Medium** |
| **M-4** | Analytics | `user_last_seen` is written before any signature check, inflating a published metric and growing an untrimmed table | **Medium** |
| **M-5** | Relay fees | No backend ceiling on validator-funded relay fees; `relay_max_gas_fee` is required at startup and never read | **Medium** |
| **L-1** | Invites | Invite reward inserts have no `ON CONFLICT`; concurrent referrals double-pay the referrer and can silently drop the referee's reward | **Low** |
| **L-2** | Search | `/api/search_username` is the one search path that does not escape LIKE metacharacters | **Low** |

The single most urgent item is **C-1**. It is unprivileged, costs one transaction, is deterministic, and — unlike an ordinary resource-exhaustion bug — its most damaging effect requires the attacker to send no traffic at all: after the setup transaction, the shared push-listener thread does the work on their behalf, forever, for every user on the node.

Three findings share one root cause worth naming separately, because fixing them individually will not stop the next instance: **there is no `statement_timeout`, no connection pool, and no query deadline anywhere in the backend.** Verified by search across the repository — zero occurrences outside documentation. `connect_db()` even accepts `timeout` and `busy_timeout_ms` arguments that roughly 30 call sites pass explicitly and that the function documents as ignored (`web/backend/db.py:21-35`). That is what turns C-1, H-1 and L-2 from slow queries into worker kills.

**Clean:** SQL injection re-verified clean by AST extraction of every f-string interpolation; error handlers leak no SQL, stack traces, or file paths; `X-Forwarded-For` is still untrusted; the `push_nonces` replay guard is real and fails closed; the reward *claim* path resisted every attack constructed against it; and the `/api/rewards/debug/*` money endpoints are closed by three independent guards. The candidates chased and the guard that killed each are recorded below, because a clean result is only meaningful when the attempts are visible.

---

## C-1 (Critical) — One blocked-topic pattern wedges the backend, and permanently kills push delivery for everyone

**Status: fixed in v1.36.0.**

**Privilege required:** an ordinary account. **Cost:** one transaction. **Effect:** gunicorn workers killed on demand, and — with no further attacker action — the platform's entire push notification system stops and silently discards every user's queued notifications.

The backend reimplements the chain's topic glob as a regular expression, converting each `*` into `.*` and matching it against every candidate row:

```695:708:web/backend/routes/public.py
def _topic_is_blocked(topic: str, blocked_exact: set[str], blocked_patterns: tuple[str, ...]) -> bool:
    if not topic:
        return False
    if blocked_exact and topic in blocked_exact:
        return True
    if blocked_patterns:
        import re as _re

        for pat in blocked_patterns:
            # Convert glob * to regex .* (don't use fnmatch — it treats ? and [] as meta)
            escaped = _re.escape(pat).replace(r"\*", ".*")
            if _re.fullmatch(escaped, topic):
                return True
    return False
```

A pattern of the form `a*a*a*…*a` becomes `a.*a.*a…a`, which is the textbook exponential-backtracking case.

### Neither validator bounds the wildcard count

The backend route rejects only *adjacent* stars, and measures length against the alphanumerics with the stars removed:

```2341:2354:web/backend/routes/core.py
        # Allow * as glob wildcard anywhere in blocked topic patterns
        _topic_alpha = topic.replace("*", "")
        if not _topic_alpha or not re.fullmatch(r"[a-z0-9]+", _topic_alpha):
            return jsonify({"error": "invalid topic format"}), 400
        if "**" in topic:
            return jsonify({"error": "invalid topic format"}), 400
```

The chain agrees, so the pattern survives to on-chain state and into the indexer:

```139:152:blockchain/x/core/module/module.go
func validateBlockedTopicPattern(topic string, maxLen, minLen uint64) error {
	topic = strings.TrimSpace(topic)
	if topic == "" {
		return fmt.Errorf("topic required for blocking")
	}
	if strings.Contains(topic, "**") {
		return fmt.Errorf("consecutive wildcards not allowed")
	}
	alpha := strings.ReplaceAll(topic, "*", "")
	if alpha == "" {
		return fmt.Errorf("pattern must contain alphanumeric characters")
	}
	return validateTopic(alpha, maxLen, minLen)
}
```

`validateTopic` sees only `alpha`, so stars are free. With `MaxTopicSize` at 35 the maximum legal pattern is 35 alphanumerics interleaved with 34 stars — a 69-character string the chain accepts.

**The chain's own matcher is safe, which is what makes this a backend bug rather than a protocol one.** `topicMatchesPattern` (`blockchain/x/core/module/module.go:156-182`) is a linear greedy `strings.Index` walk with no backtracking. The backend re-implemented the same semantics as a regex and inherited exponential behaviour the chain never had.

### Measured cost

Reproducing the exact construction at `routes/public.py:705-706`, matching a chain-legal pattern against a chain-legal 35-character topic, in a subprocess with a hard budget:

| Pattern alphanumerics | Raw pattern length | Wall time |
| ---: | ---: | ---: |
| 25 | 49 | 57 ms |
| 29 | 57 | 750 ms |
| 31 | 61 | 2.98 s |
| 33 | 65 | 11.9 s |
| 34 | 67 | **23.8 s** |
| 35 (max legal) | 69 | **> 30 s (aborted)** |

Clean doubling per added character, so the maximum legal pattern is roughly 47 s. **That is per row.** gunicorn runs sync workers with `timeout = 120` (`web/backend/gunicorn_config.py:29-31`), so a single row is a fifth of a worker's life and three rows kill it. There is no `statement_timeout` and no query deadline to reclaim anything.

### Blast radius 1 — read paths

`_topic_is_blocked` has 16 call sites, all per-row inside feed, search, comment-tree and inbox handlers: `routes/public.py:1173` (all feeds, via `_load_candidate_posts`), `:2651`, `:4756`, `:4879`, `:4887`, `:5110`, `:5177`, `:5313`, `:5735`, `:6046`, `:6639`, `:6857`, `:7064`, `:7803`.

Blocked topics are the *viewer's*, so this path burns a worker only on requests carrying the attacker's own address — but those requests are free and unauthenticated, and the edge permits 50/s per IP (`deploy/templates/caddy/Caddyfile:94-99`). The amplification is roughly 2,000×: one cheap GET against ~47 s of CPU.

### Blast radius 2 — the push listener, which needs no attacker traffic at all

This is the serious half. `_pick_visible_candidate` loads blocked topics straight from the indexer and runs the same matcher per candidate:

```888:907:web/backend/push_listener.py
    icur.execute(
        "SELECT DISTINCT LOWER(target) FROM blocked_topics WHERE LOWER(owner) = ANY(%s)",
        (topic_owners,),
    )
    raw_blocked_topics = [str(r[0] or "").strip().lower() for r in icur.fetchall()]
```

```947:949:web/backend/push_listener.py
        topic = cand["topic"]
        if topic and _topic_is_blocked(topic, blocked_exact, blocked_patterns):
            continue
```

`_poll_trending` iterates up to `PUSH_LISTENER_BATCH_SIZE = 200` due users on **one shared thread** (`push_listener.py:965`, `:980-984`). When it reaches the attacker's row it stalls for tens of seconds per candidate. The `try` at `:983` catches exceptions, not slowness, so the thread simply stops making progress.

Everyone else's notifications are then destroyed rather than delayed. Events older than `PUSH_OUTBOX_MAX_AGE_SECONDS` are marked terminal without ever being delivered:

```746:754:web/backend/push_listener.py
        if now - event["created_at"] >= PUSH_OUTBOX_MAX_AGE_SECONDS:
```

So the exploit is: send one `MsgBlockTopic` with a 69-character pattern, register for push, and stop. Push delivery for every user on the node degrades to nothing, silently, indefinitely. Recovery requires a code fix or direct database intervention — the pattern lives in on-chain state, so restarting the backend replays it.

### Remediation

Cap the wildcard count at validation time in `routes/core.py:2345` where `**` is already rejected — and, because chain-legal patterns may already be stored, defensively at match time in `_topic_is_blocked`. The structural fix is to replace the regex with the chain's own linear algorithm (`topicMatchesPattern`), which has identical semantics and no backtracking. `_blocked_topics_sql` (`routes/public.py:870-875`) converts the same glob into a SQL `LIKE`, whose Postgres matcher is also backtracking; it should be bounded by the same cap.

### Regression tests

A pattern at the maximum legal size matched against a non-matching maximum-length topic completes in bounded time; `block_topic` rejects a pattern above the wildcard cap; and a stored over-cap pattern does not stall `_poll_trending`.

---

## H-1 (High) — `page` is unbounded and multiplied into the SQL `LIMIT`

**Status: fixed in v1.36.0.**

`limit` is clamped everywhere; `page` is only floored:

```5489:5493:web/backend/routes/public.py
    limit = request.args.get("limit", 25, type=int)
    limit = min(max(1, limit), 100)
    page = request.args.get("page", 1, type=int)
    page = max(1, page)
```

Several feed paths then compute the SQL row cap as a product of the two and pass it straight to `LIMIT %s` (`routes/public.py:1126`), so a large `page` removes the limit entirely. psycopg3's default client-side cursor materializes the whole result at `execute()`, and each row is then expanded into a ~20-key Python dict.

| Path | Reachable by | Cap computed at |
| :-- | :-- | :-- |
| `_get_guest_feed` | `?feed=following` — **no address at all** | `public.py:2868` — `limit*page*2` |
| `_get_guest_feed_magic` | `?feed=home` — **no address at all** | `public.py:2933` — `limit*page*4` |
| `_get_following_feed` | `?feed=following&address=…` | `public.py:1533` — `limit*page*factor` |
| `_get_home_feed_newest` | `?feed=home&by=newest&address=…` | `public.py:1805,1809` — `max(500, (page*limit+1)*factor)` |
| `get_posts` topic/global | `?topic=all` or no `feed` | `public.py:5664` — `max(500, limit*page*factor)` |
| `get_inbox` | `?address=<any>` | `public.py:7427` — `need = offset + limit`, passed as `LIMIT` at `:7563` |

Cheapest exploit, no account and no valid address:

```
GET /api/get_posts?feed=following&page=100000000&limit=100
```

`_get_guest_feed` is selected because the viewer is empty (`public.py:1516-1517`), yielding `LIMIT 20000000000` over `posts LEFT JOIN profiles` ordered by `created_at DESC`. Postgres streams every post, content included, into the worker. The request eventually 500s when `_load_vote_and_comment_stats` exceeds psycopg's 65,535-parameter ceiling, but the memory is already committed, so the failure protects nothing. At 50 rps per IP against `2*cpu+1` sync workers, every worker holds a full-table copy within the first second; the OOM killer, not the rate limit, is the binding constraint. In the container that shares a process table with `miraged`, so this reaches consensus participation, not just the API.

`get_inbox` is the worst per-request: the same unbounded `need` is the `LIMIT` of a `UNION ALL` whose first branch is a ten-level `LEFT JOIN` self-chain on `posts` (`public.py:7482-7490`). `address` is unauthenticated, so the attacker picks the busiest account on the node.

**The guard that exists shows the omission was accidental.** The sibling magic home feed caps its pool with the correct operator:

```1952:1952:web/backend/routes/public.py
            per_source = min(limit * page * _seen_overfetch_factor(seen_posts, 4), 500)
```

Two of the uncapped sites use `max(500, …)`, which reads like a cap and is a floor. `/api/bootstrap` also clamps correctly (`public.py:4090`, `:4139`).

**Remediation:** clamp `page` once at each entry point (`public.py:5492`, `:7424`) and apply the `min(…, 500)` from `:1952` to the five uncapped pool computations.

---

## H-2 (High) — The stats fan-out hands a live admin proof to any host an unauthenticated P2P peer names

**Status: fixed in v1.36.0** — roster-bound; per-destination proof scoped out (protocol change).

`validate_fleet_endpoint` answers "is this a reachable public Internet host", not "is this a member of our fleet". Nothing downstream requires fleet membership, and the destination list is built from strings an attacker supplies for free.

The chain, verified link by link:

1. An attacker peers with a validator over the public P2P port and sets their node's moniker to a domain they own. The moniker is self-declared text in `node_info`.
2. The indexer stores it verbatim: `peers.append({"ip": ip, "moniker": str(node_info.get("moniker", "") or "").strip()})` (`indexer/main.py:988`), written to `chain_stats` at `:990`.
3. The backend reads it back unfiltered (`web/backend/chain.py:394-413`).
4. `discover_servers` turns it into a destination (`web/backend/stats.py:1148` → `:978` → `validate_fleet_endpoint`). An attacker-owned domain resolving to a public IP passes every check: scheme, shape, and `is_global` (`fleet_url.py:97-99`, `:126-159`).
5. An admin calls `/api/admin/stats/aggregate`. The handler rebuilds the admin's raw proof fields and POSTs them to each discovered endpoint:

```8156:8179:web/backend/routes/public.py
    proof = {
        "pubkey": data.get("pubkey"),
        "signature": data.get("signature"),
        "address": data.get("address"),
        "timestamp": data.get("timestamp"),
        "envelope_nonce": data.get("envelope_nonce"),
        "start": start,
        "end": end,
    }
```

6. The attacker holds a valid signature over `stats:{addr}:{ts}:{nonce}`, replayable for the remainder of the ±5-minute skew window (`routes/core.py:161`) against **other** fleet nodes, because replay protection is a per-node `UNIQUE(owner, action, nonce)` row (`web/backend/db.py:449`) and those nodes have never seen the nonce. Cross-node reuse of one proof is deliberate (`public.py:8036-8037`), which is exactly what makes the leak useful.
7. The most valuable target is not `/export` but `/api/get_stats`, which accepts the same `stats` action and serves the financial, subscriber, analytics and reward tabs (`public.py:9068-9074`).

Two aggravating details on the same path. `validate_fleet_endpoint` accepts `http://`, and `_peer_endpoint` synthesizes exactly that form for domain-less peers (`stats.py:1101-1108`), so the proof can also cross the internet in cleartext. And the attacker's response body is stored raw and returned to the dashboard (`public.py:8182`, `:8197`) with no schema validation, while `aggregate_server_stats` coerces attacker values with bare `int()` (`stats.py:1008`) outside any try/except (`public.py:8195`) — so a non-numeric field 500s the admin endpoint for as long as the attacker stays peered.

**This is not a regression of the L-1 fix.** That fix stopped monikers reaching *internal* addresses, and it holds — `fleet_url.py` resolves then connects to the resolved IP with SNI pinned, rejects split-horizon DNS, and never follows redirects. This is the orthogonal half the fix did not address: reaching an *external, attacker-chosen* host while carrying a credential. The module docstring already notes that "validator monikers are attacker-influenced text" (`fleet_url.py:3-10`); the conclusion drawn from that was about SSRF destinations, not about credential egress.

**Severity: High as a primitive, Medium on impact alone.** The `stats` action is distinct from every mutating action string, so the harvested proof cannot drive a write. It becomes unambiguous High the moment any mutating route reuses that action.

**Remediation:** derive fan-out destinations from something the attacker does not control — a configured roster, or the chain validator set with operator-confirmed domains — rather than from P2P discovery; require `https`; make the proof per-destination so a leaked one cannot be replayed to a sibling node; and validate the shape of every peer response before merging it.

---

## H-3 (High) — Quest completion is an unlocked read-modify-write

**Status: fixed in v1.36.0.**

Assignment got an advisory lock (the M-2/L-5 fix) and claiming got one. Completion — the step that actually creates money — got neither.

`connect_backend_db()` hands out autocommit connections (`web/backend/db.py:31-35`), so nothing in the tracker is transactional. `_increment_daily_progress` reads progress on one connection and writes on another:

```537:543:web/backend/quest_tracker.py
    def _increment_daily_progress(self, owner: str, quest: QuestDefinition, day_utc: int, ts: int, **kwargs) -> None:
        """Increment progress on a daily quest if requirements are met."""
        progress = self._get_daily_quest_progress(owner, quest.id, day_utc)

        # Already completed
        if progress.completed_at is not None:
            return
```

The completion guard evaluates a snapshot that is stale by the time the write lands at `:667`, and the write is an unconditional upsert rather than a compare-and-set, so a losing writer cannot detect that it lost. Between read and write the code opens two further connections, which is what makes the window wide.

The only thing preventing duplicate payment is the second-granularity unique index:

```497:505:web/backend/quest_tracker.py
                    cur.execute(
                        """
                        INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (owner, reward_type, reason, created_at) DO NOTHING
                        RETURNING id
                        """,
                        (owner, reward_type, json.dumps(reward_data), reason, ts),
                    )
```

`ts` is captured per request in the route (`routes/core.py:4342` for votes, `:4092` for posts), so two concurrent completing actions that straddle a UTC second boundary produce two surviving reward rows. Parallelism is real rather than GIL-serialized: gunicorn runs `2*cpu+1` separate sync worker processes (`gunicorn_config.py:25-31`).

Worth up to 1,000 MIRAGE base per duplicate, times the 5× multiplier cap, once per quest per day. The flash path has the identical shape (read `quest_tracker.py:329`, guard `:335-338`, write `:472`, reward `:488`).

**Currently gated by configuration, not by code.** The template ships `QUESTS_ENABLED=false` and `QUESTS_PAYOUTS_ENABLED=false`, but the H-5 production incident established that the fleet has run with quest assignment live for months, so this is a blocker for re-enabling payouts rather than a theoretical concern.

**Remediation:** wrap the read-decide-write in the existing `_locked_transaction` helper (`quest_assignment.py:36-55`), keyed per owner. A unique index on `(owner, reason, day_utc)` for quest-derived rewards would close it at the database layer regardless of what the application races on — the current index has no natural idempotency key, which is the same structural gap the H-5 investigation ran into.

---

## M-1 (Medium) — Push delivery ignores blocks and deletions that the inbox enforces

**Status: fixed in v1.36.0.**

The in-app inbox drops items whose actor the viewer blocked (`routes/public.py:7794-7795`, with agent-level blocks folded in at `:7437`). **`shared/push.py` contains no reference to any blocked list** — verified by search, zero matches. The reply path resolves the parent owner and sends unconditionally (`shared/push.py:572-618`); the mention path sends to every resolved username (`:717-736`), which requires no prior relationship at all.

So a blocked user can put attacker-authored text on the victim's lock screen by replying to them or writing `@victim` in any post — repeatable at the throttle ceiling indefinitely — while the victim sees nothing in-app to report. The trending path *does* filter blocks (`push_listener.py:849-953`), which shows the intent; the event-driven paths were never given the same filter.

Deletion is not re-checked either. Content is snapshotted into the payload at enqueue (`push_listener.py:295`) and never re-validated: `_do_reply_push` re-reads only the *parent* post's context (`shared/push.py:572`), and `_do_mentions_push` explicitly tolerates the post being gone, proceeding when `_fetch_post_context` returns `None` (`shared/push.py:684-690`) and pushing the payload text anyway (`:734`). An attacker posts abusive content mentioning the victim and deletes it within seconds; the inbox shows nothing, the device still displays it, and the delivered content is unrecoverable.

**Remediation:** apply `_get_blocked_users` in `_send_push_to_user`, and re-check `deleted` for the triggering post at delivery time. Both are single queries in code paths that already hold an indexer cursor.

---

## M-2 (Medium) — Uncapped mention fan-out silently destroys everyone's notifications

**Status: fixed in v1.36.0.**

`_extract_mentions` returns every distinct `@word` in a post with no cap and no check that the username exists (`shared/push.py:355-359`), and the listener enqueues one outbox row per mention:

```302:317:web/backend/push_listener.py
                    for mentioned_username in _extract_mentions(content_text):
                        enqueue_push_event(
                            cur,
                            mention_event_key(txhash_lc, mentioned_username),
```

At ~4 bytes per token inside a 20,000-character subscriber post, one comment produces roughly 5,000 rows, all immediately due. The single outbox thread drains 50 per tick (`push_listener.py:42`, `push_events.py:78-79`), and each bogus row still costs a fresh indexer connection and a username lookup plus a second backend connection to settle — with no connection pool.

Legitimate pushes queued behind the flood are **destroyed, not delayed**: anything older than 30 minutes is marked terminal without ever being delivered (`push_listener.py:746-754`). Cleanup cannot keep up either, deleting at most 5,000 rows per hour (`push_listener.py:46`, `:1043-1062`) against ~5,000 rows per post.

The existing cap does not help. `MAX_MENTION_PUSHES = 10` is applied at *delivery*, to the owners resolved from a single row (`shared/push.py:727-729`), and rows are keyed per username (`push_events.py:23-26`), so it bounds nothing at the queue level.

Same code path, secondary effect: up to 200 posts are enqueued in one transaction (`push_listener.py:263-323`), and the source cursor advances only on commit (`:221-232`), so a transaction that fails is retried identically forever.

**Remediation:** cap mentions per post at enqueue and resolve usernames to existing owners before inserting rows.

---

## M-3 (Medium) — `/api/upload_media` parses the whole body before the per-kind cap

**Status: fixed in v1.36.0.**

The comment states the probe runs before the body is materialized. The line above it already materialized it:

```8259:8271:web/backend/routes/public.py
        kind = (request.form.get("kind") or request.args.get("kind") or "").strip().lower()
        if kind not in ("image", "video"):
            return api_error_code("media_invalid_kind", 400)

        # Bound before request.files materializes the body into memory/disk.
        # Multipart framing adds a small overhead above the raw file size, so
        # allow 1 MiB of slack on the Content-Length probe; the post-read check
        # still enforces the exact per-kind cap.
        max_bytes = max_image_bytes() if kind == "image" else max_video_bytes()
        content_length = request.content_length
        if content_length is not None and content_length > max_bytes + (1024 * 1024):
```

Accessing `request.form` invokes Werkzeug's multipart parser, which consumes the entire stream and spools the file part to disk. The `request.args` fallback does not avoid it — `request.form` is evaluated unconditionally.

The only bound that actually applies during that parse is the global one, which is sized for video and applied identically to images:

```52:54:web/backend/factory.py
    from media.base import max_video_bytes

    app.config["MAX_CONTENT_LENGTH"] = max_video_bytes() + (16 * 1024 * 1024)
```

With the fleet values `MEDIA_MAX_VIDEO_MB=1500` and `MEDIA_MAX_IMAGE_MB=15` (`deploy/templates/env/backend.env:109-110`), an unauthenticated `kind=image` upload is fully transferred and written to disk up to **1516 MiB** before the 413 at `:8271`. The per-kind probe is dead as a guard. For a body under the global cap, `data = f.read()` (`:8276`) then copies the whole file into the worker's RAM before the post-read check and before magic-byte validation.

The exposure is bounded rather than unlimited, which is why this is Medium: `MAX_CONTENT_LENGTH` is enforced. But the edge permits 4 uploads per 10 s per IP with a 1600 MB body allowance (`Caddyfile:69-79`), each occupying a sync worker for the full transfer, in a container shared with `miraged` and PostgreSQL.

Applies only where uploads are enabled — the template default is `false`, and `deploy/migrations/v1_29_0_media_uploads_enabled.py` turns it on for domain nodes.

**Remediation:** read `kind` from `request.args` only, or set `request.max_content_length` per kind, before any access to `request.form`.

---

## M-4 (Medium) — `user_last_seen` is written before any signature check

**Status: fixed in v1.36.0.**

The helper's name implies a verified identity; it performs no verification and writes to the database as a side effect:

```149:154:web/backend/routes/core.py
def derive_address_from_pubkey(pub_dec: bytes) -> str:
    addr = _derive_address_from_pubkey(pub_dec)
    if addr:
        source = request.path if has_request_context() else ""
        update_user_last_seen(addr, source=source)
    return addr
```

The underlying derivation checks only the byte length, never that the bytes are a valid curve point (`web/backend/node.py:282-294`), so any 33 bytes yield a distinct valid-looking address.

I enumerated every `core_bp` route programmatically: **in all 28 routes that derive an address, the derivation precedes any signature verification, and 16 of them perform no backend signature check at all** (they rely on the chain ante, which is the intended design for the relay itself — but the database write happens first regardless). Using `/api/core/unblock_post` with a random 33-byte pubkey and a 64-byte zero signature, the row is committed at `core.py:2161` before the request fails downstream.

Two consequences. The value is published: `active_7d` on the unauthenticated welcome screen is the union of chain-active users and `user_last_seen` rows (`routes/public.py:9036-9042`), and the same table is the entire basis for admin DAU/MAU. Because every distinct 33-byte string yields a distinct address, the published active-user count inflates without bound — the 60-second throttle is keyed per address (`user_last_seen.py:50-66`), so distinct addresses bypass it entirely. And the table has no TTL (`db.py:186-194`), so this is unauthenticated unbounded row insertion, plus growth of a 50,000-entry in-process cache.

**This is not the accepted L-7.** That finding was the query-string `address` path, and its fix asserts an invariant that does not hold. The comment at `factory.py:104-108` states last-seen "is written only where the address came from a verified public key (see `derive_address_from_pubkey`)" — but that function verifies nothing, and the regression test only probes the query-string path (`tests/cases/test_backend_security.py:1830-1848`).

**Correction to the subagent finding this originated from:** it claimed an attacker can write last-seen "for any address", implying a victim can be made to look active. That is wrong — hitting a *specific* address requires a RIPEMD160(SHA256(·)) preimage. The real impact is unbounded *distinct* addresses, which inflates aggregates and grows the table, not targeted manipulation of a chosen account.

**Remediation:** move the write behind the signature check, or key it on `g.verified_request_address`, which `_verify_signature` already sets (`routes/core.py:732-733`).

---

## M-5 (Medium) — No backend ceiling on validator-funded relay fees

**Status: ACCEPTED AS RISK. Do not raise again.**

The validator signs the outer transaction and pays the fee. The fee is `gas_limit × min_gas_price`, where `gas_limit` is derived mechanically from a user-controlled payload with **no upper bound anywhere in the backend** — no `min()`, no absolute cap, and no comparison against any chain parameter, at any of the 25 relay construction sites (`gas_limit = max(gas_est, int(gas_used * 1.25))`, e.g. `routes/core.py:4065`).

`relay_max_gas_fee` — the parameter that exists to bound exactly this — is required at startup (`web/backend/params.py:40`) and **never read**. Verified by search: the only two occurrences in the tree are the proto field definition in `shared/datatypes.py:509` and the required-params list itself. The backend fails hard if the parameter is absent and then ignores its value.

The brake that does exist is proof-of-work, and paid users skip it: `is_subscriber()` reads `profiles.level >= 1` from the indexer and bypasses the PoW branch on every relay route (`routes/core.py:628-658`, and 20 call sites logging `pow_ignored`). The compensating user-side charge is capped at 500 MIRAGE and burned rather than credited to the validator, and it is computed from the handler's gas only, excluding the tx-size gas the validator paid for.

The chain-side absence of an ante fee ceiling is a recorded deliberate decision, on the stated grounds that the payer signs the exact amount and therefore consents. That reasoning does not transfer here: the payer is a program computing the amount from attacker input with no ceiling, so the consent is mechanical. Bounding belongs on the backend side and is absent.

I am filing this Medium rather than High because the quantification depends on production gas prices and tier configuration I did not measure against a live node, and because the free-tier variant is self-limiting through PoW. The unconditional part — a required parameter that is never consulted — is a defect regardless.

**Remediation:** compare the computed `gas_limit × min_gas_price` against `relay_max_gas_fee` before signing and reject above it. The parameter is already loaded.

---

## L-1 (Low) — Invite reward inserts have no `ON CONFLICT`

**Status: fixed in v1.36.0.**

Steps 4 and 6 of `_process_invite_quest_completion` are the only two `pending_rewards` inserts in production code without an `ON CONFLICT` clause (contrast `quest_tracker.py:501`, and step 5 immediately between them at `routes/core.py:332`, which has one):

```318:324:web/backend/routes/core.py
            cur.execute(
                """
                INSERT INTO pending_rewards (owner, reward_type, reward_data, reason, created_at)
                VALUES (%s, 'mirage', %s, 'quest:invite_recruit', %s)
                """,
                (referrer_addr, json.dumps({"amount": reward_amount_umirage, "apply_multiplier": True}), now_ts),
            )
```

Two defects. The sequence runs on an autocommit cursor, and the step-2 read (`:285-292`) is unprotected from the step-3 write (`:306-313`) — so two *different* new users registering concurrently with codes from the same referrer both observe the quest incomplete, and the referrer is paid 10,000 MIRAGE twice for one day's quest. And when two requests do collide inside the same second, the missing `ON CONFLICT` raises a unique-index violation mid-sequence; because step 3 has already committed, the referrer's quest is marked complete, the exception unwinds past step 6, and **the referee's 10,000 MIRAGE is never written** and can never be retried, since step 2 now short-circuits.

**Distinct from H-5 and from the deferred pair-level idempotency item.** H-5 was re-payment to the *same* pair on a repeat `set_username`, closed by the `is_new_user and code == 0` gate. Here the pairs are genuinely different; the missing guard is per-referrer-per-day idempotency, which no recorded fix covers.

**Currently inert** — `deploy/migrations/v1_28_5_disable_referral_bonuses.py` set `QUESTS_INVITE_RECRUIT_CHANCE=0` fleet-wide, and assignment is a strict `value < chance` test. It re-arms fully when referral rewards are switched back on, which is the same trigger already recorded for the deferred pair-level work. These belong in one change.

---

## L-2 (Low) — `/api/search_username` does not escape LIKE metacharacters

**Status: fixed in v1.36.0.**

Every other search path sanitizes first — `like_query = query_lower.replace("%", "\\%").replace("_", "\\_")` (`routes/public.py:4989`), and `search_topics` strips to alphanumerics outright (`:4822`). `search_username` interpolates `q` raw into four LIKE patterns (`:4542-4548`).

Not SQL injection: psycopg parameterizes correctly. It is wildcard injection. `?q=%` yields the pattern `%%%`, matching every profile and forcing the CTE at `:4518-4529` to evaluate `LOWER()` and a conditional `SUBSTRING` over every row before `LIMIT 20` applies; `?q=_` enables username enumeration by structure; `?q=\` produces a trailing escape character and an unauthenticated 500. Bounded by short username lengths, so the DoS tail is modest.

---

## Corrections made during verification

Two claims from the parallel audits did not survive re-verification and are recorded so they are not re-derived later.

1. **The C-1 timings were wrong in the original candidate**, which reported 6.1 s at a 27-character pattern. My first reproduction measured 0.001 s at the same size, because the subject string it used failed the match early. Re-deriving the worst case within the chain's real constraints gave a much steeper curve — 23.8 s at 34 characters and beyond 30 s at the maximum legal 35 — so the finding is materially *worse* than filed, not better. The genuinely new part, which no subagent found, is the push-listener blast radius: it converts an attacker-must-keep-requesting DoS into a one-transaction, zero-traffic, platform-wide outage, and it is the reason this is Critical.

2. **M-4 was filed as "write last-seen for any address."** Targeting a chosen victim needs a hash preimage. Corrected to unbounded distinct addresses; see M-4.

---

## Candidates chased, and the guard that killed each

A clean result is only meaningful if the attempts are visible.

| Candidate | Guard that killed it |
| :-- | :-- |
| `/api/rewards/debug/{complete,reset,set_completed}` minting rewards with no signature — confirmed they *do* insert into `pending_rewards` (`quests.py:954-971`) and fabricate completions that raise the multiplier (`:1063-1072`) | Three independent guards. `_is_debug_enabled() = BACKEND_DEBUG and _is_localhost()` checked at the top of all four handlers (`quests.py:770-771`, `:793`, `:895`, `:987`, `:1030`); `BACKEND_DEBUG` is a **required** bool that raises on absence (`settings.py:17-25`) and ships `false` (`backend.env:18`); `_is_localhost` uses `get_trusted_client_ip()` and never reads a forwarding header (`quests.py:774-783`). The `CF-Connecting-IP` spoof fails because Caddy overwrites that header with its own `{client_ip}` (`Caddyfile:81`, `:102`), and gunicorn binds loopback (`gunicorn_config.py:15-17`). |
| SQL injection anywhere in the backend | Re-verified, not taken on faith: AST extraction of every f-string interpolation inside SQL across `routes/*.py`, `stats.py`, `similarity.py`, `db.py`, `seen_posts.py`, `quest_tracker.py`, resolving each name to its assignment. All interpolations are `%s` placeholder lists or fixed internal literals. `ORDER BY` is a literal (`public.py:5665`); the user-facing `by` parameter is validated against a two-value allowlist and selects a Python branch, never SQL text (`public.py:5521-5522`). `_db_list_contains` interpolates a table and column name, and all six call sites pass string literals. |
| Concurrent reward claims double-spending | `pg_advisory_xact_lock(hashtext(owner))` taken before the unclaimed read inside a real transaction (`reward_distributor.py:459-477`), plus per-row `WHERE id = %s AND claimed_at IS NULL` (`:674-681`). |
| Crash after payout broadcast paying twice | Signed bytes persisted before broadcast (`reward_distributor.py:599-611`); reconciliation resolves by hash (`:239-267`); rebroadcast uses `release_definitive=False` so an ambiguous CheckTx cannot release rows. |
| Payout amount or recipient from client input | Amount comes from server-written `reward_data`, type-checked as a positive non-bool int (`reward_distributor.py:505-506`); recipient is the signed owner, bech32-validated twice. Rounding truncates downward, favouring the pool. |
| Multiplier from a user-influenceable source | `get_reward_multiplier` counts only server-written completion rows, capped at 5.0 (`quest_multiplier.py:10-20`). The H-3 race does not inflate it — both writers upsert the same primary-key row. |
| Account delete then re-register replaying the invite reward through `is_new_user` | `MsgDeleteUser` is a soft delete leaving `username` intact (`indexer/database.py:1997-2004`), and `is_new_user` tests `username` (`routes/core.py:1045-1050`). |
| The `quest_assignment.py` advisory-lock fix being cosmetic | Verified sound: `conn.autocommit = False` before the lock so it is genuinely transaction-scoped (`:45-48`), read inside the same transaction after the lock (`:194-195`), identical key in both callers, and a post-insert re-read that raises to force rollback (`:220-225`). |
| Attacker-chosen fee payer (C-1 regression) | `tx.py:96` hardcodes `fee_payer=rt.validator_payer_addr`; the outer SignDoc covers `auth_info` (`tx.py:140-146`); no route accepts a payer field. |
| `authority` set to a user-controlled address | All 25 assignments read `require_runtime().validator_payer_addr`. The canonical PoW bytes deliberately exclude the authority field (`pow.py:5-7`), so a user cannot sign over it. |
| Broadcast mode / sequence queries violating project rules | `BROADCAST_MODE_SYNC` (`tx.py:349`), `sequence=0` with the unordered flag (`tx.py:133`, `:404-417`); the only account query is a one-shot startup `account_number` fetch. Compliant. |
| `params.py` silently defaulting a missing chain parameter | Raises `RuntimeError` on any missing or non-coercible required param (`params.py:55-71`); `expect_params()` raises if uninitialized. Compliant. (One route-level violation noted below.) |
| DNS rebinding, IPv4-mapped IPv6, octal/decimal encodings, CGNAT, `0.0.0.0`, link-local against `fleet_url` | All dead. Validation resolves and *keeps* the addresses, and the request is addressed to a resolved IP with SNI and certificate validation pinned to the original hostname (`fleet_url.py:180-188`), so there is no second resolution to race. Split-horizon is handled deliberately: any non-global answer disqualifies the host (`:89-99`). `session.trust_env = False` removes proxy-env influence. |
| `stream_proxy` host escape, encoded-slash traversal, open proxy, request smuggling | `_STREAM_UID_RE` is hex-only with `fullmatch` (`public.py:82`, `:8331`); the `..` test runs post-decode (`:8337`); query parameters are allowlisted to six keys and re-serialized through `urlencode` (`:87`, `:8356-8363`); `allow_redirects=False` (`:8376`); only three upstream headers are echoed. |
| Filename/path traversal and stored XSS through `local.py` | No user-controlled component reaches the path — the name is a UUID plus a magic-byte-derived extension (`media/local.py:31-34`), and `_abs_path` re-checks containment with `realpath` (`:36-42`). `sniff` can only return image/video extensions (`media/base.py:76-101`), and Caddy serves `/media/*` with `nosniff` (`Caddyfile:114-117`). |
| Media provider credentials leaking into a response or log | Bunny keys and the Cloudflare token are used only as request headers; no log statement or response field carries them; provider failures become fixed strings. |
| Push token registered for another user, or a victim's token unregistered | Address derived from the verified pubkey and the signature covers the token (`routes/core.py:5047-5053`); unregister is owner-scoped (`:5172`). No route selects tokens, and register returns a constant body, so there is no existence oracle. |
| Push outbox poison pill or incorrect lease/settle | A DB `CHECK` forbids non-object pending payloads (`db.py:245-255`); per-row exceptions are caught and bounded by max attempts and a 30-minute age (`push_events.py:12-13`); every settle carries `AND status = 'pending'` and hard-fails on `rowcount != 1`; workers lease with `FOR UPDATE SKIP LOCKED`. |
| Admin level spoofed or supplied by the request | `get_user_level` reads `profiles.level` from the indexer and returns 0 on any exception — fails closed (`routes/core.py:857-869`); the client-supplied `admin` field is overwritten with the pubkey-derived address before the check. |
| A signature for action A replayed as action B | Every action string is distinct and inside the signed bytes (`routes/core.py:836`). The only shared string is `stats`, which is H-2. |
| Stack trace, SQL, or file path in a 500 body | `safe_error` returns a fixed body plus a correlation id (`error_utils.py:269-277`); `DEBUG`/`TESTING` forced off (`factory.py:44-46`); `HTTPException`s surface only `e.name`. |
| `X-Forwarded-For` trusted anywhere | Not read anywhere in the backend; `get_trusted_client_ip` uses `CF-Connecting-IP` then `remote_addr` only (`client_ip.py:29-45`). |
| IDOR on `get_inbox`, `get_preferences`, `get_user_blocked`, `bootstrap`, `referrals/summary` | Unauthenticated as written, but this is the reclassified H-2 from 2026-08-05, accepted as deliberate disclosure and pinned by `ROUTE_POLICY` in `tests/cases/test_backend_authz.py`. No deviation from the recorded decision found. `get_invite_codes` is correctly gated behind a signed read. |

---

## Sub-threshold observations

Recorded because they are cheap to fix or explain why an adjacent claim was not filed, not because they warrant their own finding.

- **No `statement_timeout`, no connection pool, and ignored timeout arguments.** Covered in the summary; it is the amplifier under C-1, H-1 and L-2. `connect_db(timeout=30.0, …)` at `public.py:7431` is the clearest example of a call site implying a bound that does not exist.
- **`similarity.py:159` caches only non-empty results.** The write is inside `if similarities:`, so an address below `MIN_SHARED` never gets a cache row and the full cross-user Pearson aggregate — which the module's own comment prices at 100–500 ms — re-runs on every request. Reachable unauthenticated with an arbitrary `address` via `/api/get_similar_users` and the magic home feed. One-line fix: negatively cache the empty result.
- **Hardcoded fallbacks contradicting the no-fallbacks rule.** `routes/core.py:3895-3903` falls back to `max_topic_size = 50` / `min_topic_size = 3` on exception, though both keys are in `_REQUIRED_INT_PARAMS` so the fallback is dead by construction — and 50 is wrong anyway, the chain default being 35. Compare `core.py:954-960`, which correctly fails to 503.
- **PoW precheck silently disabled per request.** `argon2_digest` returns `None` on any exception (`pow.py:520-521`), including a `last_block_hash` shorter than Argon2's 8-byte salt minimum, and call sites skip the check when the digest is `None` (`routes/core.py:1010-1014`). The precheck is advisory by design and the chain still rejects, so no fee is spent — but `_log_pow_precheck_error`, documented as the alert signal for "the precheck is broken and every proof is reaching the chain unscreened" (`core.py:510-522`), is called only from the `except` branch. The `None` path emits nothing, so the exact condition the alert exists to catch is invisible.
- **Chain params are snapshotted once at startup and never refreshed.** `load_params()` runs once (`factory.py:183`) and caches unconditionally; `force=True` is never called. A governance change to `block_hash_window`, `pow_base_bits`, or tier limits is invisible until restart — including the hash window the backend serves to clients, which is the coupling the comment at `chain.py:205-216` says it is protecting.
- **`node.py:336` can log the validator private key on one error path.** If a future `miraged` prints the key with a same-line prefix, the 64-hex `fullmatch` fails and the error embeds `out[:200]`, which contains the key. Startup runs at import under gunicorn, so it would land in the startup log. Success-path handling is clean — the key never reaches argv or a log.
- **No redaction in the logging layer.** `log_event` formats whatever the caller passes with no filtering (`logging_utils.py:42-48`) and `configure_logging` installs no filters. Hygiene is entirely per-call-site; it currently holds (signature call sites log `has_pubkey=bool(...)` only), but nothing enforces it.
- **`EXPO_ACCESS_TOKEN` is the one security-relevant setting that is silently defaulted.** Empty means `_expo_headers` omits the `Authorization` header entirely (`shared/push.py:77-79`), so a missing or mistyped token quietly downgrades to unauthenticated pushes instead of failing. Every other flag in `settings.py` is required.
- **Predictable push-listener lock path.** `/tmp/mirage_push_listener.lock` opened `"w"` with no `O_NOFOLLOW` (`push_listener.py:43`, `:63`). A local process holding the flock stops all push delivery with one INFO line. Requires local code execution.
- **Uncapped `push_tokens` per owner.** Registration validates token shape but has no per-owner cap (`routes/core.py:5035-5090`), and delivery builds one unchunked Expo message per token (`shared/push.py:321-329`) against Expo's documented 100-message limit.
- **`/api/get_agents` and `/api/get_topics` run four full-table aggregations each, unauthenticated and uncached**, while `/api/get_welcome_stats` caches for 30 s — the pattern exists and was not applied.

---

## Verification performed

- Full source audit of all 34 backend Python files, the 87-route authorization inventory plus the four debug handlers, the backend DB schema, and the deploy templates that set backend policy.
- Route-level programmatic check of derive-versus-verify ordering across all 28 address-deriving `core_bp` routes (the M-4 evidence).
- Empirical measurement of the C-1 backtracking curve in an isolated subprocess with a hard time budget, using the exact construction at `routes/public.py:705-706` and only chain-legal inputs. Chain acceptance verified by reading `validateBlockedTopicPattern` and `validateTopic` rather than inferring from the backend validator.
- `python -m compileall -q web/backend shared` — clean.
- `bandit -r web/backend shared` — 25,793 lines, **zero High**, 57 Low, 102 Medium. The Mediums are dominated by conservative B608 flags on the static SQL composition re-verified above; the Lows are `random.getrandbits` in `tx.py:384-389`, which seeds an unordered-tx timeout nonce, not a secret.
- `pip-audit -r web/backend/requirements.txt` — two advisories, `PYSEC-2026-3002` (pynacl) and `PYSEC-2026-1325` (ecdsa), both transitive through `cosmpy` and both already documented as accepted with per-advisory reasoning in `scripts/audit_python_deps.sh`. No new advisory. Not re-reported.
- **Not run:** `tests/test_backend.py` and `tests/test_blockchain.py`. Both submit real transactions and may only run inside local Docker after raising the PoW message limit. C-1 in particular wants an end-to-end test, which is the natural next step.
- **No production or fleet host was contacted.** Every statement about deployed configuration comes from `deploy/templates/` and the migrations. Unlike the 2026-08-13 sweep, this review has no live-fleet verification section; where a finding's reachability depends on runtime configuration (H-3, L-1, M-3) that is stated explicitly rather than assumed.

---

## Assumptions

- Runtime flags match the tracked deploy templates and migrations unless an operator overrode them; not verified against any live node.
- The chain ante remains the authoritative enforcement boundary for relay writes; the backend's checks are defence in depth except where noted.
- A validator moniker, a P2P peer moniker, and an on-chain blocked-topic pattern are all treated as hostile input.
- Existing accepted-risk decisions in `open-items.md` remain accepted; this review does not silently reopen them.

---

## Suggested remediation order (superseded)

Kept for the record. Everything below except M-5 shipped in v1.36.0; see
[Remediation](#remediation) for what was actually done.

1. **C-1** — cap the wildcard count at validation and at match time, and replace the regex with the chain's linear matcher. The push-listener half is the reason this is first.
2. **H-1** — clamp `page` at the entry points and apply the existing `min(…, 500)` to the five uncapped pool computations. Smallest diff of the four top findings.
3. **Set a `statement_timeout` on both DSNs**, and either honour or delete the ignored `timeout` arguments in `db.py`. This is what makes the whole class survivable rather than fatal.
4. **H-2** — bind fan-out destinations to a configured roster and make the proof per-destination.
5. **H-3 and L-1 together** — one advisory lock per owner around quest completion and the invite sequence, plus `ON CONFLICT` on the two invite inserts. L-1 must land before referral rewards are re-enabled, alongside the already-deferred pair-level idempotency work.
6. **M-1, M-2** — block and deletion checks at push delivery; cap mentions at enqueue.
7. **M-3, M-4, M-5, L-2** as capacity allows.

---

## Remediation

Shipped in **v1.36.0**. Every fix below has a behavioural regression check in
`tests/cases/test_backend_hardening.py` (category `backend_hardening`, walletless).
The set was mutation-tested: each fix was reverted in turn inside the container and
the corresponding check confirmed to fail. All 18 mutations were caught.

| ID | Status | What was done |
| :-- | :-- | :-- |
| **C-1** | Fixed | `topic_matches_pattern` in the new `web/backend/topic_glob.py` is a direct port of the chain's linear `topicMatchesPattern`, verified against the Go original across 6,047 differential cases. Wildcards are capped at 4 at the validator (`routes/core.py`), and `_blocked_topics_sql` drops over-cap patterns from the `LIKE` pre-filter rather than bounding them, since `_topic_is_blocked` remains authoritative and linear. |
| **H-1** | Fixed | `_clamp_page` floors at 1 and caps at `MAX_FEED_PAGE = 200` at every entry point; the five uncapped pool computations now apply `min(…, MAX_CANDIDATE_POOL)` and the inbox path `min(…, MAX_INBOX_ROWS)`. |
| **H-2** | Fixed (one part scoped out) | Fan-out destinations come from the operator-configured `STATS_FLEET_ROSTER`, which requires `https://` and a fully-qualified hostname — bare IPs are rejected, since they cannot present a name-matching certificate. P2P moniker discovery and the `http://` endpoint synthesis are deleted. Peer responses are strictly validated and normalised by `validate_peer_stats`. **Per-destination proofs are not implemented**: the proof format is shared with the client and scoping it per host is a protocol change. The roster removes the attacker's ability to choose a destination, which is the exploitable half. |
| **H-3** | Fixed | Daily and flash quest completion now run inside `_locked_transaction("quest_assignment:<owner>")`, sharing a key with quest assignment so the two serialise against each other. A `_cursor` context manager threads one cursor through every nested helper so the read-decide-write is a single transaction. Verified against a real PostgreSQL: two concurrent completers produced two reward rows unlocked, one locked. |
| **M-1** | Fixed | `_send_push_to_user` takes the actor and drops the notification when the recipient — or an agent they enabled — has blocked them, mirroring the inbox filter; the lookup fails closed. Reply and mention delivery re-check that the source post still exists and is not deleted, instead of pushing the snapshotted text. |
| **M-2** | Fixed | Mentions are capped at `MAX_MENTIONS_PER_POST = 10` per post at enqueue, and unresolvable `@words` are dropped after a single batched lookup rather than each costing a row and a connection. A 20,000-character post drops from 3,015 outbox rows to at most 10. |
| **M-3** | Fixed | `kind` is read from the query string only; reading it from `request.form` was what forced Werkzeug to parse and spool the whole body before the per-kind cap could be chosen. `request.max_content_length` is also set so a chunked upload declaring no `Content-Length` is cut off at the per-kind limit. The web client now sends `kind` in both places. |
| **M-4** | Fixed | `derive_address_from_pubkey` records a candidate; an `after_request` hook writes `user_last_seen` only when the response is under 400. Relay routes stay counted — they are authenticated by the chain ante and a rejected transaction returns 400 — while a forged pubkey now writes nothing. |
| **M-5** | **Accepted as risk** | No backend ceiling on validator-funded relay fees. Not to be raised again. |
| **L-1** | Fixed | The invite sequence takes the same per-referrer advisory lock, and both reward inserts carry `ON CONFLICT … DO NOTHING` on the existing unique index. |
| **L-2** | Fixed | `_escape_like` escapes backslash first, then `%` and `_`; applied to `/api/search_username` and to the sibling path, which escaped the metacharacters but not the escape character and so returned an unauthenticated 500 for `?q=\`. Verified against PostgreSQL: `%` went from matching every row to matching only its literal. |

### Cross-cutting

`statement_timeout`, `lock_timeout` and `connect_timeout` are now set on both DSNs
via `libpq` options, and `connect_db`'s previously-ignored `timeout` and
`busy_timeout_ms` arguments are honoured. Schema initialisation runs with the
statement timeout disabled so migrations cannot be killed mid-flight.

### Sub-threshold observations

All nine were fixed: negative caching for `similarity`, the dead
`max_topic_size = 50` fallbacks replaced with a 503, `argon2_digest` raising instead
of returning `None` (plus the one remaining `except Exception: pass` at the vote
path), a 60-second param refresh TTL with backoff, the private key no longer echoed
in the export error, `O_NOFOLLOW` on the push-listener lock, a 20-token per-owner
cap, and a 30-second cache on the anonymous topic aggregation.

**One was deliberately not made fatal.** `EXPO_ACCESS_TOKEN` is empty on every node
in the fleet while `PUSH_NOTIFICATIONS_ENABLED=true`, so raising at import — the
treatment every other required setting gets — would take the fleet offline on
upgrade rather than fix anything. It logs an error at startup instead. Closing it
properly needs a token issued and enhanced security enabled in the Expo dashboard
first; until then, anyone holding a copy of the push-token table can send pushes to
users. Tracked in `open-items.md`.

### Correction found while testing

The C-1 regression test initially used the pattern `a*a*…*b`, which the review's own
table would have predicted was expensive. It is not: Python's engine rejects on a
required-literal check and returns in 0.1 ms. The cost depends on the topic as much
as the pattern — a full-length topic whose last character cannot match forces the
engine to exhaust every split. The test now uses a 17-segment pattern against such a
topic, measured at 22.3 s. This does not change the review's finding or its measured
curve; it means an exploit needs both halves chosen correctly.
