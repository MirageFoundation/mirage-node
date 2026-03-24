#!/usr/bin/env python3
"""
Mirage Unified Status Dashboard

An ops-focused health check dashboard showing the highest-signal service
statuses in a card/tile layout.

Services monitored:
  - CometBFT (blockchain node)
  - Validator (if configured)
  - Backend API (includes PostgreSQL sub-check)
  - Indexer
  - Endpoints (Caddy + public chain RPC/REST/gRPC)
  - System (disk, ~/.mirage usage, memory, CPU)
  - Bridge Orchestrator (if configured)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
import argparse
import socket
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    import psycopg
except Exception:  # pragma: no cover - environment dependent
    psycopg = None
import requests

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).parent.parent))


class Status(Enum):
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    UNKNOWN = "unknown"


def _find_miraged() -> str:
    """Find the miraged binary path (handles both old and new directory structures)."""
    candidates = [
        "/opt/mirage/blockchain/miraged",  # new structure
        "/opt/mirage/blockchain/bin/miraged",  # old structure
        str(Path(__file__).resolve().parents[1] / "blockchain" / "miraged"),
        str(Path(__file__).resolve().parents[1] / "blockchain" / "bin" / "miraged"),
        "miraged",
    ]
    for c in candidates:
        if c == "miraged":
            return c
        if os.path.exists(c) and os.access(c, os.X_OK):
            return c
    return "miraged"


_MIRAGED_BIN: str | None = None


def get_miraged_bin() -> str:
    """Get cached miraged binary path."""
    global _MIRAGED_BIN
    if _MIRAGED_BIN is None:
        _MIRAGED_BIN = _find_miraged()
    return _MIRAGED_BIN


# ANSI color codes
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Bright foreground
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"

    # Background
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"


# Box drawing characters
class Box:
    # Heavy box
    H_TOP_LEFT = "┏"
    H_TOP_RIGHT = "┓"
    H_BOTTOM_LEFT = "┗"
    H_BOTTOM_RIGHT = "┛"
    H_HORIZONTAL = "━"
    H_VERTICAL = "┃"

    # Light box
    TOP_LEFT = "┌"
    TOP_RIGHT = "┐"
    BOTTOM_LEFT = "└"
    BOTTOM_RIGHT = "┘"
    HORIZONTAL = "─"
    VERTICAL = "│"

    # Double box
    D_TOP_LEFT = "╔"
    D_TOP_RIGHT = "╗"
    D_BOTTOM_LEFT = "╚"
    D_BOTTOM_RIGHT = "╝"
    D_HORIZONTAL = "═"
    D_VERTICAL = "║"

    # Rounded
    R_TOP_LEFT = "╭"
    R_TOP_RIGHT = "╮"
    R_BOTTOM_LEFT = "╰"
    R_BOTTOM_RIGHT = "╯"


# Status icons
ICONS = {
    Status.OK: f"{Colors.BRIGHT_GREEN}*{Colors.RESET}",
    Status.WARN: f"{Colors.BRIGHT_YELLOW}*{Colors.RESET}",
    Status.ERROR: f"{Colors.BRIGHT_RED}*{Colors.RESET}",
    Status.UNKNOWN: f"{Colors.BRIGHT_BLACK}○{Colors.RESET}",
}

STATUS_COLORS = {
    Status.OK: Colors.BRIGHT_GREEN,
    Status.WARN: Colors.BRIGHT_YELLOW,
    Status.ERROR: Colors.BRIGHT_RED,
    Status.UNKNOWN: Colors.BRIGHT_BLACK,
}


# Debug logging (opt-in: dashboard output must stay clean by default).
_DEBUG_LOG_ENABLED = os.environ.get("MIRAGE_CHECK_STATUS_DEBUG", "").strip() == "1"
_DEBUG_LOG_PATH = os.environ.get("MIRAGE_STATUS_DASHBOARD_LOG", "/tmp/mirage_status_dashboard.log").strip()

# Node staleness thresholds:
# If your chain should be producing blocks regularly, "last block: 1m ago" is bad.
NODE_LAST_BLOCK_WARN_SECS = int(os.environ.get("MIRAGE_NODE_LAST_BLOCK_WARN_SECS", "15"))
NODE_LAST_BLOCK_ERROR_SECS = int(os.environ.get("MIRAGE_NODE_LAST_BLOCK_ERROR_SECS", "60"))

MIRAGE_GRPC_ADDR = os.environ.get("MIRAGE_GRPC_ADDR", "127.0.0.1:9090").strip()


def debug_log(msg: str) -> None:
    if not _DEBUG_LOG_ENABLED:
        return
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        # Dashboard should never crash because logging failed.
        pass


def get_tmux_visibility_state() -> tuple[bool, bool]:
    """
    Check if running inside tmux and whether the session is actively visible.

    Returns:
        (is_in_tmux, is_visible)
        - is_in_tmux: True if running inside a tmux session
        - is_visible: True if the session has attached clients AND the current
                      window is the active window (user is looking at it)
    """
    # Check if we're inside tmux
    if not os.environ.get("TMUX"):
        return False, True  # Not in tmux, assume visible

    # Get our pane ID for explicit targeting
    pane_id = os.environ.get("TMUX_PANE", "")

    try:
        # Check if session has any attached clients
        result = subprocess.run(
            ["tmux", "list-clients", "-F", "#{client_name}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode != 0 or not result.stdout.strip():
            # No clients attached = detached
            debug_log("tmux: no clients attached (detached)")
            return True, False

        # Session has clients - check if current window is active
        # Get our window index and compare to the session's active window
        cmd = ["tmux", "display-message", "-p", "#{window_index} #{session_attached} #{client_session}"]
        if pane_id:
            cmd = [
                "tmux",
                "display-message",
                "-t",
                pane_id,
                "-p",
                "#{window_index} #{session_attached} #{client_session}",
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        our_window_index = result.stdout.strip().split()[0] if result.stdout.strip() else ""

        # List windows to find which one is active (has * flag)
        result = subprocess.run(
            ["tmux", "list-windows", "-F", "#{window_index} #{window_flags}"],
            capture_output=True,
            text=True,
            timeout=2,
        )

        active_window_index = None
        for line in result.stdout.strip().split("\n"):
            parts = line.split(None, 1)
            if len(parts) >= 2:
                idx, flags = parts[0], parts[1]
                if "*" in flags:
                    active_window_index = idx
                    break
            elif len(parts) == 1:
                # No flags means this might be the only window
                pass

        window_active = our_window_index == active_window_index

        debug_log(
            f"tmux: pane={pane_id} our_window={our_window_index} active_window={active_window_index} visible={window_active}"
        )

        if not window_active:
            return True, False

        # Window is active - user is looking at this
        return True, True

    except Exception as e:
        debug_log(f"tmux: visibility check failed: {e}")
        # On error, assume visible to avoid stale data
        return True, True


def format_age_secs(age_secs: float) -> str:
    if age_secs < 60:
        return f"{int(age_secs)}s ago"
    if age_secs < 3600:
        return f"{int(age_secs / 60)}m ago"
    return f"{int(age_secs / 3600)}h ago"


def tcp_connect_ms(host: str, port: int, timeout_secs: float = 1.5) -> Optional[int]:
    start = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout_secs):
            pass
        return int((time.time() - start) * 1000)
    except Exception as e:
        debug_log(f"tcp_connect_ms failed: host={host} port={port} err={e}")
        return None


def parse_host_port(addr: str) -> tuple[str, int]:
    parts = (addr or "").strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"bad addr: {addr!r} (expected host:port)")
    host = parts[0].strip() or "127.0.0.1"
    port = int(parts[1].strip())
    return host, port


def read_app_toml_value(path: str, key: str) -> Optional[str]:
    try:
        content = Path(path).read_text(encoding="utf-8")
    except Exception as e:
        debug_log(f"retention: failed to read app.toml: {e}")
        return None
    match = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", content, flags=re.MULTILINE)
    if not match:
        return None
    raw = match.group(1).strip()
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]
    return raw.strip()


def parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except Exception:
        return None


def min_non_zero(a: Optional[int], b: Optional[int]) -> Optional[int]:
    if not a or a <= 0:
        return b if b and b > 0 else None
    if not b or b <= 0:
        return a
    return a if a < b else b


def parse_env_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = str(value).strip().lower().strip('"').strip("'")
    if normalized in ("true", "1", "yes"):
        return True
    if normalized in ("false", "0", "no"):
        return False
    return None


def load_env_file(path: Path) -> dict:
    data = {}
    content = path.read_text(encoding="utf-8")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            data[key] = value
    return data


@dataclass
class ServiceStatus:
    name: str
    status: Status
    message: str
    details: dict


def get_terminal_size() -> tuple[int, int]:
    """Get terminal size (columns, rows)."""
    size = shutil.get_terminal_size((80, 24))
    return size.columns, size.lines


def truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def center_text(text: str, width: int) -> str:
    """Center text within a given width."""
    visible_len = len(text.encode("utf-8").decode("utf-8"))
    # Account for ANSI codes
    stripped = ""
    i = 0
    while i < len(text):
        if text[i] == "\033":
            j = text.find("m", i)
            if j != -1:
                i = j + 1
                continue
        stripped += text[i]
        i += 1
    visible_len = len(stripped)

    if visible_len >= width:
        return text
    padding = (width - visible_len) // 2
    return " " * padding + text + " " * (width - visible_len - padding)


def draw_card(title: str, status: Status, lines: list[str], width: int = 38, style: str = "light") -> list[str]:
    """Draw a card with a title and content lines."""
    # Select box style
    if style == "heavy":
        tl, tr, bl, br, h, v = (
            Box.H_TOP_LEFT,
            Box.H_TOP_RIGHT,
            Box.H_BOTTOM_LEFT,
            Box.H_BOTTOM_RIGHT,
            Box.H_HORIZONTAL,
            Box.H_VERTICAL,
        )
    elif style == "double":
        tl, tr, bl, br, h, v = (
            Box.D_TOP_LEFT,
            Box.D_TOP_RIGHT,
            Box.D_BOTTOM_LEFT,
            Box.D_BOTTOM_RIGHT,
            Box.D_HORIZONTAL,
            Box.D_VERTICAL,
        )
    elif style == "rounded":
        tl, tr, bl, br, h, v = (
            Box.R_TOP_LEFT,
            Box.R_TOP_RIGHT,
            Box.R_BOTTOM_LEFT,
            Box.R_BOTTOM_RIGHT,
            Box.HORIZONTAL,
            Box.VERTICAL,
        )
    else:  # light (default) - square corners
        tl, tr, bl, br, h, v = (
            Box.TOP_LEFT,
            Box.TOP_RIGHT,
            Box.BOTTOM_LEFT,
            Box.BOTTOM_RIGHT,
            Box.HORIZONTAL,
            Box.VERTICAL,
        )

    color = STATUS_COLORS[status]
    icon = ICONS[status]

    result = []
    inner_width = width - 2

    # Top border
    result.append(f"{color}{tl}{h * inner_width}{tr}{Colors.RESET}")

    # Title line with icon
    title_text = f" {icon} {Colors.BOLD}{title}{Colors.RESET}"
    # Calculate visible length (excluding ANSI codes)
    # Format is: " {icon} {title}" where icon is 1 visible char (e.g., "*")
    title_visible_len = 1 + 1 + 1 + len(title)  # space + icon + space + title
    padding = inner_width - title_visible_len
    result.append(f"{color}{v}{Colors.RESET}{title_text}{' ' * padding}{color}{v}{Colors.RESET}")

    # Separator
    result.append(f"{color}{v}{Colors.DIM}{Box.HORIZONTAL * inner_width}{Colors.RESET}{color}{v}{Colors.RESET}")

    # Content lines
    max_content_len = inner_width - 2  # Leave space for padding
    for line in lines:
        # Strip ANSI for length calculation
        stripped = ""
        i = 0
        while i < len(line):
            if line[i] == "\033":
                j = line.find("m", i)
                if j != -1:
                    i = j + 1
                    continue
            stripped += line[i]
            i += 1

        visible_len = len(stripped)

        # Truncate if too long
        if visible_len > max_content_len:
            # Truncate the stripped version to find cutoff point
            cutoff = 0
            vis_count = 0
            j = 0
            while j < len(line) and vis_count < max_content_len - 2:
                if line[j] == "\033":
                    k = line.find("m", j)
                    if k != -1:
                        cutoff = k + 1
                        j = k + 1
                        continue
                vis_count += 1
                cutoff = j + 1
                j += 1
            line = line[:cutoff] + ".."
            visible_len = vis_count + 2

        line_padding = inner_width - visible_len - 1
        if line_padding < 0:
            line_padding = 0
        result.append(f"{color}{v}{Colors.RESET} {line}{' ' * line_padding}{color}{v}{Colors.RESET}")

    # Bottom border
    result.append(f"{color}{bl}{h * inner_width}{br}{Colors.RESET}")

    return result


def merge_cards_horizontal(cards: list[list[str]], gap: int = 2) -> list[str]:
    """Merge multiple cards horizontally."""
    if not cards:
        return []

    # Find max height
    max_height = max(len(card) for card in cards)

    # Pad shorter cards
    padded = []
    for card in cards:
        if card:
            width = len(card[0]) if card else 0
            # Calculate visible width
            stripped = ""
            i = 0
            line = card[0] if card else ""
            while i < len(line):
                if line[i] == "\033":
                    j = line.find("m", i)
                    if j != -1:
                        i = j + 1
                        continue
                stripped += line[i]
                i += 1
            width = len(stripped)

            while len(card) < max_height:
                card.append(" " * width)
            padded.append(card)

    # Merge lines
    result = []
    gap_str = " " * gap
    for i in range(max_height):
        line_parts = [card[i] for card in padded if i < len(card)]
        result.append(gap_str.join(line_parts))

    return result


# ============================================================================
# Service Checkers
# ============================================================================


def check_node() -> ServiceStatus:
    """Check blockchain node status via RPC."""
    try:
        resp = requests.get("http://127.0.0.1:26657/status", timeout=3)
        data = resp.json()
        result = data.get("result", {})
        sync_info = result.get("sync_info", {})
        node_info = result.get("node_info", {})

        height = sync_info.get("latest_block_height", "?")
        catching_up = sync_info.get("catching_up", True)
        chain_id = node_info.get("network", "?")

        # RPC health probe (CometBFT /health should return 200 when healthy)
        rpc_health_ok = None
        rpc_health_ms = None
        try:
            start = time.time()
            health_resp = requests.get("http://127.0.0.1:26657/health", timeout=2)
            rpc_health_ms = int((time.time() - start) * 1000)
            rpc_health_ok = health_resp.status_code == 200
        except Exception as e:
            debug_log(f"node: rpc /health failed: {e}")
            rpc_health_ok = False

        # Calculate block age
        block_age = None
        block_age_secs = None
        try:
            block_time = sync_info.get("latest_block_time", "")
            if block_time:
                # Parse ISO format timestamp
                bt = datetime.fromisoformat(block_time.replace("Z", "+00:00"))
                if bt.tzinfo is None:
                    bt = bt.replace(tzinfo=timezone.utc)
                block_age_secs = (datetime.now(timezone.utc) - bt).total_seconds()
                block_age = format_age_secs(block_age_secs)
        except Exception as e:
            debug_log(f"node: failed to parse latest_block_time={block_time!r}: {e}")
            pass

        # Get peer count
        peers = 0
        try:
            net_resp = requests.get("http://127.0.0.1:26657/net_info", timeout=2)
            peers = len(net_resp.json().get("result", {}).get("peers", []))
        except Exception as e:
            debug_log(f"node: net_info failed: {e}")
            pass

        # Get total validator count
        validators_total = None
        try:
            val_resp = requests.get("http://127.0.0.1:26657/validators?per_page=1", timeout=2)
            validators_total = int(val_resp.json().get("result", {}).get("total", 0))
        except Exception as e:
            debug_log(f"node: validators count failed: {e}")
            pass

        details = {
            "height": height,
            "syncing": catching_up,
            "peers": peers,
            "validators_total": validators_total,
            "chain_id": chain_id,
            "block_age": block_age,
            "block_age_secs": block_age_secs,
            "rpc_health_ok": rpc_health_ok,
            "rpc_health_ms": rpc_health_ms,
        }

        status = Status.OK
        message = "Running"

        if catching_up:
            status = Status.WARN
            message = "Syncing"

        # Even if CometBFT reports catching_up=false, a stale last block is still unhealthy
        # — unless the chain is halted for a software upgrade, which is expected.
        if block_age_secs is not None:
            if block_age_secs >= NODE_LAST_BLOCK_ERROR_SECS:
                # Before marking ERROR, check if the chain is halted for an upgrade.
                # During a coordinated upgrade, all validators stop at the upgrade
                # height and no new blocks are produced until 2/3+ restart with the
                # new binary.  This is a normal, healthy state.
                upgrade_halt = False
                try:
                    plan_resp = requests.get(
                        "http://127.0.0.1:1317/cosmos/upgrade/v1beta1/current_plan",
                        timeout=2,
                    )
                    if plan_resp.status_code == 200:
                        plan = plan_resp.json().get("plan")
                        if plan and plan.get("name"):
                            plan_height = int(plan.get("height", 0))
                            current_height = int(height) if str(height).isdigit() else 0
                            # Upgrade halt: plan height matches current height
                            # (or we're within 1 block of it)
                            if plan_height > 0 and abs(current_height - plan_height) <= 1:
                                upgrade_halt = True
                                details["upgrade_plan"] = plan.get("name")
                                details["upgrade_height"] = plan_height
                except Exception as e:
                    debug_log(f"node: upgrade plan query failed: {e}")

                if upgrade_halt:
                    status = Status.WARN
                    message = f"Upgrade halt ({details['upgrade_plan']})"
                else:
                    status = Status.ERROR
                    message = "No new blocks"
            elif block_age_secs >= NODE_LAST_BLOCK_WARN_SECS and status != Status.ERROR:
                status = Status.WARN
                message = "Slow blocks"

        if peers == 0 and status == Status.OK:
            status = Status.ERROR
            message = "No peers"

        if rpc_health_ok is False and status == Status.OK:
            status = Status.WARN
            message = "RPC unhealthy"

        debug_log(
            "node: "
            f"height={height} catching_up={catching_up} peers={peers} "
            f"block_age_secs={block_age_secs} rpc_health_ok={rpc_health_ok} rpc_health_ms={rpc_health_ms} "
            f"status={status.value} message={message}"
        )

        return ServiceStatus(name="CometBFT", status=status, message=message, details=details)
    except requests.exceptions.ConnectionError:
        return ServiceStatus(name="CometBFT", status=Status.ERROR, message="Not reachable", details={})
    except Exception as e:
        return ServiceStatus(name="CometBFT", status=Status.ERROR, message=str(e)[:30], details={})


def check_retention() -> ServiceStatus:
    """Check block retention against config + chain constraints."""
    node_home = os.path.expanduser("~/.mirage/node")
    app_toml = os.path.join(node_home, "config", "app.toml")
    details: dict = {}

    try:
        status_resp = requests.get("http://127.0.0.1:26657/status", timeout=3).json()
        sync_info = status_resp.get("result", {}).get("sync_info", {})
        latest = parse_int(sync_info.get("latest_block_height"))
        earliest = parse_int(sync_info.get("earliest_block_height"))
        catching_up = sync_info.get("catching_up", True)
        retained = None
        if latest is not None and earliest is not None:
            retained = max(0, latest - earliest + 1)
    except Exception as e:
        debug_log(f"retention: status RPC failed: {e}")
        return ServiceStatus(name="Retention", status=Status.ERROR, message="RPC unavailable", details={})

    try:
        consensus_resp = requests.get("http://127.0.0.1:26657/consensus_params", timeout=3).json()
        evidence = (
            consensus_resp.get("result", {}).get("consensus_params", {}).get("evidence", {}).get("max_age_num_blocks")
        )
        evidence_max_age_blocks = parse_int(evidence)
    except Exception as e:
        debug_log(f"retention: consensus_params RPC failed: {e}")
        evidence_max_age_blocks = None

    pruning_strategy = read_app_toml_value(app_toml, "pruning")
    pruning_keep_recent = parse_int(read_app_toml_value(app_toml, "pruning-keep-recent"))
    pruning_interval = parse_int(read_app_toml_value(app_toml, "pruning-interval"))
    min_retain_blocks = parse_int(read_app_toml_value(app_toml, "min-retain-blocks"))
    snapshot_interval = parse_int(read_app_toml_value(app_toml, "snapshot-interval"))
    snapshot_keep_recent = parse_int(read_app_toml_value(app_toml, "snapshot-keep-recent"))

    snapshot_retention = None
    if snapshot_interval is not None and snapshot_keep_recent is not None:
        snapshot_retention = snapshot_interval * snapshot_keep_recent

    effective = None
    for candidate in (min_retain_blocks, evidence_max_age_blocks, snapshot_retention):
        effective = min_non_zero(effective, candidate)

    # Count actual snapshots on disk
    snapshot_count = 0
    snapshot_total_size = 0
    snapshot_heights: list[int] = []
    snapshots_dir = os.path.join(node_home, "data", "snapshots")
    try:
        if os.path.isdir(snapshots_dir):
            with os.scandir(snapshots_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            h = int(entry.name)
                            snapshot_heights.append(h)
                            sz = _get_directory_size(entry.path)
                            if sz is not None:
                                snapshot_total_size += sz
                        except ValueError:
                            pass
            snapshot_count = len(snapshot_heights)
            snapshot_heights.sort(reverse=True)
    except (PermissionError, OSError) as e:
        debug_log(f"retention: snapshot scan failed: {e}")

    details.update(
        {
            "retained_blocks": retained,
            "expected_blocks": effective,
            "min_retain_blocks": min_retain_blocks,
            "evidence_max_age_blocks": evidence_max_age_blocks,
            "snapshot_retention_blocks": snapshot_retention,
            "snapshot_interval": snapshot_interval,
            "snapshot_keep_recent": snapshot_keep_recent,
            "snapshot_count": snapshot_count,
            "snapshot_total_size": snapshot_total_size,
            "snapshot_heights": snapshot_heights[:5],
            "pruning_strategy": pruning_strategy,
            "pruning_keep_recent": pruning_keep_recent,
            "pruning_interval": pruning_interval,
            "catching_up": catching_up,
        }
    )

    mismatch = False
    if min_retain_blocks and evidence_max_age_blocks and evidence_max_age_blocks < min_retain_blocks:
        mismatch = True
    if min_retain_blocks and snapshot_retention and snapshot_retention < min_retain_blocks:
        mismatch = True

    if effective is None or retained is None:
        return ServiceStatus(name="Retention", status=Status.WARN, message="Config missing", details=details)

    tolerance = 100
    status = Status.OK
    message = "Within range"

    if retained < max(0, effective - tolerance):
        status = Status.WARN
        message = "Below expected" if not catching_up else "Syncing"
    elif retained > effective + tolerance:
        status = Status.WARN
        message = "Above expected"

    if mismatch and status == Status.OK:
        status = Status.WARN
        message = "Config mismatch"

    return ServiceStatus(name="Retention", status=status, message=message, details=details)


def _get_jail_info(node_home: str, cons_pubkey_base64: str) -> dict:
    """
    Get jail timing info from slashing module.

    Returns dict with:
        - jailed_since: datetime when jailed (if calculable)
        - jailed_since_secs: seconds since jailing
        - jailed_until: datetime when can unjail
        - tombstoned: bool if validator is tombstoned (permanent jail)
    """
    result = {}

    try:
        # Query all signing infos - we'll match by finding the one that's jailed
        # (There's typically only one validator per node anyway)
        signing_result = subprocess.run(
            [get_miraged_bin(), "query", "slashing", "signing-infos", "--home", node_home, "-o", "json"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if signing_result.returncode != 0:
            debug_log(f"validator: slashing signing-infos query failed: {signing_result.stderr}")
            return result

        signing_data = json.loads(signing_result.stdout)
        infos = signing_data.get("info", [])

        for info in infos:
            # The address field is in bech32 format, but we can match by checking
            # if this is likely our validator (there's usually only one local validator)
            val_info = info.get("validator_signing_info", info)  # Handle both formats

            jailed_until_str = val_info.get("jailed_until", "")

            # Skip if not jailed (jailed_until is zero time)
            if not jailed_until_str or jailed_until_str.startswith("0001-01-01"):
                continue

            # Parse jailed_until
            try:
                # Handle various timestamp formats
                jailed_until_str = jailed_until_str.replace("Z", "+00:00")
                # Remove nanoseconds if present (keep only microseconds)
                if "." in jailed_until_str:
                    parts = jailed_until_str.split(".")
                    frac_and_tz = parts[1]
                    # Find where the fractional seconds end
                    frac_end = 0
                    for i, c in enumerate(frac_and_tz):
                        if not c.isdigit():
                            frac_end = i
                            break
                    else:
                        frac_end = len(frac_and_tz)
                    # Keep only 6 digits for microseconds
                    frac = frac_and_tz[:frac_end][:6].ljust(6, "0")
                    tz = frac_and_tz[frac_end:]
                    jailed_until_str = f"{parts[0]}.{frac}{tz}"

                jailed_until = datetime.fromisoformat(jailed_until_str)
                if jailed_until.tzinfo is None:
                    jailed_until = jailed_until.replace(tzinfo=timezone.utc)

                result["jailed_until"] = jailed_until

                # Check for tombstone (far future date, like year 9999)
                if jailed_until.year > 9000:
                    result["tombstoned"] = True
                    debug_log(f"validator: detected tombstone, jailed_until={jailed_until}")
                    return result

                result["tombstoned"] = False

                # Query slashing params to get downtime_jail_duration
                params_result = subprocess.run(
                    [get_miraged_bin(), "query", "slashing", "params", "--home", node_home, "-o", "json"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if params_result.returncode == 0:
                    params_data = json.loads(params_result.stdout)
                    params = params_data.get("params", params_data)
                    jail_duration_str = params.get("downtime_jail_duration", "")

                    # Parse duration (format: "600s" or "600000000000" nanoseconds)
                    jail_duration_secs = 0
                    if jail_duration_str.endswith("s"):
                        jail_duration_secs = float(jail_duration_str[:-1])
                    elif jail_duration_str.isdigit():
                        # Nanoseconds
                        jail_duration_secs = int(jail_duration_str) / 1_000_000_000

                    if jail_duration_secs > 0:
                        jailed_since = jailed_until - timedelta(seconds=jail_duration_secs)
                        result["jailed_since"] = jailed_since
                        result["jailed_since_secs"] = (datetime.now(timezone.utc) - jailed_since).total_seconds()
                        debug_log(f"validator: jailed_since={jailed_since} ({result['jailed_since_secs']:.0f}s ago)")

                break  # Found our validator's info

            except Exception as e:
                debug_log(f"validator: failed to parse jailed_until={jailed_until_str!r}: {e}")
                continue

    except Exception as e:
        debug_log(f"validator: _get_jail_info failed: {e}")

    return result


def check_validator() -> ServiceStatus:
    """Check validator status."""
    node_home = os.path.expanduser("~/.mirage/node")
    priv_val_key = os.path.join(node_home, "config", "priv_validator_key.json")

    if not os.path.exists(priv_val_key):
        return ServiceStatus(
            name="Validator", status=Status.UNKNOWN, message="Not configured", details={"configured": False}
        )

    try:
        # Read local consensus key
        with open(priv_val_key) as f:
            key_data = json.load(f)
        local_addr = key_data.get("address", "")
        local_pubkey = key_data.get("pub_key", {}).get("value", "")

        # Check if node is syncing
        resp = requests.get("http://127.0.0.1:26657/status", timeout=3)
        status_data = resp.json().get("result", {})
        catching_up = status_data.get("sync_info", {}).get("catching_up", True)

        if catching_up:
            return ServiceStatus(
                name="Validator",
                status=Status.WARN,
                message="Node syncing",
                details={"configured": True, "syncing": True},
            )

        # Check validator set
        resp = requests.get("http://127.0.0.1:26657/validators?per_page=1000", timeout=3)
        validators = resp.json().get("result", {}).get("validators", [])

        # Find our validator
        in_set = False
        voting_power = 0
        for v in validators:
            if v.get("address") == local_addr:
                in_set = True
                voting_power = int(v.get("voting_power", 0))
                break

        # Get on-chain validator info by matching consensus pubkey
        moniker = None
        jailed = False
        tokens = None
        total_tokens = 0
        power_pct = None
        try:
            result = subprocess.run(
                [get_miraged_bin(), "query", "staking", "validators", "--home", node_home, "-o", "json"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                val_data = json.loads(result.stdout)
                # Calculate total bonded tokens across all validators
                for v in val_data.get("validators", []):
                    try:
                        total_tokens += int(v.get("tokens", "0"))
                    except Exception:
                        pass
                # Find our validator
                for v in val_data.get("validators", []):
                    if v.get("consensus_pubkey", {}).get("value") == local_pubkey:
                        moniker = v.get("description", {}).get("moniker")
                        jailed = v.get("jailed", False)
                        # Tokens (convert from smallest unit)
                        tok = v.get("tokens", "0")
                        try:
                            tokens = int(tok) // 1_000_000  # Convert from umirage
                            if total_tokens > 0:
                                power_pct = (int(tok) / total_tokens) * 100
                        except Exception:
                            pass
                        break
            else:
                debug_log(
                    "validator: miraged staking validators failed: "
                    f"rc={result.returncode} stderr={truncate((result.stderr or '').strip(), 120)!r}"
                )
        except Exception:
            pass

        # Payer balance — if this hits 0 every tx fails
        payer_addr = _get_validator_payer_address()
        balance_mirage = None
        if payer_addr:
            raw_balance = _query_balance_rest(payer_addr)
            if raw_balance is not None:
                balance_mirage = raw_balance / 1_000_000

        base_details = {
            "configured": True,
            "moniker": moniker,
            "tokens": tokens,
            "power_pct": power_pct,
            "voting_power": voting_power,
            "balance_mirage": balance_mirage,
        }

        if jailed:
            # Get jail timing info
            jail_info = _get_jail_info(node_home, local_pubkey)
            jail_details = {**base_details, "active": False, "jailed": True}

            if jail_info.get("tombstoned"):
                jail_details["tombstoned"] = True
                return ServiceStatus(
                    name="Validator",
                    status=Status.ERROR,
                    message="TOMBSTONED",
                    details=jail_details,
                )

            if jail_info.get("jailed_since_secs") is not None:
                jail_details["jailed_since_secs"] = jail_info["jailed_since_secs"]
            if jail_info.get("jailed_until"):
                jail_details["jailed_until"] = jail_info["jailed_until"].isoformat()

            return ServiceStatus(
                name="Validator",
                status=Status.ERROR,
                message="JAILED",
                details=jail_details,
            )

        if in_set:
            active_details = {**base_details, "active": True, "voting_power": voting_power}
            if balance_mirage is not None and balance_mirage < SERVER_BALANCE_ERROR:
                return ServiceStatus(
                    name="Validator", status=Status.ERROR, message="Balance critical", details=active_details
                )
            if balance_mirage is not None and balance_mirage < SERVER_BALANCE_WARN:
                return ServiceStatus(
                    name="Validator", status=Status.WARN, message="Balance low", details=active_details
                )
            return ServiceStatus(
                name="Validator", status=Status.OK, message="Active", details=active_details
            )
        else:
            return ServiceStatus(
                name="Validator",
                status=Status.ERROR,
                message="Not in active set",
                details={**base_details, "active": False},
            )

    except Exception as e:
        return ServiceStatus(name="Validator", status=Status.ERROR, message=str(e)[:30], details={"configured": True})


def check_postgres() -> ServiceStatus:
    """Check PostgreSQL database status."""
    db_url = os.environ.get("INDEXER_DB_URL", "postgresql://mirage:mirage@127.0.0.1:5432/mirage")

    if psycopg is None:
        return ServiceStatus(
            name="PostgreSQL",
            status=Status.ERROR,
            message="psycopg missing",
            details={"connected": False},
        )

    try:
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                # Get table count
                cur.execute("SELECT COUNT(*) FROM information_schema.tables " "WHERE table_schema = 'public'")
                tables = cur.fetchone()[0]

                # Get database size
                cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
                size = cur.fetchone()[0]

                # Get active connections
                cur.execute("SELECT COUNT(*) FROM pg_stat_activity " "WHERE datname = current_database()")
                connections = cur.fetchone()[0]

                # Get version (short)
                cur.execute("SHOW server_version")
                version = cur.fetchone()[0].split()[0]  # e.g., "15.4"

        return ServiceStatus(
            name="PostgreSQL",
            status=Status.OK,
            message="Connected",
            details={
                "connected": True,
                "tables": tables,
                "size": size,
                "connections": connections,
                "version": version,
            },
        )
    except Exception as e:
        err_msg = str(e)
        if "connection refused" in err_msg.lower():
            return ServiceStatus(
                name="PostgreSQL", status=Status.ERROR, message="Not running", details={"connected": False}
            )
        return ServiceStatus(
            name="PostgreSQL", status=Status.ERROR, message=truncate(str(e), 25), details={"connected": False}
        )


def check_backend() -> ServiceStatus:
    """Check backend API status (includes PostgreSQL sub-check)."""
    try:
        workers = 0
        try:
            result = subprocess.run(["pgrep", "-c", "-f", "gunicorn.*factory:app"], capture_output=True, text=True)
            if result.returncode == 0:
                workers = int(result.stdout.strip())
        except Exception:
            pass

        start = time.time()
        resp = requests.get("http://127.0.0.1:5000/api/get_parameters", timeout=3)
        response_ms = int((time.time() - start) * 1000)

        if resp.status_code >= 400:
            backend = ServiceStatus(
                name="Backend",
                status=Status.ERROR,
                message=f"HTTP {resp.status_code}",
                details={
                    "status_code": resp.status_code,
                    "response_ms": response_ms,
                    "workers": workers,
                },
            )
        else:
            backend = ServiceStatus(
                name="Backend",
                status=Status.OK,
                message="Running",
                details={
                    "status_code": resp.status_code,
                    "response_ms": response_ms,
                    "workers": workers,
                },
            )
    except requests.exceptions.ConnectionError:
        backend = ServiceStatus(name="Backend", status=Status.ERROR, message="Not reachable", details={})
    except Exception as e:
        backend = ServiceStatus(name="Backend", status=Status.ERROR, message=str(e)[:25], details={})

    pg = check_postgres()
    backend.details["pg_status"] = pg.status.value
    backend.details["pg_message"] = pg.message
    if pg.details.get("size"):
        backend.details["pg_size"] = pg.details["size"]
    if pg.status == Status.ERROR and backend.status == Status.OK:
        backend.status = Status.WARN
        backend.message = f"Running (DB: {pg.message})"
    return backend


def check_grpc() -> ServiceStatus:
    """Check chain gRPC port reachability (TCP connect + latency)."""
    try:
        host, port = parse_host_port(MIRAGE_GRPC_ADDR)
    except Exception as e:
        return ServiceStatus(name="gRPC", status=Status.ERROR, message="Bad addr", details={"addr": MIRAGE_GRPC_ADDR})

    ms = tcp_connect_ms(host, port, timeout_secs=1.5)
    if ms is None:
        return ServiceStatus(
            name="gRPC", status=Status.ERROR, message="Not reachable", details={"addr": MIRAGE_GRPC_ADDR}
        )

    return ServiceStatus(
        name="gRPC", status=Status.OK, message="Listening", details={"addr": MIRAGE_GRPC_ADDR, "ms": ms}
    )


def check_indexer() -> ServiceStatus:
    """Check indexer status by comparing heights."""
    db_url = os.environ.get("INDEXER_DB_URL", "postgresql://mirage:mirage@127.0.0.1:5432/mirage")

    # Check if indexer process is running
    # The indexer runs as "python3 main.py" or "python3 indexer/main.py"
    # We use pgrep to find it, excluding status_dashboard
    try:
        result = subprocess.run(
            ["pgrep", "-f", "python.*indexer.*main.py|python.*main.py.*indexer"],
            capture_output=True,
            text=True,
        )
        # If that didn't find anything, try the simpler pattern but exclude ourselves
        if result.returncode != 0:
            result = subprocess.run(
                ["bash", "-c", "pgrep -af 'python.*main\\.py' | grep -v status_dashboard | grep -v grep"],
                capture_output=True,
                text=True,
            )
        process_running = result.returncode == 0 and result.stdout.strip() != ""
    except Exception:
        process_running = False

    if not process_running:
        return ServiceStatus(name="Indexer", status=Status.ERROR, message="Not running", details={"running": False})

    try:
        # Get indexer height from DB
        with psycopg.connect(db_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM meta WHERE key='last_height'")
                row = cur.fetchone()
                indexer_height = int(row[0]) if row else 0

        # Get chain height
        resp = requests.get("http://127.0.0.1:26657/status", timeout=3)
        chain_height = int(resp.json().get("result", {}).get("sync_info", {}).get("latest_block_height", 0))

        lag = chain_height - indexer_height

        # Determine rate indicator
        if lag <= 0:
            rate = "caught up"
        elif lag <= 10:
            rate = "~1 blk/s"
        else:
            rate = "syncing..."

        base_details = {
            "running": True,
            "height": indexer_height,
            "node_height": chain_height,
            "lag": lag,
            "rate": rate,
        }

        if lag <= 10:
            return ServiceStatus(name="Indexer", status=Status.OK, message="Synced", details=base_details)
        elif lag <= 100:
            return ServiceStatus(
                name="Indexer", status=Status.WARN, message=f"Behind ({lag} blocks)", details=base_details
            )
        else:
            return ServiceStatus(
                name="Indexer", status=Status.WARN, message=f"Catching up ({lag})", details=base_details
            )
    except Exception as e:
        return ServiceStatus(
            name="Indexer",
            status=Status.WARN,
            message="Running (DB error)",
            details={"running": True, "error": str(e)[:20]},
        )


def _query_balance_rest(address: str) -> Optional[int]:
    """Query umirage balance for an address via REST API (port 1317)."""
    if not address:
        return None
    try:
        resp = requests.get(
            f"http://127.0.0.1:1317/cosmos/bank/v1beta1/balances/{address}/by_denom?denom=umirage",
            timeout=3,
        )
        if resp.status_code == 200:
            data = resp.json()
            amount = data.get("balance", {}).get("amount", "0")
            return int(amount)
    except Exception as e:
        debug_log(f"balance query failed for {address[:20]}: {e}")
    return None


def check_rewards() -> ServiceStatus:
    """Check rewards/quest enablement consistency (backend + indexer)."""
    details: dict = {}
    env_path = Path.home() / ".mirage" / "env" / "backend.env"
    details["backend_env"] = str(env_path)

    try:
        env_data = load_env_file(env_path)
    except FileNotFoundError:
        debug_log("rewards: backend.env missing")
        return ServiceStatus(name="Rewards", status=Status.ERROR, message="backend.env missing", details=details)
    except Exception as e:
        debug_log(f"rewards: failed to read backend.env: {e}")
        return ServiceStatus(
            name="Rewards", status=Status.ERROR, message="backend.env read error", details={"error": str(e)[:20]}
        )

    backend_quests_raw = env_data.get("QUESTS_ENABLED")
    backend_quests = parse_env_bool(backend_quests_raw)
    if backend_quests is None:
        debug_log(f"rewards: QUESTS_ENABLED invalid or missing: {backend_quests_raw!r}")
        return ServiceStatus(
            name="Rewards",
            status=Status.ERROR,
            message="QUESTS_ENABLED invalid",
            details={"backend_env": str(env_path), "QUESTS_ENABLED": backend_quests_raw},
        )

    # Read payouts configuration
    payouts_enabled_raw = env_data.get("QUESTS_PAYOUTS_ENABLED")
    payouts_enabled = parse_env_bool(payouts_enabled_raw)
    pool_address = env_data.get("QUESTS_REWARDS_POOL_ADDRESS", "").strip()

    backend_debug_raw = env_data.get("BACKEND_DEBUG")
    backend_debug = parse_env_bool(backend_debug_raw)
    details.update(
        {
            "backend_quests_enabled": backend_quests,
            "backend_debug": backend_debug,
            "payouts_enabled": payouts_enabled,
            "pool_address": pool_address or None,
        }
    )

    # Query reward pool balance if address is configured
    pool_balance = None
    if pool_address:
        pool_balance = _query_balance_rest(pool_address)
        if pool_balance is not None:
            details["pool_balance"] = pool_balance

    details["indexer_quests_enabled"] = None

    if backend_quests:
        status = Status.OK
        message = "Enabled"
    else:
        status = Status.OK
        message = "Quests OFF"

    # Payouts check: payouts OFF is only OK if backend quests are also OFF
    if payouts_enabled is False and backend_quests:
        status = Status.ERROR
        message = "Payouts OFF"
    elif payouts_enabled and not pool_address:
        status = Status.ERROR
        message = "No pool address"

    debug_log(
        "rewards: "
        f"backend_quests={backend_quests} payouts_enabled={payouts_enabled} pool_address={bool(pool_address)} "
        f"pool_balance={pool_balance} backend_debug={backend_debug} status={status.value} message={message}"
    )

    return ServiceStatus(name="Rewards", status=status, message=message, details=details)


# Server balance thresholds (in MIRAGE, not umirage)
SERVER_BALANCE_WARN = int(os.environ.get("MIRAGE_SERVER_BALANCE_WARN", "2000000"))  # 2MM
SERVER_BALANCE_ERROR = int(os.environ.get("MIRAGE_SERVER_BALANCE_ERROR", "1000000"))  # 1MM


def _get_validator_payer_address() -> Optional[str]:
    """Get the validator payer address from the keyring."""
    node_home = os.path.expanduser("~/.mirage/node")
    try:
        result = subprocess.run(
            [get_miraged_bin(), "keys", "list", "--output", "json", "--home", node_home, "--keyring-backend", "test"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for entry in data or []:
                if str(entry.get("name", "")) == "validator":
                    addr = str(entry.get("address", "")).strip()
                    if addr and re.fullmatch(r"mirage1[0-9a-z]{38}", addr):
                        return addr
    except Exception as e:
        debug_log(f"server: failed to get validator payer address: {e}")
    return None


def _query_difficulty_rest() -> Optional[dict]:
    """Query PoW difficulty info via REST API (port 1317)."""
    try:
        resp = requests.get("http://127.0.0.1:1317/mirage/core/v1/difficulty", timeout=3)
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        debug_log(f"server: difficulty query failed: {e}")
    return None


def check_node_internals() -> ServiceStatus:
    """Check node internals: validator balance and PoW difficulty."""
    details: dict = {}

    # Get validator payer address and balance
    payer_addr = _get_validator_payer_address()
    balance_mirage = None
    if payer_addr:
        details["payer_address"] = payer_addr
        raw_balance = _query_balance_rest(payer_addr)
        if raw_balance is not None:
            balance_mirage = raw_balance / 1_000_000
            details["balance"] = raw_balance
            details["balance_mirage"] = balance_mirage
    else:
        debug_log("server: no validator payer address found")

    # Query PoW difficulty
    diff_data = _query_difficulty_rest()
    if diff_data:
        current_diff = int(diff_data.get("current_difficulty", diff_data.get("currentDifficulty", 0)))
        pow_msg_count = int(diff_data.get("pow_message_count", diff_data.get("powMessageCount", 0)))
        calm_seq = int(diff_data.get("consecutive_low_usage", diff_data.get("consecutiveLowUsage", 0)))
        pow_base_bits = int(diff_data.get("pow_base_bits", diff_data.get("powBaseBits", 0)))
        details["pow_difficulty"] = current_diff
        details["pow_msg_count"] = pow_msg_count
        details["pow_calm_sequence"] = calm_seq
        details["pow_base_bits"] = pow_base_bits

    # Determine overall status based on balance
    status = Status.OK
    message = "Running"

    if balance_mirage is not None:
        if balance_mirage < SERVER_BALANCE_ERROR:
            status = Status.ERROR
            message = "Balance critical"
        elif balance_mirage < SERVER_BALANCE_WARN:
            status = Status.WARN
            message = "Balance low"
    elif payer_addr:
        status = Status.WARN
        message = "Balance unknown"
    else:
        status = Status.WARN
        message = "No payer key"

    debug_log(
        f"server: payer={payer_addr} balance_mirage={balance_mirage} "
        f"pow_diff={details.get('pow_difficulty')} status={status.value} message={message}"
    )

    return ServiceStatus(name="Node", status=status, message=message, details=details)


def check_endpoints() -> ServiceStatus:
    """Check Caddy + public chain endpoints (RPC/REST/gRPC)."""
    # --- Caddy process ---
    caddy_running = False
    try:
        result = subprocess.run(["pgrep", "-x", "caddy"], capture_output=True, text=True)
        caddy_running = result.returncode == 0
    except Exception:
        pass

    # --- Domain discovery ---
    domain = os.environ.get("DOMAIN", "")
    is_local = False
    if not domain:
        try:
            with open("/etc/caddy/Caddyfile") as f:
                content = f.read()
                for line in content.splitlines():
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue
                    if line.startswith(":80") or line.startswith(":443"):
                        is_local = True
                        break
                    if line.startswith("www."):
                        continue
                    match = re.match(r"^([a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", line)
                    if match:
                        domain = match.group(1)
                        break
        except Exception:
            pass

    if domain:
        if domain.startswith("https://"):
            domain = domain[8:]
        elif domain.startswith("http://"):
            domain = domain[7:]

    use_https = bool(domain) and not is_local
    host = domain
    if not host:
        if is_local:
            host = "127.0.0.1"
        else:
            try:
                resp = requests.get("https://ifconfig.me", timeout=3)
                if resp.status_code == 200:
                    host = resp.text.strip()
            except Exception:
                pass

    if not caddy_running:
        return ServiceStatus(
            name="Endpoints",
            status=Status.ERROR,
            message="Caddy not running",
            details={"caddy": False, "configured": bool(host)},
        )

    if not host:
        return ServiceStatus(
            name="Endpoints",
            status=Status.ERROR,
            message="No domain or IP",
            details={"caddy": True, "configured": False},
        )

    base_url = f"https://{host}" if use_https else f"http://{host}"

    results = {}
    all_ok = True
    block_height = None

    def check_rpc(path: str, name: str):
        nonlocal all_ok, block_height
        try:
            start = time.time()
            resp = requests.get(f"{base_url}{path}/status", timeout=5, verify=use_https)
            ms = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                height = data.get("result", {}).get("sync_info", {}).get("latest_block_height")
                network = data.get("result", {}).get("node_info", {}).get("network")
                catching_up = data.get("result", {}).get("sync_info", {}).get("catching_up", False)
                if height and network == "mirage-1":
                    if block_height is None:
                        block_height = int(height)
                    results[name] = {"ok": True, "ms": ms, "height": int(height), "catching_up": catching_up}
                else:
                    results[name] = {"ok": False, "error": "bad response"}
                    all_ok = False
            else:
                results[name] = {"ok": False, "status": resp.status_code}
                all_ok = False
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:20]}
            all_ok = False

    def check_rest(path: str, name: str):
        nonlocal all_ok
        try:
            start = time.time()
            resp = requests.get(f"{base_url}{path}/cosmos/bank/v1beta1/params", timeout=5, verify=use_https)
            ms = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                params = data.get("params", {})
                if "default_send_enabled" in params or "send_enabled" in params:
                    results[name] = {"ok": True, "ms": ms, "module": "bank"}
                else:
                    results[name] = {"ok": False, "error": "bad response"}
                    all_ok = False
            else:
                results[name] = {"ok": False, "status": resp.status_code}
                all_ok = False
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:20]}
            all_ok = False

    def check_grpc_endpoint():
        nonlocal all_ok
        try:
            grpc_host, grpc_port = parse_host_port(MIRAGE_GRPC_ADDR)
            ms = tcp_connect_ms(grpc_host, grpc_port, timeout_secs=1.5)
            if ms is not None:
                results["grpc"] = {"ok": True, "ms": ms, "addr": MIRAGE_GRPC_ADDR}
            else:
                results["grpc"] = {"ok": False, "error": "Not reachable"}
                all_ok = False
        except Exception as e:
            results["grpc"] = {"ok": False, "error": str(e)[:20]}
            all_ok = False

    # --- HTTPS probe (replaces standalone Caddy card) ---
    if use_https:
        try:
            start = time.time()
            https_resp = requests.get(f"https://{host}/api/get_parameters", timeout=5, verify=True)
            https_ms = int((time.time() - start) * 1000)
            if https_resp.status_code < 500:
                results["https"] = {"ok": True, "ms": https_ms, "status": https_resp.status_code}
            else:
                results["https"] = {"ok": False, "status": https_resp.status_code}
                all_ok = False
        except requests.exceptions.SSLError:
            results["https"] = {"ok": False, "error": "SSL error"}
            all_ok = False
        except requests.exceptions.ConnectionError:
            results["https"] = {"ok": False, "error": "refused"}
            all_ok = False
        except Exception as e:
            results["https"] = {"ok": False, "error": str(e)[:15]}
            all_ok = False

    check_rpc("/chain/rpc", "chain/rpc")
    check_rest("/chain/rest", "chain/rest")
    check_grpc_endpoint()

    details = {
        "caddy": True,
        "configured": True,
        "host": host,
        "https": use_https,
        "block_height": block_height,
        "endpoints": results,
    }

    if all_ok:
        return ServiceStatus(
            name="Endpoints",
            status=Status.OK,
            message=f"All OK @ {block_height:,}" if block_height else "All OK",
            details=details,
        )
    else:
        return ServiceStatus(
            name="Endpoints",
            status=Status.ERROR,
            message="Some unreachable",
            details=details,
        )


def check_referrals() -> ServiceStatus:
    """Check referral accrual daemon status."""
    try:
        result = subprocess.run(["pgrep", "-f", "referral_accrue.py"], capture_output=True, text=True)
        process_running = result.returncode == 0
        pid = result.stdout.strip().split()[0] if process_running and result.stdout.strip() else None
    except Exception:
        process_running = False
        pid = None

    if not process_running:
        return ServiceStatus(name="Referrals", status=Status.ERROR, message="Not running", details={"running": False})

    # Get additional info from database
    db_url = os.environ.get("INDEXER_DB_URL", "postgresql://mirage:mirage@127.0.0.1:5432/mirage")

    pending_count = 0
    total_links = 0
    total_accrued = 0
    try:
        with psycopg.connect(db_url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                # Count pending rewards
                cur.execute("SELECT COUNT(*) FROM referral_pending_rewards " "WHERE status = 'pending'")
                pending_count = cur.fetchone()[0]

                # Count total referral links
                cur.execute("SELECT COUNT(*) FROM referral_links")
                total_links = cur.fetchone()[0]

                # Count total accrued (completed payouts)
                cur.execute("SELECT COUNT(*) FROM referral_pending_rewards " "WHERE status = 'completed'")
                total_accrued = cur.fetchone()[0]
    except Exception:
        pass

    return ServiceStatus(
        name="Referrals",
        status=Status.OK,
        message="Running",
        details={
            "running": True,
            "pending": pending_count,
            "links": total_links,
            "total_accrued": total_accrued,
            "pid": pid,
        },
    )


# Base58 alphabet for Solana addresses
_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _base58_encode(data: bytes) -> str:
    """Encode bytes to base58 string (for Solana addresses)."""
    # Count leading zeros
    leading_zeros = 0
    for b in data:
        if b == 0:
            leading_zeros += 1
        else:
            break

    # Convert to integer
    num = int.from_bytes(data, "big")

    # Encode
    result = []
    while num > 0:
        num, rem = divmod(num, 58)
        result.append(_BASE58_ALPHABET[rem])

    # Add leading '1's for zero bytes
    return "1" * leading_zeros + "".join(reversed(result))


def _get_solana_pubkey(keypair_path: str) -> Optional[str]:
    """Get Solana public key from keypair file."""
    try:
        with open(keypair_path) as f:
            keypair_bytes = json.load(f)
        # Solana keypair is 64 bytes: first 32 = private key, last 32 = public key
        if len(keypair_bytes) != 64:
            return None
        pubkey_bytes = bytes(keypair_bytes[32:])
        return _base58_encode(pubkey_bytes)
    except Exception as e:
        debug_log(f"orchestrator: failed to get solana pubkey: {e}")
        return None


def _get_solana_balance(rpc_url: str, pubkey: str) -> Optional[float]:
    """Query Solana balance in SOL."""
    try:
        resp = requests.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getBalance",
                "params": [pubkey],
            },
            timeout=5,
        )
        data = resp.json()
        lamports = data.get("result", {}).get("value", 0)
        return lamports / 1_000_000_000  # Convert lamports to SOL
    except Exception as e:
        debug_log(f"orchestrator: failed to get solana balance: {e}")
        return None


# Solana balance thresholds
ORCHESTRATOR_SOL_WARN = float(os.environ.get("ORCHESTRATOR_SOL_WARN", "0.5"))
ORCHESTRATOR_SOL_ERROR = float(os.environ.get("ORCHESTRATOR_SOL_ERROR", "0.05"))

# System storage thresholds (in GB)
SYSTEM_STORAGE_WARN_GB = float(os.environ.get("MIRAGE_STORAGE_WARN_GB", "5"))
SYSTEM_STORAGE_ERROR_GB = float(os.environ.get("MIRAGE_STORAGE_ERROR_GB", "1"))

# Memory thresholds (percentage used)
SYSTEM_MEMORY_WARN_PCT = float(os.environ.get("MIRAGE_MEMORY_WARN_PCT", "85"))
SYSTEM_MEMORY_ERROR_PCT = float(os.environ.get("MIRAGE_MEMORY_ERROR_PCT", "95"))

# Load average thresholds (per CPU core)
SYSTEM_LOAD_WARN_PER_CORE = float(os.environ.get("MIRAGE_LOAD_WARN_PER_CORE", "0.8"))
SYSTEM_LOAD_ERROR_PER_CORE = float(os.environ.get("MIRAGE_LOAD_ERROR_PER_CORE", "1.5"))


def check_orchestrator() -> ServiceStatus:
    """Check Bridge Orchestrator status."""
    env_path = os.path.expanduser("~/.mirage/env/orchestrator.env")
    keypair_path = os.path.expanduser("~/.mirage/orchestrator/solana-keypair.json")

    # Check if env file exists
    if not os.path.exists(env_path):
        return ServiceStatus(
            name="Orchestrator", status=Status.UNKNOWN, message="Not configured", details={"configured": False}
        )

    # Parse env file to check if enabled
    enabled = False
    solana_rpc = None
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ORCHESTRATOR_ENABLED="):
                    val = line.split("=", 1)[1].strip().lower().strip('"').strip("'")
                    enabled = val in ("true", "1", "yes")
                elif line.startswith("ORCHESTRATOR_SOLANA_RPC="):
                    solana_rpc = line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

    base_details = {
        "configured": True,
        "enabled": enabled,
    }

    # If not enabled, show as unknown (not configured to run)
    if not enabled:
        return ServiceStatus(name="Orchestrator", status=Status.UNKNOWN, message="Disabled", details=base_details)

    # Check if process is running
    try:
        result = subprocess.run(["pgrep", "-f", "bin/orchestrator"], capture_output=True, text=True)
        process_running = result.returncode == 0
    except Exception:
        process_running = False

    base_details["running"] = process_running

    # Check if Solana keypair exists
    keypair_exists = os.path.exists(keypair_path)
    base_details["keypair"] = keypair_exists

    # Determine Solana network from RPC URL
    if solana_rpc:
        if "devnet" in solana_rpc:
            base_details["network"] = "devnet"
        elif "mainnet" in solana_rpc:
            base_details["network"] = "mainnet"
        else:
            base_details["network"] = "custom"

    # Get Solana wallet balance if keypair exists and RPC is configured
    sol_balance = None
    sol_pubkey = None
    if keypair_exists and solana_rpc:
        sol_pubkey = _get_solana_pubkey(keypair_path)
        if sol_pubkey:
            base_details["sol_pubkey"] = sol_pubkey
            sol_balance = _get_solana_balance(solana_rpc, sol_pubkey)
            if sol_balance is not None:
                base_details["sol_balance"] = sol_balance

    if not process_running:
        return ServiceStatus(name="Orchestrator", status=Status.ERROR, message="Not running", details=base_details)

    if not keypair_exists:
        return ServiceStatus(name="Orchestrator", status=Status.WARN, message="No keypair", details=base_details)

    # Check SOL balance thresholds
    if sol_balance is not None:
        if sol_balance < ORCHESTRATOR_SOL_ERROR:
            return ServiceStatus(name="Orchestrator", status=Status.ERROR, message="Low SOL!", details=base_details)
        elif sol_balance < ORCHESTRATOR_SOL_WARN:
            return ServiceStatus(
                name="Orchestrator", status=Status.WARN, message="SOL running low", details=base_details
            )

    return ServiceStatus(name="Orchestrator", status=Status.OK, message="Running", details=base_details)


def _get_cpu_count() -> int:
    """Get number of CPU cores."""
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


def _get_load_average() -> Optional[tuple[float, float, float]]:
    """Get system load average (1min, 5min, 15min)."""
    try:
        return os.getloadavg()
    except (OSError, AttributeError):
        # Windows doesn't have getloadavg
        return None


def _get_memory_info() -> Optional[dict]:
    """Get memory usage info from /proc/meminfo."""
    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    # Value is in kB, convert to bytes
                    val_parts = parts[1].strip().split()
                    if val_parts:
                        val_kb = int(val_parts[0])
                        meminfo[key] = val_kb * 1024

            total = meminfo.get("MemTotal", 0)
            available = meminfo.get("MemAvailable", 0)

            if total > 0:
                used = total - available
                used_pct = (used / total) * 100
                return {
                    "total": total,
                    "available": available,
                    "used": used,
                    "used_pct": used_pct,
                }
    except Exception as e:
        debug_log(f"system: failed to get memory info: {e}")
    return None


def _get_disk_usage(path: str) -> Optional[dict]:
    """Get disk usage for a given path."""
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        used = total - free
        used_pct = (used / total) * 100 if total > 0 else 0
        return {
            "total": total,
            "free": free,
            "used": used,
            "used_pct": used_pct,
        }
    except Exception as e:
        debug_log(f"system: failed to get disk usage for {path}: {e}")
        return None


def _get_uptime() -> Optional[float]:
    """Get system uptime in seconds."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except Exception as e:
        debug_log(f"system: failed to get uptime: {e}")
        return None


