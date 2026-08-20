import logging
import threading
import time

from settings import AUTO_ENABLED_AGENTS


logger = logging.getLogger(__name__)

# AUTO_ENABLED_AGENTS is static process config; the query in
# _resolve_auto_enabled_agents only verifies those addresses still have live
# profiles, and returns the same list for every viewer. Resolving it per call
# put a profiles lookup on every feed request on the site. Re-verify once per
# TTL instead, so a deleted agent profile still stops the overlay promptly.
AUTO_AGENTS_TTL_SECONDS = 300.0

_resolved_lock = threading.Lock()
_resolved_agents: list[str] | None = None
_resolved_expires_at = 0.0


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
    global _resolved_agents, _resolved_expires_at

    if not AUTO_ENABLED_AGENTS:
        return []

    now = time.monotonic()
    with _resolved_lock:
        if _resolved_agents is not None and now < _resolved_expires_at:
            return list(_resolved_agents)

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
        # Deliberately not cached: a misconfigured address must keep failing on
        # every request until it is corrected, not go quiet for a TTL.
        raise ValueError(f"AUTO_ENABLED_AGENTS address(es) not found: {', '.join(missing)}")

    with _resolved_lock:
        _resolved_agents = list(AUTO_ENABLED_AGENTS)
        _resolved_expires_at = time.monotonic() + AUTO_AGENTS_TTL_SECONDS

    logger.debug(
        "auto_enabled_agents.resolved configured=%d ttl=%.0fs",
        len(AUTO_ENABLED_AGENTS),
        AUTO_AGENTS_TTL_SECONDS,
    )
    return list(AUTO_ENABLED_AGENTS)
