# API Error Codes

## Response Format

Every API error response is JSON with at least these two fields:

```json
{
  "error": "human readable message (lowercase, for logs only)",
  "error_code": "snake_case_code"
}
```

Some responses include extra context fields:

```json
{
  "error": "too many agents",
  "error_code": "too_many_agents",
  "count": 5,
  "max": 3
}
```

HTTP status codes follow standard conventions (400 = client error, 403 = forbidden, 404 = not found, 500/503 = server error). Multiple different errors can share the same HTTP status — use `error_code` to distinguish them.

## Client Rules

1. **Switch on `error_code`, never on `error`.** The `error` string is for developer logs. It can change without notice.
2. **Map every `error_code` to a user-facing string in your client.** The table below has suggested copy for each code.
3. **Do not fall back to displaying `error` if `error_code` is missing or unknown.** Treat that as a bug. Log it and show a generic message like "Something went wrong."
4. **Some codes are retryable** (marked below). For those, consider showing a retry button or auto-retrying after a delay.

## Example: Handling in Swift / Kotlin

```swift
// Swift
guard let code = json["error_code"] as? String else {
    log.error("Missing error_code in response: \(json)")
    showAlert("Something went wrong.")
    return
}
showAlert(errorMessage(for: code))
```

```kotlin
// Kotlin
val code = json.optString("error_code", "")
if (code.isEmpty()) {
    Log.e("API", "Missing error_code: $json")
    showError("Something went wrong.")
    return
}
showError(errorMessage(code))
```

---

## Error Code Reference

### Registration / Signup

| Code | Suggested User Message | HTTP |
|---|---|---|
| `registration_disabled` | Registration is currently disabled on this node. | 403 |
| `invite_code_required` | An invite code is required to create an account. | 400 |
| `invite_code_invalid` | That invite code is not valid. | 400 |
| `invite_code_used` | That invite code has already been used. | 400 |
| `invite_code_check_failed` | Could not validate the invite code. Please try again. | 500 |
| `invite_code_invalid_format` | Invite code format is invalid. | 400 |
| `invite_codes_not_required` | Invite codes are not required on this node. | 400 |
| `invite_codes_main_site_only` | Invite codes only work on mirage.talk. | 403 |

### Username

| Code | Suggested User Message | HTTP |
|---|---|---|
| `username_required` | A username is required. | 400 |
| `username_too_short` | Your username is too short. | 400 |
| `username_too_long` | Your username is too long. | 400 |
| `username_invalid_format` | Usernames can only contain letters, numbers, and hyphens. | 400 |

### Referrals

| Code | Suggested User Message | HTTP |
|---|---|---|
| `referral_requires_invite_codes` | Referral links require invite codes to be enabled. | 400 |
| `referrer_not_found` | Referrer not found. | 200 |
| `referrer_not_opted_in` | This referrer has not enabled referral links. | 200 |
| `referrer_no_codes` | This referrer has no invite codes left. | 200 |
| `referrer_already_used` | You already used this referrer. | 200 |
| `referrer_username_too_long` | Referrer username is too long. | 400 |
| `referrer_username_invalid_format` | Invalid referrer username format. | 400 |
| `referrer_check_failed` | Could not validate the referrer. Please try again. | 500 |
| `self_referral` | You cannot refer yourself. | 400 |

> **Note:** The referral precheck endpoint (`/api/referrals/precheck`) returns `{"valid": false, "error": "...", "error_code": "..."}` with HTTP 200 for most cases. Check the `valid` field first, then use `error_code` to determine why.

### Auth / Envelope

