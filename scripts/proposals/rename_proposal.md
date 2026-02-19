# Proposal: Rename Distribution and Validator Accounts

Standardize all distribution and validator account usernames to use the `mirage-*` naming convention, replacing legacy `Anon-*` and ad-hoc names via governance `MsgSetUsername`.

---

## Username Renames

All five renames are `MsgSetUsername` messages executed through governance. The governance path bypasses the free-tier `Anon-` prefix enforcement.

| Current Username | New Username | Address |
|---|---|---|
| `Anon-DevelopmentDistribution` | `mirage-development-distribution` | `mirage13e3rxansuzneayrf9nwrxdpp38sphshz7ly8xd` |
| `Anon-MarketingDistribution` | `mirage-marketing-distribution` | `mirage1zjs7qn3chramktnu96wft4cs6ry2srddv27dmr` |
| `Anon-FoundersDistribution` | `mirage-founders-distribution` | `mirage1x2epe8m0x3jkfxm4x4fpns4anv8u78ywm77ygg` |
| *(unknown)* | `mirage-node-3` | `mirage1w77ptf0m759n9dnu4rflms8dm69a7g7vec6zu3` |
| `Validator-Bangalore-1` | `mirage-node-4` | `mirage1ur6xu4ue9f4pk4a2thnhnf8ctu4dpkqehp7yqs` |

---

## Submission

The governance proposal JSON is at `scripts/proposals/proposal_rename_usernames.json`. Dry-run first:

```bash
python3 scripts/submit_proposal.py remote scripts/proposals/proposal_rename_usernames.json --dry-run
```

Remove `--dry-run` to submit.

---

## Code Changes (after renames are live)

Update the comments in `web/backend/routes/public.py` to reflect the new names:

```python
_EXCLUDED_FROM_CIRCULATING = [
    "mirage1x2epe8m0x3jkfxm4x4fpns4anv8u78ywm77ygg",  # mirage-founders-distribution
    "mirage1zjs7qn3chramktnu96wft4cs6ry2srddv27dmr",  # mirage-marketing-distribution
    "mirage13e3rxansuzneayrf9nwrxdpp38sphshz7ly8xd",  # mirage-development-distribution
]
```

---

## Verification

After the proposal passes:

```bash
# Check usernames via REST
curl -s http://127.0.0.1/chain/rest/mirage/core/v1/profile/mirage13e3rxansuzneayrf9nwrxdpp38sphshz7ly8xd | jq .profile.username
curl -s http://127.0.0.1/chain/rest/mirage/core/v1/profile/mirage1zjs7qn3chramktnu96wft4cs6ry2srddv27dmr | jq .profile.username
curl -s http://127.0.0.1/chain/rest/mirage/core/v1/profile/mirage1x2epe8m0x3jkfxm4x4fpns4anv8u78ywm77ygg | jq .profile.username
curl -s http://127.0.0.1/chain/rest/mirage/core/v1/profile/mirage1w77ptf0m759n9dnu4rflms8dm69a7g7vec6zu3 | jq .profile.username
curl -s http://127.0.0.1/chain/rest/mirage/core/v1/profile/mirage1ur6xu4ue9f4pk4a2thnhnf8ctu4dpkqehp7yqs | jq .profile.username
```
