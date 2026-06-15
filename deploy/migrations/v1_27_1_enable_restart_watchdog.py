"""Enable the (now non-destructive) divergence watchdog on every validator.

Context: as of the 2026-06-14 stuck-consensus incident the watchdog's first-line
action is a NON-DESTRUCTIVE process restart (recover.sh restart). Running it
everywhere is therefore safe and lets a stuck/crashed node self-heal on every
host, not just mirage.talk.

Env files are only seeded on --init and are preserved (never overwritten) on
--update, and the template sync preserves existing non-empty values. So flipping
the template default from AUTO_DIVERGENCE_RECOVERY=false to true does NOT reach
the three already-deployed validators that still have it set to false. This
one-time migration flips it on disk.

It deliberately does NOT touch WATCHDOG_AUTORECOVER: destructive peer-pull stays
opt-in and single-host (mirage.talk keeps its true; everyone else keeps false).
"""

from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.27.1-enable-restart-watchdog"
DESCRIPTION = "Enable restart-only divergence watchdog on all hosts (AUTO_DIVERGENCE_RECOVERY=true)"

KEY = "AUTO_DIVERGENCE_RECOVERY"


def run(config_dir, logger):
    node_env = Path(config_dir) / "node.env"

    if not node_env.exists():
        # Fresh hosts get the template default (already true); nothing to do.
        logger.info("  node.env not present; template default applies")
        return "no node.env (fresh host)"

    current = parse_env_file(node_env).get(KEY)
    if current == "true":
        logger.info(f"  {KEY} already true; leaving as-is")
        return "already true"

    backup_file(node_env)

    if current is None:
        append_env_value(
            node_env,
            KEY,
            "true",
            comment="Run the divergence watchdog (restart-only unless WATCHDOG_AUTORECOVER=true)",
        )
        logger.info(f"  Appended {KEY}=true")
        return "appended true"

    update_env_value(node_env, KEY, "true")
    logger.info(f"  Updated {KEY}: {current} -> true")
    return f"updated {current} -> true"
