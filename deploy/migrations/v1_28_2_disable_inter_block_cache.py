"""Force inter-block-cache=false in node app.toml across the fleet.

Context: even after the v1.28.0 upgrade (SDK v0.54 store/v2, #24655 atomic
lastCommitInfo + state-manager serialization), a single node diverged again at
h5522659 on a MsgVote with a supply-invariant violation (recorded supply != sum
of balances). That is a money-conservation break the upstream Commit<->Query
race fix does not cover. The inter-block cache is a shared, mutable-across-blocks
CommitKVStore cache layer and is the most likely remaining surface for a
non-deterministic read during tx execution, so we disable it (the Plan-A
mitigation that was previously skipped). Config-only, read by
server.DefaultBaseappOptions; no binary change, rolling restart applies it.

app.toml is only seeded on --init and is NOT re-rendered from the template on
--update (the env sync only touches *.env files). So flipping the template
default does not reach already-deployed validators. This one-time migration
patches the live app.toml on disk. The next miraged restart picks it up.
"""

import re
from pathlib import Path

from deploy.migrations._helpers import backup_file

MIGRATION_KEY = "v1.28.2-disable-inter-block-cache"
DESCRIPTION = "Force inter-block-cache=false in node app.toml (divergence mitigation)"

TARGET_LINE = "inter-block-cache = false"
NOTE = (
    "# inter-block-cache DISABLED: shared mutable cross-block cache is the most "
    "likely remaining non-deterministic read surface after the v1.28.0 store/v2 "
    "fixes (see h5522659 MsgVote supply-invariant divergence)."
)


def run(config_dir, logger):
    config_dir = Path(config_dir)
    app_toml = config_dir.parent / "node" / "config" / "app.toml"

    if not app_toml.exists():
        # Fresh hosts render app.toml from the template, which already has
        # inter-block-cache = false; nothing to patch.
        logger.info("  app.toml not present; template default applies")
        return "no app.toml (fresh host)"

    backup_file(app_toml)
    content = app_toml.read_text(encoding="utf-8")

    key_pattern = re.compile(r"(?m)^\s*inter-block-cache\s*=\s*(true|false)\s*$")
    match = key_pattern.search(content)

    if match:
        current = match.group(1)
        if current == "false":
            logger.info("  inter-block-cache already false")
            return "already false"
        updated = key_pattern.sub(TARGET_LINE, content, count=1)
        app_toml.write_text(updated, encoding="utf-8")
        logger.info("  Updated inter-block-cache: true -> false")
        return "updated true -> false"

    # Key absent (SDK default is enabled). Insert it, preferring to sit next to
    # the other consensus-read-determinism knob.
    block = f"{NOTE}\n{TARGET_LINE}"
    for anchor in (r"(?m)^(iavl-disable-fastnode\s*=.*)$", r"(?m)^(app-db-backend\s*=.*)$"):
        anchor_pattern = re.compile(anchor)
        if anchor_pattern.search(content):
            updated = anchor_pattern.sub(rf"\1\n\n{block}", content, count=1)
            app_toml.write_text(updated, encoding="utf-8")
            logger.info("  Added inter-block-cache=false near consensus-read knobs")
            return "added key"

    updated = content.rstrip() + f"\n\n{block}\n"
    app_toml.write_text(updated, encoding="utf-8")
    logger.info("  Appended inter-block-cache=false at end of app.toml")
    return "appended key"
