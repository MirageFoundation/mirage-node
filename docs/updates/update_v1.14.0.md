# Mirage v1.14.0 Release Notes

v1.14.0 introduces **MsgDeleteUser** — users can permanently delete their account. Deletion can be initiated by the user themselves (self-signed via `envelope_pubkey`) or by governance. On-chain, the handler clears the profile KV, all profile lists, releases the username, removes the subscription index entry, and sweeps all spendable balances to the community pool. The indexer soft-deletes profiles (sets `deleted_at`) so that post attribution — the original author's username on historical posts — is preserved while deleted usernames no longer resolve for new lookups.

---

### MsgDeleteUser

Permanently remove a user account from the blockchain.

- **Authorization**: Self-signed (envelope derives to target) or governance module
- **On-chain**: Clears profile core, followed mods/users/topics, blocked users/posts/topics, username mapping, subscription index; sweeps spendable to community pool
- **Indexer**: Soft-deletes profile (`deleted_at`); username resolution excludes deleted users; post attribution still shows original username from soft-deleted rows
- **Re-registration**: If a user is deleted and later re-registers (e.g. chain replay), `upsert_profile` and `upsert_profile_full` clear `deleted_at` on conflict

---

### Technical Details

- **Blockchain**: `MsgDeleteUser` (fields: authority, envelope_*, target); `DeleteUserState` keeper method; relay gas fee deducted for self-delete
- **Indexer**: `soft_delete_profile()`, `deleted_at` column, `idx_profiles_username_active` partial index
- **Backend**: `deleted_at IS NULL` in username resolution, user search, and subscriber queries
- **Governance**: `MsgDeleteUser` in `TYPE_URL_TO_PROTO` for proposal parsing

---

### Upgrade

**Upgrade Name:** `v1.14.0`

No on-chain state migration — new message types only.

---

Have a feature suggestion? Let us know on [Mirage](https://mirage.talk) — post it in the #feedback topic or message us directly.
