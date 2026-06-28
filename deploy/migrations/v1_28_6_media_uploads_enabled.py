from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.28.6-media-uploads-enabled"
DESCRIPTION = (
    "Per-node media uploads: enable on mirage.vote/mirage.talk (behind Bunny Shield "
    "upload scanning), disable on every other existing node so no node accepts "
    "unscanned uploads. /api/upload_media + legacy /api/get_upload_url return 403 when off."
)

# Only these two domains run a scanning edge (Bunny Shield) and accept uploads.
UPLOAD_DOMAINS = {"mirage.vote", "mirage.talk"}


def run(config_dir, logger):
    """Gate public media uploads per node.

    Fresh deploys never reach here (the runner marks one-time migrations as
    "skipped (fresh deploy)"), so brand-new nodes inherit MEDIA_UPLOADS_ENABLED=true
    from the template. For existing nodes this migration is the gatekeeper: env sync
    would otherwise push the true template default onto every node, so we explicitly
    pin true on mirage.vote/mirage.talk (which sit behind Bunny Shield) and false on
    every other node (e.g. the IP-only nodes), which have no scanning edge.
    """
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    node_env = config_dir / "node.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    domain = (parse_env_file(node_env).get("DOMAIN", "") if node_env.exists() else "").strip().lower()
    target = "true" if domain in UPLOAD_DOMAINS else "false"

    backup_file(backend_env)

    current = parse_env_file(backend_env).get("MEDIA_UPLOADS_ENABLED")
    if current == target:
        logger.info(f"  MEDIA_UPLOADS_ENABLED already {target!r} (domain={domain!r})")
        return f"media uploads already {target} (domain={domain or 'none'})"

    if current is None:
        if not append_env_value(
            backend_env,
            "MEDIA_UPLOADS_ENABLED",
            target,
            comment="Public media uploads. Only true where a scanning edge (Bunny Shield) fronts uploads.",
        ):
            raise RuntimeError("Failed to append MEDIA_UPLOADS_ENABLED to backend.env")
    elif not update_env_value(backend_env, "MEDIA_UPLOADS_ENABLED", target):
        raise RuntimeError("Failed to update MEDIA_UPLOADS_ENABLED in backend.env")

    logger.info(f"  Set MEDIA_UPLOADS_ENABLED={target} (domain={domain!r})")
    return f"media uploads -> {target} (domain={domain or 'none'})"
