## Cursor Operational Rules

### #1 RULE: NEVER COMMIT OR PUSH TO GIT WITHOUT MY EXPLICIT APPROVAL.
- Do NOT run `/commit-push` or `git commit`, `git push`, or any combined commit+push command unless I specifically tell you to.
- After making code changes, STOP and wait for my go-ahead before committing.
- Do NOT auto-commit when follow-up changes occur. Each commit requires fresh approval.

### SERVERS

Addresses are not in this repo — it is public. They live in `.env` on the
operator's machine (`MIRAGE_FLEET_HOSTS`); see `.env.example`. Refer to hosts by
role in code, docs and commit messages.

- **val1**: PROD SERVER. Domain is mirage.talk
- **val2**: UAT SERVER. mirage.vote is the domain
- **val3**: 3rd node, no public domain
- **val4**: 4th node, no public domain

**NEVER INTERACT WITH PRODUCTION SERVERS!**
- Do NOT run scripts, queries, or any commands against production IPs or domains
- Do NOT SSH, curl, or connect to production in any way
- For testing, ONLY use local docker (127.0.0.1)
- It is OK to interact with servers in a purely informative way, e.g. getting logs, but not changing anything on the server.

**EXCEPTION — UAT server only (val2 / `mirage.vote`):** the agent MAY SSH
into and make changes on the UAT server when a task explicitly requires it (e.g.
the Bunny edge cutover). This carve-out is scoped to UAT ONLY. The PROD server
(val1 / `mirage.talk`) and the other validators (val3, val4) remain strictly
no-change / informative-only — never SSH to change anything there without
separate, explicit per-task approval.


### Terminology Consistency

**ALWAYS BE CONSISTENT.** Pick one term per concept and use it everywhere — UI copy, labels, settings, comments, error messages, docs.

- **Platform members are "users", never "people".** Use "users" in all user-facing strings (`Follow users`, `Sidebar users`, `Lets users sign up`, etc.) and in code comments. The only exception: existing localStorage / API keys / wire formats (e.g. `sidebar_people_limit`) — never rename those because the data is already on disk. JS variable names that mirror those storage keys can stay too; just keep visible strings consistent.
- Before adding a new term for an existing concept, search the codebase first. If a term already exists, reuse it.
- When you spot a stray inconsistency adjacent to your work, fix it (with a one-line note in the summary). Don't leave a half-consistent codebase.

### Code Quality

- **No redundant comments**:
  - Do not repeat values that are already visible in the code (e.g., `// 20 = 20%` next to `Percent: 20`)
  - Do not add "for testing" comments; values speak for themselves
  - Comments should explain WHY or provide context not obvious from the code

- **Do not use fallbacks**:
  - NEVER add fallbacks. Fail hard. No backward-compatibility handling or comments.
  - Anything that could potentially mask buggy behavior must fail immediately so issues surface early.

- **Fail fast and surface errors**:
  - On timeout/deadline, exit non-zero and print a clear error message.
  - Do not hide errors; avoid suppressing with `2>/dev/null` unless explicitly intended.

- **No indefinite loops in scripts**:
  - Loops must have a termination condition and an overall time budget.
  - Prefer event-driven patterns (e.g., WebSocket subscriptions) over tight polling.

### Blockchain Rules

- **Transaction broadcast mode**:
  - Always use unordered transactions; never ordered. Avoid sequence queries.
  - Broadcast mode must be "sync" or "async". Never "block".

- **Message Authority**:
  - `authority` field is ALWAYS the validator/node address OR governance module address
  - NEVER set `authority` to the user's address
  - User's address is derived from `envelope_pubkey`