| Code | Suggested User Message | HTTP |
|---|---|---|
| `missing_fields` | Missing required fields. | 400 |
| `invalid_pubkey` | Invalid public key. | 400 |
| `invalid_signature` | Invalid signature. | 400 |
| `invalid_timestamp` | Invalid timestamp. | 400 |
| `timestamp_required` | Timestamp is required. | 400 |
| `timestamp_must_be_millis` | Timestamp must be in milliseconds. | 400 |
| `timestamp_outside_window` | Timestamp is outside the allowed window. Check device clock. | 400 |
| `invalid_nonce` | Invalid envelope nonce. | 400 |
| `nonce_required` | Envelope nonce is required. | 400 |
| `nonce_must_be_positive` | Envelope nonce must be positive. | 400 |
| `nonce_out_of_range` | Envelope nonce exceeds allowed range. | 400 |
| `nonce_replayed` | This request has already been processed. | 400 |
| `invalid_relay_fields` | Invalid relay fields. | 400 |
| `invalid_owner` | Invalid owner. | 400 |
| `address_mismatch` | Address does not match the provided key. | 400 |
| `address_required` | Address is required. | 400 |
| `control_characters` | Fields contain invalid control characters. | 400 |
| `forbidden` | You do not have permission to perform this action. | 403 |
| `unauthorized` | Unauthorized. | 403 |
| `enabled_must_be_boolean` | Enabled must be a boolean value. | 400 |
| `owner_required` | Owner is required. | 400 |

### Server State (Retryable)

These indicate temporary server issues. Retry after a short delay.

| Code | Suggested User Message | HTTP | Retryable |
|---|---|---|---|
| `node_catching_up` | The node is syncing. Please try again shortly. | 503 | Yes |
| `backend_not_initialized` | The server is starting up. Please try again shortly. | 503 | Yes |
| `indexer_unavailable` | Data service is temporarily unavailable. | 503 | Yes |
| `internal_error` | Something went wrong. Please try again. | 500 | Maybe |
| `debug_localhost_only` | Debug endpoints are only available on localhost. | 403 | No |

### Proof of Work

| Code | Suggested User Message | HTTP |
|---|---|---|
| `pow_required` | Proof-of-work is required. | 400 |
| `insufficient_pow_precheck` | Proof-of-work is insufficient. Please try again. | 400 |
| `pow_not_allowed_agents` | Proof-of-work is not allowed for agents. | 400 |
| `pow_not_allowed_for_award` | Proof-of-work is not allowed for awards. | 400 |
| `pow_not_allowed_for_set_auto_renewal` | Proof-of-work is not allowed for auto-renewal. | 400 |
| `pow_not_allowed_for_subscribers` | Proof-of-work is not allowed for subscribers. | 400 |
| `invalid_pow_fields` | Invalid proof-of-work fields. | 400 |
| `invalid_last_block_hash` | Invalid last block hash. | 400 |

### Posts / Content

| Code | Suggested User Message | HTTP |
|---|---|---|
| `title_too_long` | Your title exceeds the maximum length. | 400 |
| `content_too_long` | Your post exceeds the maximum length. | 400 |
| `topic_too_short` | Topic name is too short. | 400 |
| `topic_too_long` | Topic name is too long. | 400 |
| `topic_invalid_format` | Topic name contains invalid characters. | 400 |
| `topic_required` | A topic is required for new posts. | 400 |
| `comment_content_required` | Comment text is required. | 400 |
| `comment_not_found` | Comment not found. | 400 |
| `comment_must_not_include_topic` | Comments must not include a topic. | 400 |
| `post_not_found` | Post not found. | 404 |
| `invalid_target` | Invalid target. | 400 |
| `invalid_target_format` | Invalid target format. | 400 |
| `target_not_found` | The target post or comment was not found. | 404 |
| `target_mismatch` | Cannot change the parent of an existing post. | 400 |
| `target_must_be_mirage1` | Target must be a valid mirage1 address. | 400 |
| `tag_too_long` | Tag is too long. | 400 |
| `invalid_tag` | Invalid tag. | 400 |
| `invalid_override` | Invalid override. | 400 |
| `post_id_required` | Post ID is required. | 400 |
| `comment_id_required` | Comment ID is required. | 400 |
| `invalid_hash` | Invalid or missing hash. | 400 |

### Media

| Code | Suggested User Message | HTTP |
|---|---|---|
| `media_not_list` | Media must be provided as a list. | 400 |
| `media_limit_exceeded` | Too many media attachments. | 400 |
| `media_item_too_long` | A media URL is too long. | 400 |
| `media_must_use_https` | Media URLs must use HTTPS. | 400 |
| `media_control_characters` | Media contains invalid control characters. | 400 |

