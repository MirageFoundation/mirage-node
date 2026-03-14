#!/usr/bin/env python3
"""Hot-swap state-sync inside the Docker container.

Pre-syncs into a parallel home directory, then swaps data with minimal downtime.
Automatically rolls back if the post-swap health check fails.

Usage:
    /opt/mirage/scripts/hot_swap_statesync.py --source <host[:port]> [--cleanup]

Required:
    --source    RPC host to sync from (e.g. mirage.vote or 64.23.136.132)

Optional:
    --cleanup   Delete old data after verified swap
"""

import argparse
import json
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

NODE_HOME = Path("/root/.mirage/node")
NODE_HOME_NEXT = Path("/root/.mirage/node.next")
LOGS_DIR = Path("/root/.mirage/logs")
NODE_ENV = Path("/root/.mirage/env/node.env")
MIRAGED = "/opt/mirage/blockchain/bin/miraged"

ALT_RPC_PORT = 27657
ALT_P2P_PORT = 27656
ALT_API_PORT = 1318
ALT_GRPC_PORT = 9091

MAX_WAIT = 7200
SWAP_WAIT = 600
MAX_LAG = 50
NO_PEER_GRACE = 120

pre_sync_proc: subprocess.Popen | None = None
old_data_path: Path | None = None
main_height_before: int | None = None
phase: str = "init"


def log(msg: str):
    print(f"==> {msg}", flush=True)


