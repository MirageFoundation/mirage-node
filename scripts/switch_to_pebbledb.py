#!/usr/bin/env python3
"""Switch a Mirage node from GoLevelDB to PebbleDB with state-sync.

This script:
1. Stops the node
2. (Optional) Exports chain state for offline analysis
3. Removes old data directory (frees space)
4. Switches db backend to PebbleDB
5. Configures state-sync and restarts the node

State-sync rebuilds the database and removes LevelDB bloat.

Usage:
    # Test on mirage.vote first!
    python3 scripts/switch_to_pebbledb.py --target mirage.vote --rpc-servers mirage.talk:26657

    # After verifying it works, do the others
    python3 scripts/switch_to_pebbledb.py --target mirage.talk --rpc-servers mirage.vote:26657
    python3 scripts/switch_to_pebbledb.py --target validator3.example.com --rpc-servers mirage.vote:26657,mirage.talk:26657

WARNING: This causes downtime (~5-10 minutes). The node will miss blocks during this time.
         Other validators will continue producing blocks - the chain won't halt.
"""

import argparse
import subprocess
import sys
import time
from datetime import datetime

SSH_USER = "root"


def status(msg: str):
    print(f"==> {msg}", flush=True)


def run(cmd: str, check: bool = True, capture: bool = False) -> str:
    """Run a shell command."""
    result = subprocess.run(
        cmd,
        shell=True,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    return result.stdout.strip() if capture else ""


def ssh(conn: str, cmd: str, check: bool = True, capture: bool = False) -> str:
    """Run command on remote host."""
    # Escape single quotes for bash: ' -> '\''
    escaped = cmd.replace("'", "'\"'\"'")
    return run(f"ssh -o StrictHostKeyChecking=accept-new {conn} '{escaped}'", check=check, capture=capture)


def switch_to_pebbledb(target_host: str, rpc_servers: str, export_state: bool, ssh_user: str = SSH_USER):
    """Switch a node from GoLevelDB to PebbleDB."""
    conn = f"{ssh_user}@{target_host}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    
    status(f"Gathering info from {target_host}...")
    
    # Check current DB backend
    current_backend = ssh(conn, 
        "grep '^db_backend' /root/.mirage/node/config/config.toml",
        capture=True, check=False)
    
    if not current_backend:
        # Key doesn't exist = node is on goleveldb (pre-migration state)
        # This is deterministic, not a fallback - goleveldb was the only option before
        current_backend = 'db_backend = "goleveldb"'
        print("  Note: db_backend key missing (pre-migration), assuming goleveldb")
    
    if "pebbledb" in current_backend.lower():
        print("Already using PebbleDB! Nothing to do.")
        sys.exit(0)
    
    # Get current block height
    height = ssh(conn,
        'docker exec mirage bash -c "curl -sf http://127.0.0.1:26657/status | jq -r \'.result.sync_info.latest_block_height\'"',
        capture=True)
    if not height or not height.isdigit():
        raise RuntimeError(f"Failed to get current block height: {height}")
    
    # Get current data directory size (BEFORE)
    data_size_before = ssh(conn, "du -sh /root/.mirage/node/data", capture=True)
    if not data_size_before:
        raise RuntimeError("Failed to get data directory size")
    
    # Show summary before confirmation
    print(f"\n{'='*50}")
    print(f"  Target:         {target_host}")
    print(f"  Current DB:     {current_backend.split('=')[1].strip().strip('\"')}")
    print(f"  Block height:   {height}")
    print(f"  Data dir size:  {data_size_before.split()[0]} (BEFORE)")
    print(f"{'='*50}")
    print("\nWARNING: This will cause ~5-10 minutes of downtime!")
    print("         The node will miss blocks but the chain will continue.")
    confirm = input("\nType 'yes' to continue: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        sys.exit(0)
    
    # Stop the node
    status("Stopping node...")
    ssh(conn, "docker exec mirage tmux send-keys -t mirage:node C-c")
    time.sleep(3)
    # Check if still running after graceful stop
    still_running = ssh(conn, "docker exec mirage pgrep -f miraged", check=False, capture=True)
    if still_running:
        status("Force killing node...")
        ssh(conn, "docker exec mirage pkill -9 -f miraged")
        time.sleep(2)
    # Verify node is stopped
    running = ssh(conn, "docker exec mirage pgrep -f miraged", check=False, capture=True)
    if running:
        raise RuntimeError(f"Node still running after kill: PID {running}")
    
    # Check disk space for export
    status("Checking disk space...")
    space = ssh(conn, "df -h /root | tail -1 | awk '{print $4}'", capture=True)
    print(f"  Available: {space}")
    
    # Optional export (offline analysis only)
    export_path = f"/root/.mirage/export-{timestamp}.json"
    if export_state:
        status("Exporting chain state (this takes 1-2 minutes)...")
        ssh(
            conn,
            "docker exec mirage /opt/mirage/blockchain/miraged export "
            "--home /root/.mirage/node "
            f"--output-document {export_path}",
        )
        export_size = ssh(conn, f"ls -lh {export_path} | awk '{{print $5}}'", capture=True)
        status(f"Export complete: {export_size}")
    else:
        status("Skipping export (use --export to enable)")
    
    # Save priv_validator_state.json then remove old data
    # We can't keep data.backup - not enough disk space (only ~1.3GB free)
    status("Saving validator state (prevents double signing)...")
    ssh(conn, "cp /root/.mirage/node/data/priv_validator_state.json /root/.mirage/priv_validator_state.json.bak")
    # Verify backup was created
    ssh(conn, "test -f /root/.mirage/priv_validator_state.json.bak")
    
    status("Removing old bloated data directory...")
    ssh(conn, "rm -rf /root/.mirage/node/data")
    
    # Switch db backend to PebbleDB (CometBFT + app)
    status("Switching db backend to PebbleDB...")
    ssh(
        conn,
        'python3 - <<"PY"\n'
        "from pathlib import Path\n"
        "import re\n"
        "\n"
        "def set_top_level_key(path: str, key: str, value: str) -> None:\n"
        "    p = Path(path)\n"
        "    lines = p.read_text().splitlines()\n"
        "    # Find first table header to keep key at top-level\n"
        '    first_table = next((i for i, l in enumerate(lines) if l.strip().startswith("[")), len(lines))\n'
        "    found = False\n"
        "    for i in range(first_table):\n"
        '        if re.match(rf"^\\s*{re.escape(key)}\\s*=", lines[i]):\n'
        '            lines[i] = f"{key} = \\"{value}\\""\n'
        "            found = True\n"
        "    if not found:\n"
        "        insert_at = first_table\n"
        '        lines.insert(insert_at, f"{key} = \\"{value}\\"")\n'
        '    p.write_text("\\n".join(lines) + "\\n")\n'
        "\n"
        'set_top_level_key("/root/.mirage/node/config/config.toml", "db_backend", "pebbledb")\n'
        'set_top_level_key("/root/.mirage/node/config/app.toml", "app-db-backend", "pebbledb")\n'
        'print("OK")\n'
        "PY",
    )
    # Verify config change
    new_backend = ssh(
        conn,
        "grep -E '^(db_backend|app-db-backend)[[:space:]]*=' /root/.mirage/node/config/config.toml /root/.mirage/node/config/app.toml",
        capture=True,
    )
    print(f"  Updated:\n{new_backend}")
    
    # Create fresh data directory
    status("Creating fresh data directory...")
    ssh(conn, "mkdir -p /root/.mirage/node/data")
    
    # Restore priv_validator_state.json (prevents double signing!)
    status("Restoring validator state...")
    ssh(conn, "cp /root/.mirage/priv_validator_state.json.bak /root/.mirage/node/data/priv_validator_state.json")
    
    # Configure state-sync for fast catch-up
    status("Configuring state-sync for fast catch-up...")
    if not rpc_servers:
        raise RuntimeError("rpc_servers is required (e.g., --rpc-servers mirage.talk:26657)")

    rpc_nodes = [n.strip() for n in rpc_servers.split(",") if n.strip()]
    if not rpc_nodes:
        raise RuntimeError("rpc_servers is empty")

    # Normalize to http://
    rpc_nodes = [n if n.startswith("http://") or n.startswith("https://") else f"http://{n}" for n in rpc_nodes]
    rpc_servers = ",".join(rpc_nodes)
    source_node = rpc_nodes[0]

    # Get a recent block for state-sync trust (via container tools)
    trust_info = ssh(
        conn,
        "docker exec mirage bash -lc "
        f"\"curl -sf {source_node}/block | "
        "jq -r '\\\"\\\\(.result.block.header.height) \\\\(.result.block_id.hash)\\\"'\"",
        capture=True,
    )
    
    if not trust_info or " " not in trust_info:
        raise RuntimeError("Failed to fetch trust height/hash for state-sync")

    trust_height, trust_hash = trust_info.split(" ", 1)
    trust_height = str(max(1, int(trust_height) - 1000))

    trust_info2 = ssh(
        conn,
        "docker exec mirage bash -lc "
        f"\"curl -sf {source_node}/block?height={trust_height} | "
        "jq -r '.result.block_id.hash'\"",
        capture=True,
    )
    if not trust_info2:
        raise RuntimeError("Failed to fetch trust hash at height")
    trust_hash = trust_info2

    status(f"State-sync trust: height={trust_height}, hash={trust_hash[:16]}...")

    # Enable state-sync in config (add/update [statesync] section)
    ssh(
        conn,
        f'python3 - <<"PY"\n'
        "from pathlib import Path\n"
        "\n"
        f'rpc_servers = "{rpc_servers}"\n'
        f"trust_height = {trust_height}\n"
        f'trust_hash = "{trust_hash}"\n'
        'trust_period = "168h0m0s"\n'
        "\n"
        'path = Path("/root/.mirage/node/config/config.toml")\n'
        "lines = path.read_text().splitlines()\n"
        "\n"
        "def set_statesync(lines):\n"
        "    out = []\n"
        "    i = 0\n"
        "    found = False\n"
        "    while i < len(lines):\n"
        "        line = lines[i]\n"
        '        if line.strip() == "[statesync]":\n'
        "            found = True\n"
        '            out.append("[statesync]")\n'
        "            i += 1\n"
        '            while i < len(lines) and not lines[i].strip().startswith("["):\n'
        "                i += 1\n"
        "            out.extend([\n"
        '                "enable = true",\n'
        '                f\'rpc_servers = "{rpc_servers}"\',\n'
        '                f"trust_height = {trust_height}",\n'
        '                f\'trust_hash = "{trust_hash}"\',\n'
        '                f\'trust_period = "{trust_period}"\',\n'
        "            ])\n"
        "            continue\n"
        "        out.append(line)\n"
        "        i += 1\n"
        "    if not found:\n"
        '        out.append("")\n'
        '        out.append("[statesync]")\n'
        "        out.extend([\n"
        '            "enable = true",\n'
        '            f\'rpc_servers = "{rpc_servers}"\',\n'
        '            f"trust_height = {trust_height}",\n'
        '            f\'trust_hash = "{trust_hash}"\',\n'
        '            f\'trust_period = "{trust_period}"\',\n'
        "        ])\n"
        "    return out\n"
        "\n"
        "lines = set_statesync(lines)\n"
        'path.write_text("\\n".join(lines) + "\\n")\n'
        'print("OK")\n'
        "PY",
    )
    print("  State-sync enabled - should catch up quickly")
    
    status("Starting node...")
    ssh(conn, 
        "docker exec mirage tmux send-keys -t mirage:node "
        "'/opt/mirage/blockchain/miraged start --home /root/.mirage/node 2>&1 | "
        "tee >(cronolog /root/.mirage/logs/node/miraged-%Y-%m-%d.log)' C-m")
    
    # Wait for node to start syncing
    status("Waiting for node to start...")
    started = False
    for i in range(60):
        result = ssh(conn, 
            'docker exec mirage bash -c "curl -sf http://127.0.0.1:26657/status | '
            'jq -r \'.result.sync_info | \\\"Height: \\(.latest_block_height), Catching up: \\(.catching_up)\\\"\'"',
            capture=True, check=False)
        if result and "Height:" in result:
            print(f"  {result}")
            started = True
            break
        time.sleep(2)
    if not started:
        raise RuntimeError("Node failed to start within 120 seconds")
    
    # Optional export cleanup reminder
    if export_state:
        status("Export saved")
        print(f"\n  Export: {export_path}")
        print("\n  To remove after verifying everything works:")
        print(f"    ssh {conn} 'rm {export_path}'")
    
    # Check new database size and show BEFORE/AFTER comparison
    status("Checking new database size...")
    time.sleep(5)  # Wait for some data to be written
    data_size_after = ssh(conn, "du -sh /root/.mirage/node/data", capture=True)
    if not data_size_after:
        raise RuntimeError("data directory not created - state-sync may have failed")
    
    # Show BEFORE/AFTER comparison
    before_size = data_size_before.split()[0]
    after_size = data_size_after.split()[0]
    print(f"\n{'='*50}")
    print(f"  BEFORE: {before_size}")
    print(f"  AFTER:  {after_size} (still syncing)")
    print(f"{'='*50}")
    
    status(f"Switch complete! Node is syncing from network.")
    print("\nNext steps:")
    print("  1. Monitor sync progress:")
    print(f"     ssh {conn} 'docker exec mirage curl -s http://127.0.0.1:26657/status | jq .result.sync_info'")
    print("  2. Once caught up, verify the node is voting:")
    print(f"     ssh {conn} 'docker exec mirage tmux attach -t mirage:node'")
    if export_state:
        print("  3. Once stable, remove export backup:")
        print(f"     ssh {conn} 'rm {export_path}'")


def main():
    parser = argparse.ArgumentParser(
        description="Switch a Mirage node from GoLevelDB to PebbleDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test on mirage.vote first!
  %(prog)s --target mirage.vote --rpc-servers mirage.talk:26657

  # Then other nodes
  %(prog)s --target mirage.talk --rpc-servers mirage.vote:26657
"""
    )
    parser.add_argument("--target", required=True, help="Target server hostname")
    parser.add_argument(
        "--rpc-servers",
        required=True,
        help="Comma-separated RPC servers for state-sync (e.g., mirage.talk:26657,mirage.vote:26657)",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export chain state before switching (offline analysis only)",
    )
    parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")
    
    args = parser.parse_args()
    switch_to_pebbledb(args.target, args.rpc_servers, args.export, args.user)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
    except subprocess.CalledProcessError as e:
        print(f"ERROR: Command failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
