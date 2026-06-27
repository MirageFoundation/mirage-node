from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.28.3-set-cloudflare-media-provider"
DESCRIPTION = (
    "Pin MEDIA_PROVIDER=cloudflare on nodes already using Cloudflare media, so "
    "the new 'local' default does not redirect uploads or break the legacy "
    "get_upload_url mobile shim"
)


def run(config_dir, logger):
    """Preserve current upload behavior for existing Cloudflare nodes.

    The media layer's default provider is now 'local'. A node that was uploading
    to Cloudflare has no MEDIA_PROVIDER set yet, so without this migration it would
    silently switch new uploads to local disk and start returning 410 from the
    deprecated get_upload_url shim (which is gated to cloudflare). We detect those
    nodes by their existing Cloudflare credentials and pin the provider explicitly.

    Fresh deploys never reach here (the runner marks one-time migrations as skipped
    when there is no .migrations file and no existing data), so new operators keep
    the 'local' default. Non-Cloudflare existing nodes fall through unchanged and
    pick up 'local' from the template during env sync.
    """
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    secrets_env = config_dir / "secrets.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    backend_vals = parse_env_file(backend_env)

    # Never override an explicit operator choice.
    existing = (backend_vals.get("MEDIA_PROVIDER") or "").strip()
    if existing:
        logger.info(f"  MEDIA_PROVIDER already set to {existing!r}, leaving as-is")
        return f"MEDIA_PROVIDER already {existing!r}"

    # Cloudflare credentials may live in secrets.env (preferred) or backend.env.
    creds = parse_env_file(secrets_env)
    creds.update(backend_vals)
    account_id = (creds.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    api_token = (creds.get("CLOUDFLARE_API_TOKEN") or "").strip()

    if not (account_id and api_token):
        logger.info("  No Cloudflare credentials found — keeping default provider (local)")
        return "not a cloudflare node; default local"

    backup_file(backend_env)
    if "MEDIA_PROVIDER" in backend_vals:
        ok = update_env_value(backend_env, "MEDIA_PROVIDER", "cloudflare")
    else:
        ok = append_env_value(backend_env, "MEDIA_PROVIDER", "cloudflare")
    if not ok:
        raise RuntimeError("Failed to set MEDIA_PROVIDER=cloudflare in backend.env")

    logger.info("  Cloudflare node detected — pinned MEDIA_PROVIDER=cloudflare")
    return "pinned MEDIA_PROVIDER=cloudflare"
