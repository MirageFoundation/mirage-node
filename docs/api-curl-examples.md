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

### Get config

Configuration snapshot including chain params and optional user context.

```bash
curl "${API_BASE}/get_config"
curl "${API_BASE}/get_config?address=mirage1abc123..."
```

### Get topics

```bash
curl "${API_BASE}/get_topics"
curl "${API_BASE}/get_topics?limit=20"
```

### Get posts

```bash
curl "${API_BASE}/get_posts"
curl "${API_BASE}/get_posts?page=2&limit=10"
curl "${API_BASE}/get_posts?topic=tech&page=1&limit=20"
curl "${API_BASE}/get_posts?address=mirage1viewer..."
```

### Get posts (multi-topic)

```bash
curl -X POST "${API_BASE}/get_posts_multi" \
  -H "Content-Type: application/json" \
  -d '{
    "topics": ["tech", "science", "general"],
    "limit": 20,
    "page": 1,
    "address": "mirage1viewer..."
  }'
```

### Get user posts

```bash
curl "${API_BASE}/get_user_posts?owner=mirage1abc123..."
curl "${API_BASE}/get_user_posts?owner=mirage1abc123...&type=submissions&page=1&limit=10"
curl "${API_BASE}/get_user_posts?owner=mirage1abc123...&type=comments"
```

### Get comments

```bash
curl "${API_BASE}/get_comments?post_id=abc123def456..."
curl "${API_BASE}/get_comments?post_id=abc123def456...&address=mirage1viewer..."
```

### Username resolution

```bash
curl "${API_BASE}/get_address_from_username?username=alice"
curl "${API_BASE}/get_username_from_address?address=mirage1abc123..."
```

### Transaction status

```bash
curl "${API_BASE}/get_tx_status?hash=abc123def456..."
```

### Peers and stats

```bash
curl "${API_BASE}/get_peers"
curl "${API_BASE}/get_stats"
```

### Inbox and reports

```bash
curl "${API_BASE}/get_inbox?address=mirage1abc123..."
curl "${API_BASE}/get_reports?address=mirage1admin...&limit=100"
```

---

## Write endpoints (POST, meta-signed)

Write endpoints accept JSON bodies containing an envelope (`pubkey`, `signature`, `last_block_hash`, `pow_difficulty`, `pow`, `timestamp`) plus message-specific fields.

For canonical signing rules and envelope details, see `docs/react-native-api-guide.md`.

These write examples deliberately avoid placeholders like `<base64-pubkey>` because they are not implementable.
Instead, generate fully signed payloads using `scripts/rn_signed_request.py` and pipe them to curl.

### Setup

```bash
conda activate mirage-node

NODE_DOMAIN="mirage.vote"
API_BASE="https://${NODE_DOMAIN}/api"
MNEMONIC="word1 word2 ... word24"
```

### Post

```bash
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" post \
  --topic "general" --title "My Post Title" --content "Post content here" --tag "" \
  | curl -X POST "${API_BASE}/core/post" -H "Content-Type: application/json" -d @-
```

### Vote

```bash
TARGET="post_txhash_here"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" vote \
  --target "${TARGET}" --direction 1 \
  | curl -X POST "${API_BASE}/core/vote" -H "Content-Type: application/json" -d @-
```

### Set username

```bash
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" set-username --username "alice" \
  | curl -X POST "${API_BASE}/core/set_username" -H "Content-Type: application/json" -d @-
```

### Edit and delete

```bash
OVERRIDE="original_post_txhash"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" edit \
  --override "${OVERRIDE}" --target "" --topic "general" --title "Updated" --content "Updated" --tag "" \
  | curl -X POST "${API_BASE}/core/edit" -H "Content-Type: application/json" -d @-

TARGET="post_txhash_to_delete"
python3 scripts/rn_signed_request.py --api-base "${API_BASE}" --mnemonic "${MNEMONIC}" delete-post \
  --target "${TARGET}" \
  | curl -X POST "${API_BASE}/core/delete_post" -H "Content-Type: application/json" -d @-
```

---

## Notes

- Addresses use the `mirage1` prefix (Bech32)
- Transaction hashes are 64-character lowercase hex strings
- `timestamp` is milliseconds since epoch (for example `Date.now()` in JavaScript)


