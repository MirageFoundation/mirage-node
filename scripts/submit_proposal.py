#!/usr/bin/env python3
import getpass
import json
import logging
import re
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
BLOCKCHAIN_DIR = ROOT / "blockchain"
MIRAGED = BLOCKCHAIN_DIR / "miraged"

KEYRING_BACKEND = "os"
LOCAL_KEYRING_BACKEND = "test"
LOCAL_KEYRING_HOME = "/root/.mirage/node"
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

# Logging setup
LOG_DIR = Path.home() / ".mirage" / "logs" / "submit_proposal"
_log_file: Path | None = None
_logger: logging.Logger | None = None


def setup_logging() -> logging.Logger:
    """Setup logging to file. Returns logger instance."""
    global _log_file, _logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file = LOG_DIR / f"proposal_{timestamp}.log"

    _logger = logging.getLogger("submit_proposal")
    _logger.setLevel(logging.DEBUG)

    # File handler - all debug info
    fh = logging.FileHandler(_log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    _logger.addHandler(fh)

    return _logger


def log(msg: str) -> None:
    """Log to file only."""
    if _logger:
        _logger.info(msg)


def log_debug(msg: str) -> None:
    """Log debug info to file only."""
    if _logger:
        _logger.debug(msg)


def info(msg: str) -> None:
    """Print to stdout and log to file."""
    print(msg)
    if _logger:
        _logger.info(msg)


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
    log_debug(f"Running: {' '.join(full_cmd)}")
    result = subprocess.run(full_cmd, capture_output=capture_output, text=True, check=check)
    if result.stdout:
        log_debug(f"stdout: {result.stdout[:500]}")
    if result.stderr:
        log_debug(f"stderr: {result.stderr[:500]}")
    return result


def query_json_rpc(rpc_endpoint: str, cmd: list[str]) -> dict:
    """Query via miraged with --node (uses HTTP internally, no home required)"""
    bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")
    cmd_with_node = [bin_path] + cmd + ["--node", rpc_endpoint, "-o", "json"]
    log_debug(f"Query: {' '.join(cmd_with_node)}")
    result = subprocess.run(cmd_with_node, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        log(f"RPC query failed: {result.stderr}")
        print(f"ERROR: RPC query failed", file=sys.stderr)
        sys.exit(1)
    log_debug(f"Response: {result.stdout[:500]}...")
    return json.loads(result.stdout)


def estimate_gas_for_proposal(proposal_json: dict, buffer_percent: float = 50.0) -> int:
    """Estimate gas needed for a proposal based on message count."""
    msgs = proposal_json.get("messages", [])
    num_messages = len(msgs) if msgs else 1
    estimated_gas = 100000 + (num_messages * 75000)
    gas_with_buffer = int(estimated_gas * (1 + buffer_percent / 100))
    log_debug(f"Gas estimate: {estimated_gas} ({num_messages} msgs) + {buffer_percent}% buffer = {gas_with_buffer}")
    return gas_with_buffer


def estimate_gas_for_vote(buffer_percent: float = 50.0) -> int:
    """Estimate gas needed for a vote transaction.

    Returns:
        Estimated gas with buffer applied
    """
    # Votes are simple transactions, typically ~100000 gas
    base_gas = 100000
    gas_with_buffer = int(base_gas * (1 + buffer_percent / 100))
    return gas_with_buffer


def estimate_gas_for_deposit(buffer_percent: float = 50.0) -> int:
    """Estimate gas needed for a deposit transaction.

    Returns:
        Estimated gas with buffer applied
    """
    # Deposits need ~170000 gas based on observed usage
    base_gas = 170000
    gas_with_buffer = int(base_gas * (1 + buffer_percent / 100))
    return gas_with_buffer


def run_with_pexpect(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Run a command with pexpect, handle keyring password prompt, and return (exit_code, output).
    For local mode (test backend), uses simple subprocess since no password is needed."""
    if _is_local_mode:
        docker_cmd = ["docker", "exec", LOCAL_CONTAINER, "/opt/mirage/blockchain/miraged"] + cmd[1:]
        log_debug(f"Docker exec: {' '.join(docker_cmd)}")
        result = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        log_debug(f"Output: {output}")
        return result.returncode, output

    log_debug(f"Running with pexpect: {' '.join(cmd)}")
    child = pexpect.spawn(cmd[0], cmd[1:], timeout=timeout, encoding="utf-8")
    output_lines: list[str] = []

    class LogOutput:
        def __init__(self, lines_list: list[str]):
            self.lines_list = lines_list

        def write(self, data: str):
            self.lines_list.append(data)

        def flush(self):
            pass

    child.logfile_read = LogOutput(output_lines)
    child.logfile_send = None

    try:
        index = child.expect(["Password:", "password:", pexpect.EOF, pexpect.TIMEOUT], timeout=min(30, timeout))
        if index < 2:
            print("Enter OS keyring password: ", end="", flush=True)
            password = input()
            child.sendline(password)
            child.expect(pexpect.EOF, timeout=timeout)
        elif index == 2:
            pass
        else:
            child.expect(pexpect.EOF, timeout=timeout)
    except pexpect.TIMEOUT:
        output = "".join(output_lines)
        log(f"Command timed out. Output: {output}")
        print("ERROR: Command timed out", file=sys.stderr)
        try:
            child.close()
        finally:
            return 124, output
    except Exception as e:
        output = "".join(output_lines)
        log(f"Command error: {e}. Output: {output}")
        print(f"ERROR: {e}", file=sys.stderr)
        try:
            child.close()
        finally:
            return 1, output

    if child.isalive():
        child.close(force=True)
    else:
        child.close()

    output = "".join(output_lines)
    log_debug(f"Command output: {output}")
    exit_status = child.exitstatus if child.exitstatus is not None else child.signalstatus
    return (exit_status or 0), output


def get_current_block_height(rpc_endpoint: str) -> int:
    """Get the current block height from the RPC endpoint"""
    try:
        response = requests.get(f"{rpc_endpoint}/status", timeout=5)
        if response.status_code == 200:
            data = response.json()
            height = int(data.get("result", {}).get("sync_info", {}).get("latest_block_height", "0"))
            log_debug(f"Current block height: {height}")
            return height
    except Exception as e:
        log_debug(f"Could not get block height: {e}")
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
        log_debug(f"Key '{account_name}' already exists")
        return account_name

    address = get_address_from_seed(seed)
    if address:
        existing_key = find_key_by_address(address)
        if existing_key:
            log_debug(f"Address {address} exists as '{existing_key}'")
            return existing_key

    info(f"Importing {account_name} key...")
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

    log_debug(f"Running: {' '.join(full_cmd)}")
    process = subprocess.Popen(
        full_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    stdout, stderr = process.communicate(input=seed + "\n\n")

    if process.returncode != 0:
        if "duplicated address" in stderr.lower() or "duplicate address" in stderr.lower():
            if address:
                existing_key = find_key_by_address(address)
                if existing_key:
                    return existing_key
        log(f"Key import failed: {stderr}")
        print(f"ERROR: Key import failed", file=sys.stderr)
        sys.exit(1)

    info(f"Key '{account_name}' imported")
    return account_name


def main():
    # Setup logging first
    setup_logging()
    log(f"Starting submit_proposal.py")

    # Parse args with optional --dry-run
    args = sys.argv[1:]
    dry_run = False
    if "--dry-run" in args:
        args.remove("--dry-run")
        dry_run = True

    if len(args) < 2:
        print("Usage: python3 submit_proposal.py <local|remote> <proposal_file_or_name> [--dry-run]")
        print("\nAvailable proposals:")
        proposals_dir = SCRIPTS_DIR / "proposals"
        if proposals_dir.exists():
            for p in sorted(proposals_dir.glob("*.json")):
                print(f"  - {p.name}")
        return 1

    mode = args[0].lower()
    if mode not in ("local", "remote"):
        print(f"ERROR: Mode must be 'local' or 'remote', got '{mode}'", file=sys.stderr)
        return 1

    global _is_local_mode
    if mode == "local":
        rpc_endpoint = LOCAL_RPC_ENDPOINT
        _is_local_mode = True
    else:
        rpc_endpoint = REMOTE_RPC_ENDPOINT
        _is_local_mode = False

    log(f"Mode: {mode}, RPC: {rpc_endpoint}")

    arg = args[1]
    p = Path(arg)
    proposal_file: Path
    if p.exists() and p.is_file():
        proposal_file = p
    else:
        proposal_file = SCRIPTS_DIR / "proposals" / arg
        if not proposal_file.exists():
            proposal_file = SCRIPTS_DIR / arg
        if not proposal_file.exists():
            print(f"ERROR: Proposal file not found: {arg}", file=sys.stderr)
            return 1

    # Load and preprocess proposal
    resolved_height: str | None = None
    proposal_json: dict | None = None
    try:
        with open(proposal_file, "r", encoding="utf-8") as f:
            proposal_json = json.load(f)
        log(f"Loaded proposal: {json.dumps(proposal_json, indent=2)}")

        msgs = proposal_json.get("messages") or []
        if msgs:
            msg0 = msgs[0]
            mtype = msg0.get("@type", "")
            plan = msg0.get("plan") or {}
            height_val = plan.get("height")
            if mtype.endswith("MsgSoftwareUpgrade") and isinstance(height_val, str) and height_val.startswith("T+"):
                plus_n = int(height_val[2:])
                current_h = get_current_block_height(rpc_endpoint)
                if current_h <= 0:
                    print(f"ERROR: Could not get block height", file=sys.stderr)
                    return 1
                new_h = current_h + plus_n
                plan["height"] = str(new_h)
                resolved_height = str(new_h)
                msg0["plan"] = plan
                proposal_json["messages"][0] = msg0
                info(f"Upgrade height: {new_h}")
                tmpdir = tempfile.mkdtemp(prefix="mirage_upgrade_")
                tmp_path = Path(tmpdir) / f"proposal_upg_{new_h}.json"
                with open(tmp_path, "w", encoding="utf-8") as wf:
                    json.dump(proposal_json, wf, ensure_ascii=False, indent=2)
                proposal_file = tmp_path
    except Exception as e:
        log(f"Proposal preprocessing error: {e}")

    # Display proposal summary
    title = proposal_json.get("title", "Unknown") if proposal_json else "Unknown"
    num_msgs = len(proposal_json.get("messages", [])) if proposal_json else 0
    is_expedited = proposal_json.get("expedited", False) if proposal_json else False

    print(f"\n{'─' * 60}")
    print(json.dumps(proposal_json, indent=2, ensure_ascii=False))
    print(f"{'─' * 60}")

    info(f"\nProposal: {title}")
    info(f"Messages: {num_msgs}, Expedited: {is_expedited}")
    info(f"Endpoint: {rpc_endpoint}")

    if dry_run:
        info("\n[DRY RUN] No transactions will be broadcast.")
        info(f"Log file: {_log_file}")
        return 0

    # Initialize keyring
    bin_path = str(MIRAGED if MIRAGED.exists() else "miraged")
    run_miraged_cmd(["keys", "list", "--keyring-backend", get_keyring_backend(), "--home", get_keyring_home()])

    # Query validators
    validators_data = query_json_rpc(rpc_endpoint, ["q", "staking", "validators"])
    chain_validators = validators_data.get("validators", [])
    log_debug(f"Found {len(chain_validators)} validators")

    # Get keys from keyring
    list_result = run_miraged_cmd(
        ["keys", "list", "--keyring-backend", get_keyring_backend(), "--home", get_keyring_home()]
    )

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

    log_debug(f"Found {len(address_to_keyname)} keys in keyring")

    # Calculate voting power
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
            log(f"Error checking validator {val_operator_addr}: {e}")

    controlled_pct = (controlled_voting_power / total_voting_power * 100) if total_voting_power > 0 else 0

    # Log detailed voting power info
    log(f"Total voting power: {total_voting_power:,}")
    log(f"Controlled: {controlled_voting_power:,} ({controlled_pct:.1f}%)")
    for moniker, tokens, key_name in validators_controlled:
        log(f"  Controlled: {moniker} ({tokens:,} tokens) - key: {key_name}")
    for moniker, tokens, addr in validators_not_controlled:
        log(f"  NOT controlled: {moniker} ({tokens:,} tokens)")

    # Check majority
    if controlled_pct < 66.67:
        info(f"\nERROR: Insufficient voting power ({controlled_pct:.1f}% < 66.67%)")
        return 1

    info(f"Voting power: {controlled_pct:.1f}% (need >66.67%)")

    # Prompt for validator seed if needed
    if not validator_accounts:
        print(f"Enter seed for '{VALIDATOR_ACCOUNT}' (for voting): ", end="", flush=True)
        validator_seed = getpass.getpass("").strip()
        if not validator_seed:
            print("ERROR: Validator seed required", file=sys.stderr)
            return 1
        actual_key_name = import_key_from_seed(VALIDATOR_ACCOUNT, validator_seed)
        validator_accounts = [actual_key_name]

    log_debug(f"Will vote with: {validator_accounts}")

    # Check faucet key and balance
    if not key_exists(FAUCET_ACCOUNT):
        print(f"Enter seed for '{FAUCET_ACCOUNT}' (for submission): ", end="", flush=True)
        faucet_seed = getpass.getpass("").strip()
        if not faucet_seed:
            print("ERROR: Faucet seed required", file=sys.stderr)
            return 1
        import_key_from_seed(FAUCET_ACCOUNT, faucet_seed)
    else:
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

                if proposal_json is None:
                    print("FATAL: proposal_json not loaded", file=sys.stderr)
                    sys.exit(1)
                if "deposit" not in proposal_json:
                    print("FATAL: proposal JSON missing 'deposit' field", file=sys.stderr)
                    sys.exit(1)
                deposit_str = proposal_json["deposit"]
                deposit_amount = int(re.sub(r"[^0-9]", "", deposit_str))
                if deposit_amount <= 0:
                    print(f"FATAL: invalid deposit amount", file=sys.stderr)
                    sys.exit(1)
                estimated_submit_gas = 500000
                total_needed = deposit_amount + estimated_submit_gas

                if balances:
                    amt_int = int(balances[0].get("amount", "0"))
                    log_debug(f"Faucet balance: {amt_int:,} umirage, need: {total_needed:,}")
                    if amt_int < total_needed:
                        info(f"ERROR: Insufficient faucet balance ({amt_int:,} < {total_needed:,} umirage)")
                        return 1
                else:
                    info(f"ERROR: Faucet account has no balance")
                    return 1
            except Exception as e:
                log(f"Balance check error: {e}")

    # Final safety check
    if controlled_pct < 66.67:
        info(f"ERROR: Cannot proceed ({controlled_pct:.1f}% < 66.67%)")
        return 1

    # Show gas estimates before confirmation
    estimated_gas = estimate_gas_for_proposal(proposal_json, buffer_percent=50.0)

    # Query gov params to get the required deposit
    gov_params = query_json_rpc(rpc_endpoint, ["q", "gov", "params"])
    params = gov_params.get("params", {}) if gov_params else {}

    min_deposit_key = "expedited_min_deposit" if is_expedited else "min_deposit"
    min_deposit_list = params.get(min_deposit_key, [])
    required_deposit = 0
    for dep in min_deposit_list:
        if dep.get("denom") == "umirage":
            required_deposit = int(dep.get("amount", "0"))
            break

    # Check if deposit should be auto-calculated
    proposal_deposit = proposal_json.get("deposit", "auto") if proposal_json else "auto"
    if proposal_deposit == "auto" or not proposal_deposit:
        # Add 25% buffer and round to nice number (nearest million)
        deposit_with_buffer = int(required_deposit * 1.25)
        deposit_amount = ((deposit_with_buffer + 999_999) // 1_000_000) * 1_000_000
        deposit_source = f"auto: {min_deposit_key} {required_deposit:,} + 25%"
    else:
        # Use explicit deposit from proposal (but ensure it meets minimum)
        explicit_deposit = int(re.sub(r"[^0-9]", "", proposal_deposit))
        if explicit_deposit < required_deposit:
            deposit_with_buffer = int(required_deposit * 1.25)
            deposit_amount = ((deposit_with_buffer + 999_999) // 1_000_000) * 1_000_000
            deposit_source = f"auto (explicit {explicit_deposit:,} < required {required_deposit:,})"
        else:
            deposit_amount = explicit_deposit
            deposit_source = "explicit"

    # Update proposal with calculated deposit
    if proposal_json:
        proposal_json["deposit"] = f"{deposit_amount}umirage"
        # Write updated proposal to temp file
        if proposal_file:
            with open(proposal_file, "w", encoding="utf-8") as wf:
                json.dump(proposal_json, wf, ensure_ascii=False, indent=2)

    total_umirage = estimated_gas + deposit_amount  # gas fee + deposit
    total_mirage = total_umirage / 1_000_000

    print(f"\nEstimated costs:")
    print(f"  Gas: {estimated_gas:,} umirage")
    print(f"  Deposit: {deposit_amount:,} umirage ({deposit_source})")
    print(f"  Total: {total_umirage:,} umirage ({total_mirage:.2f} MIRAGE)")

    # Confirmation
    try:
        if _is_local_mode:
            print(f"\n[LOCAL TESTNET]")
            input(f"Press Enter to submit (Ctrl+C to abort)... ")
        else:
            print(f"\n⚠️  REMOTE PRODUCTION CHAIN ⚠️")
            confirm = input("Type 'remote' to confirm: ").strip()
            if confirm != "remote":
                info("Aborted.")
                return 1
    except KeyboardInterrupt:
        info("\nAborted.")
        return 1

    # Submit proposal
    info("\nSubmitting proposal...")

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
        str(estimated_gas),
        "--fees",
        f"{estimated_gas}umirage",
        "--yes",
    ]

    exit_status, output = run_with_pexpect(submit_cmd, timeout=60)
    if exit_status != 0:
        log(f"Submission failed: {output}")
        info("ERROR: Proposal submission failed")
        sys.exit(1)

    # Verify transaction
    txhash_match = re.search(r"txhash:\s*([A-F0-9]{64})", output, re.IGNORECASE)
    if txhash_match:
        txhash = txhash_match.group(1)
        log(f"TX hash: {txhash}")
        time.sleep(5)

        try:
            tx_result = query_json_rpc(rpc_endpoint, ["q", "tx", txhash])
            tx_code = tx_result.get("code", 0)
            if tx_code != 0:
                raw_log = tx_result.get("raw_log", "unknown error")
                log(f"TX failed on-chain: code={tx_code}, log={raw_log}")
                info(f"ERROR: Transaction failed on-chain: {raw_log}")
                sys.exit(1)
            info("✓ Proposal submitted")
        except Exception as e:
            log(f"TX verification error: {e}")
    else:
        log(f"Could not extract txhash from: {output}")
        time.sleep(5)

    # Get proposal ID
    proposals_before = query_json_rpc(rpc_endpoint, ["q", "gov", "proposals"])
    proposals_list = proposals_before.get("proposals", [])

    if not proposals_list:
        info("ERROR: No proposals found")
        return 1

    proposal_id = proposals_list[-1]["id"]
    proposal = proposals_list[-1]

    # Verify proposal title
    if proposal_json is None:
        print("FATAL: proposal_json not available", file=sys.stderr)
        sys.exit(1)
    expected_title = proposal_json.get("title", "")
    if proposal.get("title") != expected_title:
        log(f"Title mismatch: expected '{expected_title}', got '{proposal.get('title')}'")

    info(f"Proposal #{proposal_id}: {proposal.get('status', 'N/A')}")

    # Handle deposit if needed
    status = proposal.get("status", "")
    if status == "PROPOSAL_STATUS_DEPOSIT_PERIOD":
        gov_params = query_json_rpc(rpc_endpoint, ["q", "gov", "params"])
        params = gov_params.get("params", {})

        is_expedited = proposal.get("expedited", False)
        min_deposit_list = params.get("expedited_min_deposit" if is_expedited else "min_deposit", [])

        min_deposit_amount = 0
        for dep in min_deposit_list:
            if dep.get("denom") == "umirage":
                min_deposit_amount = int(dep.get("amount", "0"))
                break

        total_deposit_list = proposal.get("total_deposit", [])
        current_deposit_amount = 0
        for dep in total_deposit_list:
            if dep.get("denom") == "umirage":
                current_deposit_amount = int(dep.get("amount", "0"))
                break

        if current_deposit_amount < min_deposit_amount:
            additional_needed = min_deposit_amount - current_deposit_amount
            info(f"Depositing {additional_needed:,} umirage...")

            deposit_gas = estimate_gas_for_deposit(buffer_percent=50.0)
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
                str(deposit_gas),
                "--fees",
                f"{deposit_gas}umirage",
                "--yes",
            ]

            exit_status, output = run_with_pexpect(deposit_cmd, timeout=60)
            if exit_status != 0:
                log(f"Deposit failed: {output}")
                info("ERROR: Deposit failed")
                sys.exit(1)

            info("✓ Deposit submitted")
            time.sleep(5)

            proposal = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", str(proposal_id)])["proposal"]
            status = proposal.get("status", "")

    # Vote if in voting period
    if status != "PROPOSAL_STATUS_VOTING_PERIOD":
        # Show helpful error info
        gov_params = query_json_rpc(rpc_endpoint, ["q", "gov", "params"])
        params = gov_params.get("params", {}) if gov_params else {}

        is_expedited = proposal.get("expedited", False)
        min_deposit_key = "expedited_min_deposit" if is_expedited else "min_deposit"
        min_deposit_list = params.get(min_deposit_key, [])
        min_deposit_amount = 0
        for dep in min_deposit_list:
            if dep.get("denom") == "umirage":
                min_deposit_amount = int(dep.get("amount", "0"))
                break

        total_deposit_list = proposal.get("total_deposit", [])
        current_deposit_amount = 0
        for dep in total_deposit_list:
            if dep.get("denom") == "umirage":
                current_deposit_amount = int(dep.get("amount", "0"))
                break

        info(f"\n⚠️  Proposal stuck in {status}")
        info(
            f"   Required deposit ({min_deposit_key}): {min_deposit_amount:,} umirage ({min_deposit_amount/1_000_000:.1f} MIRAGE)"
        )
        info(f"   Current deposit: {current_deposit_amount:,} umirage ({current_deposit_amount/1_000_000:.1f} MIRAGE)")
        if current_deposit_amount < min_deposit_amount:
            shortfall = min_deposit_amount - current_deposit_amount
            info(f"   Shortfall: {shortfall:,} umirage ({shortfall/1_000_000:.1f} MIRAGE)")
        info(f"\nLog file: {_log_file}")
        return 1

    # Filter valid validators
    valid_validator_accounts = []
    min_vote_fee = 300000
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

            balance_result = query_json_rpc(rpc_endpoint, ["q", "bank", "balances", account_addr])
            balances = balance_result.get("balances", []) if balance_result else []

            umirage_balance = 0
            for b in balances:
                if b.get("denom") == "umirage":
                    umirage_balance = int(b.get("amount", "0"))
                    break

            if umirage_balance >= min_vote_fee:
                valid_validator_accounts.append(account_name)
                log_debug(f"Validator {account_name}: {umirage_balance:,} umirage (OK)")
            else:
                log_debug(f"Validator {account_name}: {umirage_balance:,} umirage (insufficient)")
        except Exception as e:
            log(f"Error checking validator {account_name}: {e}")

    if not valid_validator_accounts:
        info("ERROR: No valid validators to vote with")
        sys.exit(1)

    info(f"Voting with {len(valid_validator_accounts)} validator(s)...")
    vote_gas = estimate_gas_for_vote(buffer_percent=50.0)

    for account_name in valid_validator_accounts:
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
            str(vote_gas),
            "--fees",
            f"{vote_gas}umirage",
            "--yes",
        ]

        exit_status, output = run_with_pexpect(vote_cmd, timeout=60)
        if exit_status != 0:
            log(f"Vote failed for {account_name}: {output}")
            info(f"⚠ {account_name} vote failed")
        else:
            info(f"✓ {account_name} voted YES")

        time.sleep(3)

    # Poll for results
    def _to_int(s: str) -> int:
        try:
            return int(s)
        except Exception:
            return 0

    def parse_time(time_str: str) -> float:
        try:
            time_str_clean = time_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(time_str_clean)
            return dt.timestamp()
        except Exception:
            return 0

    def is_final_status(status: str) -> bool:
        return status in ["PROPOSAL_STATUS_PASSED", "PROPOSAL_STATUS_REJECTED", "PROPOSAL_STATUS_FAILED"]

    prop_details = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", proposal_id])
    current_proposal = prop_details["proposal"]
    status = current_proposal.get("status", "UNKNOWN")
    voting_end_time_str = current_proposal.get("voting_end_time", "")
    voting_end_timestamp = parse_time(voting_end_time_str) if voting_end_time_str else 0

    if voting_end_timestamp > 0:
        sleep_duration = voting_end_timestamp - time.time()
        if sleep_duration > 0:
            info(f"Waiting {sleep_duration:.0f}s for voting to end...")
            time.sleep(sleep_duration)

    # Poll for final result
    info("Polling for result...")
    poll_count = 0
    max_polls = 10

    while poll_count < max_polls:
        try:
            prop_details = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", proposal_id])
            current_proposal = prop_details["proposal"]
            status = current_proposal.get("status", "UNKNOWN")

            if is_final_status(status):
                if status == "PROPOSAL_STATUS_PASSED":
                    info(f"\n✓ PROPOSAL PASSED")
                else:
                    info(f"\n✗ Proposal {status}")
                    failed_reason = current_proposal.get("failed_reason", "")
                    if failed_reason:
                        info(f"  Reason: {failed_reason}")
                break

            poll_count += 1
            if poll_count < max_polls:
                time.sleep(1)

        except KeyboardInterrupt:
            info("\nInterrupted")
            break
        except Exception as e:
            log(f"Poll error: {e}")
            poll_count += 1
            if poll_count < max_polls:
                time.sleep(1)

    if not is_final_status(status):
        info(f"Status: {status}")
        info(f"Check: miraged q gov proposal {proposal_id} --node {rpc_endpoint}")

    info(f"\nLog file: {_log_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