def die(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def need_cmd(name: str):
    if shutil.which(name) is None:
        die(f"Missing required command: {name}")


def rpc_get(url: str, timeout: float = 5) -> dict | None:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def get_status_field(rpc: str, field: str) -> str | None:
    data = rpc_get(f"{rpc}/status")
    if data is None:
        return None
    try:
        val = data["result"]["sync_info"][field]
        return str(val) if val is not None else None
    except (KeyError, TypeError):
        return None


def get_block_hash(rpc: str, height: int) -> str | None:
    data = rpc_get(f"{rpc}/block?height={height}")
    if data is None:
        return None
    try:
        return data["result"]["block_id"]["hash"]
    except (KeyError, TypeError):
        return None


def get_reference_height(rpc_list: list[str]) -> int | None:
    """Get latest height from the first reachable RPC in the list."""
    for rpc in rpc_list:
        val = get_status_field(rpc, "latest_block_height")
        if val:
            return int(val)
    return None


def get_peer_count(rpc: str) -> int | None:
    data = rpc_get(f"{rpc}/net_info")
    if data is None:
        return None
    try:
        return int(data["result"]["n_peers"])
    except (KeyError, TypeError, ValueError):
        return None


def normalize_rpc(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        die("Empty RPC address")
    if not re.match(r"^https?://", raw):
        raw = f"http://{raw}"
    host = raw.split("://", 1)[1]
    if ":" not in host:
        raw = f"{raw}:26657"
    return raw.rstrip("/")


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def tmux_send(target: str, keys: str):
    subprocess.run(["tmux", "send-keys", "-t", target, keys, "C-m"], check=True)


def tmux_interrupt(target: str):
    subprocess.run(["tmux", "send-keys", "-t", target, "C-c"])


def wait_for_process_exit(proc: subprocess.Popen, timeout: int):
    deadline = time.time() + timeout
    while proc.poll() is None:
        if time.time() >= deadline:
            proc.kill()
            proc.wait(timeout=5)
            return
        time.sleep(1)


def kill_miraged(timeout: int = 60):
    pattern = "miraged"
    deadline = time.time() + timeout
    while True:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return
        if time.time() >= deadline:
            subprocess.run(["pkill", "-KILL", "-f", pattern], capture_output=True)
            time.sleep(2)
            return
        time.sleep(1)


def start_main_node():
    cmd = f'{MIRAGED} start --home "{NODE_HOME}" 2>&1' f' | tee >(cronolog "{LOGS_DIR}/node/miraged-%Y-%m-%d.log")'
    tmux_send("mirage:node", cmd)


def rollback():
    log("ROLLING BACK: restoring old data")
    data_dir = NODE_HOME / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    if old_data_path and old_data_path.exists():
        old_data_path.rename(data_dir)
    else:
        die("Rollback failed: old data path missing")
    log("Starting main node on old data")
    try:
        start_main_node()
    except subprocess.CalledProcessError:
        die("Rollback restored data but failed to start node (tmux error)")
    die("Swap failed, rolled back to previous data")


def cleanup_handler(signum, frame):
    global phase
    log(f"Signal {signum} received during phase '{phase}'")
    if pre_sync_proc and pre_sync_proc.poll() is None:
        log(f"Killing pre-sync process {pre_sync_proc.pid}")
        pre_sync_proc.terminate()
        wait_for_process_exit(pre_sync_proc, timeout=30)
    if phase in {"swapped", "started_new", "health_check"}:
        log("Signal received after swap; attempting rollback")
        subprocess.run(["pkill", "-KILL", "-f", "miraged"], capture_output=True)
        time.sleep(2)
        if old_data_path and old_data_path.exists():
            rollback()
        die("Signal received after swap but no old data to rollback")
    sys.exit(1)


# -------------------------------------------------------------------------
# TOML editing
# -------------------------------------------------------------------------


def update_toml(path: Path, updates: dict[str, dict[str, str]]):
    """Update keys within [section] blocks of a TOML file.

    updates: {section_name: {key: formatted_value, ...}, ...}
    """
    lines = path.read_text().splitlines()
    section = ""
    out: list[str] = []
    seen: dict[str, dict[str, int]] = {sec: {k: 0 for k in keys} for sec, keys in updates.items()}

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped.strip("[]")
            out.append(line)
            continue
        if section in updates:
            for key, value in updates[section].items():
                if stripped.startswith(f"{key} ") or stripped.startswith(f"{key}="):
                    line = f"{key} = {value}"
                    seen[section][key] += 1
                    break
        out.append(line)

    missing = [f"{s}.{k}" for s, ks in seen.items() for k, c in ks.items() if c == 0]
    if missing:
        die(f"Missing keys in {path}: {', '.join(missing)}")
    path.write_text("\n".join(out) + "\n")


# -------------------------------------------------------------------------
# RPC list from source + PERSISTENT_PEERS
# -------------------------------------------------------------------------


def build_rpc_list(source_rpc: str) -> list[str]:
    items = [source_rpc]

    if NODE_ENV.exists():
        for line in NODE_ENV.read_text().splitlines():
            if line.startswith("PERSISTENT_PEERS="):
                raw = line.split("=", 1)[1].strip().strip('"').strip("'")
                for entry in raw.split(","):
                    entry = entry.strip()
                    if not entry:
                        continue
                    host = entry.split("@")[-1].split(":")[0]
                    if host:
                        rpc = normalize_rpc(host)
                        if rpc not in items:
                            items.append(rpc)
                break

    return items


# -------------------------------------------------------------------------
# Trust height / hash
# -------------------------------------------------------------------------


def find_trust_params(rpc_list: list[str]) -> tuple[int, str]:
    latest: str | None = None
    for rpc in rpc_list:
        latest = get_status_field(rpc, "latest_block_height")
        if latest:
            break
    if not latest:
        die("Cannot get latest height from any RPC for trust params")
    trust_height = int(latest) - 2000
    if trust_height < 1:
        die(f"Chain too young for state-sync (height {latest})")

    for rpc in rpc_list:
        trust_hash = get_block_hash(rpc, trust_height)
        if trust_hash:
            return trust_height, trust_hash

    die(f"Failed to fetch trust hash at height {trust_height} from any RPC")
    return 0, ""  # unreachable


# -------------------------------------------------------------------------
# Prepare alternate home directory
# -------------------------------------------------------------------------


def prepare_next_home(rpc_csv: str, trust_height: int, trust_hash: str):
    if not NODE_HOME.exists():
        die(f"Node home missing: {NODE_HOME}")
    if not (NODE_HOME / "config").exists():
        die(f"Node config missing: {NODE_HOME / 'config'}")

    if NODE_HOME_NEXT.exists():
        log(f"Removing stale next home: {NODE_HOME_NEXT}")
        shutil.rmtree(NODE_HOME_NEXT)

    log(f"Preparing next home: {NODE_HOME_NEXT}")
    (NODE_HOME_NEXT / "data").mkdir(parents=True)
    shutil.copytree(NODE_HOME / "config", NODE_HOME_NEXT / "config", dirs_exist_ok=True)

    (NODE_HOME_NEXT / "config" / "priv_validator_key.json").unlink(missing_ok=True)
    (NODE_HOME_NEXT / "config" / "node_key.json").unlink(missing_ok=True)

    pv_state = NODE_HOME_NEXT / "data" / "priv_validator_state.json"
    pv_state.write_text('{"height":"0","round":0,"step":0}')

    cfg = NODE_HOME_NEXT / "config" / "config.toml"
    app = NODE_HOME_NEXT / "config" / "app.toml"
    if not cfg.exists():
        die(f"Missing config.toml in next home: {cfg}")
    if not app.exists():
        die(f"Missing app.toml in next home: {app}")

    update_toml(
        cfg,
        {
            "rpc": {"laddr": f'"tcp://0.0.0.0:{ALT_RPC_PORT}"'},
            "p2p": {"laddr": f'"tcp://0.0.0.0:{ALT_P2P_PORT}"'},
            "statesync": {
                "enable": "true",
                "rpc_servers": f'"{rpc_csv}"',
                "trust_height": str(trust_height),
                "trust_hash": f'"{trust_hash}"',
            },
        },
    )

    update_toml(
        app,
        {
            "api": {"address": f'"tcp://0.0.0.0:{ALT_API_PORT}"'},
            "grpc": {"address": f'"0.0.0.0:{ALT_GRPC_PORT}"'},
        },
    )


# -------------------------------------------------------------------------
# Pre-sync loop
# -------------------------------------------------------------------------


def run_pre_sync(rpc_list: list[str]) -> int:
    global pre_sync_proc

    log_path = LOGS_DIR / "node" / f"miraged-presync-{datetime.now(timezone.utc):%Y-%m-%d-%H%M%S}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    log(f"Starting pre-sync node (log: {log_path})")
    with open(log_path, "w") as log_file:
        pre_sync_proc = subprocess.Popen(
            [MIRAGED, "start", "--home", str(NODE_HOME_NEXT)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )

    log(f"Waiting for pre-sync to complete (max {MAX_WAIT}s)")
    start = time.time()
    last_height: int | None = None
    no_peer_since: float | None = None

    while True:
        elapsed = time.time() - start
        if elapsed >= MAX_WAIT:
            die(f"Pre-sync did not complete within {MAX_WAIT}s")

        if pre_sync_proc.poll() is not None:
            die(f"Pre-sync process exited unexpectedly (check {log_path})")

        data = rpc_get(f"http://127.0.0.1:{ALT_RPC_PORT}/status")
        if data is None:
            time.sleep(5)
            continue

        peer_count = get_peer_count(f"http://127.0.0.1:{ALT_RPC_PORT}")
        if peer_count == 0:
            if no_peer_since is None:
                no_peer_since = time.time()
                log("Pre-sync has zero peers; waiting for P2P connections...")
            elif time.time() - no_peer_since > NO_PEER_GRACE:
                die(
                    "Pre-sync has 0 P2P peers for too long. If the source already has a "
                    "connection from this IP, temporarily set allow_duplicate_ip = true on "
                    "the source node, restart it, then re-run. Ensure it is set back to false."
                )
        elif peer_count and peer_count > 0:
            no_peer_since = None

        try:
            si = data["result"]["sync_info"]
            catching_up = si["catching_up"]
            height = int(si["latest_block_height"])
        except (KeyError, TypeError, ValueError):
            time.sleep(5)
            continue

        last_height = height

        if not catching_up:
            ref = get_reference_height(rpc_list)
            if not ref:
                die("No reachable RPC to check lag during pre-sync")
            lag = ref - height
            if lag <= MAX_LAG:
                break

        time.sleep(10)

    log(f"Pre-sync complete at height {last_height}")
    return last_height


def stop_pre_sync():
    global pre_sync_proc
    if pre_sync_proc is None:
        return
    log("Stopping pre-sync node")
    pre_sync_proc.terminate()
    wait_for_process_exit(pre_sync_proc, timeout=30)
    pre_sync_proc = None


# -------------------------------------------------------------------------
# Swap
# -------------------------------------------------------------------------


def swap_data() -> Path:
    global old_data_path

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    old_data_path = NODE_HOME / f"data.old.{ts}"
    data_dir = NODE_HOME / "data"

    log("Backing up priv_validator_state.json")
    pv_state_backup = Path("/tmp/priv_validator_state.json.hotswap")
    shutil.copy2(data_dir / "priv_validator_state.json", pv_state_backup)

    log(f"Swapping data (old data: {old_data_path})")
    data_dir.rename(old_data_path)
    (NODE_HOME_NEXT / "data").rename(data_dir)
    shutil.copy2(pv_state_backup, data_dir / "priv_validator_state.json")
    pv_state_backup.unlink(missing_ok=True)

    return old_data_path


# -------------------------------------------------------------------------
# Post-swap health check
# -------------------------------------------------------------------------


def health_check(rpc_list: list[str]) -> bool:
    log(f"Waiting for main node to be healthy (max {SWAP_WAIT}s)")
    start = time.time()
    last_log = start

    while time.time() - start < SWAP_WAIT:
        data = rpc_get("http://127.0.0.1:26657/status")
        if data is None:
            time.sleep(5)
            continue

        try:
            si = data["result"]["sync_info"]
            catching_up = si["catching_up"]
            height = int(si["latest_block_height"])
        except (KeyError, TypeError, ValueError):
            time.sleep(5)
            continue

        now = time.time()
        if now - last_log >= 60:
            ref = get_reference_height(rpc_list)
            if ref:
                log(f"Health check: height={height} catching_up={catching_up} lag={ref - height}")
            else:
                log(f"Health check: height={height} catching_up={catching_up} lag=unknown")
            last_log = now

        if not catching_up:
            ref = get_reference_height(rpc_list)
            if ref:
                lag = ref - height
                if lag <= MAX_LAG:
                    log(f"Main node healthy at height {height}")
                    return True

        time.sleep(5)

    return False


# -------------------------------------------------------------------------
# Main
# -------------------------------------------------------------------------


def main():
    global main_height_before, phase

    parser = argparse.ArgumentParser(
        description="Hot-swap state-sync inside the Docker container.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="RPC host to sync from (e.g. mirage.vote or 64.23.136.132)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete old data after verified swap",
    )
    args = parser.parse_args()

    if not Path("/.dockerenv").exists():
        die("Run this inside the container (docker exec -it mirage bash)")

    for cmd in ("tmux", "pgrep", "pkill", "cronolog"):
        need_cmd(cmd)

    signal.signal(signal.SIGINT, cleanup_handler)
    signal.signal(signal.SIGTERM, cleanup_handler)

    # Resolve source
    source_rpc = normalize_rpc(args.source)
    log(f"Source: {source_rpc}")

    # Build RPC list (source + local node's persistent peers)
    rpc_list = build_rpc_list(source_rpc)
    local_rpc = "http://127.0.0.1:26657"
    if local_rpc not in rpc_list:
        rpc_list.append(local_rpc)
    rpc_csv = ",".join(rpc_list)
    log(f"RPC servers: {rpc_csv}")

    # Trust params (tries all RPCs — some may be firewalled)
    trust_height, trust_hash = find_trust_params(rpc_list)
    log(f"Trust height: {trust_height}  hash: {trust_hash[:16]}...")

    # Main node height
    main_height_before = get_status_field("http://127.0.0.1:26657", "latest_block_height")
    if not main_height_before:
        die("Main node RPC not responding (is it running?)")
    main_height_before = int(main_height_before)
    log(f"Main node current height: {main_height_before}")

    # Check ports
    for port in (ALT_RPC_PORT, ALT_P2P_PORT, ALT_API_PORT, ALT_GRPC_PORT):
        if not port_is_free(port):
            die(f"Port {port} is already in use")

    # Prepare next home and run pre-sync
    phase = "presync"
    prepare_next_home(rpc_csv, trust_height, trust_hash)
    synced_height = run_pre_sync(rpc_list)

    if synced_height < main_height_before:
        die(f"Pre-sync height ({synced_height}) < main node height " f"({main_height_before}). Aborting.")

    stop_pre_sync()
    phase = "presync_stopped"

    # Stop main node
    result = subprocess.run(
        ["tmux", "has-session", "-t", "mirage"],
        capture_output=True,
    )
    if result.returncode != 0:
        die("tmux session 'mirage' not found")

    log("Stopping main node")
    phase = "stopping_main"
    tmux_interrupt("mirage:node")
    kill_miraged(timeout=60)
    phase = "main_stopped"

    # Swap
    old = swap_data()
    phase = "swapped"

    # Start on new data
    log("Starting main node on new data")
    start_main_node()
    phase = "started_new"

    # Health check with rollback
    phase = "health_check"
    if not health_check(rpc_list):
        log("Post-swap health check FAILED")
        tmux_interrupt("mirage:node")
        time.sleep(3)
        subprocess.run(["pkill", "-KILL", "-f", "miraged"], capture_output=True)
        time.sleep(2)
        rollback()
    phase = "done"

    # Cleanup
    if args.cleanup:
        log("Cleaning up old data and next home")
        if old.exists():
            shutil.rmtree(old)
        if NODE_HOME_NEXT.exists():
            shutil.rmtree(NODE_HOME_NEXT)
    else:
        log(f"Old data preserved at: {old}")
        log(f"To clean up: rm -rf {old} {NODE_HOME_NEXT}")

    log("Done")


if __name__ == "__main__":
    main()
