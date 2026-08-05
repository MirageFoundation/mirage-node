"""
One-time migration: tear down the bridge orchestrator on existing nodes.

- Kill the orchestrator tmux window if present
- Remove ~/.mirage/orchestrator/ (Solana keypair + config)
- Remove ~/.orchestrator/ (legacy validator registry)
- Delete orchestrator.env if present

Missing files/windows are idempotent. A discovered process or tmux window must
be stopped successfully before its configuration and key material are removed.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

MIGRATION_KEY = "v1.31.0-remove-orchestrator"
DESCRIPTION = "Stop orchestrator tmux window and remove orchestrator files"


def run(config_dir, logger):
    actions = []
    config_dir = Path(config_dir)
    mirage_home = config_dir.parent  # ~/.mirage

    # Kill orchestrator tmux window if present.
    try:
        list_result = subprocess.run(
            ["tmux", "list-windows", "-t", "mirage", "-F", "#{window_name}"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if list_result.returncode != 0:
            stderr = (list_result.stderr or "").strip()
            if "can't find session" in stderr or "no server running" in stderr:
                windows = []
            else:
                raise RuntimeError(f"tmux list-windows failed: {stderr}")
        else:
            windows = (list_result.stdout or "").splitlines()
        if "orchestrator" in windows:
            kill_result = subprocess.run(
                ["tmux", "kill-window", "-t", "mirage:orchestrator"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if kill_result.returncode == 0:
                logger.info("  killed mirage:orchestrator tmux window")
                actions.append("killed-tmux")
            else:
                raise RuntimeError(f"tmux kill-window failed: {(kill_result.stderr or '').strip()}")
        else:
            logger.info("  no orchestrator tmux window")
    except FileNotFoundError:
        logger.info("  tmux not available; skipping window kill")

    # Stop any leftover process and verify termination before deleting keys.
    pattern = "blockchain/bin/[o]rchestrator"
    kill_result = subprocess.run(
        ["pkill", "-TERM", "-f", pattern],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if kill_result.returncode not in (0, 1):
        raise RuntimeError(f"pkill orchestrator failed: {(kill_result.stderr or '').strip()}")
    if kill_result.returncode == 0:
        for _ in range(20):
            running = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if running.returncode == 1:
                actions.append("stopped-process")
                logger.info("  stopped leftover orchestrator process")
                break
            if running.returncode != 0:
                raise RuntimeError(f"pgrep orchestrator failed: {(running.stderr or '').strip()}")
            time.sleep(0.5)
        else:
            raise RuntimeError("orchestrator process did not stop after SIGTERM")

    orchestrator_dir = mirage_home / "orchestrator"
    if orchestrator_dir.exists():
        shutil.rmtree(orchestrator_dir)
        logger.info(f"  removed {orchestrator_dir}")
        actions.append("removed-dir")
    else:
        logger.info(f"  {orchestrator_dir} already absent")

    registry_dir = mirage_home.parent / ".orchestrator"
    if registry_dir.exists():
        shutil.rmtree(registry_dir)
        logger.info(f"  removed {registry_dir}")
        actions.append("removed-registry")
    else:
        logger.info(f"  {registry_dir} already absent")

    orchestrator_env = config_dir / "orchestrator.env"
    if orchestrator_env.exists():
        orchestrator_env.unlink()
        logger.info(f"  deleted {orchestrator_env}")
        actions.append("deleted-env")
    else:
        logger.info(f"  {orchestrator_env.name} already absent")

    if not actions:
        return "already clean"
    return "; ".join(actions)