- **Failure policy — the node must not die, and must not fork either**:
  - This **narrows the general fail-hard rule above for `blockchain/` only**. Everywhere
    else (backend, indexer, deploy scripts, tests) the general rule is unchanged.
  - **Outside block finalization — return errors, never exit.** Public queries, CheckTx,
    ReCheckTx and Simulate commit nothing, so no divergence is possible and killing the
    process buys no safety at all. Any reader with an `error` return propagates it. A
    reader without one gates on `ExecMode() == ExecModeFinalize` and only then halts.
    The backend simulates every user action, so these paths are reachable from public RPC
    and must never be able to take a validator down.
  - **During finalization — never continue past a fault that would change the AppHash.**
    A node that keeps going after a store fault commits state its peers did not and has
    silently forked, which is worse than stopping: the chain survives one halted validator,
    but a forked one is off consensus while reporting healthy. This is the `v1.34.0`
    fail-closed contract and it stands.
  - **Halt cleanly; do not crash.** A bare `panic` with a stack trace is not an acceptable
    operator experience. Consensus-fatal conditions go through `consensusfatal` with a
    named reason, an actionable message, and a preserved forensic snapshot (see the node
    recovery rule below). Raw panics on consensus paths should be converted as they are
    touched.
  - **Never swallow.** Silently substituting a zero, an empty list or a default for a
    failed read is the worst of the three options: it neither reports nor stops, and it is
    how a node forks without anyone noticing. Return the error and let the caller decide.

### Node Recovery — ALWAYS Snapshot Diverged State Before Wiping

**HARD RULE (NON-NEGOTIABLE): Never destroy a diverged chain DB without first preserving it.**

- A divergence/AppHash-mismatch recovery (peer-pull, state-sync, manual wipe) MUST take a forensic snapshot of the diverged chain DBs BEFORE any wipe.
- This is enforced in `scripts/recover.sh` at the single wipe chokepoint (`wipe_chain_dbs` → `snapshot_diverged_state`). The diverged DBs are moved into `/root/.mirage/.divergence_forensics/<utc>-h<height>/` (rename = instant + lossless) with a `MANIFEST.txt` (height, app_hash, version, mode).
- It is NOT gated by `--force`, NOT optional, and applies to BOTH automated (watchdog) and manual recovery. The diverged state is the single most valuable artifact for root-causing the divergence (replay the offending block).
- If you ever add a new recovery path that removes chain DBs, it MUST route through `wipe_chain_dbs` (or call `snapshot_diverged_state` first). Without the diverged DB, the divergence cannot be diagnosed — getting back online fast is no excuse for losing it.
- Retention is bounded by `FORENSIC_KEEP` (default 2). Tune via env, never disable the capture.

### Client IP — Trusted Sources Only

- **NEVER trust `X-Forwarded-For`** — trivially spoofable by the client.
- Use `CF-Connecting-IP` (set by Cloudflare, not spoofable) with fallback to `request.remote_addr` (TCP peer, not spoofable).
- See `get_trusted_client_ip()` in `web/backend/client_ip.py`.

### Database Schema Changes

- **Approval required**:
  - Never create new tables or add columns without explicit confirmation from me.

- **Do NOT create new tables when an existing table can be extended.** Add a column to an existing table instead.
- Only create a new table when the data has a genuinely different primary key or lifecycle.
- Always check existing schema in `web/backend/db.py` and `indexer/database.py` before proposing new tables.

### Query Sources - Dual-Database Backend Architecture

- **Two PostgreSQL databases**: `mirage_indexer` (indexer-owned, chain data) and `mirage_backend` (backend-owned, operational data).
- **Backend reads chain state from the indexer DB via read-only role** (`mirage_indexer_ro`): profiles, balances, params, difficulty, block hashes, supply, validators. No gRPC.
- **Backend writes operational data to `mirage_backend`**: quests, rewards, push notifications, invite codes, reports, similarity cache, user activity, inbox state.
- **Backend simulates and broadcasts via Cosmos tx REST** (`/cosmos/tx/v1beta1/simulate` + `/cosmos/tx/v1beta1/txs` with `BROADCAST_MODE_SYNC`). No gRPC, no DB tx queue.
- **Local node files are read ONCE at backend startup only** (keyring/config for validator keys and gas price). No re-reads at runtime.
- **Indexer handles chain indexing only** — gRPC for queries, CometBFT WebSocket for live blocks, writes indexed state to `mirage_indexer` DB. Does NOT broadcast transactions. Does NOT touch `mirage_backend`.
- NO FALLBACKS. If either DB is unavailable, the backend returns 503. Hard fail only.

