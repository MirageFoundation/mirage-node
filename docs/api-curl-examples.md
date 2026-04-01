# Mirage API Curl Examples (Public)

This document provides copy-pasteable `curl` examples for the Mirage HTTP API.

### Variables used below

```bash
NODE_DOMAIN="<YOUR_NODE_DOMAIN>"
API_BASE="https://${NODE_DOMAIN}/api"
```

If you want to test against a public node, set `API_BASE` accordingly.

---

## Read endpoints (GET)

### Get parameters

Latest block hash and current PoW difficulty. Optionally include balance for an address.

```bash
curl "${API_BASE}/get_parameters"
curl "${API_BASE}/get_parameters?address=mirage1abc123..."
```

### Get chain config

Chain governance params (tiers, limits, subscription_period, etc.).

```bash
curl "${API_BASE}/get_chain_config"
```

### Get node config

Per-node static settings (validator info, feature flags).

```bash
curl "${API_BASE}/get_node_config"
```

### Get user status

User-specific status (level, reserve funds, balance, subscription expiry).

```bash
curl "${API_BASE}/get_user_status?address=mirage1abc123..."
```

### Get profile

Full profile data for an address.

```bash
curl "${API_BASE}/get_profile?address=mirage1abc123..."
```

### Get user followed

Lists of users, topics, and agents an address has enabled.

```bash
curl "${API_BASE}/get_user_followed?address=mirage1abc123..."
```

### Get user blocked

Lists of blocked users and blocked posts for an address.

```bash
curl "${API_BASE}/get_user_blocked?address=mirage1abc123..."
```

### Get blocked users

Blocked users list for an address.

```bash
curl "${API_BASE}/get_blocked_users?address=mirage1abc123..."
```

### Get preferences

User preferences for an address.

```bash
curl "${API_BASE}/get_preferences?address=mirage1abc123..."
```

### Get similar users

Find users with similar voting patterns.

```bash
curl "${API_BASE}/get_similar_users?address=mirage1abc123..."
```

### Get users

Paginated list of users.

```bash
curl "${API_BASE}/get_users"
curl "${API_BASE}/get_users?limit=100&page=2"
curl "${API_BASE}/get_users?has_username=true"
```

### Get topics

```bash
curl "${API_BASE}/get_topics"
curl "${API_BASE}/get_topics?limit=20&min_posts=5"
```

### Search topics

```bash
curl "${API_BASE}/search_topics?q=tech"
curl "${API_BASE}/search_topics?q=tech&limit=20&offset=0"
```

### Search (unified)

Search across topics, users, and posts.

```bash
curl "${API_BASE}/search?q=hello"
curl "${API_BASE}/search?q=hello&type=posts&limit=20&offset=0"
curl "${API_BASE}/search?q=hello&type=users"
curl "${API_BASE}/search?q=hello&type=topics"
curl "${API_BASE}/search?q=hello&address=mirage1viewer..."
```

### Get posts

```bash
curl "${API_BASE}/get_posts"
curl "${API_BASE}/get_posts?page=2&limit=10"
curl "${API_BASE}/get_posts?topic=tech&page=1&limit=20"
curl "${API_BASE}/get_posts?address=mirage1viewer..."
curl "${API_BASE}/get_posts?feed=home&address=mirage1viewer..."
curl "${API_BASE}/get_posts?feed=following&address=mirage1viewer..."
curl "${API_BASE}/get_posts?by=newest"
curl "${API_BASE}/get_posts?by=magic"
curl "${API_BASE}/get_posts?allowed_tags=sensitive,violence"
```

### Get user posts

```bash
curl "${API_BASE}/get_user_posts?owner=mirage1abc123..."
curl "${API_BASE}/get_user_posts?owner=mirage1abc123...&type=submissions&page=1&limit=10"
curl "${API_BASE}/get_user_posts?owner=mirage1abc123...&type=comments"
curl "${API_BASE}/get_user_posts?owner=mirage1abc123...&address=mirage1viewer..."
```

### Get comments

```bash
curl "${API_BASE}/get_comments?post_id=abc123def456..."
curl "${API_BASE}/get_comments?post_id=abc123def456...&address=mirage1viewer..."
```

### Get root post ID

Resolve a comment back to its root post.

