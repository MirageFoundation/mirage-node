#!/usr/bin/env python3
import getpass
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import tempfile

import requests

import pexpect

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
NODE_DIR = ROOT / "node"
MIRAGED = NODE_DIR / "miraged"

KEYRING_BACKEND = "os"
LOCAL_KEYRING_BACKEND = "test"
LOCAL_KEYRING_HOME = "/root/.mirage/main"
LOCAL_CONTAINER = "mirage"

# Account names
FAUCET_ACCOUNT = "faucet"
VALIDATOR_ACCOUNT = "validator"

# RPC endpoints
LOCAL_RPC_ENDPOINT = "http://127.0.0.1:26657"
REMOTE_RPC_ENDPOINT = "http://159.203.114.27:26657"

# Create a minimal temp config dir for keyring operations (miraged needs config to start)
# Keys are stored in OS credential store, not in this directory
_temp_keyring_home = None
_is_local_mode = False


def get_keyring_backend() -> str:
    """Get keyring backend based on mode"""
    return LOCAL_KEYRING_BACKEND if _is_local_mode else KEYRING_BACKEND


def get_keyring_home() -> str:
    """Get keyring home directory based on mode"""
    global _temp_keyring_home
    if _is_local_mode:
        return LOCAL_KEYRING_HOME
    if _temp_keyring_home is None:
        temp_dir = tempfile.mkdtemp(prefix="mirage_keyring_")
        config_dir = Path(temp_dir) / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "client.toml").write_text('chain-id = "mirage-1"\nkeyring-backend = "os"\n')
        (config_dir / "app.toml").write_text("")
        (config_dir / "config.toml").write_text("")
        _temp_keyring_home = temp_dir
    return _temp_keyring_home


