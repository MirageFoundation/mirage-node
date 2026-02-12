# Reward API

The reward system exposes quest progress, flash quests, and pending rewards through a single endpoint.

## GET /api/rewards/summary

Returns all reward-related data for a user in one call: daily quests, the active flash quest, and pending (claimable) rewards.

### Query Parameters

| Param | Type   | Required | Description     |
|-------|--------|----------|-----------------|
| owner | string | yes      | User address    |

### Response

```json
{
  "suspended": false,
  "daily_quests": [
    {
      "id": "vote_3",
      "title": "Cast 3 Votes",
      "description": "Vote on 3 different posts",
      "action_type": "vote",
      "progress": 1,
      "target": 3,
      "completed": false,
      "rewards": [{ "type": "mirage", "amount": 5, "apply_multiplier": true }],
      "min_content_length": null,
      "time_spacing_minutes": null,
      "unique_target": true,
      "unique_topics_min": null,
      "quality_threshold": null,
      "count_vote_changes": true
    }
  ],
  "flash_quest": {
    "id": "quick_vote",
    "title": "Speed Voter",
    "description": "Vote on 5 posts in 30 minutes",
    "action_type": "vote",
    "progress": 2,
    "target": 5,
    "completed": false,
    "starts_at": 1739350000,
    "ends_at": 1739351800,
    "seconds_remaining": 1200,
    "rewards": [{ "type": "mirage", "amount": 10, "apply_multiplier": true }]
  },
  "pending_rewards": [
    {
      "id": 42,
      "type": "mirage",
      "data": { "amount": 5000000, "apply_multiplier": true },
      "reason": "quest:vote_3",
      "created_at": 1739340000
    }
  ],
  "seconds_until_reset": 43200,
  "reward_multiplier": 2.5,
  "total_mirage": 5000000,
  "total_mirage_after_multiplier": 12500000,
  "pending_invite_codes": 0,
  "claiming_available": true,
  "debug": false
}
```

### Key fields

- **suspended** / **suspension** — if `true`, all arrays are empty and a `suspension` object with details is included.
- **disabled** — returned (with `true`) when the quest system is turned off server-side (`QUESTS_ENABLED=false`).
- **daily_quests** — today's assigned quests with live progress.
- **flash_quest** — the currently active flash quest, or `null`.
- **pending_rewards** — unclaimed reward rows.
- **reward_multiplier** — loyalty multiplier (1x–5x, ramps over 30 days).
- **total_mirage** — raw sum of pending MIRAGE (umirage).
- **total_mirage_after_multiplier** — total after applying the loyalty multiplier to eligible rewards.
- **claiming_available** — `false` when the reward distribution wallet is not configured.
- **debug** — `true` when `BACKEND_DEBUG=true` in the backend environment.

### Why a single endpoint?

Previously the frontend made three parallel requests to load the quest card:

| Old endpoint              | Data                        |
|---------------------------|-----------------------------|
| GET /api/rewards/daily    | Daily quests + multiplier   |
| GET /api/rewards/flash    | Flash quest                 |
| GET /api/rewards/pending  | Pending rewards + totals    |

All three shared the same `owner` parameter and repeated identical work (suspension check, quest-definition loading, multiplier calculation). They have been removed and replaced by `/api/rewards/summary`, which eliminates redundant DB queries and cuts network round-trips from 3 to 1.

## POST /api/rewards/claim

Claims all pending rewards for the user.

### Body

```json
{ "owner": "mirage1abc..." }
```

### Response (success)

```json
{
  "success": true,
  "rewards": [
    { "type": "mirage", "amount": 12500000 }
  ],
  "tx_hash": "ABCDEF1234..."
}
```

### Response (error)

```json
{
  "success": false,
  "error": "no_rewards",
  "message": "No pending rewards to claim"
}
```

## GET /api/rewards/achievements

Returns all achievements with the user's unlock status. Not included in `/summary` because it is loaded separately on its own page.

### Query Parameters

| Param | Type   | Required | Description  |
|-------|--------|----------|--------------|
| owner | string | yes      | User address |

### Response

```json
{
  "achievements": [
    {
      "id": "first_vote",
      "title": "First Vote",
      "description": "Cast your first vote",
      "progress": 1,
      "target": 1,
      "unlocked": true,
      "unlocked_at": 1739300000,
      "badge_icon": "vote_badge",
      "rewards": []
    }
  ]
}
```