### Chain Parameters - EVERYTHING MUST BE QUERYABLE

**CRITICAL**: When adding or changing ANY chain parameter:

1. **Proto definition** (`node/proto/mirage/core/v1/params.proto`):
   - Add field to `Params` message with unique field number
   - For complex types (like tiers), define separate message type

2. **Go defaults** (`node/x/core/types/params.go`):
   - Add to `DefaultParams()` with sensible default
   - Add validation in `Validate()` if needed

3. **Genesis** (`node/genesis/genesis.json`):
   - Add param with value in `app_state.core.params`

4. **Upgrade handler** (`node/app/upgrades.go`):
   - For existing chains, set default value in upgrade handler

5. **Python datatypes** (`shared/datatypes.py`):
   - Add field to `Params` message definition with SAME field number as proto
   - Export any new message types

6. **Backend params** (`web/backend/params.py`):
   - Add to `_REQUIRED_INT_PARAMS` or `_REQUIRED_FLOAT_PARAMS`
   - Backend MUST fail hard if param is missing

7. **Query endpoints** - ALL params must be queryable via:
   - **gRPC**: `Query/Params` returns all params
   - **REST**: `/mirage/core/v1/params` (auto-generated from gRPC)
   - **CLI**: `miraged q core params`

8. **Dynamic state** (like `current_difficulty`) needs dedicated query:
   - Add to `query.proto` as new RPC method
   - Implement handler in `module.go`
   - Add to Python `datatypes.py`
   - Backend should use gRPC, not ABCI hacks

**NO HARDCODED VALUES IN BACKEND** - Everything comes from the indexer DB (populated by the indexer from chain gRPC).

### Python Environment

- **Use conda environment `mirage-node`** for all Python scripts
- Activate with: `conda activate mirage-node`

### Shell Commands — Avoid Approval Prompts

- Do NOT use `required_permissions: ["all"]` unless absolutely necessary (e.g. `git push`).
- Instead, use the `working_directory` parameter to set the cwd, and just run commands normally.
- For Python scripts: `conda activate mirage-node && python script.py` with `working_directory` set — no special permissions needed.
- Sandbox already allows network and workspace writes, which covers most use cases.

### Profile Data Architecture

**Single Source of Truth**: `ProfileCore` is defined in `node/proto/mirage/core/v1/genesis.proto` and generated into Go code. Do NOT duplicate this struct elsewhere.

**Profile Structure**:
- `ProfileCore` (proto-generated): scalar fields stored at `profiles/{owner}` KV prefix
- List fields stored separately under their own prefixes. Never hand-build these
  keys — use the typed helpers in `blockchain/x/core/types/keys.go` (`fu/`, `bu/`,
  `bp/`) and `kv.go` (`jc|`, `bc|`), which are the source of truth:
  - followed users (`FollowedUsersPrefix`)
  - joined communities (`KeyJoin`, plus its reverse index and count)
  - blocked users (`BlockedUsersPrefix`)
  - blocked posts (`BlockedPostsPrefix`)
  - blocked communities (`KeyBlockCommunity`, plus index/count/next)
- Agents and topics are gone as of v1.39.0. Their prefixes (`ft/`, `ea/`, `bt/`,
  `plist_*`) survive **only** so the v1.39 migration and historical decode paths
  can drain them. Do not write to them.