def run_miraged_cmd(cmd: list[str], capture_output: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    """Run miraged command, via docker exec for local mode"""
    bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")
    if _is_local_mode:
        full_cmd = ["docker", "exec", LOCAL_CONTAINER, "/opt/mirage/blockchain/miraged"] + cmd
    else:
        full_cmd = [bin_path] + cmd
    return subprocess.run(full_cmd, capture_output=capture_output, text=True, check=check)


def query_json_rpc(rpc_endpoint: str, cmd: list[str]) -> dict:
    """Query via miraged with --node (uses HTTP internally, no home required)"""
    bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")
    cmd_with_node = [bin_path] + cmd + ["--node", rpc_endpoint, "-o", "json"]
    result = subprocess.run(cmd_with_node, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"Error querying RPC {rpc_endpoint}: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def run_with_pexpect(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Run a command with pexpect, handle keyring password prompt, and return (exit_code, output).
    For local mode (test backend), uses simple subprocess since no password is needed."""
    if _is_local_mode:
        docker_cmd = ["docker", "exec", LOCAL_CONTAINER, "/opt/mirage/blockchain/miraged"] + cmd[1:]
        print(f"==> Running via docker exec...")
        result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        print(output)
        return result.returncode, output

    print("==> Running with pexpect (will handle password prompt)...")
    child = pexpect.spawn(cmd[0], cmd[1:], timeout=timeout, encoding="utf-8")
    output_lines: list[str] = []

    class LogOutput:
        def __init__(self, lines_list: list[str]):
            self.lines_list = lines_list

        def write(self, data: str):
            self.lines_list.append(data)
            sys.stdout.write(data)
            sys.stdout.flush()

        def flush(self):
            sys.stdout.flush()

    child.logfile_read = LogOutput(output_lines)
    child.logfile_send = None

    try:
        index = child.expect(["Password:", "password:", pexpect.EOF, pexpect.TIMEOUT], timeout=min(30, timeout))
        if index < 2:
            print("\n==> Password prompt detected. Enter OS keyring password:")
            password = input("Password: ")
            child.sendline(password)
            child.expect(pexpect.EOF, timeout=timeout)
        elif index == 2:
            pass
        else:
            child.expect(pexpect.EOF, timeout=timeout)
    except pexpect.TIMEOUT:
        output = "".join(output_lines)
        print("\nERROR: Command timed out", file=sys.stderr)
        if output:
            print("\nCommand output so far:", file=sys.stderr)
            print(output, file=sys.stderr)
        try:
            child.close()
        finally:
            return 124, output
    except Exception as e:
        output = "".join(output_lines)
        print(f"\nERROR: {e}", file=sys.stderr)
        if output:
            print("\nCommand output:", file=sys.stderr)
            print(output, file=sys.stderr)
        try:
            child.close()
        finally:
            return 1, output

    # Ensure process is closed
    if child.isalive():
        child.close(force=True)
    else:
        child.close()

    exit_status = child.exitstatus if child.exitstatus is not None else child.signalstatus
    return (exit_status or 0), "".join(output_lines)


def get_current_block_height(rpc_endpoint: str) -> int:
    """Get the current block height from the RPC endpoint"""
    try:
        # Use direct HTTP request to /status endpoint
        response = requests.get(f"{rpc_endpoint}/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            height = int(data.get("result", {}).get("sync_info", {}).get("latest_block_height", "0"))
            return height
    except Exception as e:
        print(f"Warning: Could not get block height: {e}", file=sys.stderr)
    return 0


def key_exists(account_name: str) -> bool:
    """Check if a key exists in the keyring"""
    result = run_miraged_cmd(
        ["keys", "show", account_name, "--keyring-backend", get_keyring_backend(), "--home", get_keyring_home()]
    )
    return result.returncode == 0


def get_address_from_seed(seed: str) -> str:
    """Derive address from seed without adding to keyring (dry-run)"""
    bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")
    temp_name = f"_temp_check_{int(time.time())}"
    cmd = [
        "keys",
        "add",
        temp_name,
        "--recover",
        "--dry-run",
        "--keyring-backend",
        get_keyring_backend(),
        "--home",
        get_keyring_home(),
    ]

    if _is_local_mode:
        full_cmd = ["docker", "exec", "-i", LOCAL_CONTAINER, "/opt/mirage/blockchain/miraged"] + cmd
    else:
        full_cmd = [bin_path] + cmd

    process = subprocess.Popen(
        full_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr = process.communicate(input=seed + "\n")

    if process.returncode != 0:
        return ""

    for line in stdout.splitlines():
        if line.startswith("address:"):
            return line.split(":", 1)[1].strip()
    return ""


def find_key_by_address(target_address: str) -> str:
    """Find key name in keyring that has the given address"""
    list_result = run_miraged_cmd(
        ["keys", "list", "--keyring-backend", get_keyring_backend(), "--home", get_keyring_home()]
    )

    if list_result.returncode != 0:
        return ""

    key_names = []
    for line in list_result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if parts:
            key_name = parts[0]
            if key_name not in ["-", "address:", "pubkey:", "type:"] and key_name not in key_names:
                key_names.append(key_name)

    for key_name in key_names:
        addr_result = run_miraged_cmd(
            ["keys", "show", key_name, "-a", "--keyring-backend", get_keyring_backend(), "--home", get_keyring_home()]
        )
        if addr_result.returncode == 0:
            address = addr_result.stdout.strip()
            if address == target_address:
                return key_name

    return ""


def import_key_from_seed(account_name: str, seed: str) -> str:
    """Import a key from seed into keyring. Returns the actual key name to use."""
    bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")

    if key_exists(account_name):
        print(f"Key '{account_name}' already exists in keyring")
        return account_name

    address = get_address_from_seed(seed)
    if address:
        existing_key = find_key_by_address(address)
        if existing_key:
            print(f"Address {address} already exists in keyring as '{existing_key}'")
            print(f"  Will use existing key '{existing_key}' instead of '{account_name}'")
            return existing_key

    print(f"\n==> Importing {account_name} key from seed...")
    if not _is_local_mode:
        print("==> You will be prompted for a keyring password (OS backend)")
    cmd = [
        "keys",
        "add",
        account_name,
        "--recover",
        "--keyring-backend",
        get_keyring_backend(),
        "--home",
        get_keyring_home(),
    ]

    if _is_local_mode:
        full_cmd = ["docker", "exec", "-i", LOCAL_CONTAINER, "/opt/mirage/blockchain/miraged"] + cmd
    else:
        full_cmd = [bin_path] + cmd

    process = subprocess.Popen(
        full_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout, stderr = process.communicate(input=seed + "\n\n")

    if process.returncode != 0:
        if "duplicated address" in stderr.lower() or "duplicate address" in stderr.lower():
            if address:
                existing_key = find_key_by_address(address)
                if existing_key:
                    print(f"Address {address} already exists in keyring as '{existing_key}'")
                    print(f"  Will use existing key '{existing_key}' instead of '{account_name}'")
                    return existing_key
        print(f"Error importing key: {stderr}", file=sys.stderr)
        if not _is_local_mode:
            print(f"Note: OS backend may require interactive password entry", file=sys.stderr)
        sys.exit(1)

    print(f"Key '{account_name}' imported successfully")
    return account_name


def main():
    # Parse args with optional --dry-run
    args = sys.argv[1:]
    dry_run = False
    if "--dry-run" in args:
        args.remove("--dry-run")
        dry_run = True

    if len(args) < 2:
        print("Usage: python3 submit_proposal.py <local|remote> <proposal_file_or_name> [--dry-run]", file=sys.stderr)
        print("\nExample:", file=sys.stderr)
        print("  python3 submit_proposal.py local proposal_make_admin.json", file=sys.stderr)
        print("  python3 submit_proposal.py remote proposal_make_admin.json", file=sys.stderr)
        print("  python3 submit_proposal.py local scripts/proposals/proposal_change_params.json", file=sys.stderr)
        print(
            "  python3 submit_proposal.py local scripts/proposals/proposal_upgrade_1_2.json --dry-run", file=sys.stderr
        )
        print("\nAvailable proposals:", file=sys.stderr)
        proposals_dir = SCRIPTS_DIR / "proposals"
        if proposals_dir.exists():
            for p in sorted(proposals_dir.glob("*.json")):
                print(f"  - {p.name}", file=sys.stderr)
        print(f"\nLocal endpoint: {LOCAL_RPC_ENDPOINT} (Docker container)")
        print(f"Remote endpoint: {REMOTE_RPC_ENDPOINT}")
        return 1

    mode = args[0].lower()
    if mode not in ("local", "remote"):
        print(f"ERROR: Mode must be 'local' or 'remote', got '{mode}'", file=sys.stderr)
        return 1

    global _is_local_mode
    if mode == "local":
        rpc_endpoint = LOCAL_RPC_ENDPOINT
        _is_local_mode = True
        print(f"==> Using test keyring at {LOCAL_KEYRING_HOME}")
    else:
        rpc_endpoint = REMOTE_RPC_ENDPOINT
        _is_local_mode = False
        print(f"==> Using OS keyring backend (keys stored in OS credential store)")

    arg = args[1]
    # Accept direct file path first (relative or absolute)
    p = Path(arg)
    proposal_file: Path
    if p.exists() and p.is_file():
        proposal_file = p
    else:
        # Try proposals/ subdirectory relative to repo, then scripts/ root
        proposal_file = SCRIPTS_DIR / "proposals" / arg
        if not proposal_file.exists():
            proposal_file = SCRIPTS_DIR / arg
        if not proposal_file.exists():
            print(f"Error: proposal file not found: {arg}", file=sys.stderr)
            return 1

    # Preprocess software-upgrade proposals with T+N height placeholder
    # Format: "T+60" means current_height + 60 blocks
    resolved_height: str | None = None
    proposal_json: dict | None = None
    try:
        with open(proposal_file, "r", encoding="utf-8") as f:
            proposal_json = json.load(f)
        msgs = proposal_json.get("messages") or []
        if msgs:
            msg0 = msgs[0]
            mtype = msg0.get("@type", "")
            plan = msg0.get("plan") or {}
            height_val = plan.get("height")
            if (
                (
                    mtype.endswith("cosmos.upgrade.v1beta1.MsgSoftwareUpgrade")
                    or mtype == "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade"
                )
                and isinstance(height_val, str)
                and height_val.startswith("T+")
            ):
                try:
                    plus_n = int(height_val[2:])
                except Exception:
                    print(f"ERROR: Invalid T+N placeholder: {height_val}", file=sys.stderr)
                    return 1
                current_h = get_current_block_height(rpc_endpoint)
                if current_h <= 0:
                    print(f"ERROR: Could not determine current block height from {rpc_endpoint}", file=sys.stderr)
                    return 1
                new_h = current_h + plus_n
                plan["height"] = str(new_h)
                resolved_height = str(new_h)
                msg0["plan"] = plan
                proposal_json["messages"][0] = msg0
                print(f"==> Resolved upgrade height: {current_h} + {plus_n} = {new_h}")
                # Write to temp file and use that for submission
                tmpdir = tempfile.mkdtemp(prefix="mirage_upgrade_")
                tmp_path = Path(tmpdir) / f"proposal_upg_{new_h}.json"
                with open(tmp_path, "w", encoding="utf-8") as wf:
                    json.dump(proposal_json, wf, ensure_ascii=False, indent=2)
                proposal_file = tmp_path
    except Exception:
        # Best-effort preprocessing; continue with original file on parse errors
        pass

    print("=" * 80)
    print(f"SUBMITTING PROPOSAL: {proposal_file}")
    print(f"RPC ENDPOINT: {rpc_endpoint}")
    print("=" * 80)

    # Always display the full proposal content that will be submitted
    try:
        with open(proposal_file, "r", encoding="utf-8") as f:
            try:
                _full_proposal_obj = json.load(f)
                print("\n==> FULL PROPOSAL JSON:")
                print(json.dumps(_full_proposal_obj, ensure_ascii=False, indent=2))
            except Exception:
                f.seek(0)
                print("\n==> FULL PROPOSAL (raw file contents):")
                print(f.read())
    except Exception as e:
        print(f"\nWarning: Could not read proposal file for display: {e}")

    if dry_run:
        try:
            if proposal_json is None:
                with open(proposal_file, "r", encoding="utf-8") as f:
                    proposal_json = json.load(f)
            msgs = proposal_json.get("messages") or []
            deposit = proposal_json.get("deposit", "")
            title = proposal_json.get("title", "")
            summary = proposal_json.get("summary", "")
            print("\n==> DRY RUN")
            print(f"Title: {title}")
            print(f"Summary: {summary}")
            print(f"Deposit: {deposit}")
            if msgs:
                m0 = msgs[0]
                print(f"Message[0] type: {m0.get('@type','')}")
                plan = m0.get("plan") or {}
                print(f"Plan name: {plan.get('name','')}")
                print(f"Plan height: {plan.get('height','')}{' (resolved)' if resolved_height else ''}")
            bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")
            print("\nCommand that would run:")
            print(
                f"{bin_path} tx gov submit-proposal {proposal_file} "
                f"--from {FAUCET_ACCOUNT} --keyring-backend {get_keyring_backend()} "
                f"--home {get_keyring_home()} --node {rpc_endpoint} --broadcast-mode sync "
                f"--gas 275000 --fees 275000umirage --yes"
            )
            print("\nNo transactions broadcast due to --dry-run.")
        except Exception as e:
            print(f"ERROR during dry-run: {e}", file=sys.stderr)
            return 1
        return 0

    # Initialize keyring if needed
    bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")
    run_miraged_cmd(["keys", "list", "--keyring-backend", get_keyring_backend(), "--home", get_keyring_home()])

    # FIRST: Check for validator keys before doing anything else
    print(f"\n==> Querying validators from chain...")
    validators_data = query_json_rpc(rpc_endpoint, ["q", "staking", "validators"])
    chain_validators = validators_data.get("validators", [])

    if not chain_validators:
        print("WARNING: No validators found on chain")
    else:
        print(f"Found {len(chain_validators)} validator(s) on chain")

    # Get all keys from keyring (text format only - JSON not supported)
    list_result = run_miraged_cmd(
        ["keys", "list", "--keyring-backend", get_keyring_backend(), "--home", get_keyring_home()]
    )

    # Parse text output - format is:
    # - address: mirage1...
    #   name: keyname
    #   type: local
    #   pubkey: '{"@type":...'
    address_to_keyname = {}
    if list_result.returncode == 0:
        current_address = None
        for line in list_result.stdout.splitlines():
            line = line.strip()
            if line.startswith("- address:") or (line.startswith("address:") and not current_address):
                current_address = line.split(":", 1)[1].strip()
            elif line.startswith("name:") and current_address:
                name = line.split(":", 1)[1].strip()
                address_to_keyname[current_address] = name
                current_address = None

    print(f"Found {len(address_to_keyname)} key(s) in keyring")

    # Calculate total voting power and track which validators we control
    total_voting_power = 0
    controlled_voting_power = 0
    validator_accounts = []
    validators_controlled = []
    validators_not_controlled = []

    for validator in chain_validators:
        val_operator_addr = validator.get("operator_address", "")
        if not val_operator_addr:
            continue

        try:
            val_details = query_json_rpc(rpc_endpoint, ["q", "staking", "validator", val_operator_addr])
            val_info = val_details.get("validator", {})
            moniker = val_info.get("description", {}).get("moniker", "")
            tokens = int(val_info.get("tokens", "0"))
            status = val_info.get("status", "")

            if status != "BOND_STATUS_BONDED":
                continue

            total_voting_power += tokens
            found_key = False

            for key_addr, key_name in address_to_keyname.items():
                try:
                    delegation_cmd = [
                        bin_path,
                        "q",
                        "staking",
                        "delegation",
                        key_addr,
                        val_operator_addr,
                        "--node",
                        rpc_endpoint,
                        "-o",
                        "json",
                    ]
                    delegation_result = subprocess.run(delegation_cmd, capture_output=True, text=True, check=False)

                    if delegation_result.returncode == 0:
                        delegation = json.loads(delegation_result.stdout)
                        if delegation.get("delegation_response"):
                            if key_name not in validator_accounts:
                                validator_accounts.append(key_name)
                                controlled_voting_power += tokens
                                validators_controlled.append((moniker, tokens, key_name))
                                found_key = True
                                break
                except Exception:
                    pass

            if not found_key:
                validators_not_controlled.append((moniker, tokens, val_operator_addr))

        except Exception as e:
            print(f"Error checking validator {val_operator_addr}: {e}")

    # Display voting power summary
    print(f"\n{'=' * 60}")
    print("VOTING POWER ANALYSIS")
    print(f"{'=' * 60}")
    print(f"Total validators: {len(chain_validators)}")
    print(f"Total voting power: {total_voting_power:,} tokens")

    if validators_controlled:
        print(f"\nValidators we control ({len(validators_controlled)}):")
        for moniker, tokens, key_name in validators_controlled:
            pct = (tokens / total_voting_power * 100) if total_voting_power > 0 else 0
            print(f"  [OK] {moniker}: {tokens:,} tokens ({pct:.1f}%) - key: {key_name}")

    if validators_not_controlled:
        print(f"\nValidators we DO NOT control ({len(validators_not_controlled)}):")
        for moniker, tokens, addr in validators_not_controlled:
            pct = (tokens / total_voting_power * 100) if total_voting_power > 0 else 0
            print(f"  [!!] {moniker}: {tokens:,} tokens ({pct:.1f}%)")

    controlled_pct = (controlled_voting_power / total_voting_power * 100) if total_voting_power > 0 else 0
    print(f"\nControlled voting power: {controlled_voting_power:,} / {total_voting_power:,} ({controlled_pct:.1f}%)")

    # Check if we have majority
    if controlled_pct < 66.67:
        print(f"\n{'=' * 60}")
        print("ERROR: INSUFFICIENT VOTING POWER")
        print(f"{'=' * 60}")
        print(f"You control {controlled_pct:.1f}% of voting power.")
        print(f"You need at least 66.67% (2/3 majority) to pass proposals.")
        if validators_not_controlled:
            print(f"\nYou are missing keys for {len(validators_not_controlled)} validator(s).")
            print("Add the missing validator keys to your keyring to proceed.")
        return 1

    print(f"\n[OK] You control {controlled_pct:.1f}% of voting power (>66.67% required)")

    # If no validators found, prompt for one
    if not validator_accounts:
        print(f"\n==> No validator keys found in keyring")
        print(f"==> Enter seed phrase for '{VALIDATOR_ACCOUNT}' account (will be used to vote):")
        validator_seed = getpass.getpass("Seed: ").strip()
        if not validator_seed:
            print("ERROR: Validator seed is required", file=sys.stderr)
            return 1
        actual_key_name = import_key_from_seed(VALIDATOR_ACCOUNT, validator_seed)
        validator_accounts = [actual_key_name]

    print(f"\n==> Will vote with {len(validator_accounts)} validator account(s)")

    # SECOND: Now check if faucet key exists, prompt if not
    if not key_exists(FAUCET_ACCOUNT):
        print(f"\n==> Key '{FAUCET_ACCOUNT}' not found in keyring")
        print(f"==> Enter seed phrase for '{FAUCET_ACCOUNT}' account (will be used to submit proposal):")
        faucet_seed = getpass.getpass("Seed: ").strip()
        if not faucet_seed:
            print("ERROR: Faucet seed is required", file=sys.stderr)
            return 1
        import_key_from_seed(FAUCET_ACCOUNT, faucet_seed)
    else:
        print(f"Key '{FAUCET_ACCOUNT}' found in keyring")
        faucet_addr_result = run_miraged_cmd(
            [
                "keys",
                "show",
                FAUCET_ACCOUNT,
                "-a",
                "--keyring-backend",
                get_keyring_backend(),
                "--home",
                get_keyring_home(),
            ]
        )
        if faucet_addr_result.returncode == 0:
            faucet_addr = faucet_addr_result.stdout.strip()
            try:
                balance_result = query_json_rpc(rpc_endpoint, ["q", "bank", "balances", faucet_addr])
                balances = balance_result.get("balances", [])
                total_needed = 1275000  # 1000000 deposit + 275000 fees
                if balances:
                    amt_str = balances[0].get("amount", "0")
                    denom = balances[0].get("denom", "")
                    amt_int = int(amt_str) if amt_str.isdigit() else 0
                    print(f"  Balance: {amt_int}{denom}")
                    if amt_int < total_needed:
                        print(f"\nERROR: Insufficient balance!", file=sys.stderr)
                        print(f"  Account: {faucet_addr}", file=sys.stderr)
                        print(f"  Current: {amt_int}{denom}", file=sys.stderr)
                        print(f"  Required: {total_needed}umirage (1000000 deposit + 275000 fees)", file=sys.stderr)
                        print(f"  Please fund the account before submitting proposals.", file=sys.stderr)
                        return 1
                else:
                    print(f"  WARNING: Account {faucet_addr} has no balance!")
                    print(f"  Required: {total_needed}umirage (1000000 deposit + 275000 fees)")
                    print(f"  Please fund the account before submitting proposals.")
                    return 1
            except Exception as e:
                print(f"  Could not check balance: {e}")

    # Confirm submission if proposal is not expedited
    is_expedited = False
    try:
        # Reuse already loaded proposal_json if available, otherwise load it
        if proposal_json is None:
            with open(proposal_file, "r", encoding="utf-8") as f:
                proposal_json = json.load(f)
        is_expedited = bool(proposal_json.get("expedited", False))
    except Exception:
        # If parsing fails, treat as not expedited to be safe
        is_expedited = False

    # Final safety check: must have majority voting power
    if controlled_pct < 66.67:
        print(f"\nERROR: Cannot proceed without majority voting power ({controlled_pct:.1f}% < 66.67%)")
        return 1

    # Confirmation: local = Enter, remote = type "remote"
    try:
        if _is_local_mode:
            expedited_note = " (expedited)" if is_expedited else " (NOT expedited)"
            input(f"\nPress Enter to submit proposal{expedited_note} and vote (Ctrl+C to abort)... ")
        else:
            expedited_note = " (expedited)" if is_expedited else " (NOT expedited)"
            print(f"\n{'=' * 60}")
            print("REMOTE EXECUTION CONFIRMATION")
            print(f"{'=' * 60}")
            print(f"You are about to submit a proposal{expedited_note} to REMOTE chain.")
            print(f"Endpoint: {rpc_endpoint}")
            print(f"Controlled voting power: {controlled_pct:.1f}%")
            confirm = input("\nType 'remote' to confirm and proceed: ").strip()
            if confirm != "remote":
                print("Aborted: confirmation not received.")
                return 1
    except KeyboardInterrupt:
        print("\nAborted by user.")
        return 1

    # Submit proposal (signed locally, broadcast via RPC)
    print(f"\n==> Submitting proposal via RPC...")
    if not _is_local_mode:
        print("==> You will be prompted for keyring password (OS backend)")

    # For local mode, copy proposal file into container
    proposal_path_for_cmd = str(proposal_file)
    if _is_local_mode:
        container_proposal_path = "/tmp/proposal.json"
        subprocess.run(["docker", "cp", str(proposal_file), f"{LOCAL_CONTAINER}:{container_proposal_path}"], check=True)
        proposal_path_for_cmd = container_proposal_path

    submit_cmd = [
        bin_path,
        "tx",
        "gov",
        "submit-proposal",
        proposal_path_for_cmd,
        "--from",
        FAUCET_ACCOUNT,
        "--keyring-backend",
        get_keyring_backend(),
        "--home",
        get_keyring_home(),
        "--node",
        rpc_endpoint,
        "--broadcast-mode",
        "sync",
        "--gas",
        "275000",
        "--fees",
        "275000umirage",
        "--yes",
    ]

    exit_status, output = run_with_pexpect(submit_cmd, timeout=60)
    if exit_status != 0:
        print(f"\nERROR: Proposal submission failed with exit code {exit_status}", file=sys.stderr)
        if output:
            print("\nCommand output:", file=sys.stderr)
            print(output, file=sys.stderr)
        else:
            print("No output captured. This might indicate the command failed silently.", file=sys.stderr)
        sys.exit(1)

    print("✓ Proposal submitted (check output above for txhash)")
    time.sleep(5)

    # Get proposal ID (via RPC)
    proposals = query_json_rpc(rpc_endpoint, ["q", "gov", "proposals"])

    if not proposals.get("proposals"):
        print("No proposals found", file=sys.stderr)
        return 1

    proposal_id = proposals["proposals"][-1]["id"]
    proposal = proposals["proposals"][-1]

    print(f"\n{'=' * 80}")
    print(f"PROPOSAL #{proposal_id}")
    print(f"{'=' * 80}")
    print(f"Title: {proposal.get('title', 'N/A')}")
    print(f"Status: {proposal.get('status', 'N/A')}")
    print(f"Expedited: {proposal.get('expedited', False)}")
    print(f"Voting ends: {proposal.get('voting_end_time', 'N/A')}")

    if proposal.get("messages"):
        print(f"\nMessages:")
        for msg in proposal["messages"]:
            print(f"  - {msg.get('type', msg.get('@type', 'unknown'))}")

    # Check if proposal needs more deposit
    status = proposal.get("status", "")
    if status == "PROPOSAL_STATUS_DEPOSIT_PERIOD":
        # Get governance params to check minimum deposit
        gov_params = query_json_rpc(rpc_endpoint, ["q", "gov", "params"])
        params = gov_params.get("params", {})

        # Check if expedited (needs expedited_min_deposit) or regular (needs min_deposit)
        is_expedited = proposal.get("expedited", False)
        if is_expedited:
            min_deposit_list = params.get("expedited_min_deposit", [])
        else:
            min_deposit_list = params.get("min_deposit", [])

        min_deposit_amount = 0
        for dep in min_deposit_list:
            if dep.get("denom") == "umirage":
                min_deposit_amount = int(dep.get("amount", "0"))
                break

        # Get current total deposit
        total_deposit_list = proposal.get("total_deposit", [])
        current_deposit_amount = 0
        for dep in total_deposit_list:
            if dep.get("denom") == "umirage":
                current_deposit_amount = int(dep.get("amount", "0"))
                break

        if current_deposit_amount < min_deposit_amount:
            additional_needed = min_deposit_amount - current_deposit_amount
            print(f"\n{'=' * 80}")
            print("DEPOSIT")
            print(f"{'=' * 80}")
            print(f"Current deposit: {current_deposit_amount}umirage")
            print(f"Minimum deposit: {min_deposit_amount}umirage")
            print(f"Additional needed: {additional_needed}umirage")
            print(f"\n==> Depositing additional {additional_needed}umirage...")
            if not _is_local_mode:
                print("==> You will be prompted for keyring password (OS backend)")

            deposit_cmd = [
                bin_path,
                "tx",
                "gov",
                "deposit",
                str(proposal_id),
                f"{additional_needed}umirage",
                "--from",
                FAUCET_ACCOUNT,
                "--keyring-backend",
                get_keyring_backend(),
                "--home",
                get_keyring_home(),
                "--node",
                rpc_endpoint,
                "--broadcast-mode",
                "sync",
                "--gas",
                "200000",
                "--fees",
                "200000umirage",
                "--yes",
            ]

            exit_status, output = run_with_pexpect(deposit_cmd, timeout=60)
            if exit_status != 0:
                print(f"\nERROR: Deposit failed with exit code {exit_status}", file=sys.stderr)
                if output:
                    print("\nCommand output:", file=sys.stderr)
                    print(output, file=sys.stderr)
                sys.exit(1)

            print(f"✓ Additional deposit submitted")
            time.sleep(5)

            # Refresh proposal status
            proposal = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", str(proposal_id)])["proposal"]
            status = proposal.get("status", "")

    # Only vote if proposal is in voting period
    if status != "PROPOSAL_STATUS_VOTING_PERIOD":
        print(f"\n{'=' * 80}")
        print("SKIPPING VOTE")
        print(f"{'=' * 80}")
        print(f"Proposal status: {status}")
        if status == "PROPOSAL_STATUS_DEPOSIT_PERIOD":
            print("Proposal is still in deposit period. It will enter voting period once minimum deposit is reached.")
        else:
            print("Proposal is not in voting period yet.")
        return 0

    print(f"\n{'=' * 80}")
    print("VOTING")
    print(f"{'=' * 80}")

    # Filter validator accounts to only those that exist on-chain
    valid_validator_accounts = []
    for account_name in validator_accounts:
        try:
            addr_result = run_miraged_cmd(
                [
                    "keys",
                    "show",
                    account_name,
                    "--keyring-backend",
                    get_keyring_backend(),
                    "--home",
                    get_keyring_home(),
                    "-a",
                ]
            )
            if addr_result.returncode != 0:
                continue
            account_addr = addr_result.stdout.strip()

            # Check if account exists on-chain by checking if it has any balance
            balance_result = query_json_rpc(rpc_endpoint, ["q", "bank", "balances", account_addr])
            balances = balance_result.get("balances", []) if balance_result else []

            # Account exists if it has any balance (even 0 is stored as an entry)
            # Or we can check total supply which should be non-empty for initialized accounts
            if balances and len(balances) > 0:
                valid_validator_accounts.append(account_name)
                print(f"✓ {account_name} ({account_addr[:20]}...) exists on-chain")
            else:
                print(
                    f"⊘ Skipping {account_name} ({account_addr[:20]}...) - not initialized on-chain (no balance record)"
                )
        except Exception as e:
            print(f"⊘ Skipping {account_name} - error checking account: {e}")

    if not valid_validator_accounts:
        print("\nERROR: No valid validator accounts found to vote with", file=sys.stderr)
        sys.exit(1)

    print(f"\nVoting with {len(valid_validator_accounts)} validator account(s)...")

    # Vote with all valid validator accounts
    for account_name in valid_validator_accounts:
        print(f"\nVoting with {account_name}...")
        if not _is_local_mode:
            print("==> You will be prompted for keyring password (OS backend)")

        vote_cmd = [
            bin_path,
            "tx",
            "gov",
            "vote",
            str(proposal_id),
            "yes",
            "--from",
            account_name,
            "--keyring-backend",
            get_keyring_backend(),
            "--home",
            get_keyring_home(),
            "--node",
            rpc_endpoint,
            "--broadcast-mode",
            "sync",
            "--gas",
            "200000",
            "--fees",
            "200000umirage",
            "--yes",
        ]

        exit_status, output = run_with_pexpect(vote_cmd, timeout=60)
        if exit_status != 0:
            print(f"\n⚠ Warning: Vote failed with exit code {exit_status}", file=sys.stderr)
            if output:
                print("\nCommand output:", file=sys.stderr)
                print(output, file=sys.stderr)
            print(f"⊘ {account_name} vote failed (continuing with remaining validators)", file=sys.stderr)
        else:
            print(f"✓ {account_name} voted YES")

        # Wait for vote to be committed
        time.sleep(3)

    # Poll for proposal status until voting ends and we have a verdict
    print(f"\n{'=' * 80}")
    print("POLLING FOR RESULTS")
    print(f"{'=' * 80}")

    def _to_int(s: str) -> int:
        try:
            return int(s)
        except Exception:
            try:
                return int(float(s))
            except Exception:
                return 0

    def parse_time(time_str: str) -> float:
        """Parse ISO 8601 time string to Unix timestamp"""
        try:
            # Remove timezone info if present (e.g., "2025-11-04T05:39:17.496029999Z")
            time_str_clean = time_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(time_str_clean)
            return dt.timestamp()
        except Exception:
            return 0

    def is_final_status(status: str) -> bool:
        """Check if proposal has reached a final status"""
        final_statuses = [
            "PROPOSAL_STATUS_PASSED",
            "PROPOSAL_STATUS_REJECTED",
            "PROPOSAL_STATUS_FAILED",
        ]
        return status in final_statuses

    # Get initial proposal details
    prop_details = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", proposal_id])
    current_proposal = prop_details["proposal"]
    status = current_proposal.get("status", "UNKNOWN")
    voting_end_time_str = current_proposal.get("voting_end_time", "")
    voting_end_timestamp = parse_time(voting_end_time_str) if voting_end_time_str else 0

    # Sleep until voting end time
    if voting_end_timestamp > 0:
        current_timestamp = time.time()
        sleep_duration = voting_end_timestamp - current_timestamp
        if sleep_duration > 0:
            print(f"Waiting until voting ends ({voting_end_time_str})...")
            print(f"Sleeping for {sleep_duration:.1f} seconds...")
            time.sleep(sleep_duration)
        else:
            print(f"Voting period has already ended (was {voting_end_time_str})")
    else:
        print("Warning: Could not determine voting end time, starting immediate polling")

    # Now poll every second for up to 10 times
    print(f"\nPolling for final result (up to 10 seconds)...")
    poll_count = 0
    max_polls = 10

    while poll_count < max_polls:
        try:
            # Get current proposal status
            prop_details = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", proposal_id])
            current_proposal = prop_details["proposal"]
            status = current_proposal.get("status", "UNKNOWN")

            # Get tally
            tally_result = query_json_rpc(rpc_endpoint, ["q", "gov", "tally", proposal_id])
            tally = tally_result.get("tally", {})

            yes_weight = _to_int(tally.get("yes_count", "0"))
            no_weight = _to_int(tally.get("no_count", "0"))
            abstain_weight = _to_int(tally.get("abstain_count", "0"))
            veto_weight = _to_int(tally.get("no_with_veto_count", "0"))
            total_voted = yes_weight + no_weight + abstain_weight + veto_weight
            effective_total = yes_weight + no_weight + veto_weight

            # Get total voting power
            validators = query_json_rpc(rpc_endpoint, ["q", "staking", "validators"])
            total_power = sum(int(v.get("tokens", "0")) for v in validators.get("validators", []))

            # Print current status
            if total_power > 0:
                pct = (effective_total / total_power) * 100.0
                status_line = f"\rPoll {poll_count + 1}/{max_polls}: Status: {status} | YES: {yes_weight} | NO: {no_weight} | ABSTAIN: {abstain_weight} | VETO: {veto_weight} | Voted: {effective_total}/{total_power} ({pct:.2f}%)"
            else:
                status_line = f"\rPoll {poll_count + 1}/{max_polls}: Status: {status} | YES: {yes_weight} | NO: {no_weight} | ABSTAIN: {abstain_weight} | VETO: {veto_weight}"
            print(status_line, end="", flush=True)

            # Check if we have a final verdict
            if is_final_status(status):
                print()  # New line after status
                print(f"\n{'=' * 80}")
                print("FINAL RESULT")
                print(f"{'=' * 80}")
                print(f"Status: {status}")

                # Get and display block height when proposal passed
                if status == "PROPOSAL_STATUS_PASSED":
                    block_height = get_current_block_height(rpc_endpoint)
                    if block_height > 0:
                        print(f"\n{'=' * 80}")
                        print(f"PROPOSAL PASSED AT BLOCK HEIGHT: {block_height}")
                        print(f"{'=' * 80}")
                    else:
                        print("\n(Block height not available)")

                failed_reason = current_proposal.get("failed_reason", "")
                if failed_reason:
                    print(f"Failed reason: {failed_reason}")

                # Show final tally
                print(f"\nFinal Tally:")
                print(f"  YES:    {yes_weight}")
                print(f"  NO:     {no_weight}")
                print(f"  ABSTAIN: {abstain_weight}")
                print(f"  VETO:   {veto_weight}")
                if total_power > 0:
                    yes_pct = (yes_weight / total_power) * 100.0
                    no_pct = (no_weight / total_power) * 100.0
                    veto_pct = (veto_weight / total_power) * 100.0
                    print(f"\nPercentages (of total voting power):")
                    print(f"  YES:    {yes_pct:.2f}%")
                    print(f"  NO:     {no_pct:.2f}%")
                    print(f"  VETO:   {veto_pct:.2f}%")

                # Show balances for mint recipient if present
                try:
                    msgs = current_proposal.get("messages", []) or []
                    for m in msgs:
                        recipient = m.get("recipient") or m.get("to_address") or ""
                        if recipient:
                            print(f"\nRecipient: {recipient}")
                            balance = query_json_rpc(rpc_endpoint, ["q", "bank", "balances", recipient])
                            balances = balance.get("balances", [])
                            if balances:
                                print("Balances:")
                                for b in balances:
                                    print(f"  - {b.get('amount', '0')}{b.get('denom', '')}")
                except Exception:
                    pass

                break

            poll_count += 1
            if poll_count < max_polls:
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n\nPolling interrupted by user")
            break
        except Exception as e:
            print(f"\nError polling proposal status: {e}")
            poll_count += 1
            if poll_count < max_polls:
                time.sleep(1)
            continue

    # If we didn't get a final status, show current status
    if not is_final_status(status):
        print()  # New line
        print(f"\nPolling completed. Final status not yet available:")
        print(f"Status: {status}")
        print(f"Check again later with:")
        print(f"  ./blockchain/miraged q gov proposal {proposal_id} --node {rpc_endpoint}")
    else:
        print(f"\nCheck status with:")
        print(f"  ./blockchain/miraged q gov proposal {proposal_id} --node {rpc_endpoint}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
