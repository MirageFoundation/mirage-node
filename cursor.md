## Cursor Operational Rules

Use these rules to avoid hanging sessions and enforce fail-fast behavior.

### Project Structure

The workspace root is `/home/nik/projects/mirage/`, but the actual git repository and project code is in `public/mirage-node/`:

```
/home/nik/projects/mirage/           # Workspace root (NOT a git repo)
├── cursor.md                        # This file
├── private/                         # Projects related to Mirage, but not for the public
└── public/
    └── mirage-node/                 # ← GIT REPO ROOT - all code lives here
        ├── blockchain/              # Go blockchain node (miraged binary)
        ├── deploy/                  # Deployment scripts & Docker
        ├── docs/                    # Documentation
        ├── indexer/                 # Python indexer service
        ├── scripts/                 # Utility scripts
        ├── shared/                  # Shared Python modules
        └── web/
            ├── backend/             # Python Flask backend
            └── frontend/            # React frontend
```

**IMPORTANT**: All git commands must be run from `public/mirage-node/`, not the workspace root.

### #1 RULE: Git Commands Must Be Explicit

**NEVER** run git commands through `conda run` (e.g., `conda run -n mirage-node git ...`).
This hides the git command output and is strictly forbidden.

**ALWAYS** run git commands from `public/mirage-node/` explicitly:
```bash
# GOOD:
cd /home/nik/projects/mirage/public/mirage-node && git status
cd /home/nik/projects/mirage/public/mirage-node && git add -A && git commit -m "message" && git push

# BAD (NEVER DO THIS):
conda run -n mirage-node git status
cd /home/nik/projects/mirage && git status  # Wrong directory!
```

### Deployment

All paths below are relative to `public/mirage-node/`.

- **Local deployment**: Use `deploy/deploy.sh root@127.0.0.1 --init` to deploy locally
  - Builds and runs the node in a Docker container
  - On `--init`, you will be prompted for a funded mnemonic; it is imported before startup.
  - Node data persists at `~/.mirage/main/`
  - Access: http://127.0.0.1:8080/
- **Frontend development**: For frontend-only changes, do NOT redeploy.
  - The React dev server is ALWAYS running in this workspace. NEVER run `npm start` in `web/frontend/`.
  - The dev server proxies API calls to the Docker container at localhost:80
  - Hot reload works automatically for JS/CSS changes
- **NEVER DEPLOY REMOTELY UNLESS SPECIFICALLY ASKED FOR**

### Branch-Specific Docker Tarballs

Docker tarballs are branch-specific:
- `deploy/mirage-docker-prod.tar.gz` - used on `prod` branch
- `deploy/mirage-docker-dev.tar.gz` - used on any non-prod branch (dev, feature branches, etc.)

**After merging dev → prod and deploying successfully:**
1. Commit outstanding changes on dev
2. Merge dev into prod: `git checkout prod && git merge dev`
3. Delete old prod tarball: `rm deploy/mirage-docker-prod.tar.gz`
4. Rename dev tarball to prod: `mv deploy/mirage-docker-dev.tar.gz deploy/mirage-docker-prod.tar.gz`
5. Switch back to dev: `git checkout dev`

**Why**: The dev tarball was just tested/deployed successfully, so it becomes the new prod tarball.

### SERVERS
- 159.203.114.27:   PROD SERVER. Domain is mirage.talk
- 64.23.136.132:    UAT SERVER. mirage.vote is the domain
- 146.190.108.140:  3rd node
- 139.59.9.96:      4th Node

**NEVER INTERACT WITH PRODUCTION SERVERS!**
- Do NOT run scripts, queries, or any commands against production IPs or domains
- Do NOT SSH, curl, or connect to production in any way
- For testing, ONLY use local docker (127.0.0.1)

### Config generation and templates

- **Authoritative runtime configs in Docker**:
  - Production and local Docker deployments render configs from `deploy/templates/*.toml` via `deploy/init.sh`.
  - `--update-init` sets `MIGRATE_CONFIG=1` and re-renders `~/.mirage/main/config/app.toml` and `config.toml` from these templates, overwriting previous files.
- **SDK defaults in code are NOT used by Docker**:
  - Values set in `blockchain/cmd/miraged/cmd/config.go` (e.g., pruning, min-retain-blocks, state-sync, logging) are not applied in Docker flows.
  - When changing SDK defaults, update `deploy/templates/app.toml` and `deploy/templates/config.toml` to match, then re-deploy with `--update-init`.
- **Current expected template defaults** (keep these in sync with `config.go`):
  - `app.toml`:
    - `minimum-gas-prices = "5000umirage"`
    - `pruning = "custom"`, `pruning-keep-recent = "1000"`, `pruning-interval = "100"`
    - `min-retain-blocks = 28800`
    - `[state-sync] snapshot-interval = 1000`, `snapshot-keep-recent = 2`
    - `[logging] format = "plain"`, `level = "info"`
  - `config.toml`:
    - `[consensus] create_empty_blocks = false`, `create_empty_blocks_interval = "600s"`, `timeout_commit = "3s"`

