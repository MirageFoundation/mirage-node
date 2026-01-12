"""
Migration: v1.8.0-economics - Major economics rebalancing for 10,000x token multiplier

This migration updates app.toml on existing deployments:
- minimum-gas-prices: "0.025umirage" → "5000umirage"

Chain-side changes (via upgrade handler):
- RelayMinGasPrice: 25 → 5000 (now umirage per gas, was per 1000 gas)
- RelayMaxGasFee: 5000 → 500,000,000 (500 MIRAGE cap)
- SubscriptionReservePercent: 40 → 80 (80% to reserve, 20% burned)
- MintQuantity: 100,000 → 350,000,000 (350 MIRAGE per 10min)
- Tier period fees: 10/20/30 MIRAGE → 100K/200K/300K MIRAGE
- Gov min_deposit: 10 MIRAGE → 500K MIRAGE ($5)
- Gov expedited_min_deposit: 10 MIRAGE → 1M MIRAGE ($10)

NOTE: This migration runs during container startup *before* miraged is started.
The binary will fail to start if minimum-gas-prices is not exactly "5000umirage".
"""

import re
from pathlib import Path

MIGRATION_KEY = "v1.8.0-economics"
DESCRIPTION = "Economics rebalancing for 10,000x token multiplier"


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    results = []
    data_dir = config_dir.parent  # ~/.mirage

    # Support both old (main) and new (node) directory names
    node_dir = data_dir / "node"
    main_dir = node_dir if node_dir.exists() else data_dir / "main"

    # Update app.toml: minimum-gas-prices = "5000umirage"
    app_toml = main_dir / "config" / "app.toml"
    if app_toml.exists():
        content = app_toml.read_text()
        old_content = content

        # Replace minimum-gas-prices value
        # Match: minimum-gas-prices = "..." (any value)
        pattern = r'minimum-gas-prices\s*=\s*"[^"]*"'
        new_value = 'minimum-gas-prices = "5000umirage"'

        if re.search(pattern, content):
            content = re.sub(pattern, new_value, content)
            if content != old_content:
                app_toml.write_text(content)
                logger.info("    Updated minimum-gas-prices to 5000umirage in app.toml")
                results.append("updated minimum-gas-prices to 5000umirage")
            else:
                logger.info("    minimum-gas-prices already set to 5000umirage")
        else:
            logger.warning("    minimum-gas-prices not found in app.toml")
            results.append("minimum-gas-prices not found in app.toml")

    if results:
        return "; ".join(results)
    return "no changes needed"