```bash
curl "${API_BASE}/get_root_post_id?comment_id=abc123def456..."
```

### Get comment context

Get the parent chain for a comment (up to `max_depth` levels).

```bash
curl "${API_BASE}/get_comment_context?comment_id=abc123def456..."
curl "${API_BASE}/get_comment_context?comment_id=abc123def456...&address=mirage1viewer...&max_depth=3"
```

### Username resolution

```bash
# Single lookup
curl "${API_BASE}/get_address_from_username?username=alice"
curl "${API_BASE}/get_username_from_address?address=mirage1abc123..."

# Bulk lookup (POST)
curl -X POST "${API_BASE}/get_address_from_username" \
  -H "Content-Type: application/json" \
  -d '{"usernames": ["alice", "bob"]}'

curl -X POST "${API_BASE}/get_username_from_address" \
  -H "Content-Type: application/json" \
  -d '{"addresses": ["mirage1abc...", "mirage1def..."]}'
```

### Transaction status

```bash
curl "${API_BASE}/get_tx_status?hash=abc123def456..."
curl "${API_BASE}/get_tx_status?hash=abc123def456...&address=mirage1abc123..."
```

### Peers and stats

```bash
curl "${API_BASE}/get_peers"
curl "${API_BASE}/get_stats"
curl "${API_BASE}/get_stats?tab=signups"
curl "${API_BASE}/get_stats?tab=subscribers"
curl "${API_BASE}/get_stats?tab=accounts"
curl "${API_BASE}/get_stats?tab=analytics"
curl "${API_BASE}/get_stats?tab=rewards"
```

### Network and supply

```bash
curl "${API_BASE}/get_network_stats"
curl "${API_BASE}/get_welcome_stats"
curl "${API_BASE}/get_total_supply"
curl "${API_BASE}/get_circulating_supply"
curl "${API_BASE}/get_circulation_stats"
curl "${API_BASE}/get_supply_history"
```

### Inbox and reports

```bash
curl "${API_BASE}/get_inbox?address=mirage1abc123..."
curl "${API_BASE}/get_inbox?address=mirage1abc123...&page=2&limit=50"
curl "${API_BASE}/get_reports?address=mirage1admin...&limit=100"
```

### Referrals and invite codes

```bash
curl "${API_BASE}/referral/stats?address=mirage1abc123..."
curl "${API_BASE}/get_invite_codes?address=mirage1abc123..."

curl -X POST "${API_BASE}/validate_invite_code" \
  -H "Content-Type: application/json" \
  -d '{"code": "XXXXX-XXXX"}'
```

### Rewards

```bash
curl "${API_BASE}/rewards/summary?owner=mirage1abc123..."
curl "${API_BASE}/rewards/achievements?owner=mirage1abc123..."
```

### Bridge

```bash
curl "${API_BASE}/bridge/config"
curl "${API_BASE}/bridge/status?burn_sequence=1&chain=ethereum"
curl "${API_BASE}/bridge/status?burn_tx_hash=abc123def456..."
```

---

## Write endpoints (POST, meta-signed)

Write endpoints accept JSON bodies containing an envelope (`pubkey`, `signature`, `last_block_hash`, `pow_difficulty`, `pow`, `timestamp`) plus message-specific fields.

For canonical signing rules and envelope details, see `docs/react-native-api-guide.md`.

These write examples deliberately avoid placeholders like `<base64-pubkey>` because they are not implementable.
Instead, generate fully signed payloads using `scripts/curl_examples.py` and pipe them to curl.

### Setup

```bash
conda activate mirage-node

NODE_DOMAIN="mirage.vote"
API_BASE="https://${NODE_DOMAIN}/api"
MNEMONIC="word1 word2 ... word24"
```

### Post

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" post \
  --topic "general" --title "My Post Title" --content "Post content here" --tag "" \
  | curl -X POST "${API_BASE}/core/post" -H "Content-Type: application/json" -d @-
```

### Comment

```bash
PARENT="parent_post_txhash_here"
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" comment \
  --parent "${PARENT}" --content "My comment" \
  | curl -X POST "${API_BASE}/core/post" -H "Content-Type: application/json" -d @-
```

### Vote

```bash
TARGET="post_txhash_here"
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" vote \
  --target "${TARGET}" --direction 1 \
  | curl -X POST "${API_BASE}/core/vote" -H "Content-Type: application/json" -d @-