### Code Quality

- **No redundant comments**:
  - Do not repeat values that are already visible in the code (e.g., `// 20 = 20%` next to `Percent: 20`)
  - Do not add "for testing" comments; values speak for themselves
  - Comments should explain WHY or provide context not obvious from the code

- **Do not use fallbacks**:
  - NEVER add fallbacks. Fail hard. No backward-compatibility handling or comments.
  - Anything that could potentially mask buggy behavior must fail immediately so issues surface early.

- **Prefer explicit arguments over implicit environment variables**:
  - Pass configuration as function/CLI arguments, not hidden env vars
  - If a value is needed, make it an explicit parameter
  - Environment variables should only be used for values defined in `.env` files
  - Exception: Internal deploy flags like `MIGRATE_CONFIG` that are set by scripts

- **NEVER hardcode seeds or mnemonics**:
  - Seeds must ALWAYS be passed via CLI arguments or secure prompts
  - Never commit mnemonics, private keys, or seeds to the codebase
  - Test scripts must require seeds as arguments (--seed-free, --seed-subscriber)

- **Fail fast and surface errors**:
  - On timeout/deadline, exit non-zero and print a clear error message.
  - Do not hide errors; avoid suppressing with `2>/dev/null` unless explicitly intended.

- **No indefinite loops in scripts**:
  - Loops must have a termination condition and an overall time budget.
  - Prefer event-driven patterns (e.g., WebSocket subscriptions) over tight polling.

### Blockchain Rules

**🚨 CRITICAL - NEVER EXECUTE PROPOSALS OR STATE-CHANGING BLOCKCHAIN OPERATIONS 🚨**

- **NEVER** submit governance proposals, mint tokens, or any state-changing blockchain transactions
- **NEVER** execute scripts that interact with ANY blockchain (local or remote) without EXPLICIT user confirmation
- **NEVER** pipe input to bypass confirmation prompts (e.g., `echo "" | python script.py`)
- The "local" mode in scripts is for LOCAL TESTING ONLY - but even then, ASK FIRST
- If a script has a confirmation prompt, that prompt exists FOR A REASON - let the user confirm manually
- When in doubt: **STOP AND ASK THE USER**

This includes:
- `submit_proposal.py` - NEVER run this
- Any `tx` commands via `miraged tx ...`
- Any minting, burning, staking, or governance operations
- ANY command that modifies blockchain state

**VIOLATION OF THIS RULE CAN CAUSE IRREVERSIBLE DAMAGE TO PRODUCTION SYSTEMS**

- **CometBFT transactions**:
  - Always use unordered transactions; never ordered. Avoid sequence queries.
  - CometBFT broadcast mode must be "sync" or "async". Never "block".

- **Message Authority**:
  - `authority` field is ALWAYS the validator/node address OR governance module address
  - NEVER set `authority` to the user's address
  - User's address is derived from `envelope_pubkey`

### Query Sources - Use the standard approach

- App/module state (params, profiles, difficulty, etc.): query via gRPC/REST/CLI ONLY.
- Consensus fields (block IDs/hashes, peer/net info, tx lookup): query via CometBFT RPC ONLY.
- NO FALLBACKS. Pick the single canonical source per category and HARD FAIL if it is unavailable or returns unexpected data.
- Backend must fail hard when required data is missing. Do not silently recover or guess.

### API Paths - Caddy Routes

**CRITICAL**: The web server (Caddy) exposes chain endpoints at these paths:

- `/chain/rpc/*` → CometBFT RPC (port 26657) - WebSocket at `/chain/rpc/websocket`
- `/chain/rest/*` → Cosmos SDK REST (port 1317)
- `/api/*` → Python backend (port 5000)

**Examples**:
```bash
# Query params via REST
curl http://127.0.0.1/chain/rest/mirage/core/v1/params

# Query status via RPC  
curl http://127.0.0.1/chain/rpc/status

# NOT /api/params - that doesn't exist!
```

Legacy paths `/rpc/*` and `/lcd/*` are deprecated (remove after 2026-02-20).

### Chain Parameters - EVERYTHING MUST BE QUERYABLE

All paths below are relative to `public/mirage-node/`.

**CRITICAL**: When adding or changing ANY chain parameter:

1. **Proto definition** (`blockchain/proto/mirage/core/v1/params.proto`):
   - Add field to `Params` message with unique field number
   - For complex types (like tiers), define separate message type

2. **Go defaults** (`blockchain/x/core/types/params.go`):
   - Add to `DefaultParams()` with sensible default
   - Add validation in `Validate()` if needed

3. **Genesis** (`blockchain/genesis/genesis.json`):
   - Add param with value in `app_state.core.params`

