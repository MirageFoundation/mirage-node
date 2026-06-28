from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.28.5-disable-referral-bonuses"
DESCRIPTION = (
    "Disable referral bonuses fleet-wide: QUESTS_INVITE_RECRUIT_CHANCE=0 and "
    "QUESTS_INVITE_EARNER_CHANCE=0 (no invite_recruit/earner quest -> no 10k payouts)"
)

# Setting both roll chances to 0 means the invite_recruit / invite_earner quests
# are never assigned, so the 10k recruit + 10k welcome bonuses never pay out.
TARGETS = {
    "QUESTS_INVITE_RECRUIT_CHANCE": "0",
    "QUESTS_INVITE_EARNER_CHANCE": "0",
}


def run(config_dir, logger):
    """Pin referral bonus roll chances to 0 on existing nodes.

    Fresh deploys never reach here (the runner marks one-time migrations as
    "skipped (fresh deploy)") and inherit the 0 default straight from the
    template. For existing nodes this migration flips the previously-live
    0.30 chances to 0. The subsequent env sync preserves "0" because it is a
    non-empty value, so the change is durable across restarts.
    """
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    backup_file(backend_env)

    values = parse_env_file(backend_env)
    changed = []

    for key, target in TARGETS.items():
        current = values.get(key)
        if current == target:
            logger.info(f"  {key} already {target!r}, leaving as-is")
            continue
        if current is None:
            if not append_env_value(backend_env, key, target):
                raise RuntimeError(f"Failed to append {key} to backend.env")
        elif not update_env_value(backend_env, key, target):
            raise RuntimeError(f"Failed to update {key} in backend.env")
        logger.info(f"  Set {key}={target} (was {current!r})")
        changed.append(key)

    if changed:
        return f"disabled referral bonuses ({', '.join(changed)})"
    return "referral bonuses already disabled"
