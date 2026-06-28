import logging

from settings import AUTO_ENABLED_AGENTS


logger = logging.getLogger(__name__)


def merge_auto_enabled_agents(cur, agents: list[str]) -> list[str]:
    """Append globally configured agents to a user's enabled-agent list."""
    merged: list[str] = []
    seen: set[str] = set()
    for agent in agents:
        value = str(agent or "").strip().lower()
        if not value:
            raise ValueError("enabled agent address cannot be empty")
        if value not in seen:
            seen.add(value)
            merged.append(value)

    for agent in _resolve_auto_enabled_agents(cur):
        if agent not in seen:
            seen.add(agent)
            merged.append(agent)
    return merged


def _resolve_auto_enabled_agents(cur) -> list[str]:
    if not AUTO_ENABLED_AGENTS:
        return []

    ph = ",".join(["%s"] * len(AUTO_ENABLED_AGENTS))
    cur.execute(
        f"""
        SELECT LOWER(owner)
        FROM profiles
        WHERE LOWER(owner) IN ({ph})
          AND deleted_at IS NULL
        """,
        list(AUTO_ENABLED_AGENTS),
    )
    valid_addresses = {row[0] for row in cur.fetchall() if row[0]}
    missing = [a for a in AUTO_ENABLED_AGENTS if a not in valid_addresses]
    if missing:
        raise ValueError(f"AUTO_ENABLED_AGENTS address(es) not found: {', '.join(missing)}")

    logger.debug(
        "auto_enabled_agents.resolved configured=%d",
        len(AUTO_ENABLED_AGENTS),
    )
    return list(AUTO_ENABLED_AGENTS)
