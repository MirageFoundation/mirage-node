#!/usr/bin/env python3
"""
Import all keys from remote server's test keyring to local OS keyring.
Usage: deploy/import_key_to_os.py <remote_host>

Interactively prompts for a name for each key found.
"""

import sys
import os
import subprocess
import json


def main():
    if len(sys.argv) < 2:
        print("Usage: deploy/import_key_to_os.py <remote_host>", file=sys.stderr)
        sys.exit(1)

    remote_host = sys.argv[1]

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bin_path = os.path.join(root_dir, "blockchain", "miraged")

    if not os.path.exists(bin_path):
        print(f"Binary not found: {bin_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Listing keys from remote server {remote_host}...")

    list_cmd = [
        "ssh",
        remote_host,
        "docker exec mirage /opt/mirage/blockchain/miraged keys list --keyring-backend test --home /root/.mirage/node --output json",
    ]

    result = subprocess.run(list_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to list keys: {result.stderr}", file=sys.stderr)
        print(f"Output: {result.stdout}", file=sys.stderr)
        sys.exit(1)

    try:
        keys = json.loads(result.stdout.strip())
    except json.JSONDecodeError as e:
        print(f"Failed to parse keys: {e}", file=sys.stderr)
        sys.exit(1)

    if not keys:
        print("No keys found on remote server")
        sys.exit(0)

    print(f"Found {len(keys)} key(s) to import\n")

    for idx, key in enumerate(keys, 1):
        remote_key_name = key.get("name")
        if not remote_key_name:
            print(f"Skipping key with no name: {key}")
            continue

        address = key.get("address", "unknown")
        print(f"Key {idx}/{len(keys)}: '{remote_key_name}' ({address})")

        while True:
            import_name = input(f"  Enter local name for this key (or 's' to skip): ").strip()
            if import_name.lower() == "s":
                print("  Skipped\n")
                break
            if not import_name:
                print("  Name cannot be empty. Try again or enter 's' to skip.")
                continue

            print(f"  Exporting key '{remote_key_name}'...")

            ssh_cmd = [
                "ssh",
                remote_host,
                f"docker exec mirage /opt/mirage/blockchain/miraged keys export {remote_key_name} --keyring-backend test --home /root/.mirage/node --unsafe --unarmored-hex -y",
            ]

            result = subprocess.run(ssh_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  Export failed: {result.stderr}", file=sys.stderr)
                break

            hex_key = result.stdout.strip()
            if not hex_key:
                print(f"  Export returned empty key", file=sys.stderr)
                break

            print(f"  Importing as '{import_name}' to local OS keyring...")

            import_cmd = [bin_path, "keys", "import-hex", import_name, hex_key, "--keyring-backend", "os"]

            result = subprocess.run(import_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  Import failed: {result.stderr}", file=sys.stderr)
                break

            print(f"  Successfully imported as '{import_name}'\n")
            break

    print("Done!")


if __name__ == "__main__":
    main()
