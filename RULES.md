## Cursor Operational Rules

### #1 RULE: NEVER COMMIT OR PUSH TO GIT WITHOUT MY EXPLICIT APPROVAL.
- Do NOT run `/commit-push` or `git commit`, `git push`, or any combined commit+push command unless I specifically tell you to.
- After making code changes, STOP and wait for my go-ahead before committing.
- Do NOT auto-commit when follow-up changes occur. Each commit requires fresh approval.

### SERVERS
- 159.203.114.27:   PROD SERVER. Domain is mirage.talk
- 64.23.136.132:    UAT SERVER. mirage.vote is the domain
- 146.190.108.140:  3rd node
- 139.59.9.96:      4th Node

**NEVER INTERACT WITH PRODUCTION SERVERS!**
- Do NOT run scripts, queries, or any commands against production IPs or domains
- Do NOT SSH, curl, or connect to production in any way
- For testing, ONLY use local docker (127.0.0.1)
- It is OK to interact with servers in a purely informative way, e.g. getting logs, but not changing anything on the server.


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
- List fields stored separately at their own prefixes:
  - `plist_agents/{owner}` - enabled agents
  - `followed_users/{owner}` - followed users
  - `followed_topics/{owner}` - followed topics
  - `blocked_users/{owner}` - blocked users
  - `blocked_posts/{owner}` - blocked posts
  - `blocked_topics/{owner}` - blocked topics

**Chain list limits — hard cap vs deque**:
- `enabled_agents`, `followed_users`, `followed_topics`: **hard cap** — the chain rejects the transaction when the tier limit is reached. The user must disable/unfollow first.
- `blocked_users`, `blocked_posts`, `blocked_topics`: **deque** — the chain silently evicts the oldest entry when the limit is exceeded. The indexer stores the full history (up to 100k per user per list) so feed filtering still sees old blocks.
- `get_profile` endpoint: ALL fields (scalar + lists) from indexer DB. No chain queries.
- Feed filtering (`_get_blocked_posts`, `_get_blocked_users`, `_get_blocked_topics`) reads from indexer DB.

**Genesis Export/Import**:
- `ExportGenesis` exports ALL KV pairs to `raw_state` (complete state)
- `InitGenesis` imports `raw_state` first, then `initial_profiles` (only if profile not already present)
- `InitialProfile` wraps `ProfileCore` + all list fields for backfill scenarios

**Indexer DB tables**:
- `profiles`, `enabled_agents`, `followed_users`, `followed_topics`, `blocked_users`, `blocked_posts`, `blocked_topics`
- All list tables have a `position` column for ordering and deque eviction (cap: `INDEXER_LIST_CAP` = 100k in `indexer/database.py`)

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

### Tests

- **Two test suites**: `tests/test_backend.py` (backend API/integration) and `tests/test_blockchain.py` (direct chain-level tx submission). Both are thin entry points.
- **Test cases** live in `tests/cases/`, prefixed by suite: `test_backend_*.py` and `test_blockchain_*.py`.
- **Shared infrastructure** is in `tests/common.py`. Backend tx helpers in `tests/backend_helpers.py`. Blockchain gRPC helpers in `tests/blockchain_helpers.py`.
- Add new tests to the appropriate `tests/cases/test_{suite}_{domain}.py` file. Never create standalone test files.

### Git etiquette for Cursor

- Do **not** run `git commit` unless I explicitly ask you to.
- When I do ask you to "commit" (or similar), run a single command that both commits **and** pushes to the remote (e.g. `git commit ... && git push`).
- **NEVER push directly to `prod`.** All production releases go through the `/prod-release` skill. If you find yourself on the `prod` branch, switch back to `dev` before committing. The only exception is if I explicitly confirm a direct push to prod.
- When making a new version release (e.g. v1.6.3), also create/update the git tag:
  ```bash
  git tag -f v1.6.3 && git push origin v1.6.3 --force
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
