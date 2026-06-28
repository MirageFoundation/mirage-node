from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.29.0-video-caps-30min"
DESCRIPTION = (
    "Raise video caps to allow ~30-min uploads: MEDIA_VIDEO_MAX_DURATION_SEC 600->1800 "
    "and MEDIA_MAX_VIDEO_MB 300->1500. Only bumps nodes still on the old defaults so a "
    "custom operator value is never clobbered. (Caddy @upload max_size is raised in the template.)"
)

# key -> (old default we are replacing, new value)
BUMPS = {
    "MEDIA_VIDEO_MAX_DURATION_SEC": ("600", "1800"),
    "MEDIA_MAX_VIDEO_MB": ("300", "1500"),
}


def run(config_dir, logger):
    """Bump video duration/size caps on existing nodes.

    Fresh deploys inherit the new values from the template (this migration is marked
    "skipped" there). Env sync preserves a node's existing non-empty values, so for
    existing nodes we update in place — but only when the current value is the old
    default (or missing), leaving any deliberately customized value untouched.
    """
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    values = parse_env_file(backend_env)
    backed_up = False
    results = []

    for key, (old_default, new_value) in BUMPS.items():
        current = values.get(key)
        if current == new_value:
            results.append(f"{key} already {new_value}")
            continue
        if current is not None and current != old_default:
            results.append(f"{key} customized ({current}); left as-is")
            continue

        if not backed_up:
            backup_file(backend_env)
            backed_up = True

        if current is None:
            if not append_env_value(backend_env, key, new_value, comment=f"{key} (30-min video caps)"):
                raise RuntimeError(f"Failed to append {key} to backend.env")
        elif not update_env_value(backend_env, key, new_value):
            raise RuntimeError(f"Failed to update {key} in backend.env")
        logger.info(f"  Set {key}={new_value} (was {current!r})")
        results.append(f"{key} -> {new_value}")

    return "; ".join(results)