**Chain list limits — hard cap vs deque**:
- followed users, joined communities: **hard cap** — the chain rejects the transaction when the tier limit is reached. The user must unfollow/leave first.
- blocked users, blocked posts, blocked communities: **deque** — the chain evicts the oldest entry when the limit is exceeded. The indexer stores the full history (up to 100k per user per list) so feed filtering still sees old blocks.
- A tier limit of `0` means the list is **disabled** and the handler rejects the write. It does NOT mean unlimited — the keeper's deque helper reads a zero cap as "never evict", so every deque handler must check for zero itself (see `BlockUser`, `BlockPost`, `BlockCommunity`).
- `get_profile` endpoint: ALL fields (scalar + lists) from indexer DB. No chain queries.
- Feed filtering reads from the indexer DB, never the chain.

**Genesis Export/Import**:
- `ExportGenesis` exports ALL KV pairs to `raw_state` (complete state)
- `InitGenesis` imports `raw_state` first, then `initial_profiles` (only if profile not already present)
- `InitialProfile` wraps `ProfileCore` + all list fields for backfill scenarios

**Indexer DB tables**:
- `profiles`, `followed_users`, `blocked_users`, `blocked_posts`, `blocked_communities`, `community_curation_preferences`
- There is **no** `joined_communities` table. A user's joined communities are derived from the rows they have in `community_curation_preferences` — joining a community *is* having a preference row for it. See `_build_user_followed` in `web/backend/routes/public.py`.
- List tables have a `position` column for ordering and deque eviction (cap: `INDEXER_LIST_CAP` = 100k in `indexer/database.py`)
- `topic_content_stats` and `user_topic_stats` keep their `topic` naming on purpose: renaming a table whose data is already on disk is never worth it.

### Docker Container Paths

- Scripts go to `/opt/mirage/scripts/` inside the container (NOT `/root/scripts/`).
- Example: `docker cp scripts/foo.py mirage:/opt/mirage/scripts/foo.py`

### SCP to Servers

When asked to "scp" a file to a server (e.g. `mirage.talk`), the file must end up inside the Docker container, not just on the host. Use a two-step command:

```bash
scp <local-path> root@<server>:/tmp/<filename> && ssh root@<server> 'docker cp /tmp/<filename> mirage:/opt/mirage/scripts/<filename> && rm /tmp/<filename>'
```

Example for `mirage.talk`:
```bash
scp scripts/user_analysis.py root@mirage.talk:/tmp/user_analysis.py && ssh root@mirage.talk 'docker cp /tmp/user_analysis.py mirage:/opt/mirage/scripts/user_analysis.py && rm /tmp/user_analysis.py'
```

### General

- After you're done with stuff, give me a short cmdline to run it if I want to
- I want you to add logs of debug statements, so that you can easily find it in the future and work with things

### Frontend: Blockchain Button Pattern

All buttons that trigger blockchain transactions (votes, follows, posts, etc.) MUST follow the same pattern:

1. **Global state tracking**: Use a hook that tracks pending operations globally
   - Operations persist across page navigation
   - State stored in `TransactionHandler` singleton with listener pattern
   - Examples: `usePendingVotes()`, `usePendingFollows()`

2. **Queue position display**: Show queue status using `formatStatusForPosition(queuePosition)`
   - Returns: `"Queued (in 2)"`, `"Processing (1.5s)"`, `"Submitting (0.8s)"`, etc.
   - Uses the global `useTxStatus()` hook internally

3. **Action-specific fallback**: If no queue position, show action type
   - `"Following..."` / `"Unfollowing..."`
   - `"Voting..."` / etc.

4. **Track queue position on enqueue**: Store `queuePosition` when adding to queue
   - `pendingFollows.set(key, { action, type, target, queuePosition })`
   - `pendingVotes.set(key, { direction, queuePosition })`