```

### Set username

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" set-username \
  --username "alice" \
  | curl -X POST "${API_BASE}/core/set_username" -H "Content-Type: application/json" -d @-

# With referrer
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" set-username \
  --username "alice" --referrer "mirage1referrer..." \
  | curl -X POST "${API_BASE}/core/set_username" -H "Content-Type: application/json" -d @-
```

### Edit and delete

```bash
OVERRIDE="original_post_txhash"
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" edit \
  --override "${OVERRIDE}" --target "" --topic "general" --title "Updated" --content "Updated" --tag "" \
  | curl -X POST "${API_BASE}/core/edit" -H "Content-Type: application/json" -d @-

TARGET="post_txhash_to_delete"
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" delete-post \
  --target "${TARGET}" \
  | curl -X POST "${API_BASE}/core/delete_post" -H "Content-Type: application/json" -d @-
```

### Enable / disable agent

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" enable-agent \
  --agent "mirage1agent..." \
  | curl -X POST "${API_BASE}/core/enable_agent" -H "Content-Type: application/json" -d @-

python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" disable-agent \
  --agent "mirage1agent..." \
  | curl -X POST "${API_BASE}/core/disable_agent" -H "Content-Type: application/json" -d @-
```

### Follow / unfollow user

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" follow-user \
  --user "mirage1user..." \
  | curl -X POST "${API_BASE}/core/follow_user" -H "Content-Type: application/json" -d @-

python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unfollow-user \
  --user "mirage1user..." \
  | curl -X POST "${API_BASE}/core/unfollow_user" -H "Content-Type: application/json" -d @-
```

### Follow / unfollow topic

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" follow-topic \
  --topic "tech" \
  | curl -X POST "${API_BASE}/core/follow_topic" -H "Content-Type: application/json" -d @-

python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unfollow-topic \
  --topic "tech" \
  | curl -X POST "${API_BASE}/core/unfollow_topic" -H "Content-Type: application/json" -d @-
```

### Block / unblock post

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" block-post \
  --target "post_txhash_here" \
  | curl -X POST "${API_BASE}/core/block_post" -H "Content-Type: application/json" -d @-

python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unblock-post \
  --target "post_txhash_here" \
  | curl -X POST "${API_BASE}/core/unblock_post" -H "Content-Type: application/json" -d @-
```

### Block / unblock user

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" block-user \
  --target "mirage1user..." \
  | curl -X POST "${API_BASE}/core/block_user" -H "Content-Type: application/json" -d @-

python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" unblock-user \
  --target "mirage1user..." \
  | curl -X POST "${API_BASE}/core/unblock_user" -H "Content-Type: application/json" -d @-
```

### Send tokens

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" send-tokens \
  --target "mirage1recipient..." --amount 1000000 \
  | curl -X POST "${API_BASE}/core/send_tokens" -H "Content-Type: application/json" -d @-
```

### Upgrade level (subscribe)

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" upgrade-level \
  --level 1 \
  | curl -X POST "${API_BASE}/core/subscribe" -H "Content-Type: application/json" -d @-
```

### Set auto-renewal

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" set-auto-renewal \
  --auto-renew true \
  | curl -X POST "${API_BASE}/core/set_auto_renewal" -H "Content-Type: application/json" -d @-
```

### Report

```bash
python3 scripts/curl_examples.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" report \
  --target "post_txhash_here" --reason "Spam content" \
  | curl -X POST "${API_BASE}/core/report" -H "Content-Type: application/json" -d @-
```

### Mark inbox viewed

```bash
curl -X POST "${API_BASE}/mark_inbox_viewed" \
  -H "Content-Type: application/json" \
  -d '{"address": "mirage1abc123..."}'
```

---

## Notes

- Addresses use the `mirage1` prefix (Bech32)
- Transaction hashes are 64-character lowercase hex strings
- `timestamp` is milliseconds since epoch (for example `Date.now()` in JavaScript)
- Amount values are in `umirage` (1 MIRAGE = 1,000,000 umirage)
- Vote `direction`: 1 = upvote, -1 = downvote, 0 = remove vote
- Tag must be one of: `""`, `"sensitive"`, `"adult"`, `"gore"`, `"violence"`, `"death"`
