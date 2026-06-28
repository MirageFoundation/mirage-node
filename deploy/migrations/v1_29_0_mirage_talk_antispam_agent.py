from pathlib import Path

from deploy.migrations._helpers import (
    append_env_value,
    backup_file,
    parse_env_file,
    update_env_value,
)

MIGRATION_KEY = "v1.29.0-mirage-talk-antispam-agent"
DESCRIPTION = (
    "Enable AntiSpamBot by default for every user on mirage.talk by adding it to "
    "AUTO_ENABLED_AGENTS (preserving any existing agents). No-op on every other node."
)

# Only mirage.talk gets AntiSpamBot enabled by default.
TARGET_DOMAIN = "mirage.talk"
ANTISPAM_AGENT = "mirage17jn2j2wwnvqdhtecwfh0wa0vpj9qa5gcalztap"


def run(config_dir, logger):
    """Add AntiSpamBot to AUTO_ENABLED_AGENTS on mirage.talk only.

    Fresh deploys are marked "skipped" by the runner, so this is purely a
    gatekeeper for existing nodes. It appends the agent to any existing
    AUTO_ENABLED_AGENTS list (comma-separated) and is idempotent: if the agent is
    already present, nothing changes.
    """
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"
    node_env = config_dir / "node.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    domain = (parse_env_file(node_env).get("DOMAIN", "") if node_env.exists() else "").strip().lower()
    if domain != TARGET_DOMAIN:
        logger.info(f"  Not {TARGET_DOMAIN} (domain={domain!r}); leaving AUTO_ENABLED_AGENTS unchanged")
        return f"skipped (domain={domain or 'none'})"

    current = parse_env_file(backend_env).get("AUTO_ENABLED_AGENTS", "")
    agents = [a.strip() for a in current.split(",") if a.strip()]
    if ANTISPAM_AGENT in agents:
        logger.info("  AntiSpamBot already in AUTO_ENABLED_AGENTS")
        return "antispam agent already enabled"

    agents.append(ANTISPAM_AGENT)
    new_value = ",".join(agents)

    backup_file(backend_env)
    if current == "" and "AUTO_ENABLED_AGENTS" not in parse_env_file(backend_env):
        if not append_env_value(
            backend_env,
            "AUTO_ENABLED_AGENTS",
            new_value,
            comment="Agents enabled by default for every user (comma-separated mirage1 addresses)",
        ):
            raise RuntimeError("Failed to append AUTO_ENABLED_AGENTS to backend.env")
    elif not update_env_value(backend_env, "AUTO_ENABLED_AGENTS", new_value):
        raise RuntimeError("Failed to update AUTO_ENABLED_AGENTS in backend.env")

    logger.info(f"  Set AUTO_ENABLED_AGENTS={new_value}")
    return f"antispam agent enabled (agents={len(agents)})"