Example pattern from `useFollowState.js`:
```javascript
const formatTopicStatus = useCallback((topic) => {
    const info = getInfo('topic', topic);
    if (!info) return null;
    const formatted = formatStatusForPosition(info.queuePosition);
    if (formatted) return formatted;
    return info.action === 'unfollow' ? 'Unfollowing...' : 'Following...';
}, [getInfo, formatStatusForPosition]);
```

### Release Publishing — LOCAL, NOT CI

- **"Create a release" means a node can update onto it.** The finish line is not
  a git tag: it is a signed manifest on `prod` that a node picks up by running
  `mirage-update` (ordinary releases) or `mirage-upgrade` (releases activated by
  a governance halt). A tagged release with no signed manifest for that
  `VERSION`, or one whose `release_id` is not strictly greater than the previous
  manifest's, is not a release — nodes reject it and nothing can update. Always
  finish the manifest, and say which of the two commands applies.
- **The normal release path is local.** Build and push the image with the existing
  local GHCR login, generate the candidate manifest, sign it with
  `.release_signing.pem`, commit/push the signed manifest, run the tests relevant
  to the changed components, then use `/prod-release`.
- **Ordinary software releases are not blockchain upgrades.** Deploy scripts,
  host tools, installers, frontend and backend changes do not require
  `scripts/test_upgrade.sh` unless the release also contains a real blockchain
  upgrade as defined below.
- `.github/workflows/release.yml` is optional. **Never dispatch or wait for the
  candidate workflow unless the operator explicitly asks for CI.**
- CI availability or GHCR permissions are not a release gate and must not delay
  a requested release.

### Blockchain Upgrades — ALWAYS `scripts/test_upgrade.sh`, NEVER A MANUAL EQUIVALENT

A **blockchain upgrade** is a release that changes chain consensus/state-transition
behavior and is activated through a governance software-upgrade plan and halt.
Only those releases use this section. Do not run the rehearsal merely because an
ordinary image is being published.

**Every blockchain upgrade must be validated by `scripts/test_upgrade.sh`. No exceptions.**

```bash
scripts/test_upgrade.sh          # run the pipeline, launch the panes
scripts/test_upgrade.sh --wait   # block until done; exit 0 iff all three passed
```

- **Never hand-run the equivalent steps.** Reset, upgrade proposal, halt, deploy,
  PoW raise, `test_blockchain`, `test_backend`, `verify_upgrade` — running these
  yourself is NOT a substitute, even if you run all of them in order. The script
  exists so the sequence and its gates cannot be partially performed.
- **The release is not ready until `blockchain`, `backend` and `verify` all report
  `passed`.** Read `~/.mirage/upgrade_tests/all.json` and `verify.out`.
- **On any failure: fix the cause and re-run the whole pipeline.** Re-running a
  single pane and declaring the release verified is not acceptable.
- The rehearsal deploys the way production deploys, which is why it catches what
  unit tests cannot. In `v1.36.0` it caught a binary reporting
  `v1.36.0-1-gd783da08` — every suite passed and the release would still have
  shipped mislabelled.
- Agents: launch it with `required_permissions: ["all"]`. It writes status files
  to `~/.mirage/upgrade_tests`, outside the workspace, so the sandbox kills it at
  the first step with `rm: Permission denied`. `--wait` only reads, so it works
  sandboxed.

### Tests

**BEFORE RUNNING `tests/test_backend.py` OR `tests/test_blockchain.py` — NON-NEGOTIABLE:**

1. **RUN INSIDE LOCAL DOCKER ONLY.** Both suites submit real transactions. Host execution is disabled in `tests/common.py`; do not run either entry point with host Python. They may ONLY execute inside the local `mirage` container (`hostname=testnet`) against `127.0.0.1`. Never run them inside or against val1/val2/val3/val4 or any domain.
2. **TEST LIMITS.** PoW difficulty scales with recent message volume, so a suite that submits hundreds of txs makes itself progressively slower until it crawls and times out. A subscriber's daily relay quota is spent the same way: the suites run as a handful of wallets, so `sub1` alone burns a real user's whole day and the rest of the run fails with `subscriber_daily_limit_reached`. `scripts/reset_local_testnet.py` writes `pow_message_limit=9999999` and `subscriber_daily_relay_limit=10000` into genesis, so a fresh local reset already has the suite limits. If the chain was not reset that way, raise them with:

```bash
python3 scripts/submit_proposal.py local scripts/proposals/proposal_set_pow_message_limit_9999999.json
python3 scripts/submit_proposal.py local scripts/proposals/proposal_set_subscriber_daily_relay_limit_10000.json
```

The suite runner queries both chain parameters and aborts before wallet setup unless they are exactly `9999999` and `10000`. If a suite run is inexplicably slow or stalls on `[pow]` lines, the limits were not raised.

Then run a suite inside the container:

```bash
docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage python3 tests/test_backend.py'
docker exec mirage bash -lc 'cd /opt/mirage && set -a; for f in /root/.mirage/env/*.env; do . "$f"; done; set +a; PYTHONPATH=/opt/mirage python3 tests/test_blockchain.py'
```

When every selected backend category is walletless, the runner skips wallet provisioning automatically; use `--category` for focused source, schema, and database probes instead of generating unnecessary chain traffic.

- **Two test suites**: `tests/test_backend.py` (backend API/integration) and `tests/test_blockchain.py` (direct chain-level tx submission). Both are thin entry points.
- **Test cases** live in `tests/cases/`, prefixed by suite: `test_backend_*.py` and `test_blockchain_*.py`.
- **Shared infrastructure** is in `tests/common.py`. Backend tx helpers in `tests/backend_helpers.py`. Blockchain gRPC helpers in `tests/blockchain_helpers.py`.
- Add new tests to the appropriate `tests/cases/test_{suite}_{domain}.py` file. Never create standalone test files.

### Git etiquette for Cursor

- Do **not** run `git commit` unless I explicitly ask you to.
- When I do ask you to "commit" (or similar), run a single command that both commits **and** pushes to the remote (e.g. `git commit ... && git push`).
- **NEVER push directly to `prod`.** All production releases go through the `/prod-release` skill. If you find yourself on the `prod` branch, switch back to `dev` before committing. The only exception is if I explicitly confirm a direct push to prod.
- When making a new version release (e.g. v1.6.3), create the git tag **once** on `prod` and push it without `--force`. Never `git tag -f`. Development does not pre-create the next tag.
  ```bash
  git tag v1.6.3 && git push origin v1.6.3
  ```

### Migration Versioning

- **All migrations must match the current git tag version.**
- This applies to **deploy migrations** and **indexer migrations** (and any other migration system).
- If the current tag is `v1.16.0`, all new migration filenames/keys must be `v1_16_0_*` (no future versions).

### Release notes

- File goes in `docs/updates/update_vX.Y.Z.md`
- **Headline**: Start with `# Mirage vX.Y.Z Release Notes`
- **Section headers**: Each section gets a `### Header`, e.g. `### Account deletion`, `### Feed interleaving`, `### Rate limiting`
- **Marketing tone, not technical**: Write for users, not engineers. No bullet points, no tables, no code blocks, no field names. Think blog post / changelog announcement.
- **~6 paragraphs max**: Each paragraph covers one theme (main feature, how it works, governance/community angle, infrastructure, UX details, testing/security). Keep it punchy.
- **Sell the feature**: Lead with what the user gets, not what changed internally. "Your data, your choice" not "Added MsgDeleteUser handler."
- **Be honest about tradeoffs**: Never omit, sugarcoat, or lie about limitations. If decentralization means nodes can ignore a request, say so. If "deletion" is really "marked for deletion", call it that. Users deserve the truth — write release notes you'd be comfortable defending in public.
- See `docs/updates/update_v1.14.0.md` as the reference example.



# GENERAL RULES

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
