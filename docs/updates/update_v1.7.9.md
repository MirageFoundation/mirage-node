# Mirage v1.7.9 Release Notes

### Overview

v1.7.9 is a **chain upgrade** that completes the directory restructuring started in v1.7.8 by changing the `miraged` binary's default home directory from `~/.mirage/main/` to `~/.mirage/node/`.

---

### DefaultNodeHome Change

The `miraged` binary now uses `~/.mirage/node/` as its default home directory instead of `~/.mirage/main/`.

- **Old default**: `~/.mirage/main/`
- **New default**: `~/.mirage/node/`

This change was implemented via a chain upgrade handler (`v1.7.9-node-home`).

---

### Symlink Removal

The v1.7.8 migration created a backward-compatibility symlink `~/.mirage/main` → `~/.mirage/node` to support the old binary during the transition. 

With this upgrade, that symlink is no longer needed and is removed by the `v1_7_9_remove_main_symlink.py` migration.

---

### Directory Structure (Final)

After v1.7.9, the `~/.mirage/` directory structure is:

```
~/.mirage/
├── config/           # Configuration files
├── env/              # Environment files
├── logs/             # Cronolog output
│   └── node/         # miraged logs (miraged-YYYY-MM-DD.log)
├── node/             # Node home (data, keyring, etc.)
│   ├── config/       # CometBFT config
│   ├── data/         # Blockchain data
│   └── keyring-test/ # Keys
└── postgres/         # PostgreSQL data
```

Note: `~/.mirage/main/` no longer exists (neither as directory nor symlink).

---

### For Operators

- **Chain Upgrade**: Validators must update their `miraged` binary before the upgrade height.
- **Automatic cleanup**: The migration automatically removes the `main` symlink.
- **Verify**: Use `scripts/verify_upgrade.py` to confirm all checks pass.

---

### Verification

After the upgrade, `scripts/verify_upgrade.py` checks:
1. `~/.mirage/node/` exists
2. `~/.mirage/postgres/` exists
3. `~/.mirage/main/` does **not** exist (no symlink)
4. Chain params are correct (tier fees, subscription period)
5. Cronolog is writing logs
