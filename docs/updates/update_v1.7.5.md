# Mirage v1.7.5 Release Notes

### Overview

v1.7.5 focuses on **IBC infrastructure reliability**. After our IBC client to Osmosis expired due to relayer downtime, we've rebuilt the Hermes relayer setup from the ground up with better automation, persistence, and monitoring.

This release also includes a mobile UX fix for keyboard interactions.

---

### IBC Relayer Overhaul

The `setup_hermes_relayer.sh` script has been completely rewritten:

- **Automatic channel detection**: Script now queries existing IBC channels instead of using hardcoded values
- **Safe channel creation**: New `--create-new-channel` flag with mandatory confirmation to prevent accidental duplicate channels
- **Persistence verification**: Hermes config is stored in `~/.mirage/hermes` (automatically persisted with main volume)
- **Dynamic config generation**: Generates Hermes `config.toml` with correct chain endpoints and gas settings
- **Docker-aware operation**: Detects container environment and uses appropriate process management
- **Clear post-setup instructions**: Reminds operators to restart the container for auto-start on future boots

Channel creation now requires explicit opt-in:
```bash
# Normal setup (uses existing channel)
./setup_hermes_relayer.sh

# Create new channel (requires typing 'CREATE' to confirm)
./setup_hermes_relayer.sh --create-new-channel
```

---

### IBC Health Monitoring

New `scripts/check_hermes_status.sh` script for monitoring relayer status:

- Checks if Hermes process is running
- Verifies config file exists
- Queries IBC client health (expired/frozen detection)
- Checks channel state (OPEN/CLOSED)
- Optional webhook alerts for Slack/Discord integration
- Exit codes for scripted monitoring (0=healthy, 1=warning, 2=critical)

Usage:
```bash
# Manual check
./scripts/check_hermes_status.sh

# With webhook alerts
./scripts/check_hermes_status.sh --alert-webhook "https://hooks.slack.com/..."
```

---

### Deployment Improvements

- **Dockerfile**: Now includes `setup_hermes_relayer.sh` in the image for consistent deployments
- **deploy.sh**: Removed `--volumes` from Docker prune to prevent accidental deletion of persistent data (Hermes config, keys)

---

### Mobile UI

- **Bottom navigation hides when keyboard is open**: On mobile, the bottom nav bar now automatically hides when a text input or textarea is focused, preventing it from obscuring the keyboard or input area

---

### New Scripts

- `scripts/check_hermes_status.sh`: IBC relayer health monitoring with optional webhook alerts
- `scripts/check_osmosis_balance.py`: Query MIRAGE token balances on Osmosis for debugging IBC transfers

---

### IBC Channel Update

Due to the previous IBC client expiration, Mirage now uses a new channel to Osmosis:

| Chain | Old Channel | New Channel |
|-------|-------------|-------------|
| Mirage | channel-0 | channel-1 |
| Osmosis | channel-108600 | channel-108698 |

**IBC Denom Change**: The new channel results in a different IBC denom for MIRAGE on Osmosis:

| | Old (Expired) | New (Active) |
|--|---------------|--------------|
| Osmosis Channel | channel-108600 | channel-108698 |
| IBC Denom | `ibc/FD0C5BF3...B32` | `ibc/E132A35D...BE2` |

Full new denom: `ibc/E132A35DC380C8D68E99F46BC7A5083602F171D00E3BE9471541FB1AA62D8BE2`

PRs submitted to update the chain registry and Osmosis asset lists.

---

### For Operators

If running a node with IBC enabled:

1. The Hermes relayer should run continuously to keep IBC clients alive (trusting period is ~13 days)
2. Use `check_hermes_status.sh` in a cron job to monitor status
3. Hermes config is stored in `~/.mirage/hermes` (persisted automatically with main volume)