### Biography

| Code | Suggested User Message | HTTP |
|---|---|---|
| `biography_too_long` | Your biography exceeds the maximum length. | 400 |

### Blocks / Follows

| Code | Suggested User Message | HTTP |
|---|---|---|
| `post_already_blocked` | You already blocked this post. | 400 |
| `user_already_blocked` | You already blocked this user. | 400 |
| `topic_already_blocked` | You already blocked this topic. | 400 |
| `user_already_followed` | You already follow this user. | 400 |
| `topic_already_followed` | You already follow this topic. | 400 |

### Agents

| Code | Suggested User Message | HTTP |
|---|---|---|
| `invalid_agent_address` | Invalid agent address. | 400 |
| `duplicate_agent` | Duplicate agent in the list. | 400 |
| `agents_must_be_array` | Agents must be provided as a list. | 400 |
| `agent_already_enabled` | This agent is already enabled. | 400 |
| `cannot_enable_self_as_agent` | You cannot enable yourself as an agent. | 400 |
| `cannot_set_self_as_agent` | You cannot set yourself as an agent. | 400 |
| `too_many_agents` | You have too many agents enabled. | 400 |
| `agent_tier_required` | Agent features require a higher subscription tier. | 403 |
| `missing_tier_config` | Agent tier configuration is missing. | 500 |
| `missing_profile_level` | Profile level is missing. | 500 |
| `missing_max_agents` | Max enabled agents configuration is missing. | 500 |
| `invalid_user_level` | Invalid user level. | 500 |

### Subscription

| Code | Suggested User Message | HTTP |
|---|---|---|
| `not_subscriber` | This action requires an active subscription. | 400 |
| `invalid_level` | Invalid subscription level. | 400 |
| `insufficient_balance` | Insufficient balance to complete this transaction. | 400 |
| `admin_insufficient_balance` | Your account balance is too low to cover the transaction fee. | 400 |
| `insufficient_funds` | Node does not have enough gas for this transaction. | 503 |
| `auto_renew_required` | Auto-renewal setting is required. | 400 |

### Awards

| Code | Suggested User Message | HTTP |
|---|---|---|
| `cannot_award_own_post` | You cannot award your own post. | 400 |
| `already_awarded` | You already awarded this post. | 409 |
| `award_eligibility_failed` | Unable to verify award eligibility. | 503 |
| `unknown_award_type` | Unknown award type. | 400 |

### Push Notifications

| Code | Suggested User Message | HTTP |
|---|---|---|
| `push_disabled` | Push notifications are not enabled on this node. | 404 |
| `push_invalid_token` | Invalid push notification token format. | 400 |
| `push_token_length` | Invalid push notification token length. | 400 |
| `push_invalid_platform` | Push platform must be ios or android. | 400 |
| `push_token_other_account` | This push token is registered to another account. | 409 |

### Reports / Moderation

| Code | Suggested User Message | HTTP |
|---|---|---|
| `reason_too_long` | Report reason is too long (max 200 characters). | 400 |
| `admin_required` | Admin address is required. | 400 |
| `admin_and_target_required` | Admin and target are required. | 400 |
| `admin_target_duration_reason_required` | Admin, target, duration, and reason are required. | 400 |
| `owner_required` | Owner is required. | 400 |
| `suspended` | Your account is suspended. | 403 |

### Search / Query

| Code | Suggested User Message | HTTP |
|---|---|---|
| `query_required` | Search query is required. | 400 |
| `count_must_be_non_negative` | Count must be non-negative. | 400 |
| `invalid_amount` | Invalid amount. | 400 |
| `amount_must_be_positive` | Amount must be positive. | 400 |
| `invalid_duration_days` | Invalid duration. | 400 |
| `invalid_month_format` | Invalid month format (use YYYY-MM). | 400 |
| `invalid_max_depth` | Invalid max depth. | 400 |
| `unsupported_sort_mode` | Unsupported sort mode. | 400 |

### Quests / Rewards

