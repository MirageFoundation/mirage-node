"""
Migration: v1.9.7 - Ensure tx_index is enabled in node config.

Ensures:
- config.toml has [tx_index] section with indexer = "kv"
"""

from pathlib import Path
import re

MIGRATION_KEY = "v1_9_7_tx_index"
DESCRIPTION = "Enable tx_index in node config.toml"


def run(config_dir, logger):
    config_dir = Path(config_dir)
    data_dir = config_dir.parent
    node_config_dir = data_dir / "node" / "config"

    config_toml = node_config_dir / "config.toml"
    if not config_toml.exists():
        raise RuntimeError(f"Missing config.toml at {config_toml}")

    logger.info("  Updating node config for tx_index...")
    content = config_toml.read_text()

    # Check if [tx_index] section exists
    tx_index_section = re.search(r'^\[tx_index\]', content, re.MULTILINE)

    if tx_index_section:
        # Section exists - check if indexer is set to kv
        # Find the section and check/update indexer value
        section_start = tx_index_section.start()
        # Find the next section or end of file
        next_section = re.search(r'^\[', content[section_start + 1:], re.MULTILINE)
        section_end = section_start + 1 + next_section.start() if next_section else len(content)
        section_content = content[section_start:section_end]

        indexer_match = re.search(r'^indexer\s*=\s*"([^"]*)"', section_content, re.MULTILINE)
        if indexer_match:
            if indexer_match.group(1) == "kv":
                return "no changes"
            # Update indexer to kv
            new_section = re.sub(
                r'^indexer\s*=\s*"[^"]*"',
                'indexer = "kv"',
                section_content,
                flags=re.MULTILINE
            )
            content = content[:section_start] + new_section + content[section_end:]
            logger.info("    Updated indexer to 'kv' in [tx_index] section")
        else:
            # Add indexer = "kv" after [tx_index]
            new_section = section_content.rstrip() + '\nindexer = "kv"\n\n'
            content = content[:section_start] + new_section + content[section_end:]
            logger.info("    Added indexer = 'kv' to [tx_index] section")
    else:
        # Remove any stale top-level tx_index = "on" if present
        content = re.sub(r'^tx_index\s*=\s*"[^"]*"\n?', '', content, flags=re.MULTILINE)

        # Add [tx_index] section before the first existing section
        first_section = re.search(r'^\[', content, re.MULTILINE)
        if first_section:
            insert_pos = first_section.start()
            content = content[:insert_pos] + '[tx_index]\nindexer = "kv"\n\n' + content[insert_pos:]
        else:
            # No sections exist, add at end
            content = content.rstrip() + '\n\n[tx_index]\nindexer = "kv"\n'
        logger.info("    Added [tx_index] section with indexer = 'kv'")

    config_toml.write_text(content)
    return "updated"
