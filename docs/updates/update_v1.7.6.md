# Mirage v1.7.6 Release Notes

### Overview

v1.7.6 introduces a **deploy migration system** for managing configuration changes across updates, and restructures environment files for better secrets management.

---

### Deploy Migration System

New migration system that runs automatically on container startup:

- **One-time migrations**: Tracked in `.migrations` file, run once per deployment
- **Env file sync**: Runs every startup to keep config files updated with latest templates
- **Automatic backups**: Creates timestamped backups before any changes

```bash
# Check migration status
python3 -m deploy.migrations --list

# Migrations run automatically on container start
```

---

### Environment File Restructuring

Simplified env file management:

- **Renamed `.env.example` → `.env`** in templates
- **Deploy preserves user values**: Only copies template if file doesn't exist
- **Secrets consolidated**: Sensitive credentials moved to dedicated `secrets.env`

Template files:
- `backend.env` - Backend server settings
- `frontend.env` - Frontend build settings  
- `indexer.env` - Blockchain indexer settings
- `node.env` - Node/validator settings
- `secrets.env` - API keys and tokens (Cloudflare, Telegram, OpenAI)

---

### v1.7.6 Migration: Secrets Separation

The `v1_7_6_secrets_env` migration automatically:

1. Moves sensitive credentials to `secrets.env`:
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_HASH`, `CLOUDFLARE_STREAM_CUSTOMER_CODE`
   - `OPENAI_API_KEY`

2. Removes migrated keys from source files (`backend.env`, `node.env`)

3. Deletes deprecated `.env.example` files

---

### Env Sync on Every Deploy

The env sync ensures config files stay current:

- **Preserves all existing user values**
- **Adds new keys** from templates with default values
- **Removes deprecated keys** no longer in templates
- **Maintains file structure** and comments from templates

This means new configuration options are automatically available after updates without manual intervention.

---

### For Operators

No manual action required. On next deploy:

1. Migration runs automatically to move secrets
2. Env sync updates files to latest format
3. Backups created in `~/.mirage/env/.backups/`

If you need to restore previous config:
```bash
ls ~/.mirage/env/.backups/
cp ~/.mirage/env/.backups/backend.env.TIMESTAMP.bak ~/.mirage/env/backend.env
```

---

### Technical Details

New files:
- `deploy/migrations/__init__.py` - Migration runner
- `deploy/migrations/_sync_env_files.py` - Env sync utility
- `deploy/migrations/v1_7_6_secrets_env.py` - Secrets migration

Updated:
- `deploy/entrypoint.sh` - Runs migrations on startup
- `deploy/deploy.sh` - Only copies env files if missing
- `deploy/Dockerfile` - Includes migration system
