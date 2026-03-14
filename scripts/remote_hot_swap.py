#!/usr/bin/env python3
"""Run a remote hot-swap state-sync via SSH.

Temporarily enables allow_duplicate_ip on the source node so the target's
pre-sync process can establish P2P connections, runs the in-container
hot_swap_statesync.py on the target, then restores the source config.

Usage:
    python scripts/remote_hot_swap.py --source mirage.vote --target 146.190.108.140 [--cleanup]

The source config is always restored, even on error.
"""

import argparse
import json
import pathlib
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

SSH_USER = "root"
CONTAINER = "mirage"
CONFIG_PATH = "/root/.mirage/node/config/config.toml"
SWAP_SCRIPT = "/opt/mirage/scripts/hot_swap_statesync.py"
HOT_SWAP_TIMEOUT = 9000


def log(msg: str):
    print(f"==> {msg}", flush=True)


def die(msg: str):
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(msg)


def ssh(host: str, cmd: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    full = ["ssh", "-o", "ConnectTimeout=10", f"{SSH_USER}@{host}", cmd]
    log(f"[{host}] {cmd}")
    result = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        die(
            f"SSH command failed on {host}:\n  cmd: {cmd}\n  stderr: {result.stderr.strip()}\n  stdout: {result.stdout.strip()}"
        )
    return result


def docker_exec(host: str, cmd: str, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess:
    return ssh(host, f"docker exec {CONTAINER} {cmd}", check=check, timeout=timeout)


def rpc_get(url: str, timeout: float = 10) -> dict | None:
    try:
        with urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def wait_for_rpc(host: str, max_wait: int = 120):
    """Wait for a node's RPC to respond."""
    log(f"Waiting for {host} RPC to come online (max {max_wait}s)")
    deadline = time.time() + max_wait
    while time.time() < deadline:
        data = rpc_get(f"http://{host}:26657/status")
        if data:
            try:
                height = data["result"]["sync_info"]["latest_block_height"]
                log(f"{host} is up at height {height}")
                return
            except (KeyError, TypeError):
                pass
        time.sleep(3)
    die(f"{host} RPC did not come online within {max_wait}s")


MIRAGED_START_CMD = (
    '/opt/mirage/blockchain/bin/miraged start --home "/root/.mirage/node" 2>&1'
    ' | tee >(cronolog "/root/.mirage/logs/node/miraged-%Y-%m-%d.log")'
)


def restart_node(host: str):
    """Stop and restart miraged inside the container via tmux."""
    docker_exec(host, "tmux send-keys -t mirage:node C-c", check=False)
    time.sleep(5)
    docker_exec(host, "pkill -f miraged", check=False)
    time.sleep(3)
    ssh(host, (f"docker exec {CONTAINER} tmux send-keys -t mirage:node" f" '{MIRAGED_START_CMD}' C-m"))
    wait_for_rpc(host)


def enable_duplicate_ip(source: str):
    log(f"Enabling allow_duplicate_ip on {source}")
    exists = ssh(
        source,
        f"docker exec {CONTAINER} grep -q '^allow_duplicate_ip = true$' {CONFIG_PATH}",
        check=False,
    )
    if exists.returncode == 0:
        die("allow_duplicate_ip is already true on the source; set it to false before running.")

    ssh(source, (f"docker exec {CONTAINER}" r" sed -i '/^\[p2p\]$/a allow_duplicate_ip = true'" f" {CONFIG_PATH}"))
    log("Patched config.toml")
    verify = ssh(
        source,
        f"docker exec {CONTAINER} grep -q '^allow_duplicate_ip = true$' {CONFIG_PATH}",
        check=False,
    )
    if verify.returncode != 0:
        die("Failed to enable allow_duplicate_ip (line not present after patch).")
    restart_node(source)


def disable_duplicate_ip(source: str):
    log(f"Disabling allow_duplicate_ip on {source}")
    ssh(source, (f"docker exec {CONTAINER}" r" sed -i '/^allow_duplicate_ip = true$/d'" f" {CONFIG_PATH}"), check=False)
    log("Restored config.toml")
    verify = ssh(
        source,
        f"docker exec {CONTAINER} grep -q '^allow_duplicate_ip = true$' {CONFIG_PATH}",
        check=False,
    )
    if verify.returncode == 0:
        die("Failed to disable allow_duplicate_ip (line still present).")
    restart_node(source)


def scp_swap_script(target: str, local_script: str):
    log(f"Copying swap script to {target}")
    subprocess.run(
        ["scp", local_script, f"{SSH_USER}@{target}:/tmp/hot_swap_statesync.py"],
        check=True,
    )
    ssh(target, f"docker cp /tmp/hot_swap_statesync.py {CONTAINER}:{SWAP_SCRIPT}")
    docker_exec(target, f"chmod +x {SWAP_SCRIPT}")


def run_hot_swap(target: str, source: str, cleanup: bool):
    cmd = f"python3 {SWAP_SCRIPT} --source {source}"
    if cleanup:
        cmd += " --cleanup"

    log(f"Running remote hot swap on {target} (max {HOT_SWAP_TIMEOUT}s)")
    full = [
        "ssh",
        "-o",
        "ConnectTimeout=10",
        f"{SSH_USER}@{target}",
        f"docker exec {CONTAINER} {cmd}",
    ]
    proc = subprocess.Popen(full, stdout=sys.stdout, stderr=sys.stderr)
    start = time.time()
    last_log = start
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        now = time.time()
        if now - start > HOT_SWAP_TIMEOUT:
            log("Hot swap exceeded time limit; sending SIGTERM to remote script")
            ssh(
                target,
                f"docker exec {CONTAINER} pkill -TERM -f hot_swap_statesync.py",
                check=False,
            )
            time.sleep(5)
            proc.kill()
            die(f"Hot swap timed out after {HOT_SWAP_TIMEOUT}s on {target}")
        if now - last_log >= 60:
            log(f"Hot swap still running... {int(now - start)}s elapsed")
            last_log = now
        time.sleep(5)
    if rc != 0:
        die(f"Hot swap failed on {target} (exit code {rc})")
    log(f"Hot swap succeeded on {target}")


def main():
    parser = argparse.ArgumentParser(
        description="Run a remote hot-swap state-sync via SSH.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Source node hostname/IP to sync from (e.g. mirage.vote)",
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target node hostname/IP to hot-swap (e.g. 146.190.108.140)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete old data on target after verified swap",
    )
    args = parser.parse_args()

    local_script = pathlib.Path(__file__).parent / "hot_swap_statesync.py"
    if not local_script.exists():
        die(f"Local swap script not found: {local_script}")

    log(f"Source: {args.source}")
    log(f"Target: {args.target}")

    wait_for_rpc(args.source)

    error: str | None = None
    cleanup_error: str | None = None

    try:
        enable_duplicate_ip(args.source)
        scp_swap_script(args.target, str(local_script))
        run_hot_swap(args.target, args.source, args.cleanup)
    except SystemExit as exc:
        error = str(exc) or "Hot swap failed"
    finally:
        try:
            disable_duplicate_ip(args.source)
        except SystemExit as exc:
            cleanup_error = str(exc) or "Failed to restore allow_duplicate_ip"

    if error:
        if cleanup_error:
            die(f"{error}; also failed to restore allow_duplicate_ip: {cleanup_error}")
        die(error)
    if cleanup_error:
        die(cleanup_error)

    log("All done")


if __name__ == "__main__":
    main()
