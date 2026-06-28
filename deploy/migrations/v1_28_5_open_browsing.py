from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.28.5-open-browsing"
DESCRIPTION = (
    "Per-node open browsing: enable on mirage.vote/mirage.talk, keep off on every "
    "other existing node (default-true template would otherwise open them via env sync)"
)

# Only these two domains get open browsing on existing nodes.
OPEN_DOMAINS = {"mirage.vote", "mirage.talk"}


def run(config_dir, logger):
    """Gate open browsing per node.

    Fresh deploys never reach here (the runner marks one-time migrations as
    "skipped (fresh deploy)"), so brand-new nodes inherit OPEN_BROWSING_ENABLED=true
    from the template. For existing nodes this migration is the gatekeeper: env
    sync would otherwise push the open template default onto every node, so we
    explicitly pin true on mirage.vote/mirage.talk and false everywhere else.
    """
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    node_env = config_dir / "node.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    domain = (parse_env_file(node_env).get("DOMAIN", "") if node_env.exists() else "").strip().lower()
    target = "true" if domain in OPEN_DOMAINS else "false"

    backup_file(backend_env)

    current = parse_env_file(backend_env).get("OPEN_BROWSING_ENABLED")
    if current == target:
        logger.info(f"  OPEN_BROWSING_ENABLED already {target!r} (domain={domain!r})")
        return f"open browsing already {target} (domain={domain or 'none'})"

    if current is None:
        if not append_env_value(
            backend_env,
            "OPEN_BROWSING_ENABLED",
            target,
            comment="Open browsing for logged-out visitors (write actions still prompt)",
        ):
            raise RuntimeError("Failed to append OPEN_BROWSING_ENABLED to backend.env")
    elif not update_env_value(backend_env, "OPEN_BROWSING_ENABLED", target):
        raise RuntimeError("Failed to update OPEN_BROWSING_ENABLED in backend.env")

    logger.info(f"  Set OPEN_BROWSING_ENABLED={target} (domain={domain!r})")
    return f"open browsing -> {target} (domain={domain or 'none'})"
