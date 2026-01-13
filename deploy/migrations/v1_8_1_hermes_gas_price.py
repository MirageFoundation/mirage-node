"""
Migration: v1.8.1-hermes-gas-price - Fix Hermes gas price for v1.8.0 economics

Updates Hermes config.toml gas_price for mirage-1 chain from old value to 5000.
This fixes IBC relay failures after the v1.8.0 economics update.
"""

import re
from pathlib import Path

MIGRATION_KEY = "v1.8.1-hermes-gas-price"
DESCRIPTION = "Update Hermes gas_price for mirage-1 to 5000"


def run(config_dir: Path, logger) -> str:
    """Run the migration."""
    results = []
    data_dir = config_dir.parent  # ~/.mirage

    # Update Hermes config.toml: gas_price for mirage-1 chain
    hermes_config = data_dir / "hermes" / "config.toml"
    if hermes_config.exists():
        content = hermes_config.read_text()
        old_content = content

        # Find the mirage-1 chain section and update gas_price
        # The config has [[chains]] sections, we need to update the one with id = 'mirage-1'
        # Pattern matches: gas_price = { price = <number>, denom = 'umirage' }
        # We need to be careful to only update the mirage-1 section

        lines = content.split("\n")
        new_lines = []
        in_mirage_chain = False

        for line in lines:
            # Detect start of mirage-1 chain section
            if line.strip() == "id = 'mirage-1'":
                in_mirage_chain = True
            # Detect start of a different chain section (reset flag)
            elif line.strip().startswith("id = '") and "mirage-1" not in line:
                in_mirage_chain = False
            # Detect new [[chains]] block (could be mirage or other)
            elif line.strip() == "[[chains]]":
                in_mirage_chain = False

            # Update gas_price if we're in the mirage-1 section
            if in_mirage_chain and "gas_price" in line and "umirage" in line:
                # Match gas_price = { price = <any_number>, denom = 'umirage' }
                old_line = line
                line = re.sub(r"gas_price\s*=\s*\{\s*price\s*=\s*[\d.]+", "gas_price = { price = 5000", line)
                if line != old_line:
                    logger.info("    Updated Hermes gas_price for mirage-1 to 5000")

            new_lines.append(line)

        new_content = "\n".join(new_lines)
        if new_content != old_content:
            hermes_config.write_text(new_content)
            results.append("updated Hermes gas_price for mirage-1 to 5000")
        else:
            logger.info("    Hermes gas_price already set to 5000 for mirage-1")
    else:
        logger.info("    No Hermes config found (not a relayer node)")

    if results:
        return "; ".join(results)
    return "no changes needed"
