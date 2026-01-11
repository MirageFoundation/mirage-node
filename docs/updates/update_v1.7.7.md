# Mirage v1.7.7 Release Notes

### Overview

v1.7.7 is a chain upgrade that updates subscription tier pricing to a 30-day billing cycle and removes Go-based log rotation from `miraged`.

---

### Tier Pricing Update

Subscription costs changed from daily to monthly (30-day) pricing:

| Tier | Old (per day) | New (per 30 days) |
|------|---------------|-------------------|
| Trusted (1) | 1 MIRAGE | 10 MIRAGE |
| Established (2) | 2 MIRAGE | 20 MIRAGE |
| Distinguished (3) | 3 MIRAGE | 30 MIRAGE |

The `subscription_period` parameter changed from 1440 minutes (1 day) to 43200 minutes (30 days).

---

### Go Log Rotation Removal

Removed internal Go-based log rotation from `miraged`. All logging now goes through shell-based cronolog to `~/.mirage/logs/node/miraged-YYYY-MM-DD.log`.

---

### Chain Upgrade

**Governance proposal**: `v1.7.7-tier-pricing`

The upgrade handler updates:
- Tier `period_fee` values (10/20/30 MIRAGE)
- `subscription_period` param (43200 minutes)

---

### Migration

`v1.7.7-tier-pricing` migration cleans up old Go log files from `~/.mirage/node/logs/`.

---

### Verification

```bash
python3 scripts/verify_v1_7_7_tier_pricing.py
```
