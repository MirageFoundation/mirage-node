#!/usr/bin/env python3
"""
Mirage Unified Status Dashboard

A unified health check dashboard combining all service statuses in a
visually appealing card/tile layout.

Services monitored:
  - CometBFT (blockchain node)
  - Validator (if configured)
  - PostgreSQL database
  - Backend API
  - Indexer
  - Caddy (web server)
  - Hermes IBC relayer (if configured)
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
from datetime import datetime, timezone
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
            cmd = ["tmux", "display-message", "-t", pane_id, "-p", "#{window_index} #{session_attached} #{client_session}"]
        
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
        
        debug_log(f"tmux: pane={pane_id} our_window={our_window_index} active_window={active_window_index} visible={window_active}")
        
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

        details = {
            "height": height,
            "syncing": catching_up,
            "peers": peers,
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

        # Even if CometBFT reports catching_up=false, a stale last block is still unhealthy.
        if block_age_secs is not None:
            if block_age_secs >= NODE_LAST_BLOCK_ERROR_SECS:
                status = Status.ERROR
                message = "No new blocks"
            elif block_age_secs >= NODE_LAST_BLOCK_WARN_SECS and status != Status.ERROR:
                status = Status.WARN
                message = "Slow blocks"

        if peers == 0 and status == Status.OK:
            status = Status.WARN
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

        base_details = {
            "configured": True,
            "moniker": moniker,
            "tokens": tokens,
            "power_pct": power_pct,
            "voting_power": voting_power,
        }

        if jailed:
            return ServiceStatus(
                name="Validator",
                status=Status.ERROR,
                message="JAILED",
                details={**base_details, "active": False, "jailed": True},
            )

        if in_set:
            return ServiceStatus(
                name="Validator",
                status=Status.OK,
                message="Active",
                details={**base_details, "active": True, "voting_power": voting_power},
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
    """Check backend API status."""
    try:
        # Count gunicorn workers first
        workers = 0
        try:
            result = subprocess.run(["pgrep", "-c", "-f", "gunicorn.*factory:app"], capture_output=True, text=True)
            if result.returncode == 0:
                workers = int(result.stdout.strip())
        except Exception:
            pass

        # Try the parameters endpoint (simple GET that should always work)
        start = time.time()
        resp = requests.get("http://127.0.0.1:5000/api/get_parameters", timeout=3)
        response_ms = int((time.time() - start) * 1000)

        if resp.status_code >= 400:
            return ServiceStatus(
                name="Backend",
                status=Status.ERROR,
                message=f"HTTP {resp.status_code}",
                details={
                    "status_code": resp.status_code,
                    "response_ms": response_ms,
                    "workers": workers,
                },
            )

        return ServiceStatus(
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
        return ServiceStatus(name="Backend", status=Status.ERROR, message="Not reachable", details={})
    except Exception as e:
        return ServiceStatus(name="Backend", status=Status.ERROR, message=str(e)[:25], details={})


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
    try:
        result = subprocess.run(["pgrep", "-f", "indexer/main.py"], capture_output=True, text=True)
        process_running = result.returncode == 0
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


def check_caddy() -> ServiceStatus:
    """Check Caddy web server status by actually making requests."""
    # Try to get domain from env first, then from Caddyfile
    domain = os.environ.get("DOMAIN", "")

    # If not in env, read from Caddyfile (more reliable)
    if not domain:
        try:
            with open("/etc/caddy/Caddyfile") as f:
                content = f.read()
                # Look for domain (not :80 or www.)
                for line in content.splitlines():
                    line = line.strip()
                    # Skip :80, www., comments, empty lines
                    if line.startswith(":") or line.startswith("www.") or line.startswith("#") or not line:
                        continue
                    # Match domain-like pattern at start of line (before {)
                    match = re.match(r"^([a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", line)
                    if match:
                        domain = match.group(1)
                        break
        except Exception:
            pass

    # Strip protocol from domain if present
    clean_domain = domain
    if clean_domain.startswith("https://"):
        clean_domain = clean_domain[8:]
    elif clean_domain.startswith("http://"):
        clean_domain = clean_domain[7:]

    # Check if process is running
    try:
        result = subprocess.run(["pgrep", "-x", "caddy"], capture_output=True, text=True)
        process_running = result.returncode == 0
    except Exception:
        process_running = False

    if not process_running:
        return ServiceStatus(name="Caddy", status=Status.ERROR, message="Not running", details={"running": False})

    # Actually test HTTP connectivity
    http_ok = False
    https_ok = False
    http_status = None
    https_status = None
    response_ms = None

    # Test HTTP on localhost - TCP connect only (backend check already tests the endpoint)
    ms = tcp_connect_ms("127.0.0.1", 80, timeout_secs=2)
    if ms is not None:
        response_ms = ms
        http_status = ms  # Show latency as the status
        http_ok = True
    else:
        http_status = "refused"

    # If DOMAIN is set, test HTTPS
    if clean_domain:
        try:
            resp = requests.get(f"https://{clean_domain}/api/get_parameters", timeout=5, verify=True)
            https_status = resp.status_code
            https_ok = resp.status_code < 500
        except requests.exceptions.SSLError as e:
            https_status = "SSL error"
        except requests.exceptions.ConnectionError:
            https_status = "refused"
        except Exception as e:
            https_status = str(e)[:15]

    details = {
        "running": True,
        "domain": clean_domain if clean_domain else None,
        "http": http_status,
        "https": https_status if clean_domain else None,
        "response_ms": response_ms,
    }

    # Determine status
    if clean_domain:
        # If domain is set, HTTPS must work
        if https_ok:
            return ServiceStatus(
                name="Caddy",
                status=Status.OK,
                message="HTTPS OK",
                details=details,
            )
        elif http_ok:
            # HTTP works but HTTPS doesn't - this is bad
            return ServiceStatus(
                name="Caddy",
                status=Status.ERROR,
                message="HTTPS failed",
                details=details,
            )
        else:
            return ServiceStatus(
                name="Caddy",
                status=Status.ERROR,
                message="Not responding",
                details=details,
            )
    else:
        # No domain - just HTTP
        if http_ok:
            return ServiceStatus(
                name="Caddy",
                status=Status.OK,
                message="HTTP OK",
                details=details,
            )
        else:
            return ServiceStatus(
                name="Caddy",
                status=Status.ERROR,
                message="Not responding",
                details=details,
            )


def check_endpoints() -> ServiceStatus:
    """Check public chain endpoints (RPC/REST paths through Caddy)."""
    # Get domain from env or Caddyfile
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
                    # Local mode: Caddyfile starts with :80 (no domain)
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

    # Clean domain
    if domain:
        if domain.startswith("https://"):
            domain = domain[8:]
        elif domain.startswith("http://"):
            domain = domain[7:]

    # If local mode (no domain, just :80), use localhost
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

    if not host:
        return ServiceStatus(
            name="Endpoints",
            status=Status.ERROR,
            message="No domain or IP",
            details={"configured": False},
        )

    # Build base URL
    base_url = f"https://{host}" if use_https else f"http://{host}"

    results = {}
    all_ok = True
    new_ok = True
    legacy_ok = True
    block_height = None

    def check_rpc(path: str, name: str, is_legacy: bool):
        nonlocal all_ok, new_ok, legacy_ok, block_height
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
                    results[name] = {"ok": False, "error": f"bad response"}
                    all_ok = False
                    if is_legacy:
                        legacy_ok = False
                    else:
                        new_ok = False
            else:
                results[name] = {"ok": False, "status": resp.status_code}
                all_ok = False
                if is_legacy:
                    legacy_ok = False
                else:
                    new_ok = False
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:20]}
            all_ok = False
            if is_legacy:
                legacy_ok = False
            else:
                new_ok = False

    def check_rest(path: str, name: str, is_legacy: bool):
        nonlocal all_ok, new_ok, legacy_ok
        try:
            start = time.time()
            # Query bank module params to verify REST is functional
            resp = requests.get(f"{base_url}{path}/cosmos/bank/v1beta1/params", timeout=5, verify=use_https)
            ms = int((time.time() - start) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                # Check we got valid bank params
                params = data.get("params", {})
                if "default_send_enabled" in params or "send_enabled" in params:
                    results[name] = {"ok": True, "ms": ms, "module": "bank"}
                else:
                    results[name] = {"ok": False, "error": "bad response"}
                    all_ok = False
                    if is_legacy:
                        legacy_ok = False
                    else:
                        new_ok = False
            else:
                results[name] = {"ok": False, "status": resp.status_code}
                all_ok = False
                if is_legacy:
                    legacy_ok = False
                else:
                    new_ok = False
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)[:20]}
            all_ok = False
            if is_legacy:
                legacy_ok = False
            else:
                new_ok = False

    # Check new paths
    check_rpc("/chain/rpc", "chain/rpc", False)
    check_rest("/chain/rest", "chain/rest", False)

    # Check legacy paths
    check_rpc("/rpc", "rpc (legacy)", True)
    check_rest("/lcd", "lcd (legacy)", True)

    details = {
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
    elif new_ok and not legacy_ok:
        return ServiceStatus(
            name="Endpoints",
            status=Status.WARN,
            message="Legacy unreachable",
            details=details,
        )
    elif not new_ok and legacy_ok:
        return ServiceStatus(
            name="Endpoints",
            status=Status.ERROR,
            message="Primary unreachable",
            details=details,
        )
    else:
        return ServiceStatus(
            name="Endpoints",
            status=Status.ERROR,
            message="Paths unreachable",
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


def check_hermes() -> ServiceStatus:
    """Check Hermes IBC relayer status."""
    hermes_home = os.path.expanduser("~/.mirage/hermes")
    config_path = os.path.join(hermes_home, "config.toml")

    # Active IBC channel (Mirage <-> Osmosis)
    # channel-1 on mirage-1 <-> channel-108698 on osmosis-1
    monitor_channel = "channel-1"

    if not os.path.exists(config_path):
        return ServiceStatus(
            name="Hermes IBC", status=Status.UNKNOWN, message="Not configured", details={"configured": False}
        )

    # Check if process is running
    try:
        result = subprocess.run(["pgrep", "-f", "hermes.*start"], capture_output=True, text=True)
        process_running = result.returncode == 0
    except Exception:
        process_running = False

    # Parse config.toml to get chain IDs
    chains = []
    try:
        with open(config_path) as f:
            config_content = f.read()
            chain_matches = re.findall(r'id\s*=\s*["\']([^"\']+)["\']', config_content)
            chains = chain_matches[:3]
    except Exception:
        pass

    # Check if relayer keys exist
    keys_missing = []
    for chain_id in chains:
        key_path = os.path.join(hermes_home, "keys", chain_id, "keyring-test", "relayer.json")
        if not os.path.exists(key_path):
            keys_missing.append(chain_id)

    base_details = {
        "configured": True,
        "running": process_running,
        "chains": ", ".join(chains) if chains else None,
        "channel": monitor_channel if monitor_channel else None,
    }

    if not process_running:
        return ServiceStatus(name="Hermes IBC", status=Status.ERROR, message="Not running", details=base_details)

    # Critical: relayer keys missing
    if keys_missing:
        return ServiceStatus(
            name="Hermes IBC",
            status=Status.ERROR,
            message="Keys missing",
            details={**base_details, "keys_missing": ", ".join(keys_missing)},
        )

    # Check channel and client health via hermes CLI
    try:
        # Check if channel is open and get connection info
        result = subprocess.run(
            [
                "hermes",
                "--config",
                config_path,
                "--json",
                "query",
                "channel",
                "end",
                "--chain",
                "mirage-1",
                "--port",
                "transfer",
                "--channel",
                monitor_channel,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return ServiceStatus(
                name="Hermes IBC",
                status=Status.WARN,
                message="Query failed",
                details={**base_details, "error": truncate((result.stderr or result.stdout).strip(), 40)},
            )

        # Hermes may print multiple JSON lines (e.g., a JSON log line + a JSON result line).
        # Parse the last JSON object that contains a "result" field.
        payload = None
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict) and "result" in obj:
                payload = obj

        if not payload or not isinstance(payload.get("result"), dict):
            return ServiceStatus(
                name="Hermes IBC",
                status=Status.WARN,
                message="Bad JSON",
                details={**base_details, "error": "Could not parse hermes JSON output"},
            )

        channel_state = payload["result"].get("state")
        state_upper = (channel_state or "").upper()
        channel_open = state_upper == "OPEN"

        if not channel_open:
            return ServiceStatus(
                name="Hermes IBC",
                status=Status.ERROR,
                message="Channel closed",
                details={**base_details, "channel_state": channel_state or "unknown"},
            )

        # Extract connection ID from channel query JSON (preferred)
        connection_id = None
        hops = payload["result"].get("connection_hops")
        if isinstance(hops, list) and hops:
            connection_id = str(hops[0])
        if not connection_id:
            # Fallback to regex
            conn_match = re.search(r"connection-\d+", result.stdout)
            connection_id = conn_match.group(0) if conn_match else None

        if connection_id:
            # Get the client ID for this specific connection
            conn_result = subprocess.run(
                [
                    "hermes",
                    "--config",
                    config_path,
                    "query",
                    "connection",
                    "end",
                    "--chain",
                    "mirage-1",
                    "--connection",
                    connection_id,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            # Extract client ID (e.g., "client_id: 07-tendermint-2")
            client_match = re.search(r"07-tendermint-\d+", conn_result.stdout)
            client_id = client_match.group(0) if client_match else None

            if client_id:
                # Check this specific client's status
                client_status = subprocess.run(
                    [
                        "hermes",
                        "--config",
                        config_path,
                        "query",
                        "client",
                        "status",
                        "--chain",
                        "mirage-1",
                        "--client",
                        client_id,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                combined = client_status.stdout + client_status.stderr
                if (
                    "expired" in combined.lower()
                    or "frozen" in combined.lower()
                    or "outside of trusting period" in combined
                ):
                    return ServiceStatus(
                        name="Hermes IBC",
                        status=Status.ERROR,
                        message="Client expired",
                        details={**base_details, "expired": True, "client": client_id},
                    )
                base_details["client"] = client_id

        return ServiceStatus(
            name="Hermes IBC",
            status=Status.OK,
            message="Running",
            details={**base_details, "channel_open": True, "channel_state": channel_state or "OPEN"},
        )
    except subprocess.TimeoutExpired:
        return ServiceStatus(name="Hermes IBC", status=Status.WARN, message="Query timeout", details=base_details)
    except Exception as e:
        return ServiceStatus(name="Hermes IBC", status=Status.WARN, message=str(e)[:20], details=base_details)


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
        return ServiceStatus(
            name="Orchestrator", status=Status.UNKNOWN, message="Disabled", details=base_details
        )

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

    if not process_running:
        return ServiceStatus(
            name="Orchestrator", status=Status.ERROR, message="Not running", details=base_details
        )

    if not keypair_exists:
        return ServiceStatus(
            name="Orchestrator", status=Status.WARN, message="No keypair", details=base_details
        )

    return ServiceStatus(
        name="Orchestrator", status=Status.OK, message="Running", details=base_details
    )


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

    # Status message
    color = STATUS_COLORS[status.status]
    lines.append(f"{color}{status.message}{Colors.RESET}")

    # Bullet prefix for detail lines
    bullet = f"{Colors.DIM}-{Colors.RESET} "

    # Service-specific details (4 bullets each)
    if status.name == "CometBFT":
        if details.get("height"):
            try:
                h = int(details["height"])
                lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {h:,}")
            except (ValueError, TypeError):
                lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {details['height']}")
        if "peers" in details:
            peers = details["peers"]
            peer_color = Colors.BRIGHT_GREEN if peers > 0 else Colors.BRIGHT_YELLOW
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
        if details.get("rpc_health_ok") is not None:
            ok = details["rpc_health_ok"]
            ms = details.get("rpc_health_ms")
            if ok:
                extra = f" ({ms}ms)" if isinstance(ms, int) else ""
                lines.append(
                    f"{bullet}{Colors.DIM}RPC health:{Colors.RESET} {Colors.BRIGHT_GREEN}OK{extra}{Colors.RESET}"
                )
            else:
                lines.append(f"{bullet}{Colors.DIM}RPC health:{Colors.RESET} {Colors.BRIGHT_RED}BAD{Colors.RESET}")

    elif status.name == "Validator":
        if details.get("moniker"):
            moniker = details["moniker"]
            # Strip https:// prefix for cleaner display
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
        if details.get("voting_power"):
            vp = details["voting_power"]
            lines.append(f"{bullet}{Colors.DIM}Voting power:{Colors.RESET} {vp:,}")
        if details.get("jailed"):
            lines.append(f"{bullet}{Colors.BRIGHT_RED}JAILED!{Colors.RESET}")

    elif status.name == "PostgreSQL":
        if details.get("tables") is not None:
            lines.append(f"{bullet}{Colors.DIM}Tables:{Colors.RESET} {details['tables']}")
        if details.get("size"):
            lines.append(f"{bullet}{Colors.DIM}Size:{Colors.RESET} {details['size']}")
        if details.get("connections") is not None:
            lines.append(f"{bullet}{Colors.DIM}Connections:{Colors.RESET} {details['connections']}")
        if details.get("version"):
            lines.append(f"{bullet}{Colors.DIM}Version:{Colors.RESET} {details['version']}")

    elif status.name == "Backend":
        if details.get("workers"):
            lines.append(f"{bullet}{Colors.DIM}Workers:{Colors.RESET} {details['workers']}")
        if details.get("response_ms") is not None:
            ms = details["response_ms"]
            ms_color = Colors.BRIGHT_GREEN if ms < 100 else Colors.BRIGHT_YELLOW if ms < 500 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}Response:{Colors.RESET} {ms_color}{ms}ms{Colors.RESET}")
        if details.get("status_code"):
            code = details["status_code"]
            code_color = Colors.BRIGHT_GREEN if code < 400 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}HTTP:{Colors.RESET} {code_color}{code}{Colors.RESET}")

    elif status.name == "gRPC":
        addr = details.get("addr") or MIRAGE_GRPC_ADDR
        lines.append(f"{bullet}{Colors.DIM}Addr:{Colors.RESET} {truncate(str(addr), 22)}")
        ms = details.get("ms")
        if isinstance(ms, int):
            ms_color = Colors.BRIGHT_GREEN if ms < 50 else Colors.BRIGHT_YELLOW if ms < 200 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}Connect:{Colors.RESET} {ms_color}{ms}ms{Colors.RESET}")

    elif status.name == "Indexer":
        if details.get("height"):
            lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {details['height']:,}")
        if details.get("lag") is not None:
            lag = details["lag"]
            lag_color = Colors.BRIGHT_GREEN if lag <= 10 else Colors.BRIGHT_YELLOW
            lines.append(f"{bullet}{Colors.DIM}Lag:{Colors.RESET} {lag_color}{lag}{Colors.RESET} blocks")
        if details.get("rate"):
            lines.append(f"{bullet}{Colors.DIM}Rate:{Colors.RESET} {details['rate']}")

    elif status.name == "Caddy":
        if details.get("domain"):
            lines.append(f"{bullet}{Colors.DIM}Domain:{Colors.RESET} {truncate(details['domain'], 18)}")
        # Show HTTP status (now shows TCP connect latency, not HTTP status code)
        http_val = details.get("http")
        https_ok = isinstance(details.get("https"), int) and details.get("https") < 400
        if http_val is not None:
            if isinstance(http_val, int):
                # It's TCP connect latency in ms
                ms_color = Colors.BRIGHT_GREEN if http_val < 50 else Colors.BRIGHT_YELLOW if http_val < 200 else Colors.BRIGHT_RED
                lines.append(f"{bullet}{Colors.DIM}HTTP:{Colors.RESET} {ms_color}{http_val}ms{Colors.RESET}")
            elif http_val == "refused" and https_ok:
                # HTTP refused is expected when HTTPS is working
                lines.append(f"{bullet}{Colors.DIM}HTTP:{Colors.RESET} {Colors.BRIGHT_GREEN}redirected{Colors.RESET}")
            else:
                lines.append(f"{bullet}{Colors.DIM}HTTP:{Colors.RESET} {Colors.BRIGHT_RED}{http_val}{Colors.RESET}")
        # Show HTTPS status if domain is set
        https_val = details.get("https")
        if https_val is not None:
            if isinstance(https_val, int) and https_val < 400:
                lines.append(f"{bullet}{Colors.DIM}HTTPS:{Colors.RESET} {Colors.BRIGHT_GREEN}{https_val}{Colors.RESET}")
            elif isinstance(https_val, int):
                lines.append(
                    f"{bullet}{Colors.DIM}HTTPS:{Colors.RESET} {Colors.BRIGHT_YELLOW}{https_val}{Colors.RESET}"
                )
            else:
                lines.append(f"{bullet}{Colors.DIM}HTTPS:{Colors.RESET} {Colors.BRIGHT_RED}{https_val}{Colors.RESET}")
        elif not details.get("domain"):
            lines.append(f"{bullet}{Colors.DIM}Mode:{Colors.RESET} HTTP only")
        # Response time
        if details.get("response_ms") is not None:
            ms = details["response_ms"]
            ms_color = Colors.BRIGHT_GREEN if ms < 100 else Colors.BRIGHT_YELLOW if ms < 500 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}Response:{Colors.RESET} {ms_color}{ms}ms{Colors.RESET}")

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

    elif status.name == "Hermes IBC":
        if details.get("keys_missing"):
            lines.append(f"{bullet}{Colors.BRIGHT_RED}Keys missing:{Colors.RESET} {details['keys_missing']}")
        if details.get("expired"):
            lines.append(f"{bullet}{Colors.BRIGHT_RED}Client EXPIRED{Colors.RESET}")
        if details.get("channel_open"):
            lines.append(f"{bullet}{Colors.DIM}Channel:{Colors.RESET} {Colors.BRIGHT_GREEN}OPEN{Colors.RESET}")
        elif details.get("channel"):
            lines.append(f"{bullet}{Colors.DIM}Channel:{Colors.RESET} {details['channel']}")
        if details.get("chains"):
            lines.append(f"{bullet}{Colors.DIM}Chains:{Colors.RESET} {details['chains']}")

    elif status.name == "Orchestrator":
        if details.get("network"):
            network = details["network"]
            net_color = Colors.BRIGHT_YELLOW if network == "devnet" else Colors.BRIGHT_GREEN
            lines.append(f"{bullet}{Colors.DIM}Network:{Colors.RESET} {net_color}{network}{Colors.RESET}")
        if details.get("keypair"):
            lines.append(f"{bullet}{Colors.DIM}Keypair:{Colors.RESET} {Colors.BRIGHT_GREEN}OK{Colors.RESET}")
        elif details.get("enabled"):
            lines.append(f"{bullet}{Colors.DIM}Keypair:{Colors.RESET} {Colors.BRIGHT_RED}Missing{Colors.RESET}")

    # Ensure minimum card height (4 detail lines + status = 5 total)
    while len(lines) < 5:
        lines.append("")

    return lines


def render_dashboard(refresh_secs: int):
    """Render the full dashboard."""
    term_width, term_height = get_terminal_size()

    # Collect all statuses
    statuses = [
        check_node(),
        check_validator(),
        check_postgres(),
        check_backend(),
        check_grpc(),
        check_indexer(),
        check_caddy(),
        check_endpoints(),
        check_hermes(),
        check_orchestrator(),
    ]

    # Filter out unconfigured services for cleaner display
    # But keep them if they have errors
    display_statuses = [
        s
        for s in statuses
        if s.status != Status.UNKNOWN
        or s.name in ("CometBFT", "PostgreSQL", "Backend", "gRPC", "Indexer", "Caddy", "Endpoints")
    ]

    # Render header
    output = render_header(term_width)

    # Render summary
    output.extend(render_summary(statuses, term_width))

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


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Mirage unified status dashboard")
    parser.add_argument("--once", action="store_true", help="Render once and exit")
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
