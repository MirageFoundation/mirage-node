"""
Write `STATS_FLEET_ROSTER` so the admin stats fan-out has a destination list.

The fan-out used to derive its destinations from validator monikers and live P2P
peer monikers, all of which are self-declared text from unauthenticated sources.
Peering with a node and setting your moniker to a domain you own put your host on
that list, and the aggregate route then POSTed the admin's live signature proof
to it — a proof that is deliberately replayable across fleet nodes, so one
harvested copy worked against siblings that had never seen the nonce.

The backend now reads the roster from configuration instead and refuses to start
without the key, so every existing node needs the value written down before it
restarts on the new build.

Empty is the correct value for a node that should aggregate only itself, and it
is what this migration writes: an operator listing sibling nodes here is an
explicit decision to send them admin proofs, and it is not one a migration should
make on their behalf. A blank roster degrades the dashboard to local-only stats,
never to a leaked credential.

Idempotent, and never overwrites a value an operator already chose.
"""

from __future__ import annotations

from pathlib import Path

from deploy.migrations._helpers import append_env_value, backup_file, parse_env_file

MIGRATION_KEY = "v1.36.0-stats-fleet-roster"
DESCRIPTION = "Write STATS_FLEET_ROSTER so admin stats fan-out uses a configured roster, not P2P monikers"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    backend_env = config_dir / "backend.env"

    if not backend_env.exists():
        raise FileNotFoundError(f"backend.env not found: {backend_env}")

    existing = parse_env_file(backend_env)
    if "STATS_FLEET_ROSTER" in existing:
        logger.info(f"  STATS_FLEET_ROSTER already set to {existing['STATS_FLEET_ROSTER']!r}")
        return "STATS_FLEET_ROSTER already explicit"

    backup_file(backend_env)
    if not append_env_value(
        backend_env,
        "STATS_FLEET_ROSTER",
        "",
        comment=(
            "Comma-separated https base URLs of fleet nodes this node may forward an admin "
            "stats proof to. Empty = aggregate only this node. http:// is rejected."
        ),
    ):
        raise RuntimeError("failed to append STATS_FLEET_ROSTER to backend.env")

    logger.info("  Appended STATS_FLEET_ROSTER= (empty: aggregate only this node)")
    return "wrote STATS_FLEET_ROSTER="
