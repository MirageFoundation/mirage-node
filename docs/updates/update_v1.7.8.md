# Mirage v1.7.8 Release Notes

### Overview

v1.7.8 restructures the `~/.mirage` directory, improves deployment scripts, and enhances backend reliability.

---

### Directory Restructuring

The `~/.mirage` directory has been reorganized:

**Before:**
```
~/.mirage/
├── main/                  # node home
│   ├── config/
│   ├── data/
│   │   └── postgres/
│   └── keyring-test/
```

**After:**
```
~/.mirage/
├── node/                  # renamed from main/
│   ├── config/
│   ├── data/              # blockchain data only
│   └── keyring-test/
├── postgres/              # moved to top level
```

**Why:**
- `node/` is clearer than `main/`
- PostgreSQL is a separate service, shouldn't be nested in blockchain data
- Aligns with `MIRAGE_NODE_HOME` and `node.env` naming

---

### Deploy Script Improvements

**Tarball hash check**: Skips upload if remote already has identical file:
```
==> Remote tarball hash matches, skipping upload.
```

**ProxyJump support**: Deploy through jump hosts:
```bash
./scripts/deploy_all_prod.sh --update -J jump-host.example.com
```

---

### Backend Reliability

- **Extended retry timeouts**: Backend waits up to 1 hour for chain connection (was 5 min)
- **Chain params TTL**: 5-minute cache refresh (tier pricing updates automatically after chain upgrades)

---

### Migration

`v1.7.8-directory-restructuring` runs automatically on container start:
1. Moves postgres: `~/.mirage/main/data/postgres/` → `~/.mirage/postgres/`
2. Renames: `~/.mirage/main/` → `~/.mirage/node/`

---

### For Operators

No manual action required. On next deploy, migration handles everything automatically.
