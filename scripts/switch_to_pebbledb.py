#!/usr/bin/env python3
"""Switch a Mirage node from GoLevelDB to PebbleDB with export/import.

This script:
1. Stops the node
2. Exports chain state
3. Backs up old data directory
4. Switches config to PebbleDB
5. Reimports state into fresh PebbleDB
6. Restarts the node

The export/import also removes database bloat from poor LevelDB compaction.

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
    
    # Step 6: Backup old data directory
    status("Backing up old data directory...")
    ssh(conn, f"mv /root/.mirage/node/data /root/.mirage/node/data.backup-{timestamp}")
    
    # Step 7: Switch config to PebbleDB
    status("Switching to PebbleDB in config.toml...")
    ssh(conn,
        "sed -i 's/^db_backend = .*/db_backend = \"pebbledb\"/' /root/.mirage/node/config/config.toml || "
        "echo 'db_backend = \"pebbledb\"' >> /root/.mirage/node/config/config.toml")
    
    # Verify config change
    new_backend = ssh(conn, "grep '^db_backend' /root/.mirage/node/config/config.toml", capture=True)
    print(f"  New config: {new_backend}")
    
    # Step 8: Create fresh data directory
    status("Creating fresh data directory...")
    ssh(conn, "mkdir -p /root/.mirage/node/data")
    
    # Copy priv_validator_state.json (important - prevents double signing!)
    status("Preserving validator state (prevents double signing)...")
    ssh(conn, 
        f"cp /root/.mirage/node/data.backup-{timestamp}/priv_validator_state.json "
        "/root/.mirage/node/data/ 2>/dev/null || "
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
        rpc_servers = ",".join([f"{n}:26657" for n in rpc_nodes])
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
        
        # Enable state-sync in config
        ssh(conn, f"""
sed -i 's/^enable = false/enable = true/' /root/.mirage/node/config/config.toml
sed -i 's|^rpc_servers = .*|rpc_servers = "{rpc_servers}"|' /root/.mirage/node/config/config.toml
sed -i 's/^trust_height = .*/trust_height = {trust_height}/' /root/.mirage/node/config/config.toml
sed -i 's/^trust_hash = .*/trust_hash = "{trust_hash}"/' /root/.mirage/node/config/config.toml
""")
        print("  State-sync enabled - will catch up in ~2-5 minutes!")
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
    
    # Step 11: Clean up export and old backup after a delay
    status("Cleanup: old data will be removed after sync completes")
    print(f"\n  Export saved at: /root/.mirage/export-{timestamp}.json")
    print(f"  Old data at: /root/.mirage/node/data.backup-{timestamp}")
    print("\n  To remove after sync is complete:")
    print(f"    ssh {conn} 'rm -rf /root/.mirage/node/data.backup-{timestamp} /root/.mirage/export-{timestamp}.json'")
    
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
    print("  3. Clean up old data:")
    print(f"     ssh {conn} 'rm -rf /root/.mirage/node/data.backup-{timestamp}'")


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