4. **Upgrade handler** (`blockchain/app/upgrades.go`):
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

**NO HARDCODED VALUES IN BACKEND** - Everything comes from chain via gRPC query.

### Python Environment

- **Use conda environment `mirage-node`** for all Python scripts
- Activate with: `conda activate mirage-node`

### Profile Data Architecture

**Single Source of Truth**: `ProfileCore` is defined in `blockchain/proto/mirage/core/v1/genesis.proto` and generated into Go code. Do NOT duplicate this struct elsewhere.

**Profile Structure**:
- `ProfileCore` (proto-generated): scalar fields stored at `profiles/{owner}` KV prefix
- List fields stored separately at their own prefixes:
  - `followed_mods/{owner}` - followed moderators
  - `followed_users/{owner}` - followed users
  - `followed_topics/{owner}` - followed topics
  - `blocked_users/{owner}` - blocked users
  - `blocked_posts/{owner}` - blocked posts
  - `quality_posts/{owner}` - quality posts

**Genesis Export/Import**:
- `ExportGenesis` exports ALL KV pairs to `raw_state` (complete state)
- `InitGenesis` imports `raw_state` first, then `initial_profiles` (only if profile not already present)
- `InitialProfile` wraps `ProfileCore` + all list fields for backfill scenarios

**Indexer DB vs Chain KV**:
- Indexer DB has: `profiles`, `followed_mods`, `blocked_users`, `blocked_posts`
- Chain KV has: all of the above PLUS `followed_users`, `followed_topics`, `quality_posts`
- When backfilling from indexer, missing lists will be empty (correct behavior)

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

### Server Modifications

**NEVER manually modify files on servers (SSH + edit)**. All configuration changes must go through:
1. Template files in `deploy/templates/`
2. Migration scripts in `deploy/migrations/`
3. The deploy process

If a new config value is needed:
1. Add it to the appropriate template file
2. Add a migration if existing deployments need updating
3. Let the deploy/migration system handle it

**NEVER "quick fix" something on the server**. If something is broken after deploy:
1. **DO NOT** manually run commands to fix it on the server
2. **DO** fix the deploy scripts/templates/migrations first
3. **THEN** redeploy to apply the fix
4. This ensures the fix is permanent and works on all future deploys

### Syncing Files to Remote Servers

**Files run inside Docker containers, NOT on the host!** When syncing scripts or files to remote servers:

```bash
# WRONG - syncs to host filesystem (not accessible by container)
rsync file.py server:/opt/mirage/scripts/

# CORRECT - copy into the Docker container
rsync file.py server:/tmp/ && ssh server "docker cp /tmp/file.py mirage:/opt/mirage/scripts/ && rm /tmp/file.py"

# Or in one command:
cat file.py | ssh server "docker exec -i mirage tee /opt/mirage/scripts/file.py > /dev/null"
```

The Docker container name is `mirage`. All code runs at `/opt/mirage/` inside the container.

### Git etiquette for Cursor

- Do **not** run `git commit` unless I explicitly ask you to.
- When I do ask you to "commit" (or similar), run a single command that both commits **and** pushes to the remote:
  ```bash
  cd /home/nik/projects/mirage/public/mirage-node && git add -A && git commit -m "message" && git push
  ```

### Branch workflow (CRITICAL)

- **All development happens on `dev`**.
- **Do NOT merge `dev` into `prod`** unless I explicitly tell you to do so.
- When I explicitly tell you to merge `dev` → `prod`, do it intentionally:
  - `git checkout prod && git merge dev`
  - push `prod`
  - then switch back to `dev`
  - (and only do this when I say so)

### Public Repository & Git Tags

The public repo is at `github.com/MirageFoundation/mirage-node`. All commits must use the MirageFoundation identity (already configured in `.git/config`).

**Git tag versioning is MANDATORY:**
- Every push to the public repo should have an up-to-date git tag
- Current version: Check with `git describe --tags --abbrev=0`
- When working on new features for a dev release, **ASK the user** what the new version should be before tagging
- Tags must be pushed to both `dev` and `prod` branches on the public remote

**To update the version tag:**
```bash
cd /home/nik/projects/mirage/public/mirage-node
git tag -a vX.Y.Z -m "Mirage Node vX.Y.Z"
git push public vX.Y.Z
```

**Pre-push hook**: A hook at `.git/hooks/pre-push` blocks pushes to the public remote unless:
1. Local git config is set to MirageFoundation
2. All commits being pushed are authored by MirageFoundation

### Release notes

Paths relative to `public/mirage-node/`:
- When creating release notes, follow the guide in `docs/update_docs_guide.md`
- File goes in `docs/updates/update_vX.Y.Z.md`
- Overview section should be 2-3 paragraphs of marketing/philosophy
- Use `###` for all section headers (not `##`)
- Keep bullet points concise, skip trivial changes