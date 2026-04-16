# TODO

## Breaking API changes (next major update)

### `/api/get_inbox` response field rename

The response currently uses legacy `reply_*` prefixes for every inbox item type (reply, mention, award, follow, donation, trending). This was fine when the inbox only served replies, but is now a misnomer — e.g. a trending post has `reply_timestamp`, `reply_owner`, `reply_username` that aren't reply-related at all.

Plan: rename to generic `item_*` / `post_*` in the next breaking API bump.

Proposed new names:

| Old (legacy)          | New                  |
|-----------------------|----------------------|
| `reply_id`            | `item_id`            |
| `reply_owner`         | `actor_owner`        |
| `reply_username`      | `actor_username`     |
| `reply_author_level`  | `actor_level`        |
| `reply_author_is_new` | `actor_is_new`       |
| `reply_content`       | `item_content`       |
| `reply_timestamp`     | `item_timestamp`     |
| `parent_id`           | `post_id`            |
| `parent_content`      | `post_preview`       |
| `parent_owner`        | `post_owner`         |
| `root_post_id`        | `root_post_id`       |
| `award_type`          | `award_type`         |
| `type`                | `type`               |
| `amount`              | `amount`             |

**Mobile dev:** please parse `type` first and rely on it for rendering logic — do NOT hardcode around the `reply_*` names beyond what's strictly necessary, so the future rename is a small patch.

**Backend:** when ready, return both old + new keys for a grace period, then drop the old keys one release later.
