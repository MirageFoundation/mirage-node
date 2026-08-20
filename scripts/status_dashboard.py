#!/usr/bin/env python3
"""
Mirage Unified Status Dashboard

An ops-focused health check dashboard showing the highest-signal service
statuses in a card/tile layout.

Services monitored:
  - CometBFT (blockchain node)
  - Validator (if configured)
  - Earnings (validator payer balance changes)
  - Backend API (includes PostgreSQL sub-check)
  - Indexer
  - Endpoints (Caddy + public chain RPC/REST/gRPC)
  - System (disk, ~/.mirage usage, memory, CPU)
"""

import argparse
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import NamedTuple, Optional

try:
    import psycopg
except Exception:  # pragma: no cover - environment dependent
    psycopg = None
import requests

# Add parent directory for shared imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from deploy.bootstrap_join import TRUST_LOOKBACK


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

# Caddy answers 503 on every route while this file exists, and
# run_maintenance_gate.sh only removes it once the backend answers — which for a
# node joining by state sync is after the entire catch-up. Every 503 seen while
# it exists is the holding page doing its job, not a fault.
MAINTENANCE_FLAG = os.environ.get("MIRAGE_MAINTENANCE_FLAG", "/etc/caddy/.maintenance").strip()

# Block-progress samples. A node replaying history sits on a last block that is
# hours old while CometBFT reports catching_up=false (blocksync exits before the
# consensus reactor has closed the gap), so block age alone cannot tell "catching
# up" from "halted" — and reporting a healthy sync as a stalled chain is what
# made a working install look broken. Height movement between two samples
# separates them, which is the same signal run_maintenance_gate.sh uses.
PROGRESS_SAMPLE_PATH = os.environ.get("MIRAGE_STATUS_PROGRESS_FILE", "/tmp/mirage_status_progress.json").strip()
# Older than this and the node may have restarted in between; too close together
# and a slow replay shows no movement yet. Outside the window, probe live.
PROGRESS_SAMPLE_MAX_AGE_SECS = 120.0
PROGRESS_SAMPLE_MIN_GAP_SECS = 0.8
PROGRESS_PROBE_SLEEP_SECS = 1.5

# Status line + four detail lines. Every card renders exactly this many so the
# grid stays rectangular whatever any single card has to say.
CARD_CONTENT_LINES = 5
CARD_DETAIL_LINES = CARD_CONTENT_LINES - 1

MIRAGE_GRPC_ADDR = os.environ.get("MIRAGE_GRPC_ADDR", "127.0.0.1:9090").strip()
EARNINGS_DAY_SECS = 24 * 60 * 60
EARNINGS_WINDOW_SECS = 30 * EARNINGS_DAY_SECS
EARNINGS_CACHE_SECS = 60
_EARNINGS_HISTORY_CACHE: dict = {"rows": None, "expires": 0.0}


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


_SUPERVISOR_STATES: dict[str, dict] = {}