def _format_uptime(seconds: float) -> str:
    """Format uptime in human-readable form."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def _format_bytes(b: int) -> str:
    """Format bytes in human-readable form."""
    if b >= 1024**4:
        return f"{b / (1024 ** 4):.1f} TB"
    elif b >= 1024**3:
        return f"{b / (1024 ** 3):.1f} GB"
    elif b >= 1024**2:
        return f"{b / (1024 ** 2):.1f} MB"
    elif b >= 1024:
        return f"{b / 1024:.1f} KB"
    else:
        return f"{b} B"


def _get_pending_updates() -> Optional[dict]:
    """
    Check for pending system updates (Debian/Ubuntu/Arch).

    Returns dict with:
        - total: total number of upgradable packages
        - security: number of security updates (Debian/Ubuntu only)
        - names: list of package names (truncated)
    """
    try:
        # Try apt first (Debian/Ubuntu)
        if os.path.exists("/usr/bin/apt"):
            result = subprocess.run(
                ["apt", "list", "--upgradable"],
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "LANG": "C"},
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                # First line is "Listing..." header
                packages = [l for l in lines[1:] if l.strip()]

                total = len(packages)
                security = 0
                names = []

                for pkg in packages[:10]:
                    pkg_name = pkg.split("/")[0]
                    names.append(pkg_name)
                    if "-security" in pkg or "security" in pkg.lower():
                        security += 1

                return {"total": total, "security": security, "names": names}

        # Try pacman (Arch Linux)
        if os.path.exists("/usr/bin/pacman"):
            # checkupdates is the safe way to check for updates (doesn't need root)
            # Falls back to pacman -Qu if checkupdates isn't available
            cmd = ["checkupdates"] if os.path.exists("/usr/bin/checkupdates") else ["pacman", "-Qu"]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "LANG": "C"},
            )

            # pacman -Qu returns 1 if no updates, checkupdates returns 2 if no updates
            if result.returncode in (0, 1, 2):
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                total = len(lines)
                names = []

                for pkg in lines[:10]:
                    # Format: "package old_version -> new_version"
                    pkg_name = pkg.split()[0] if pkg else ""
                    if pkg_name:
                        names.append(pkg_name)

                # Arch doesn't distinguish security updates in the same way
                return {"total": total, "security": 0, "names": names}

        # Try dnf (Fedora/RHEL)
        if os.path.exists("/usr/bin/dnf"):
            result = subprocess.run(
                ["dnf", "check-update", "-q"],
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "LANG": "C"},
            )

            # dnf returns 100 if updates available, 0 if none
            if result.returncode in (0, 100):
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                total = len(lines)
                names = [l.split()[0] for l in lines[:10] if l.split()]

                return {"total": total, "security": 0, "names": names}

        return None

    except subprocess.TimeoutExpired:
        debug_log("system: update check timed out")
        return None
    except Exception as e:
        debug_log(f"system: _get_pending_updates failed: {e}")
        return None


def _get_directory_size(path: str) -> Optional[int]:
    """Recursively compute total size (bytes) of a directory using os.scandir()."""
    try:
        total = 0

        def _walk(p: str) -> None:
            nonlocal total
            try:
                with os.scandir(p) as it:
                    for entry in it:
                        try:
                            if entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                            elif entry.is_dir(follow_symlinks=False):
                                _walk(entry.path)
                        except (PermissionError, OSError):
                            pass
            except (PermissionError, OSError):
                pass

        _walk(path)
        return total
    except Exception as e:
        debug_log(f"system: _get_directory_size({path}) failed: {e}")
        return None


def _get_mirage_dir_sizes() -> tuple[Optional[int], dict[str, int]]:
    """Return (total_size, {subdir_name: size}) for ~/.mirage.

    Scans every immediate subdirectory so nothing is missed.
    """
    mirage_home = os.path.expanduser("~/.mirage")
    if not os.path.isdir(mirage_home):
        return None, {}

    total = _get_directory_size(mirage_home)
    breakdown: dict[str, int] = {}
    try:
        with os.scandir(mirage_home) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    sz = _get_directory_size(entry.path)
                    if sz is not None and sz > 0:
                        breakdown[entry.name] = sz
    except (PermissionError, OSError):
        pass

    return total, breakdown


def check_disk_usage() -> ServiceStatus:
    """Report ~/.mirage data footprint with per-subdirectory breakdown."""
    mirage_home = os.path.expanduser("~/.mirage")
    if not os.path.isdir(mirage_home):
        return ServiceStatus(name="Disk Usage", status=Status.UNKNOWN, message="No ~/.mirage", details={})

    total, breakdown = _get_mirage_dir_sizes()
    if total is None:
        return ServiceStatus(name="Disk Usage", status=Status.WARN, message="Scan failed", details={})

    details = {"total": total, "breakdown": breakdown}
    return ServiceStatus(name="Disk Usage", status=Status.OK, message=f"Total: {_format_bytes(total)}", details=details)


def check_system() -> ServiceStatus:
    """Check system health: disk space, memory, CPU load, ~/.mirage size."""
    details = {}
    issues = []

    # Disk usage for root filesystem
    disk = _get_disk_usage("/")
    if disk:
        free_gb = disk["free"] / (1024**3)
        details["disk_total"] = disk["total"]
        details["disk_free"] = disk["free"]
        details["disk_used_pct"] = disk["used_pct"]
        details["disk_free_gb"] = free_gb

        if free_gb < SYSTEM_STORAGE_ERROR_GB:
            issues.append(("error", "disk_critical"))
        elif free_gb < SYSTEM_STORAGE_WARN_GB:
            issues.append(("warn", "disk_low"))

    # Separate mount check for ~/.mirage
    mirage_home = os.path.expanduser("~/.mirage")
    if os.path.exists(mirage_home):
        mirage_disk = _get_disk_usage(mirage_home)
        root_total = disk.get("total") if disk else None
        if mirage_disk and mirage_disk.get("total") != root_total:
            free_gb = mirage_disk["free"] / (1024**3)
            details["mirage_disk_free"] = mirage_disk["free"]
            details["mirage_disk_used_pct"] = mirage_disk["used_pct"]
            details["mirage_disk_free_gb"] = free_gb

            if free_gb < SYSTEM_STORAGE_ERROR_GB:
                issues.append(("error", "mirage_disk_critical"))
            elif free_gb < SYSTEM_STORAGE_WARN_GB:
                issues.append(("warn", "mirage_disk_low"))

    # Memory
    mem = _get_memory_info()
    if mem:
        details["mem_total"] = mem["total"]
        details["mem_available"] = mem["available"]
        details["mem_used_pct"] = mem["used_pct"]

        if mem["used_pct"] >= SYSTEM_MEMORY_ERROR_PCT:
            issues.append(("error", "memory_critical"))
        elif mem["used_pct"] >= SYSTEM_MEMORY_WARN_PCT:
            issues.append(("warn", "memory_high"))

    # CPU load
    load = _get_load_average()
    cpu_count = _get_cpu_count()
    if load:
        details["load_1m"] = load[0]
        details["load_5m"] = load[1]
        details["load_15m"] = load[2]
        details["cpu_count"] = cpu_count

        load_per_core = load[0] / cpu_count
        details["load_per_core"] = load_per_core

        if load_per_core >= SYSTEM_LOAD_ERROR_PER_CORE:
            issues.append(("error", "load_critical"))
        elif load_per_core >= SYSTEM_LOAD_WARN_PER_CORE:
            issues.append(("warn", "load_high"))

    # Security updates only
    updates = _get_pending_updates()
    if updates:
        details["updates_total"] = updates["total"]
        details["updates_security"] = updates["security"]
        details["updates_names"] = updates["names"]

        if updates["security"] > 0:
            issues.append(("error", "security_updates"))

    # Determine overall status
    has_error = any(level == "error" for level, _ in issues)
    has_warn = any(level == "warn" for level, _ in issues)

    if has_error:
        status = Status.ERROR
        error_types = [t for l, t in issues if l == "error"]
        if "security_updates" in error_types:
            message = "Security updates!"
        elif "disk_critical" in error_types or "mirage_disk_critical" in error_types:
            message = "Disk CRITICAL!"
        elif "memory_critical" in error_types:
            message = "Memory CRITICAL!"
        elif "load_critical" in error_types:
            message = "Load CRITICAL!"
        else:
            message = "Critical issues"
    elif has_warn:
        status = Status.WARN
        warn_types = [t for l, t in issues if l == "warn"]
        if "disk_low" in warn_types or "mirage_disk_low" in warn_types:
            message = "Low disk space"
        elif "memory_high" in warn_types:
            message = "High memory"
        elif "load_high" in warn_types:
            message = "High load"
        else:
            message = "Warnings"
    else:
        status = Status.OK
        message = "Healthy"

    details["issues"] = issues

    return ServiceStatus(name="System", status=status, message=message, details=details)


# ============================================================================
# Dashboard Rendering
# ============================================================================


def render_header(width: int) -> list[str]:
    """Render the dashboard header."""
    lines = []

    # ASCII art title
    title_art = [
        f"{Colors.BRIGHT_CYAN}╔╦╗╦╦═╗╔═╗╔═╗╔═╗{Colors.RESET}",
        f"{Colors.BRIGHT_CYAN}║║║║╠╦╝╠═╣║ ╦║╣ {Colors.RESET}",
        f"{Colors.BRIGHT_CYAN}╩ ╩╩╩╚═╩ ╩╚═╝╚═╝{Colors.RESET}",
    ]

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

    lines.append("")
    for art_line in title_art:
        lines.append(center_text(art_line, width))
    lines.append(center_text(f"{Colors.DIM}System Status Dashboard{Colors.RESET}", width))
    lines.append(center_text(f"{Colors.DIM}{timestamp}{Colors.RESET}", width))
    lines.append("")

    return lines


def render_summary(statuses: list[ServiceStatus], width: int) -> list[str]:
    """Render a summary bar."""
    ok_count = sum(1 for s in statuses if s.status == Status.OK)
    warn_count = sum(1 for s in statuses if s.status == Status.WARN)
    error_count = sum(1 for s in statuses if s.status == Status.ERROR)
    unknown_count = sum(1 for s in statuses if s.status == Status.UNKNOWN)

    summary = (
        f"{Colors.BRIGHT_GREEN}{ok_count} OK{Colors.RESET}  "
        f"{Colors.BRIGHT_YELLOW}{warn_count} WARN{Colors.RESET}  "
        f"{Colors.BRIGHT_RED}{error_count} ERR{Colors.RESET}  "
        f"{Colors.BRIGHT_BLACK}○ {unknown_count} N/A{Colors.RESET}"
    )

    return [center_text(summary, width), ""]


def format_card_content(status: ServiceStatus) -> list[str]:
    """Format card content based on service status and details."""
    lines = []
    details = status.details

    color = STATUS_COLORS[status.status]
    lines.append(f"{color}{status.message}{Colors.RESET}")

    bullet = f"{Colors.DIM}-{Colors.RESET} "

    if status.name == "CometBFT":
        if details.get("height"):
            try:
                h = int(details["height"])
                lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {h:,}")
            except (ValueError, TypeError):
                lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {details['height']}")
        if "peers" in details:
            peers = details["peers"]
            peer_color = Colors.BRIGHT_GREEN if peers > 0 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}Peers:{Colors.RESET} {peer_color}{peers}{Colors.RESET}")
        if details.get("block_age"):
            age_secs = details.get("block_age_secs")
            age_human = details["block_age"]
            if age_secs is None:
                lines.append(
                    f"{bullet}{Colors.DIM}Last block:{Colors.RESET} {Colors.BRIGHT_YELLOW}unknown{Colors.RESET}"
                )
            elif age_secs >= NODE_LAST_BLOCK_ERROR_SECS:
                lines.append(
                    f"{bullet}{Colors.DIM}Last block:{Colors.RESET} {Colors.BRIGHT_RED}{age_human} STALE{Colors.RESET}"
                )
            elif age_secs >= NODE_LAST_BLOCK_WARN_SECS:
                lines.append(
                    f"{bullet}{Colors.DIM}Last block:{Colors.RESET} {Colors.BRIGHT_YELLOW}{age_human} OLD{Colors.RESET}"
                )
            else:
                lines.append(
                    f"{bullet}{Colors.DIM}Last block:{Colors.RESET} {Colors.BRIGHT_GREEN}{age_human}{Colors.RESET}"
                )

    elif status.name == "Retention":
        retained = details.get("retained_blocks")
        expected = details.get("expected_blocks")
        if retained is not None and expected is not None:
            lines.append(
                f"{bullet}{Colors.DIM}Retained:{Colors.RESET} {retained:,} / {expected:,} blocks"
            )
        elif retained is not None:
            lines.append(f"{bullet}{Colors.DIM}Retained:{Colors.RESET} {retained:,} blocks")
        pruning = details.get("pruning_strategy")
        keep = details.get("pruning_keep_recent")
        if pruning:
            extra = f" (keep {keep:,})" if keep else ""
            lines.append(f"{bullet}{Colors.DIM}Pruning:{Colors.RESET} {pruning}{extra}")
        snap_count = details.get("snapshot_count", 0)
        snap_heights = details.get("snapshot_heights", [])
        if snap_heights:
            latest = snap_heights[0]
            lines.append(f"{bullet}{Colors.DIM}Snapshot:{Colors.RESET} #{latest:,} ({snap_count} total)")

    elif status.name == "Validator":
        if details.get("moniker"):
            moniker = details["moniker"]
            if moniker.startswith("https://"):
                moniker = moniker[8:]
            elif moniker.startswith("http://"):
                moniker = moniker[7:]
            lines.append(f"{bullet}{Colors.DIM}Moniker:{Colors.RESET} {truncate(moniker, 18)}")
        if details.get("tokens"):
            tok = details["tokens"]
            if tok >= 1_000_000:
                tok_m = tok / 1_000_000
                lines.append(f"{bullet}{Colors.DIM}Stake:{Colors.RESET} {tok_m:,.0f}mm MIRAGE")
            else:
                lines.append(f"{bullet}{Colors.DIM}Stake:{Colors.RESET} {tok:,} MIRAGE")
        if details.get("power_pct") is not None:
            pct = details["power_pct"]
            lines.append(f"{bullet}{Colors.DIM}Power:{Colors.RESET} {pct:.2f}%")
        balance_mirage = details.get("balance_mirage")
        if balance_mirage is not None:
            if balance_mirage < SERVER_BALANCE_ERROR:
                bal_color = Colors.BRIGHT_RED
            elif balance_mirage < SERVER_BALANCE_WARN:
                bal_color = Colors.BRIGHT_YELLOW
            else:
                bal_color = Colors.BRIGHT_GREEN
            lines.append(
                f"{bullet}{Colors.DIM}Balance:{Colors.RESET} {bal_color}{balance_mirage:,.0f} MIRAGE{Colors.RESET}"
            )
        if details.get("tombstoned"):
            lines.append(f"{bullet}{Colors.BRIGHT_RED}TOMBSTONED (permanent){Colors.RESET}")
        elif details.get("jailed"):
            jailed_secs = details.get("jailed_since_secs")
            if jailed_secs is not None:
                jail_duration = format_age_secs(jailed_secs).replace(" ago", "")
                lines.append(f"{bullet}{Colors.BRIGHT_RED}Jailed for: {jail_duration}{Colors.RESET}")
            else:
                lines.append(f"{bullet}{Colors.BRIGHT_RED}JAILED!{Colors.RESET}")

    elif status.name == "Backend":
        if details.get("response_ms") is not None:
            ms = details["response_ms"]
            ms_color = Colors.BRIGHT_GREEN if ms < 100 else Colors.BRIGHT_YELLOW if ms < 500 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}Response:{Colors.RESET} {ms_color}{ms}ms{Colors.RESET}")
        if details.get("status_code"):
            code = details["status_code"]
            code_color = Colors.BRIGHT_GREEN if code < 400 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}HTTP:{Colors.RESET} {code_color}{code}{Colors.RESET}")
        pg_st = details.get("pg_status")
        if pg_st:
            pg_color = Colors.BRIGHT_GREEN if pg_st == "ok" else Colors.BRIGHT_RED if pg_st == "error" else Colors.BRIGHT_YELLOW
            pg_label = details.get("pg_message", pg_st)
            pg_extra = f" ({details['pg_size']})" if details.get("pg_size") else ""
            lines.append(f"{bullet}{Colors.DIM}DB:{Colors.RESET} {pg_color}{pg_label}{pg_extra}{Colors.RESET}")

    elif status.name == "Indexer":
        if details.get("height"):
            lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {details['height']:,}")
        if details.get("lag") is not None:
            lag = details["lag"]
            lag_color = Colors.BRIGHT_GREEN if lag <= 10 else Colors.BRIGHT_YELLOW
            lines.append(f"{bullet}{Colors.DIM}Lag:{Colors.RESET} {lag_color}{lag}{Colors.RESET} blocks")

    elif status.name == "Rewards":
        if details.get("payouts_enabled"):
            lines.append(f"{bullet}{Colors.DIM}Payouts:{Colors.RESET} {Colors.BRIGHT_GREEN}ON{Colors.RESET}")
            pool_balance = details.get("pool_balance")
            if pool_balance is not None:
                balance_mirage = pool_balance / 1_000_000
                lines.append(f"{bullet}{Colors.DIM}Pool:{Colors.RESET} {balance_mirage:,.0f} MIRAGE")
        else:
            lines.append(f"{bullet}{Colors.DIM}Payouts:{Colors.RESET} OFF")

    elif status.name == "Endpoints":
        endpoints = details.get("endpoints", {})
        for name, info in endpoints.items():
            if info.get("ok"):
                ms = info.get("ms", "?")
                lines.append(f"{bullet}{Colors.DIM}{name}:{Colors.RESET} {Colors.BRIGHT_GREEN}OK{Colors.RESET} {ms}ms")
            else:
                err = info.get("error") or info.get("status") or "fail"
                err = str(err)[:12]
                lines.append(f"{bullet}{Colors.DIM}{name}:{Colors.RESET} {Colors.BRIGHT_RED}{err}{Colors.RESET}")

    elif status.name == "Disk Usage":
        breakdown = details.get("breakdown", {})
        if breakdown:
            sorted_dirs = sorted(breakdown.items(), key=lambda x: -x[1])
            for name, sz in sorted_dirs[:5]:
                lines.append(f"{bullet}{Colors.DIM}{name}:{Colors.RESET} {_format_bytes(sz)}")

    elif status.name == "Orchestrator":
        if details.get("network"):
            network = details["network"]
            net_color = Colors.BRIGHT_YELLOW if network == "devnet" else Colors.BRIGHT_GREEN
            lines.append(f"{bullet}{Colors.DIM}Network:{Colors.RESET} {net_color}{network}{Colors.RESET}")
        if details.get("keypair"):
            lines.append(f"{bullet}{Colors.DIM}Keypair:{Colors.RESET} {Colors.BRIGHT_GREEN}OK{Colors.RESET}")
        elif details.get("enabled"):
            lines.append(f"{bullet}{Colors.DIM}Keypair:{Colors.RESET} {Colors.BRIGHT_RED}Missing{Colors.RESET}")
        if "sol_balance" in details:
            bal = details["sol_balance"]
            if bal < ORCHESTRATOR_SOL_ERROR:
                bal_color = Colors.BRIGHT_RED
                bal_suffix = " CRITICAL!"
            elif bal < ORCHESTRATOR_SOL_WARN:
                bal_color = Colors.BRIGHT_YELLOW
                bal_suffix = " LOW"
            else:
                bal_color = Colors.BRIGHT_GREEN
                bal_suffix = ""
            lines.append(f"{bullet}{Colors.DIM}SOL:{Colors.RESET} {bal_color}{bal:.4f}{bal_suffix}{Colors.RESET}")

    elif status.name == "System":
        # Disk free space
        if "disk_free_gb" in details:
            free_gb = details["disk_free_gb"]
            if free_gb < SYSTEM_STORAGE_ERROR_GB:
                disk_color = Colors.BRIGHT_RED
                disk_suffix = " CRITICAL!"
            elif free_gb < SYSTEM_STORAGE_WARN_GB:
                disk_color = Colors.BRIGHT_YELLOW
                disk_suffix = " LOW"
            else:
                disk_color = Colors.BRIGHT_GREEN
                disk_suffix = ""
            lines.append(
                f"{bullet}{Colors.DIM}Disk:{Colors.RESET} {disk_color}{free_gb:.1f} GB free{disk_suffix}{Colors.RESET}"
            )

        # Mirage data disk (if different mount)
        if "mirage_disk_free_gb" in details:
            free_gb = details["mirage_disk_free_gb"]
            if free_gb < SYSTEM_STORAGE_ERROR_GB:
                disk_color = Colors.BRIGHT_RED
                disk_suffix = " CRITICAL!"
            elif free_gb < SYSTEM_STORAGE_WARN_GB:
                disk_color = Colors.BRIGHT_YELLOW
                disk_suffix = " LOW"
            else:
                disk_color = Colors.BRIGHT_GREEN
                disk_suffix = ""
            lines.append(
                f"{bullet}{Colors.DIM}Data vol:{Colors.RESET} {disk_color}{free_gb:.1f} GB free{disk_suffix}{Colors.RESET}"
            )

        # Memory usage
        if "mem_used_pct" in details:
            used_pct = details["mem_used_pct"]
            mem_avail = details.get("mem_available", 0)
            if used_pct >= SYSTEM_MEMORY_ERROR_PCT:
                mem_color = Colors.BRIGHT_RED
            elif used_pct >= SYSTEM_MEMORY_WARN_PCT:
                mem_color = Colors.BRIGHT_YELLOW
            else:
                mem_color = Colors.BRIGHT_GREEN
            avail_str = _format_bytes(mem_avail)
            lines.append(
                f"{bullet}{Colors.DIM}Memory:{Colors.RESET} {mem_color}{used_pct:.0f}% used{Colors.RESET} ({avail_str} free)"
            )

        # CPU load
        if "load_1m" in details:
            load_1m = details["load_1m"]
            cpu_count = details.get("cpu_count", 1)
            load_pct = (load_1m / cpu_count) * 100
            if load_pct >= SYSTEM_LOAD_ERROR_PER_CORE * 100:
                load_color = Colors.BRIGHT_RED
            elif load_pct >= SYSTEM_LOAD_WARN_PER_CORE * 100:
                load_color = Colors.BRIGHT_YELLOW
            else:
                load_color = Colors.BRIGHT_GREEN
            lines.append(
                f"{bullet}{Colors.DIM}CPU:{Colors.RESET} {load_color}{load_pct:.0f}%{Colors.RESET} ({cpu_count} cores)"
            )

        # Security updates only (skip non-security)
        security = details.get("updates_security", 0)
        if security > 0:
            total = details.get("updates_total", security)
            lines.append(f"{bullet}{Colors.BRIGHT_RED}Updates:{Colors.RESET} {total} ({security} security!)")

    # Ensure minimum card height (4 detail lines + status = 5 total)
    while len(lines) < 5:
        lines.append("")

    return lines


def render_dashboard(refresh_secs: int):
    """Render the full dashboard."""
    term_width, term_height = get_terminal_size()

    # Collect all statuses -- ops-focused set only
    statuses = [
        check_node(),
        check_retention(),
        check_validator(),
        check_backend(),
        check_rewards(),
        check_indexer(),
        check_endpoints(),
        check_orchestrator(),
        check_disk_usage(),
        check_system(),
    ]

    # Hide unconfigured optional services (Validator, Orchestrator)
    display_statuses = [
        s
        for s in statuses
        if s.status != Status.UNKNOWN
        or s.name in ("CometBFT", "Retention", "Backend", "Rewards", "Indexer", "Endpoints", "Disk Usage", "System")
    ]

    # Render header
    output = render_header(term_width)

    # Render summary (only count displayed services)
    output.extend(render_summary(display_statuses, term_width))

    # Calculate card layout
    card_width = 38
    gap = 2
    cards_per_row = max(1, (term_width + gap) // (card_width + gap))

    # Create cards
    cards = []
    for status in display_statuses:
        content = format_card_content(status)
        card = draw_card(status.name, status.status, content, width=card_width)
        cards.append(card)

    # Arrange cards in rows
    for i in range(0, len(cards), cards_per_row):
        row_cards = cards[i : i + cards_per_row]
        merged = merge_cards_horizontal(row_cards, gap=gap)

        # Center the row
        if merged:
            # Calculate row width
            first_line = merged[0]
            stripped = ""
            j = 0
            while j < len(first_line):
                if first_line[j] == "\033":
                    k = first_line.find("m", j)
                    if k != -1:
                        j = k + 1
                        continue
                stripped += first_line[j]
                j += 1
            row_width = len(stripped)

            left_margin = max(0, (term_width - row_width) // 2)
            margin_str = " " * left_margin

            for line in merged:
                output.append(margin_str + line)
        output.append("")

    # Print output
    print("\n".join(output))

    # Footer
    footer = f"{Colors.DIM}Press Ctrl+C to exit • Auto-refresh: {refresh_secs}s{Colors.RESET}"
    print()
    print(center_text(footer, term_width))


def run_health_check_json(required_services: list[str]) -> dict:
    """
    Run health checks and return JSON-serializable result.

    Args:
        required_services: List of service names that must be healthy.

    Returns:
        Dict with:
            - healthy: bool (True if all required services are OK or WARN)
            - services: dict mapping service name to status info
            - errors: list of error messages for unhealthy required services
    """
    all_statuses = [
        check_node(),
        check_validator(),
        check_backend(),
        check_indexer(),
        check_endpoints(),
    ]

    # Build services dict
    services = {}
    for s in all_statuses:
        services[s.name] = {
            "status": s.status.value,
            "message": s.message,
            "healthy": s.status in (Status.OK, Status.WARN),
            "details": s.details,
        }

    # Check required services
    errors = []
    all_healthy = True

    for req in required_services:
        if req not in services:
            errors.append(f"{req}: service not found")
            all_healthy = False
            continue

        svc = services[req]
        if not svc["healthy"]:
            errors.append(f"{req}: {svc['status']} - {svc['message']}")
            all_healthy = False

    return {
        "healthy": all_healthy,
        "services": services,
        "errors": errors,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Mirage unified status dashboard")
    parser.add_argument("--once", action="store_true", help="Render once and exit")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output JSON health check result and exit (for scripting)",
    )
    parser.add_argument(
        "--require",
        type=str,
        default="CometBFT,Validator,Backend,Indexer,Endpoints",
        help="Comma-separated list of required services for --json health check",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("MIRAGE_CHECK_STATUS_INTERVAL", "3")),
        help="Refresh interval when visible in seconds (default: 3)",
    )
    parser.add_argument(
        "--idle-interval",
        type=int,
        default=int(os.environ.get("MIRAGE_CHECK_STATUS_IDLE_INTERVAL", "600")),
        help="Refresh interval when not visible in seconds (default: 600 = 10 min)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="Do not clear the screen before rendering",
    )
    args = parser.parse_args()

    # JSON health check mode
    if args.json:
        required = [s.strip() for s in args.require.split(",") if s.strip()]
        result = run_health_check_json(required)
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["healthy"] else 1)

    active_interval = max(1, int(args.interval))
    idle_interval = max(1, int(args.idle_interval))

    # Track last render time for idle mode
    last_render_time = 0

    try:
        while True:
            is_in_tmux, is_visible = get_tmux_visibility_state()

            if is_visible:
                # Actively visible - render and use short interval
                if not args.no_clear:
                    print("\033[2J\033[H", end="")
                render_dashboard(refresh_secs=active_interval)
                last_render_time = time.time()

                if args.once:
                    return
                time.sleep(active_interval)
            else:
                # Not visible (detached or different window)
                # Only render if idle_interval has passed since last render
                now = time.time()
                time_since_render = now - last_render_time

                if time_since_render >= idle_interval:
                    if not args.no_clear:
                        print("\033[2J\033[H", end="")
                    render_dashboard(refresh_secs=idle_interval)
                    last_render_time = time.time()

                if args.once:
                    return

                # Sleep in shorter chunks to detect visibility changes quickly
                # Check every 2 seconds if we became visible
                time.sleep(2)

    except KeyboardInterrupt:
        print("\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