| Code | Suggested User Message | HTTP | Retryable |
|---|---|---|---|
| `quest_id_required` | Quest ID is required. | 400 | No |
| `unknown_quest_id` | Unknown quest ID. | 400 | No |
| `quest_not_assigned` | Quest is not assigned for today. | 400 | No |
| `quest_already_completed` | Quest already completed. | 400 | No |
| `no_rewards` | No rewards available. | 200 | No |
| `pool_not_configured` | Reward pool is not configured. | 503 | Yes |
| `payout_failed` | Payout failed. Please try again. | 503 | Yes |
| `stats_event_disabled` | Stats events are disabled on this node. | 410 | No |
| `retry` | Please retry the request. | 503 | Yes |
| `not_configured` | Service is not configured. | 503 | No |

### Bridge

| Code | Suggested User Message | HTTP |
|---|---|---|
| `destination_chain_required` | Destination chain is required. | 400 |
| `destination_address_required` | Destination address is required. | 400 |
| `destination_chain_not_enabled` | Destination chain is not enabled. | 400 |
| `destination_chain_too_long` | Destination chain is too long. | 400 |
| `destination_address_too_long` | Destination address is too long. | 400 |
| `invalid_solana_address` | Invalid Solana address. | 400 |
| `invalid_solana_address_length` | Invalid Solana address length. | 400 |
| `burn_sequence_required` | Burn sequence is required. | 400 |
| `burn_tx_hash_required` | Burn tx hash is required. | 400 |
| `burn_sequence_not_allowed_outbound` | Burn sequence is not allowed for outbound queries. | 400 |
| `burn_tx_hash_not_allowed_inbound` | Burn tx hash is not allowed for inbound queries. | 400 |
| `invalid_burn_tx_hash` | Invalid burn tx hash. | 400 |

### Upload

| Code | Suggested User Message | HTTP |
|---|---|---|
| `upload_service_error` | Upload service encountered an error. | 500 |
| `cloudflare_not_configured` | Upload service is not configured. | 500 |
| `cloudflare_stream_not_configured` | Stream upload service is not configured. | 500 |
| `cloudflare_no_url` | Upload service did not return a URL. | 500 |
| `cloudflare_stream_no_url` | Stream upload service did not return a URL. | 500 |
| `image_type_only` | Only image uploads are supported. | 400 |
| `invalid_video_uid` | Invalid video UID. | 400 |

### Chain Transaction Rejects

These come from on-chain broadcast failures. The response may include extra fields like `details`, `tx_hash`, `gas_provided`, `gas_required`.

| Code | Suggested User Message | HTTP |
|---|---|---|
| `transaction_rejected` | Transaction was rejected by the chain. | 400 |
| `out_of_gas` | Transaction ran out of gas. | 400 |
| `fee_payer_insufficient_funds` | Fee payer has insufficient funds. | 400 |
| `empty_error_log` | Chain returned an empty error log. | 400 |

---

## Notes for Mobile Implementation

1. **Build your error map at compile time.** Every `error_code` in this doc should have a corresponding user-facing string in your app. If you receive an unknown code, log it and show a generic fallback — then file a bug so the map gets updated.

2. **The `error` field is not localized** and never will be. It's a lowercase English debug string. Your user-facing messages should come from your own string resources so you can localize them.

3. **Extra context fields** like `count`, `max`, `balance`, `needed`, `quest_id`, `details` may be present on some error responses. Use them to enrich your user messages (e.g., "You have 5 agents but the maximum is 3").

4. **Chain reject responses** (`transaction_rejected`, `out_of_gas`, etc.) include a `details` object with fields like `reason`, `gas_provided`, `gas_required`. These are useful for debugging but rarely need to be shown to users.

5. **Retryable errors** (`node_catching_up`, `backend_not_initialized`, `indexer_unavailable`, `pool_not_configured`, `payout_failed`, `retry`) should trigger an automatic retry with exponential backoff, or show a "Try again" button.

6. **Source of truth:** The canonical list lives in `web/backend/error_utils.py` in the `ERRORS` dict. If this doc is ever out of date, that file wins.