def refresh_supervisor_states() -> dict[str, dict]:
    """Parse `supervisorctl status` once per dashboard frame."""
    global _SUPERVISOR_STATES
    states: dict[str, dict] = {}
    try:
        result = subprocess.run(
            ["supervisorctl", "-c", "/etc/supervisor/supervisord.conf", "status"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        for line in (result.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            name, state = parts[0], parts[1]
            states[name] = {"state": state, "raw": line.strip()}
    except Exception as e:
        debug_log(f"supervisor: status query failed: {e}")
    _SUPERVISOR_STATES = states
    return states


def supervisor_detail(program: str) -> dict:
    info = _SUPERVISOR_STATES.get(program)
    if not info:
        return {"supervisor_program": program, "supervisor_state": "unknown"}
    return {
        "supervisor_program": program,
        "supervisor_state": info["state"],
        "supervisor_raw": info["raw"],
    }


def format_prepared_upgrade(chain_height: int | None = None) -> str | None:
    prepared = load_prepared_upgrade()
    if not prepared:
        return None
    name = prepared.get("upgrade_name") or prepared.get("plan_name") or "?"
    plan_h = prepared.get("plan_height") or prepared.get("height") or "?"
    digest = str(prepared.get("image") or prepared.get("digest") or "")
    digest_short = digest[-12:] if digest else "?"
    if prepared.get("halt_detected"):
        return f"Prepared {name} @ {plan_h} — halt detected, activating"
    remaining = None
    try:
        remaining = int(plan_h) - int(chain_height)
    except (TypeError, ValueError):
        remaining = None
    if remaining is None:
        return f"Prepared {name} @ height {plan_h}  staged …{digest_short}"
    if remaining > 0:
        return f"Prepared {name} @ {plan_h} ({remaining} blocks remaining)  staged …{digest_short}"
    return f"Prepared {name} @ {plan_h} (at/past halt)  staged …{digest_short}"


def comet_height_from_statuses(statuses: list) -> int | None:
    for status in statuses:
        if status.name != "CometBFT":
            continue
        raw = status.details.get("height")
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None
    return None


def load_prepared_upgrade() -> dict | None:
    path = Path.home() / ".mirage" / "upgrade" / "prepared.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        debug_log(f"upgrade: prepared.json unreadable: {e}")
        return None
    halt_path = Path.home() / ".mirage" / "upgrade" / "halt-detected.txt"
    data["halt_detected"] = halt_path.is_file()
    return data


def format_age_secs(age_secs: float) -> str:
    if age_secs < 60:
        return f"{int(age_secs)}s ago"
    if age_secs < 3600:
        return f"{int(age_secs / 60)}m ago"
    return f"{int(age_secs / 3600)}h ago"


def format_duration_secs(secs: float) -> str:
    """A span of time, for "behind" and "ETA" — never a point in the past."""
    secs = max(0, int(secs))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    hours, minutes = secs // 3600, (secs % 3600) // 60
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"


def maintenance_held() -> bool:
    """True while Caddy is serving the holding page instead of the site."""
    try:
        return os.path.exists(MAINTENANCE_FLAG)
    except OSError as e:
        debug_log(f"maintenance: flag check failed: {e}")
        return False


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


def format_mirage(amount: float) -> str:
    """Compact MIRAGE amount, matching the `5mm` form the cards already use.

    Card content is 34 columns wide, so a grouped integer plus its label runs
    past the edge and gets cut mid-word.
    """
    for unit, scale in (("bn", 1_000_000_000), ("mm", 1_000_000)):
        if amount >= scale:
            value = amount / scale
            text = f"{value:,.1f}" if value < 100 else f"{value:,.0f}"
            return f"{text.removesuffix('.0')}{unit}"
    return f"{amount:,.0f}"


def format_mirage_delta(amount_umirage: int) -> str:
    """Format an earnings delta with useful precision inside a card."""
    amount = abs(int(amount_umirage)) / 1_000_000
    if amount >= 1_000_000:
        return format_mirage(amount)
    if amount >= 1_000:
        return f"{amount:,.0f}"
    if amount >= 100:
        return f"{amount:,.1f}".rstrip("0").rstrip(".")
    if amount >= 1:
        return f"{amount:,.2f}".rstrip("0").rstrip(".")
    return f"{amount:.6f}".rstrip("0").rstrip(".") or "0"


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


class BlockProgress(NamedTuple):
    """Two block observations, and how far apart they were."""

    height: int
    block_age_secs: float
    height_delta: Optional[int]
    age_delta_secs: Optional[float]
    elapsed_secs: Optional[float]


def _read_progress_sample() -> Optional[dict]:
    try:
        with open(PROGRESS_SAMPLE_PATH, encoding="utf-8") as f:
            sample = json.load(f)
        return {
            "height": int(sample["height"]),
            "block_age_secs": float(sample["block_age_secs"]),
            "at": float(sample["at"]),
        }
    except (OSError, ValueError, KeyError, TypeError) as e:
        debug_log(f"progress: no usable previous sample: {e}")
        return None


def _write_progress_sample(height: int, block_age_secs: float, at: float) -> None:
    try:
        tmp = f"{PROGRESS_SAMPLE_PATH}.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"height": height, "block_age_secs": block_age_secs, "at": at}, f)
        os.replace(tmp, PROGRESS_SAMPLE_PATH)
    except OSError as e:
        # Losing the sample only costs a live probe on the next stale frame.
        debug_log(f"progress: sample write failed: {e}")


def _probe_height_and_block_age() -> Optional[tuple[int, float]]:
    try:
        sync_info = (
            requests.get("http://127.0.0.1:26657/status", timeout=3).json().get("result", {}).get("sync_info", {})
        )
        bt = datetime.fromisoformat(str(sync_info["latest_block_time"]).replace("Z", "+00:00"))
        if bt.tzinfo is None:
            bt = bt.replace(tzinfo=timezone.utc)
        return (
            int(sync_info["latest_block_height"]),
            (datetime.now(timezone.utc) - bt).total_seconds(),
        )
    except (requests.RequestException, ValueError, KeyError, TypeError) as e:
        debug_log(f"progress: live probe failed: {e}")
        return None


def observe_block_progress(height: int, block_age_secs: float, probe: bool) -> BlockProgress:
    """Record this block observation and diff it against the previous one.

    The live dashboard refreshes every second, so the previous sample is
    normally fresh enough to diff for free. A one-shot run (the container health
    check) usually has none, so when the block is stale enough to be called a
    fault it pays for a second live probe rather than guessing.
    """
    now = time.time()
    previous = _read_progress_sample()
    _write_progress_sample(height, block_age_secs, now)

    if previous is not None:
        elapsed = now - previous["at"]
        if PROGRESS_SAMPLE_MIN_GAP_SECS <= elapsed <= PROGRESS_SAMPLE_MAX_AGE_SECS:
            return BlockProgress(
                height=height,
                block_age_secs=block_age_secs,
                height_delta=height - previous["height"],
                age_delta_secs=previous["block_age_secs"] - block_age_secs,
                elapsed_secs=elapsed,
            )

    if not probe:
        return BlockProgress(height, block_age_secs, None, None, None)

    time.sleep(PROGRESS_PROBE_SLEEP_SECS)
    probed = _probe_height_and_block_age()
    if probed is None:
        return BlockProgress(height, block_age_secs, None, None, None)

    probed_height, probed_age = probed
    _write_progress_sample(probed_height, probed_age, time.time())
    return BlockProgress(
        height=probed_height,
        block_age_secs=probed_age,
        height_delta=probed_height - height,
        age_delta_secs=block_age_secs - probed_age,
        elapsed_secs=PROGRESS_PROBE_SLEEP_SECS,
    )


def classify_block_progress(progress: BlockProgress) -> tuple[Status, str, Optional[int]]:
    """Verdict for a node whose last block is old. Returns (status, message, eta).

    A chain that has stopped and a chain being replayed from history look
    identical in `latest_block_time`; only the height tells them apart.
    """
    age = progress.block_age_secs
    if age < NODE_LAST_BLOCK_WARN_SECS:
        return (Status.OK, "Running", None)
    # Between the two thresholds the node is near the tip on a slow chain, not
    # thousands of blocks behind, so no catch-up is in question either way.
    if age < NODE_LAST_BLOCK_ERROR_SECS:
        return (Status.WARN, "Slow blocks", None)
    # Height that is not moving is the fault. A regressed height means the node
    # restarted from lower state — a wipe and resync — between the samples, which
    # says nothing about the current block: treat it as no measurement rather
    # than invent a fault from it.
    if not progress.height_delta or progress.height_delta < 0:
        return (Status.ERROR, "No new blocks", None)

    eta = None
    if progress.age_delta_secs and progress.elapsed_secs:
        # Seconds of chain history closed per second of wall clock. Replay is
        # far faster than block production, so this is comfortably above 1 —
        # unless the node is only keeping pace, and then there is no ETA to give.
        closure_rate = progress.age_delta_secs / progress.elapsed_secs
        if closure_rate > 0:
            eta = int(age / closure_rate)
    return (Status.WARN, "Catching up", eta)


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
        state_sync_target = None
        state_sync_starting = False
        try:
            with (Path.home() / ".mirage" / "node" / "config" / "config.toml").open("rb") as config_file:
                state_sync = tomllib.load(config_file)["statesync"]
            if state_sync["enable"] and (catching_up or int(height) == 0):
                state_sync_target = int(state_sync["trust_height"]) + TRUST_LOOKBACK
                state_sync_starting = int(height) == 0
        except (FileNotFoundError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as e:
            debug_log(f"node: state-sync config unavailable: {e}")
        syncing = catching_up or state_sync_starting

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
            "syncing": syncing,
            "sync_target": state_sync_target,
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

        if syncing:
            status = Status.WARN
            message = "State sync starting" if state_sync_starting else "Syncing"

        # Even if CometBFT reports catching_up=false, a stale last block is still
        # unhealthy — unless this node is replaying history to reach the tip, or the
        # chain is halted for a software upgrade. Both are expected.
        if block_age_secs is not None and not syncing:
            progress = observe_block_progress(
                int(height) if str(height).isdigit() else 0,
                block_age_secs,
                probe=block_age_secs >= NODE_LAST_BLOCK_ERROR_SECS,
            )
            # The probe path re-reads /status, so prefer its fresher numbers.
            height = progress.height or height
            block_age_secs = progress.block_age_secs
            block_age = format_age_secs(block_age_secs)
            details.update({"height": height, "block_age": block_age, "block_age_secs": block_age_secs})

            status, message, eta_secs = classify_block_progress(progress)
            if message == "Catching up":
                details["behind_secs"] = int(block_age_secs)
                details["eta_secs"] = eta_secs
                details["syncing"] = True
            elif status == Status.ERROR:
                # During a coordinated upgrade, every validator stops at the
                # upgrade height and no new blocks are produced until 2/3+ restart
                # with the new binary. That is a normal, healthy state.
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
                                details["upgrade_plan"] = plan.get("name")
                                details["upgrade_height"] = plan_height
                                status = Status.WARN
                                message = f"Upgrade halt ({plan.get('name')})"
                except Exception as e:
                    debug_log(f"node: upgrade plan query failed: {e}")

        if peers == 0 and status == Status.OK:
            status = Status.ERROR
            message = "No peers"

        if rpc_health_ok is False and status == Status.OK:
            status = Status.WARN
            message = "RPC unhealthy"

        debug_log(
            "node: "
            f"height={height} catching_up={catching_up} state_sync_starting={state_sync_starting} peers={peers} "
            f"block_age_secs={block_age_secs} rpc_health_ok={rpc_health_ok} rpc_health_ms={rpc_health_ms} "
            f"behind_secs={details.get('behind_secs')} eta_secs={details.get('eta_secs')} "
            f"status={status.value} message={message}"
        )

        details.update(supervisor_detail("node"))
        return ServiceStatus(name="CometBFT", status=status, message=message, details=details)
    except requests.exceptions.ConnectionError:
        details = supervisor_detail("node")
        state = details.get("supervisor_state")
        message = f"Supervisor {state}" if state not in (None, "unknown", "RUNNING") else "Not reachable"
        return ServiceStatus(name="CometBFT", status=Status.ERROR, message=message, details=details)
    except Exception as e:
        details = supervisor_detail("node")
        return ServiceStatus(name="CometBFT", status=Status.ERROR, message=str(e)[:30], details=details)


def classify_retention(retained: int, effective: int, catching_up: bool, mismatch: bool) -> tuple[Status, str]:
    """Judge the block window against the configured one.

    A window shorter than configured is not a fault. Pruning only trims once
    the store passes min-retain-blocks, so a short window means it has not
    filled yet — a node that just state-synced or was recovered starts at its
    snapshot base and grows one block at a time. A window *longer* than
    configured is the real problem: pruning is not reclaiming and the disk
    fills.
    """
    tolerance = 100
    if retained > effective + tolerance:
        return Status.WARN, "Above expected"
    if mismatch:
        return Status.WARN, "Config mismatch"
    if retained < max(0, effective - tolerance):
        return Status.OK, "Syncing" if catching_up else "Building up"
    return Status.OK, "Within range"


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

    # Blockstore retention is driven by min-retain-blocks (capped by evidence max age).
    # Snapshot retention is independent — it only affects state-sync availability.
    effective = None
    for candidate in (min_retain_blocks, evidence_max_age_blocks):
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

    if effective is None or retained is None:
        return ServiceStatus(name="Retention", status=Status.WARN, message="Config missing", details=details)

    status, message = classify_retention(retained, effective, catching_up, mismatch)
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


def _load_min_liquid_mirage() -> Optional[float]:
    """Liquid floor in MIRAGE from the signed network manifest. None if absent."""
    candidates = [
        os.path.join(os.path.expanduser("~"), ".mirage", "env", "network-manifest.json"),
        "/opt/mirage/release/network.json",
    ]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            um = int(data["min_liquid_umirage"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
            debug_log(f"validator: cannot read min_liquid_umirage from {path}: {e}")
            continue
        if um >= 1_000_000:
            return um / 1_000_000
    return None


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
        found_on_chain = False
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
                        found_on_chain = True
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

        # The manifest floor is the number the chain-side rules are written
        # against; SERVER_BALANCE_ERROR only covers a host with no manifest.
        min_liquid = _load_min_liquid_mirage()
        floor = min_liquid if min_liquid is not None else float(SERVER_BALANCE_ERROR)

        base_details = {
            "configured": True,
            "moniker": moniker,
            "tokens": tokens,
            "power_pct": power_pct,
            "voting_power": voting_power,
            "balance_mirage": balance_mirage,
            "min_liquid_mirage": floor,
            "registered": found_on_chain,
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
            if balance_mirage is not None and balance_mirage < floor:
                return ServiceStatus(
                    name="Validator",
                    status=Status.ERROR,
                    message="Liquid below floor",
                    details=active_details,
                )
            if balance_mirage is not None and balance_mirage < SERVER_BALANCE_WARN:
                return ServiceStatus(
                    name="Validator", status=Status.WARN, message="Balance low", details=active_details
                )
            return ServiceStatus(name="Validator", status=Status.OK, message="Active", details=active_details)
        if found_on_chain:
            return ServiceStatus(
                name="Validator",
                status=Status.ERROR,
                message="Registered, not in active set",
                details={**base_details, "active": False},
            )
        return ServiceStatus(
            name="Validator",
            status=Status.WARN,
            message="Not registered",
            details={**base_details, "active": False, "enrollment": "pending"},
        )

    except Exception as e:
        return ServiceStatus(name="Validator", status=Status.ERROR, message=str(e)[:30], details={"configured": True})


def check_postgres() -> ServiceStatus:
    """Check PostgreSQL database status."""
    db_url = os.environ.get(
        "INDEXER_DB_URL", "postgresql://mirage_indexer:mirage_indexer@127.0.0.1:5432/mirage_indexer"
    )

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
    maintenance = maintenance_held()
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
                    "maintenance": maintenance,
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
        details = supervisor_detail("backend")
        details["maintenance"] = maintenance
        state = details.get("supervisor_state")
        message = f"Supervisor {state}" if state not in (None, "unknown", "RUNNING") else "Not reachable"
        backend = ServiceStatus(name="Backend", status=Status.ERROR, message=message, details=details)
    except requests.exceptions.Timeout:
        # A backend that accepts the connection and then never answers: a Gunicorn
        # worker stuck on its first query looks exactly like this from outside.
        # This used to surface as a clipped exception repr — "HTTPConnectionPool(host='"
        # — which tells an operator nothing at all.
        backend = ServiceStatus(
            name="Backend",
            status=Status.ERROR,
            message="No response (timeout)",
            details={**supervisor_detail("backend"), "maintenance": maintenance},
        )
    except Exception as e:
        debug_log(f"backend: probe failed: {e}")
        backend = ServiceStatus(
            name="Backend",
            status=Status.ERROR,
            message=truncate(type(e).__name__, 25),
            details={**supervisor_detail("backend"), "maintenance": maintenance, "error": str(e)[:120]},
        )

    pg = check_postgres()
    backend.details["pg_status"] = pg.status.value
    backend.details["pg_message"] = pg.message
    if pg.details.get("size"):
        backend.details["pg_size"] = pg.details["size"]
    if pg.status == Status.ERROR and backend.status == Status.OK:
        backend.status = Status.WARN
        backend.message = f"Running (DB: {pg.message})"
    backend.details.update(supervisor_detail("backend"))
    backend.details["postgres_supervisor_state"] = supervisor_detail("postgres").get("supervisor_state")
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
    db_url = os.environ.get(
        "INDEXER_DB_URL", "postgresql://mirage_indexer:mirage_indexer@127.0.0.1:5432/mirage_indexer"
    )

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

    indexer_sv = supervisor_detail("indexer")
    if not process_running:
        state = indexer_sv.get("supervisor_state")
        message = f"Supervisor {state}" if state not in (None, "unknown", "RUNNING") else "Not running"
        return ServiceStatus(
            name="Indexer",
            status=Status.ERROR,
            message=message,
            details={"running": False, **indexer_sv},
        )

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
            **indexer_sv,
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


def summarize_earnings_history(rows: list[tuple], now: int) -> dict:
    """Classify sampled validator asset changes without counting stake as spent."""
    cutoff_24h = now - EARNINGS_DAY_SECS
    cutoff_30d = now - EARNINGS_WINDOW_SECS
    earned_24h = 0
    staked_24h = 0
    spent_24h = 0
    earned_30d = 0

    for previous, current in zip(rows, rows[1:]):
        current_ts = int(current[1])
        asset_delta = (int(current[2]) + int(current[3])) - (int(previous[2]) + int(previous[3]))
        staked_delta = int(current[3]) - int(previous[3])
        if current_ts >= cutoff_30d and asset_delta > 0:
            earned_30d += asset_delta
        if current_ts >= cutoff_24h:
            if asset_delta > 0:
                earned_24h += asset_delta
            elif asset_delta < 0:
                spent_24h += -asset_delta
            if staked_delta > 0:
                staked_24h += staked_delta

    in_window = [int(row[1]) for row in rows if int(row[1]) >= cutoff_30d]
    coverage_secs = 0
    if len(in_window) >= 2:
        coverage_secs = max(0, min(now, in_window[-1]) - in_window[0])

    return {
        "earned_24h": earned_24h,
        "staked_24h": staked_24h,
        "spent_24h": spent_24h,
        "earned_30d": earned_30d,
        "coverage_secs": coverage_secs,
        "sample_count": len(in_window),
    }


def check_earnings() -> ServiceStatus:
    """Summarize validator payer earnings, staking, and spending."""
    if psycopg is None:
        return ServiceStatus(
            name="Earnings", status=Status.ERROR, message="psycopg missing", details={"sample_count": 0}
        )

    db_url = os.environ.get("INDEXER_DB_RO_URL", "").strip()
    if not db_url:
        debug_log("earnings: INDEXER_DB_RO_URL missing")
        return ServiceStatus(
            name="Earnings", status=Status.ERROR, message="DB URL missing", details={"sample_count": 0}
        )

    now = int(time.time())
    cutoff_30d = now - EARNINGS_WINDOW_SECS
    rows = _EARNINGS_HISTORY_CACHE["rows"]
    if rows is None or time.monotonic() >= _EARNINGS_HISTORY_CACHE["expires"]:
        try:
            with psycopg.connect(db_url, connect_timeout=3) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT height, created_at, node_balance, node_staked
                        FROM supply_history
                        WHERE node_balance IS NOT NULL
                          AND node_staked IS NOT NULL
                          AND created_at >= %s
                        ORDER BY height ASC
                        """,
                        (cutoff_30d,),
                    )
                    rows = cur.fetchall()
        except Exception as e:
            debug_log(f"earnings: supply_history query failed: {e}")
            # This card is the first place a missing read-only grant shows, and
            # it is the whole reason a fresh install can sit on the maintenance
            # page. "History unavailable" sent the operator looking at earnings.
            denied = isinstance(e, psycopg.errors.InsufficientPrivilege)
            return ServiceStatus(
                name="Earnings",
                status=Status.ERROR,
                message="DB grant missing" if denied else "History unavailable",
                details={"error": str(e)[:120], "sample_count": 0},
            )
        _EARNINGS_HISTORY_CACHE["rows"] = rows
        _EARNINGS_HISTORY_CACHE["expires"] = time.monotonic() + EARNINGS_CACHE_SECS

    details = summarize_earnings_history(rows, now)
    samples = details["sample_count"]
    if samples < 2:
        debug_log(f"earnings: collecting history samples={samples}")
        return ServiceStatus(name="Earnings", status=Status.OK, message="Collecting history", details=details)

    coverage = details["coverage_secs"]
    if coverage >= EARNINGS_WINDOW_SECS - (2 * 60 * 60):
        message = "30d tracked"
    elif coverage >= EARNINGS_DAY_SECS:
        message = f"Collecting · {coverage // EARNINGS_DAY_SECS}d"
    elif coverage >= 60 * 60:
        message = f"Collecting · {coverage // (60 * 60)}h"
    else:
        message = f"Collecting · {max(1, coverage // 60)}m"

    debug_log(
        "earnings: "
        f"samples={samples} coverage={coverage}s earned_24h={details['earned_24h']} "
        f"staked_24h={details['staked_24h']} spent_24h={details['spent_24h']} "
        f"earned_30d={details['earned_30d']}"
    )
    return ServiceStatus(name="Earnings", status=Status.OK, message=message, details=details)


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
        pow_base_bits = int(
            diff_data.get(
                "min_difficulty",
                diff_data.get("minDifficulty", diff_data.get("pow_base_bits", diff_data.get("powBaseBits", 0))),
            )
        )
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

    maintenance = maintenance_held()
    details = {
        "caddy": True,
        "configured": True,
        "host": host,
        "https": use_https,
        "block_height": block_height,
        "endpoints": results,
        "maintenance": maintenance,
    }

    if all_ok:
        return ServiceStatus(
            name="Endpoints",
            status=Status.OK,
            message=f"All OK @ {block_height:,}" if block_height else "All OK",
            details=details,
        )
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
    db_url = os.environ.get(
        "INDEXER_DB_URL", "postgresql://mirage_indexer:mirage_indexer@127.0.0.1:5432/mirage_indexer"
    )

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


# System storage thresholds (in GB)
SYSTEM_STORAGE_WARN_GB = float(os.environ.get("MIRAGE_STORAGE_WARN_GB", "5"))
SYSTEM_STORAGE_ERROR_GB = float(os.environ.get("MIRAGE_STORAGE_ERROR_GB", "1"))

# Memory thresholds (percentage used)
SYSTEM_MEMORY_WARN_PCT = float(os.environ.get("MIRAGE_MEMORY_WARN_PCT", "85"))
SYSTEM_MEMORY_ERROR_PCT = float(os.environ.get("MIRAGE_MEMORY_ERROR_PCT", "95"))

# Load average thresholds (per CPU core)
SYSTEM_LOAD_WARN_PER_CORE = float(os.environ.get("MIRAGE_LOAD_WARN_PER_CORE", "0.8"))
SYSTEM_LOAD_ERROR_PER_CORE = float(os.environ.get("MIRAGE_LOAD_ERROR_PER_CORE", "1.5"))


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


def _dashboard_versions() -> str:
    """Binary + frontend release versions for the header (highest-signal identity)."""
    binary = "unknown"
    try:
        out = subprocess.check_output(
            [get_miraged_bin(), "version"],
            stderr=subprocess.STDOUT,
            timeout=3,
            text=True,
        )
        for line in reversed(out.splitlines()):
            token = line.strip()
            if token:
                binary = token
                break
    except Exception as e:
        debug_log(f"dashboard: miraged version failed: {e}")

    frontend = "unknown"
    for path in (
        "/opt/mirage/web/frontend/build/version.txt",
        "/opt/mirage/web/frontend/public/version.txt",
        str(Path(__file__).resolve().parents[1] / "web" / "frontend" / "public" / "version.txt"),
    ):
        try:
            if os.path.isfile(path):
                frontend = open(path, encoding="utf-8").read().strip() or "unknown"
                break
        except Exception as e:
            debug_log(f"dashboard: version.txt read failed ({path}): {e}")

    return f"binary {binary}  ·  frontend {frontend}"


def render_header(width: int, chain_height: int | None = None) -> list[str]:
    """Render the dashboard header."""
    lines = []

    # ASCII art title
    title_art = [
        f"{Colors.BRIGHT_CYAN}╔╦╗╦╦═╗╔═╗╔═╗╔═╗{Colors.RESET}",
        f"{Colors.BRIGHT_CYAN}║║║║╠╦╝╠═╣║ ╦║╣ {Colors.RESET}",
        f"{Colors.BRIGHT_CYAN}╩ ╩╩╩╚═╩ ╩╚═╝╚═╝{Colors.RESET}",
    ]

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    versions = _dashboard_versions()

    lines.append("")
    for art_line in title_art:
        lines.append(center_text(art_line, width))
    lines.append(center_text(f"{Colors.DIM}System Status Dashboard{Colors.RESET}", width))
    lines.append(center_text(f"{Colors.BRIGHT_WHITE}{versions}{Colors.RESET}", width))
    lines.append(center_text(f"{Colors.DIM}{timestamp}{Colors.RESET}", width))
    upgrade_text = format_prepared_upgrade(chain_height)
    if upgrade_text:
        if "halt detected" in upgrade_text:
            colored = f"{Colors.BRIGHT_YELLOW}{upgrade_text}{Colors.RESET}"
        else:
            colored = f"{Colors.BRIGHT_CYAN}{upgrade_text}{Colors.RESET}"
        lines.append(center_text(colored, width))
    lines.append("")

    return lines


def format_sync_banner(statuses: list[ServiceStatus]) -> Optional[str]:
    """One line explaining a catch-up, or None when the node is at the tip.

    Counts alone ("2 WARN") do not tell an operator whether a fresh install is
    working or broken, and every degraded card during a catch-up has the same
    single cause. Say it once, at the top.
    """
    node = next((s for s in statuses if s.name == "CometBFT"), None)
    if node is None or not node.details.get("behind_secs"):
        return None

    parts = [f"CATCHING UP — {format_duration_secs(node.details['behind_secs'])} behind"]
    eta_secs = node.details.get("eta_secs")
    if eta_secs:
        parts.append(f"caught up in ~{format_duration_secs(eta_secs)}")
    if any(s.details.get("maintenance") for s in statuses):
        parts.append("public endpoints held until then")
    return "  ·  ".join(parts)


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

    lines = [center_text(summary, width)]
    banner = format_sync_banner(statuses)
    if banner:
        lines.append(center_text(f"{Colors.BRIGHT_YELLOW}{truncate(banner, width)}{Colors.RESET}", width))
    lines.append("")
    return lines


def format_card_content(status: ServiceStatus) -> list[str]:
    """Format card content based on service status and details."""
    lines = []
    details = status.details

    color = STATUS_COLORS[status.status]
    lines.append(f"{color}{status.message}{Colors.RESET}")

    bullet = f"{Colors.DIM}-{Colors.RESET} "
    sv = details.get("supervisor_state")
    if sv and sv != "RUNNING":
        lines.append(f"{bullet}{Colors.DIM}Supervisor:{Colors.RESET} {Colors.BRIGHT_RED}{sv}{Colors.RESET}")

    if status.name == "CometBFT":
        if details.get("sync_target") is not None:
            height = int(details["height"])
            target = int(details["sync_target"])
            percent = min(100.0, height * 100 / target)
            lines.append(f"{bullet}{Colors.DIM}Sync:{Colors.RESET} " f"{height:,} / ~{target:,} ({percent:.1f}%)")
        elif "height" in details:
            try:
                h = int(details["height"])
                lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {h:,}")
            except (ValueError, TypeError):
                lines.append(f"{bullet}{Colors.DIM}Height:{Colors.RESET} {details['height']}")
        if "peers" in details:
            peers = details["peers"]
            peer_color = Colors.BRIGHT_GREEN if peers > 0 else Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}Peers:{Colors.RESET} {peer_color}{peers}{Colors.RESET}")
        if details.get("behind_secs"):
            # A replaying node's last block is hours old by definition, so the age
            # of it is not the useful number — the distance left to cover is.
            behind = format_duration_secs(details["behind_secs"])
            lines.append(f"{bullet}{Colors.DIM}Behind:{Colors.RESET} {Colors.BRIGHT_YELLOW}{behind}{Colors.RESET}")
            eta_secs = details.get("eta_secs")
            eta = f"~{format_duration_secs(eta_secs)}" if eta_secs else "unknown"
            lines.append(f"{bullet}{Colors.DIM}Caught up in:{Colors.RESET} {eta}")
        elif details.get("block_age"):
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
        # "blocks" does not fit beside two grouped counts, and the card is
        # already named for what it retains.
        if retained is not None and expected is not None:
            lines.append(f"{bullet}{Colors.DIM}Retained:{Colors.RESET} {retained:,} / {expected:,}")
        elif retained is not None:
            lines.append(f"{bullet}{Colors.DIM}Retained:{Colors.RESET} {retained:,}")
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
            lines.append(f"{bullet}{Colors.DIM}Stake:{Colors.RESET} {format_mirage(details['tokens'])} MIRAGE")
        if details.get("power_pct") is not None:
            pct = details["power_pct"]
            lines.append(f"{bullet}{Colors.DIM}Power:{Colors.RESET} {pct:.2f}%")
        balance_mirage = details.get("balance_mirage")
        if balance_mirage is not None:
            min_liquid = details.get("min_liquid_mirage")
            if min_liquid is not None and balance_mirage < min_liquid:
                bal_color = Colors.BRIGHT_RED
            elif balance_mirage < SERVER_BALANCE_WARN:
                bal_color = Colors.BRIGHT_YELLOW
            else:
                bal_color = Colors.BRIGHT_GREEN
            # The floor itself is not shown: the colour says whether the balance
            # is under it, and the card message names it when it is.
            lines.append(
                f"{bullet}{Colors.DIM}Liquid:{Colors.RESET} "
                f"{bal_color}{format_mirage(balance_mirage)} MIRAGE{Colors.RESET}"
            )
        if details.get("enrollment") == "pending":
            lines.append(f"{bullet}{Colors.BRIGHT_YELLOW}Enrollment pending{Colors.RESET}")
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
            if code < 400:
                code_color = Colors.BRIGHT_GREEN
            elif details.get("maintenance"):
                code_color = Colors.BRIGHT_YELLOW
            else:
                code_color = Colors.BRIGHT_RED
            lines.append(f"{bullet}{Colors.DIM}HTTP:{Colors.RESET} {code_color}{code}{Colors.RESET}")
        pg_st = details.get("pg_status")
        if pg_st:
            pg_color = (
                Colors.BRIGHT_GREEN
                if pg_st == "ok"
                else Colors.BRIGHT_RED if pg_st == "error" else Colors.BRIGHT_YELLOW
            )
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
                lines.append(
                    f"{bullet}{Colors.DIM}Pool:{Colors.RESET} {format_mirage(pool_balance / 1_000_000)} MIRAGE"
                )
        else:
            lines.append(f"{bullet}{Colors.DIM}Payouts:{Colors.RESET} OFF")

    elif status.name == "Earnings":
        if details.get("sample_count", 0) >= 2:
            earned_24h = int(details["earned_24h"])
            staked_24h = int(details["staked_24h"])
            spent_24h = int(details["spent_24h"])
            earned_30d = int(details["earned_30d"])
            lines.append(
                f"{bullet}{Colors.DIM}Earned 24h:{Colors.RESET} "
                f"{Colors.BRIGHT_GREEN}+{format_mirage_delta(earned_24h)} MIRAGE{Colors.RESET}"
            )
            lines.append(
                f"{bullet}{Colors.DIM}Staked 24h:{Colors.RESET} "
                f"{Colors.BRIGHT_CYAN}+{format_mirage_delta(staked_24h)} MIRAGE{Colors.RESET}"
            )
            lines.append(
                # "Spent" is a letter shorter than "Earned" and "Staked", so the
                # extra space keeps all four amounts in one column.
                f"{bullet}{Colors.DIM}Spent 24h:{Colors.RESET}  "
                f"{Colors.BRIGHT_RED}-{format_mirage_delta(spent_24h)} MIRAGE{Colors.RESET}"
            )
            lines.append(
                f"{bullet}{Colors.DIM}Earned 30d:{Colors.RESET} "
                f"{Colors.BRIGHT_GREEN}+{format_mirage_delta(earned_30d)} MIRAGE{Colors.RESET}"
            )
        else:
            lines.append(f"{bullet}{Colors.DIM}Waiting for balance samples{Colors.RESET}")

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
            # Largest first, and only as many as a card holds: the smallest
            # directories are the least interesting and were the ones making this
            # card taller than every other.
            sorted_dirs = sorted(breakdown.items(), key=lambda x: -x[1])
            for name, sz in sorted_dirs[:CARD_DETAIL_LINES]:
                lines.append(f"{bullet}{Colors.DIM}{name}:{Colors.RESET} {_format_bytes(sz)}")

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

    # Every card is exactly this tall: the status line plus four details. The
    # floor stops a short card from collapsing; the ceiling stops a long one from
    # stretching its whole row and breaking the grid, which is what one extra
    # ~/.mirage subdirectory used to do to Disk Usage.
    while len(lines) < CARD_CONTENT_LINES:
        lines.append("")

    return lines[:CARD_CONTENT_LINES]


def explain_sync_hold(statuses: list[ServiceStatus]) -> list[ServiceStatus]:
    """Recast "the site is down" as "the site is waiting", but only when true.

    While the holding page is up, Caddy answers 503 on every route and the
    backend refuses to serve state it knows is stale, so a node that is still
    catching up reports the backend and every public endpoint as failures. Those
    are one expected consequence of one cause, and saying so is the difference
    between a working install and an install that looks broken.

    The excuse has to expire, though. A node sitting at the tip with a backend
    that still will not answer is genuinely broken — that is how a fresh install
    whose read-only DB grants never landed presents — so the downgrade requires
    something to actually still be behind.
    """
    if not any(s.details.get("maintenance") for s in statuses):
        return statuses

    node = next((s for s in statuses if s.name == "CometBFT"), None)
    indexer = next((s for s in statuses if s.name == "Indexer"), None)
    chain_behind = bool(node and node.details.get("behind_secs"))
    # The backend reads chain state from the indexer, so it stays 503 until the
    # indexer has caught up too, well after CometBFT reaches the tip.
    indexer_behind = bool(indexer and (indexer.details.get("lag") or 0) > 100)
    if not (chain_behind or indexer_behind):
        return statuses

    for status in statuses:
        if status.status != Status.ERROR:
            continue
        if status.name == "Backend":
            status.status = Status.WARN
            status.message = "Waiting for chain sync"
        elif status.name == "Endpoints":
            status.status = Status.WARN
            status.message = "Holding page (syncing)"
    return statuses


def collect_statuses() -> list[ServiceStatus]:
    refresh_supervisor_states()
    return explain_sync_hold(
        [
            check_node(),
            check_retention(),
            check_validator(),
            check_earnings(),
            check_backend(),
            check_rewards(),
            check_indexer(),
            check_endpoints(),
            check_disk_usage(),
            check_system(),
        ]
    )


def display_statuses(statuses: list[ServiceStatus]) -> list[ServiceStatus]:
    return [
        s
        for s in statuses
        if s.status != Status.UNKNOWN
        or s.name
        in ("CometBFT", "Retention", "Earnings", "Backend", "Rewards", "Indexer", "Endpoints", "Disk Usage", "System")
    ]


def render_compact_dashboard(
    statuses: list[ServiceStatus],
    width: int,
    height: int,
    refresh_secs: int,
    chain_height: int | None = None,
    pin_bottom: bool = False,
) -> list[str]:
    """Single-column layout for 80x24 and other short/narrow terminals."""
    output = []
    output.append(f"{Colors.BOLD}MIRAGE{Colors.RESET}  {_dashboard_versions()}")
    output.append(time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()))
    upgrade_text = format_prepared_upgrade(chain_height)
    if upgrade_text:
        output.append(truncate(upgrade_text, width))
    ok_count = sum(1 for s in statuses if s.status == Status.OK)
    warn_count = sum(1 for s in statuses if s.status == Status.WARN)
    error_count = sum(1 for s in statuses if s.status == Status.ERROR)
    output.append(
        f"{Colors.BRIGHT_GREEN}{ok_count} OK{Colors.RESET}  "
        f"{Colors.BRIGHT_YELLOW}{warn_count} WARN{Colors.RESET}  "
        f"{Colors.BRIGHT_RED}{error_count} ERR{Colors.RESET}"
    )
    banner = format_sync_banner(statuses)
    if banner:
        output.append(truncate(f"{Colors.BRIGHT_YELLOW}{banner}{Colors.RESET}", width))
    output.append("-" * min(width, 80))
    for status in statuses:
        icon = ICONS.get(status.status, "?")
        sv = status.details.get("supervisor_state")
        sv_bit = f"  [{sv}]" if sv and sv != "RUNNING" else ""
        line = f"{icon} {status.name:<12} {status.message}{sv_bit}"
        output.append(truncate(line, width))
        extra = []
        if status.name == "CometBFT" and status.details.get("height") is not None:
            extra.append(f"h={status.details.get('height')}")
            if status.details.get("peers") is not None:
                extra.append(f"peers={status.details['peers']}")
            if status.details.get("behind_secs"):
                extra.append(f"behind={format_duration_secs(status.details['behind_secs'])}")
        if status.name == "Indexer" and status.details.get("lag") is not None:
            extra.append(f"lag={status.details['lag']}")
        if extra:
            output.append(truncate(f"    {Colors.DIM}{' '.join(str(x) for x in extra)}{Colors.RESET}", width))
        if status.name == "Earnings" and status.details.get("sample_count", 0) >= 2:
            earned_24h = int(status.details["earned_24h"])
            staked_24h = int(status.details["staked_24h"])
            spent_24h = int(status.details["spent_24h"])
            earned_30d = int(status.details["earned_30d"])
            output.append(
                truncate(
                    f"    24h  +{format_mirage_delta(earned_24h)} earned  " f"-{format_mirage_delta(spent_24h)} spent",
                    width,
                )
            )
            output.append(
                truncate(
                    f"    24h  +{format_mirage_delta(staked_24h)} staked  "
                    f"30d +{format_mirage_delta(earned_30d)} earned",
                    width,
                )
            )
    trailer = render_trailer(width, f"Ctrl+C exits  refresh {refresh_secs}s", center=False)
    # Keep the compact view inside the terminal height.
    body_rows = max(8, height - len(trailer))
    output = fit_rows(output, body_rows)
    if pin_bottom:
        while len(output) < body_rows:
            output.append("")
    else:
        output.append("")
    output.extend(trailer)
    return output


def render_dashboard(refresh_secs: int, pin_bottom: bool = False) -> list[str]:
    """Build one full frame. Returns lines; the caller owns painting."""
    term_width, term_height = get_terminal_size()
    statuses = display_statuses(collect_statuses())
    chain_height = comet_height_from_statuses(statuses)

    if term_width < 100 or term_height < 28:
        return render_compact_dashboard(
            statuses, term_width, term_height, refresh_secs, chain_height, pin_bottom=pin_bottom
        )

    # Render header
    output = render_header(term_width, chain_height)

    # Render summary (only count displayed services)
    output.extend(render_summary(statuses, term_width))

    # Calculate card layout
    card_width = 38
    gap = 2
    cards_per_row = max(1, (term_width + gap) // (card_width + gap))

    # Create cards
    cards = []
    for status in statuses:
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

    trailer = render_trailer(
        term_width, f"{Colors.DIM}Press Ctrl+C to exit • Auto-refresh: {refresh_secs}s{Colors.RESET}", center=True
    )
    if sum(1 for line in output if line) + len(trailer) > term_height:
        return render_compact_dashboard(
            statuses, term_width, term_height, refresh_secs, chain_height, pin_bottom=pin_bottom
        )
    # A frame taller than the terminal scrolls, which breaks in-place repainting
    # and brings the flicker back.
    body_rows = term_height - len(trailer)
    output = fit_rows(output, body_rows)
    if pin_bottom:
        while len(output) < body_rows:
            output.append("")
    else:
        output.append("")
    output.extend(trailer)
    return output


def node_public_url() -> str:
    """Where operators reach this node: its domain, else its public IP.

    Both values are written to node.env at install and exported into the
    container, so this costs nothing on the refresh path.
    """
    domain = os.environ.get("DOMAIN", "").strip()
    if domain:
        for scheme in ("https://", "http://"):
            if domain.startswith(scheme):
                domain = domain[len(scheme) :]
        return f"https://{domain.rstrip('/')}"
    external = os.environ.get("EXTERNAL_ADDRESS", "").strip()
    if external:
        if external.startswith("tcp://"):
            external = external[len("tcp://") :]
        # Drop the P2P port; IPv6 literals arrive bracketed.
        host = external.rsplit(":", 1)[0]
        if host:
            return f"http://{host}"
    return ""


def fit_rows(lines: list[str], rows: int) -> list[str]:
    """Shrink a frame to `rows`, giving up blank spacing before content.

    Cutting from the end clips a card's bottom border, so drop the decorative
    blank rows first, closest to the bottom first.
    """
    out = list(lines)
    while len(out) > rows:
        blank = next((i for i in range(len(out) - 1, -1, -1) if out[i] == ""), None)
        if blank is None:
            break
        out.pop(blank)
    del out[rows:]
    return out


def render_trailer(width: int, footer: str, center: bool) -> list[str]:
    """The two rows pinned to the bottom: this node's address, then the footer."""
    url = node_public_url()
    address = url if url else f"{Colors.BRIGHT_YELLOW}address unknown{Colors.RESET}"
    if center:
        return [center_text(address, width), center_text(footer, width)]
    return [truncate(address, width), truncate(footer, width)]


def paint(lines: list[str]) -> None:
    """Overwrite the previous frame in place, in a single write.

    Erasing the screen before collecting the next frame leaves the terminal
    blank for as long as collection takes, which reads as a black flash once a
    second. Each row is overwritten and erased to its end instead, and the
    write is wrapped in synchronized-output so terminals that support it show
    no intermediate state.
    """
    body = "\033[K\r\n".join(lines) + "\033[K"
    sys.stdout.write("\033[?2026h\033[H" + body + "\033[J\033[?2026l")
    sys.stdout.flush()


def create_session_pid_file(raw_path: str) -> Optional[Path]:
    """Publish this process for the host wrapper to clean up on disconnect."""
    if not raw_path:
        return None
    path = Path(raw_path)
    if path.parent != Path("/tmp") or not re.fullmatch(r"mirage-status-\d+-\d+-\d+\.pid", path.name):
        raise RuntimeError(f"invalid MIRAGE_STATUS_PID_FILE: {raw_path!r}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as pid_file:
        pid_file.write(f"{os.getpid()}\n")
    return path


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
    refresh_supervisor_states()
    all_statuses = explain_sync_hold(
        [
            check_node(),
            check_validator(),
            check_backend(),
            check_indexer(),
            check_endpoints(),
        ]
    )

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
        default=1,
        help="Live refresh interval in seconds (positive integer, default: 1)",
    )
    args = parser.parse_args()

    if args.json and args.once:
        parser.error("--json and --once cannot be combined")
    if args.interval is not None and args.interval < 1:
        parser.error("--interval must be a positive integer")

    if args.json:
        required = [s.strip() for s in args.require.split(",") if s.strip()]
        result = run_health_check_json(required)
        prepared = load_prepared_upgrade()
        if prepared:
            result["prepared_upgrade"] = prepared
        print(json.dumps(result, indent=2))
        sys.exit(0 if result["healthy"] else 1)

    interactive = sys.stdout.isatty() and not args.once
    refresh_requested = threading.Event()

    def request_refresh(_signum=None, _frame=None):
        refresh_requested.set()

    def terminate(signum, _frame=None):
        # Default SIGTERM/SIGHUP death skips the restore and leaves the
        # operator on the alternate screen with no cursor.
        raise SystemExit(128 + signum)

    if interactive:
        signal.signal(signal.SIGWINCH, request_refresh)
        signal.signal(signal.SIGTERM, terminate)
        signal.signal(signal.SIGHUP, terminate)

    entered_alt = False
    hide_cursor = False
    session_pid_file: Optional[Path] = None

    def restore_terminal():
        nonlocal entered_alt, hide_cursor
        if hide_cursor:
            sys.stdout.write("\033[?25h")
            hide_cursor = False
        if entered_alt:
            sys.stdout.write("\033[?1049l")
            entered_alt = False
        sys.stdout.flush()

    try:
        if interactive:
            session_pid_file = create_session_pid_file(os.environ.get("MIRAGE_STATUS_PID_FILE", "").strip())
            sys.stdout.write("\033[?1049h\033[?25l\033[2J")
            sys.stdout.flush()
            entered_alt = True
            hide_cursor = True
        while True:
            frame = render_dashboard(refresh_secs=args.interval, pin_bottom=interactive)
            if interactive:
                paint(frame)
            else:
                print("\n".join(frame), flush=True)
            if args.once:
                return
            refresh_requested.wait(args.interval)
            refresh_requested.clear()
    except KeyboardInterrupt:
        restore_terminal()
        sys.exit(130)
    finally:
        try:
            restore_terminal()
        finally:
            if session_pid_file is not None:
                session_pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
