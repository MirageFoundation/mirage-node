#!/usr/bin/env python3
"""Switch a Mirage node from GoLevelDB to PebbleDB with state-sync.

This script:
1. Stops the node
2. Exports chain state (emergency backup)
3. Removes old data directory (frees space)
4. Switches db backend to PebbleDB
5. Configures state-sync and restarts the node

State-sync rebuilds the database and removes LevelDB bloat. The export is
kept only as a fallback if something goes wrong.

Usage:
    # Test on mirage.vote first!
    python3 scripts/switch_to_pebbledb.py --target mirage.vote

    # After verifying it works, do the others
    python3 scripts/switch_to_pebbledb.py --target mirage.talk
    python3 scripts/switch_to_pebbledb.py --target validator3.example.com

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
    return run(f"ssh -o StrictHostKeyChecking=accept-new {conn} '{cmd}'", check=check, capture=capture)


def switch_to_pebbledb(target_host: str, ssh_user: str = SSH_USER):
    """Switch a node from GoLevelDB to PebbleDB."""
    conn = f"{ssh_user}@{target_host}"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    
    status(f"Switching {target_host} to PebbleDB")
    print("\nWARNING: This will cause ~5-10 minutes of downtime!")
    print("         The node will miss blocks but the chain will continue.")
    confirm = input("\nType 'yes' to continue: ")
    if confirm.lower() != "yes":
        print("Aborted.")
        sys.exit(0)
    
    # Step 1: Check current DB backend
    status("Checking current configuration...")
    current_backend = ssh(conn, 
        "grep '^db_backend' /root/.mirage/node/config/config.toml 2>/dev/null || echo 'db_backend = \"goleveldb\"'",
        capture=True)
    print(f"  Current: {current_backend}")
    
    if "pebbledb" in current_backend.lower():
        print("Already using PebbleDB! Nothing to do.")
        sys.exit(0)
    
    # Step 2: Get current block height
    status("Getting current block height...")
    height = ssh(conn,
        "docker exec mirage curl -s http://127.0.0.1:26657/status 2>/dev/null | jq -r '.result.sync_info.latest_block_height' || echo 'unknown'",
        capture=True)
    print(f"  Current height: {height}")
    
    # Step 3: Stop the node
    status("Stopping node...")
    ssh(conn, "docker exec mirage tmux send-keys -t mirage:node C-c 2>/dev/null || true")
    time.sleep(3)
    ssh(conn, "docker exec mirage pkill -9 -f miraged 2>/dev/null || true")
    time.sleep(2)
    
    # Step 4: Check disk space for export
    status("Checking disk space...")
    space = ssh(conn, "df -h /root | tail -1 | awk '{print $4}'", capture=True)
    print(f"  Available: {space}")
    
    # Step 5: Export chain state
    status("Exporting chain state (this takes 1-2 minutes)...")
    ssh(conn, 
        "docker exec mirage /opt/mirage/blockchain/miraged export "
        "--home /root/.mirage/node "
        f"--output-document /root/.mirage/export-{timestamp}.json")
    
    # Verify export
    export_size = ssh(conn, f"ls -lh /root/.mirage/export-{timestamp}.json | awk '{{print $5}}'", capture=True)
    status(f"Export complete: {export_size}")
    
    # Step 6: Save priv_validator_state.json then remove old data
    # We can't keep data.backup - not enough disk space (only ~1.3GB free)
    status("Saving validator state (prevents double signing)...")
    ssh(conn, "cp /root/.mirage/node/data/priv_validator_state.json /root/.mirage/priv_validator_state.json.bak 2>/dev/null || true")
    
    status("Removing old bloated data directory...")
    ssh(conn, "rm -rf /root/.mirage/node/data")
    
    # Step 7: Switch db backend to PebbleDB (CometBFT + app)
    status("Switching db backend to PebbleDB...")
    ssh(
        conn,
        "python3 - <<'PY'\n"
        "from pathlib import Path\n"
        "import re\n"
        "\n"
        "def set_top_level_key(path: str, key: str, value: str) -> None:\n"
        "    p = Path(path)\n"
        "    lines = p.read_text().splitlines()\n"
        "    # Find first table header to keep key at top-level\n"
        "    first_table = next((i for i, l in enumerate(lines) if l.strip().startswith(\"[\")), len(lines))\n"
        "    found = False\n"
        "    for i in range(first_table):\n"
        "        if re.match(rf\"^\\s*{re.escape(key)}\\s*=\", lines[i]):\n"
        "            lines[i] = f\"{key} = \\\"{value}\\\"\"\n"
        "            found = True\n"
        "    if not found:\n"
        "        insert_at = first_table\n"
        "        lines.insert(insert_at, f\"{key} = \\\"{value}\\\"\")\n"
        "    p.write_text(\"\\n\".join(lines) + \"\\n\")\n"
        "\n"
        "set_top_level_key(\"/root/.mirage/node/config/config.toml\", \"db_backend\", \"pebbledb\")\n"
        "set_top_level_key(\"/root/.mirage/node/config/app.toml\", \"app-db-backend\", \"pebbledb\")\n"
        "print(\"OK\")\n"
        "PY",
    )
    # Verify config change
    new_backend = ssh(
        conn,
        "grep -E '^(db_backend|app-db-backend)[[:space:]]*=' /root/.mirage/node/config/config.toml /root/.mirage/node/config/app.toml",
        capture=True,
    )
    print(f"  Updated:\n{new_backend}")
    
    # Step 8: Create fresh data directory
    status("Creating fresh data directory...")
    ssh(conn, "mkdir -p /root/.mirage/node/data")
    
    # Restore priv_validator_state.json (prevents double signing!)
    status("Restoring validator state...")
    ssh(conn, 
        "cp /root/.mirage/priv_validator_state.json.bak /root/.mirage/node/data/priv_validator_state.json 2>/dev/null || "
        'echo \'{"height": "0", "round": 0, "step": 0}\' > /root/.mirage/node/data/priv_validator_state.json')
    
    # Step 9: Configure state-sync for fast catch-up
    status("Configuring state-sync for fast catch-up...")
    
    # Use other nodes as RPC servers (exclude the target itself)
    all_nodes = ["mirage.vote", "mirage.talk"]  # Add more as needed
    rpc_nodes = [n for n in all_nodes if n != target_host]
    
    if not rpc_nodes:
        status("WARNING: No other nodes available for state-sync, will do full sync")
        rpc_servers = ""
        trust_info = ""
    else:
        rpc_servers = ",".join([f"http://{n}:26657" for n in rpc_nodes])
        source_node = rpc_nodes[0]
        
        # Get a recent block for state-sync trust
        trust_info = ssh(conn,
            f"curl -s http://{source_node}:26657/block 2>/dev/null | "
            "jq -r '\"\\(.result.block.header.height) \\(.result.block_id.hash)\"' || echo ''",
            capture=True)
    
    if trust_info and " " in trust_info:
        trust_height, trust_hash = trust_info.split(" ", 1)
        # Go back ~1000 blocks for safety
        trust_height = str(max(1, int(trust_height) - 1000))
        
        # Get the hash at that height
        trust_info2 = ssh(conn,
            f"curl -s 'http://{source_node}:26657/block?height={trust_height}' 2>/dev/null | "
            "jq -r '.result.block_id.hash' || echo ''",
            capture=True)
        if trust_info2:
            trust_hash = trust_info2
        
        status(f"State-sync trust: height={trust_height}, hash={trust_hash[:16]}...")
        
        # Enable state-sync in config (add/update [statesync] section)
        ssh(
            conn,
            f"python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "\n"
            f"rpc_servers = \"{rpc_servers}\"\n"
            f"trust_height = {trust_height}\n"
            f"trust_hash = \"{trust_hash}\"\n"
            "trust_period = \"168h0m0s\"\n"
            "\n"
            "path = Path(\"/root/.mirage/node/config/config.toml\")\n"
            "lines = path.read_text().splitlines()\n"
            "\n"
            "def set_statesync(lines):\n"
            "    out = []\n"
            "    i = 0\n"
            "    found = False\n"
            "    while i < len(lines):\n"
            "        line = lines[i]\n"
            "        if line.strip() == \"[statesync]\":\n"
            "            found = True\n"
            "            out.append(\"[statesync]\")\n"
            "            i += 1\n"
            "            while i < len(lines) and not lines[i].strip().startswith(\"[\"):\n"
            "                i += 1\n"
            "            out.extend([\n"
            "                \"enable = true\",\n"
            "                f\"rpc_servers = \\\"{rpc_servers}\\\"\",\n"
            "                f\"trust_height = {trust_height}\",\n"
            "                f\"trust_hash = \\\"{trust_hash}\\\"\",\n"
            "                f\"trust_period = \\\"{trust_period}\\\"\",\n"
            "            ])\n"
            "            continue\n"
            "        out.append(line)\n"
            "        i += 1\n"
            "    if not found:\n"
            "        out.append(\"\")\n"
            "        out.append(\"[statesync]\")\n"
            "        out.extend([\n"
            "            \"enable = true\",\n"
            "            f\"rpc_servers = \\\"{rpc_servers}\\\"\",\n"
            "            f\"trust_height = {trust_height}\",\n"
            "            f\"trust_hash = \\\"{trust_hash}\\\"\",\n"
            "            f\"trust_period = \\\"{trust_period}\\\"\",\n"
            "        ])\n"
            "    return out\n"
            "\n"
            "lines = set_statesync(lines)\n"
            "path.write_text(\"\\n\".join(lines) + \"\\n\")\n"
            "print(\"OK\")\n"
            "PY",
        )
        print("  State-sync enabled - should catch up quickly")
    else:
        status("WARNING: Could not get state-sync info, will do full sync (slower)")
    
    status("Starting node...")
    ssh(conn, 
        "docker exec mirage tmux send-keys -t mirage:node "
        "'/opt/mirage/blockchain/miraged start --home /root/.mirage/node 2>&1 | "
        "tee >(cronolog /root/.mirage/logs/node/miraged-%Y-%m-%d.log)' C-m")
    
    # Step 10: Wait for node to start syncing
    status("Waiting for node to start...")
    for i in range(60):
        try:
            result = ssh(conn, 
                "docker exec mirage curl -s http://127.0.0.1:26657/status 2>/dev/null | "
                "jq -r '.result.sync_info | \"Height: \\(.latest_block_height), Catching up: \\(.catching_up)\"'",
                capture=True, check=False)
            if "Height:" in result:
                print(f"  {result}")
                break
        except Exception:
            pass
        time.sleep(2)
    
    # Step 11: Export is kept as emergency backup
    status("Export saved as emergency backup")
    print(f"\n  Export: /root/.mirage/export-{timestamp}.json")
    print("  (Can be used to restore if something goes wrong)")
    print("\n  To remove after verifying everything works:")
    print(f"    ssh {conn} 'rm /root/.mirage/export-{timestamp}.json'")
    
    # Step 12: Check new database size
    status("Checking new database size...")
    time.sleep(5)  # Wait for some data to be written
    new_size = ssh(conn, "du -sh /root/.mirage/node/data/application.db 2>/dev/null || echo 'still syncing'", capture=True)
    print(f"  New application.db: {new_size}")
    
    status(f"Switch complete! Node is syncing from network.")
    print("\nNext steps:")
    print("  1. Monitor sync progress:")
    print(f"     ssh {conn} 'docker exec mirage curl -s http://127.0.0.1:26657/status | jq .result.sync_info'")
    print("  2. Once caught up, verify the node is voting:")
    print(f"     ssh {conn} 'docker exec mirage tmux attach -t mirage:node'")
    print("  3. Once stable, remove export backup:")
    print(f"     ssh {conn} 'rm /root/.mirage/export-{timestamp}.json'")


def main():
    parser = argparse.ArgumentParser(
        description="Switch a Mirage node from GoLevelDB to PebbleDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test on mirage.vote first!
  %(prog)s --target mirage.vote

  # Then other nodes
  %(prog)s --target mirage.talk
"""
    )
    parser.add_argument("--target", required=True, help="Target server hostname")
    parser.add_argument("--user", default=SSH_USER, help=f"SSH user (default: {SSH_USER})")
    
    args = parser.parse_args()
    switch_to_pebbledb(args.target, args.user)


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
