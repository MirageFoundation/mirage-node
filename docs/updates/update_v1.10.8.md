# Mirage v1.10.8 Release Notes

### Overview

v1.10.8 is an infrastructure and observability release. The Server page now has real charts — node balance over time, earned vs spent, total supply, and minted vs burned — all built with lightweight inline SVGs that load instantly. Staking data is visible too. Under the hood, every validator query that used to shell out to the CLI now goes through gRPC, which is faster and doesn't spawn subprocesses.

On the ops side, deployments got smarter. The Go binary only rebuilds when Go source files actually change — Python and frontend commits no longer trigger a full recompile. A new maintenance page replaces raw 502 errors during upgrades, so users see a clear "upgrade in progress" screen instead of a broken page. And registration is now off by default for new nodes, with hard failures on missing config instead of silent defaults that could leave a node wide open.

Quest configuration was cleaned up: all env vars now follow a consistent `QUESTS_*` naming convention, and the flash quest cap actually enforces the configured limit. Small release, big improvements to the foundation.

---

### Network Charts

- New **Node Balance** chart: 7-day line chart of the validator's liquid MIRAGE balance, green when rising, red when falling
- New **Earned vs Spent** chart: cumulative earned and spent derived from node balance deltas
- New **Total Supply** chart: 7-day supply trend with color indicating growth or decline
- Renamed "Tokenomics" section to **Minted vs Burned** for clarity
- All charts share consistent layout constants, axis formatting, and a compact `fmtMirage()` number formatter
- Staked MIRAGE balance now displayed on the Server page

---

### gRPC Migration

- Validator monikers, staking info, and delegations now fetched via gRPC instead of `miraged` CLI subprocess calls
- New gRPC functions: `get_staked_balance()`, `get_validator()`, `get_all_validators()` in `bank.py`
- Subprocess dependency removed from `public.py` and `chain.py`

---

### Registration Hardening

- Registration and invite codes are now **off by default** for fresh node deployments
- Backend calls `require_bool_env()` at startup — missing or invalid boolean config crashes immediately instead of falling back to defaults
- Frontend requires both `registrationEnabled` and `inviteCodeRequired` from node config; shows "Registration unavailable" if either is missing
- Invite code validation only runs when invite codes are actually required
- Migration sets registration on with invite codes for `mirage.talk`; other nodes stay closed

---

### Quests Cleanup

- Flash quest cap now enforced with a real `COUNT` query instead of a boolean existence check
- Setting `QUESTS_FLASH_COUNT=0` disables flash quests entirely
- All quest and backend env vars renamed to a consistent prefix scheme (`QUESTS_*`, `BACKEND_*`)
- Fixed double-prefix bug where env vars like `QUEST_QUEST_INVITE_RECRUIT_CHANCE` were read instead of `QUEST_INVITE_RECRUIT_CHANCE`
- Deploy migration handles the rename automatically

---

### Maintenance Page

- Caddy now serves a styled maintenance page on 502/503 instead of a raw error
- Page shows "Upgrade in Progress" with a spinner and auto-refreshes every 30 seconds
- Backup health checks now test via real external endpoints instead of curling localhost from inside the server

---

### Deploy Improvements

- Go binary rebuild is based strictly on hashing Go source files (`blockchain/{go.mod,go.sum,app,cmd,orchestrator,x}`), not git tags or commit metadata
- Python-only and frontend-only changes no longer trigger a binary recompile
- `verify_upgrade.py` updated for v1.10.8 as a services-only release (no chain upgrade required)
- Binary version check relaxed to accept `git describe` suffixes like `v1.10.8-3-g67679d3`
- Fixed false positives in verify script from substring matching and missing frontend source on host

---

### Roadmap

- Galleries — multiple images and videos in a single post
- Tag users with @ mentions for notifications
- Block entire topics or keywords you don't want to see

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
