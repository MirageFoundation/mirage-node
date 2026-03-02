#!/usr/bin/env python3
import getpass
import json
import logging
import re
import shlex
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

# Cached miraged path (detected at runtime)
_miraged_path: Path | None = None


def get_miraged_path() -> Path | None:
    """Get the local miraged binary path.

    Handles both new (blockchain/miraged) and old (blockchain/bin/miraged) structures.
    Returns None if binary is not found (will fall back to 'miraged' in PATH).
    """
    global _miraged_path
    if _miraged_path is not None:
        return _miraged_path

    # Check new path first, then fall back to old path
    new_path = BLOCKCHAIN_DIR / "miraged"
    old_path = BLOCKCHAIN_DIR / "bin" / "miraged"

    if new_path.exists():
        _miraged_path = new_path
    elif old_path.exists():
        _miraged_path = old_path

    return _miraged_path


KEYRING_BACKEND = "os"
LOCAL_KEYRING_BACKEND = "test"
LOCAL_KEYRING_HOME = "/root/.mirage/node"
LOCAL_CONTAINER = "mirage"

# Binary paths (new structure vs old structure)
_local_miraged_path: str | None = None


def get_local_miraged_path() -> str:
    """Get the miraged binary path inside the local container.

    Handles both old (/opt/mirage/blockchain/bin/miraged) and
    new (/opt/mirage/blockchain/miraged) directory structures.
    """
    global _local_miraged_path
    if _local_miraged_path is not None:
        return _local_miraged_path

    # Check new path first, then fall back to old path
    new_path = "/opt/mirage/blockchain/miraged"
    old_path = "/opt/mirage/blockchain/bin/miraged"

    result = subprocess.run(
        ["docker", "exec", LOCAL_CONTAINER, "test", "-f", new_path],
        capture_output=True,
    )
    if result.returncode == 0:
        _local_miraged_path = new_path
    else:
        _local_miraged_path = old_path

    return _local_miraged_path


# Account names
FAUCET_ACCOUNT = "faucet"
VALIDATOR_ACCOUNT = "validator"


def get_submission_account() -> str:
    """Get the account to use for proposal submission.
    For local mode, use validator since backups don't have faucet."""
    return VALIDATOR_ACCOUNT if _is_local_mode else FAUCET_ACCOUNT


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


def _format_umirage_in_text(text: str) -> str:
    """Convert umirage amounts to MIRAGE in text for display.

    E.g., '521550umirage' -> '0.52 MIRAGE'
    """

    def replace_umirage(match: re.Match) -> str:
        amount = int(match.group(1))
        mirage = amount / 1_000_000
        if mirage >= 1000:
            return f"{mirage:,.0f} MIRAGE"
        elif mirage >= 1:
            return f"{mirage:,.2f} MIRAGE"
        else:
            return f"{mirage:.6f} MIRAGE"

    return re.sub(r"(\d+)umirage", replace_umirage, text)


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
    miraged = get_miraged_path()
    bin_path = str(miraged) if miraged else "miraged"
    if _is_local_mode:
        full_cmd = ["docker", "exec", LOCAL_CONTAINER, get_local_miraged_path()] + cmd
    else:
        full_cmd = [bin_path] + cmd
    log_debug(f"Running: {' '.join(full_cmd)}")
    result = subprocess.run(full_cmd, capture_output=capture_output, text=True, check=check)
    if result.stdout:
        log_debug(f"stdout: {result.stdout[:500]}")
    if result.stderr:
        log_debug(f"stderr: {result.stderr[:500]}")
    return result


class QueryError(RuntimeError):
    """Raised when a miraged query fails (e.g. JSON marshal errors for float64 fields)."""

    pass


def query_json_rpc(rpc_endpoint: str, cmd: list[str], fatal: bool = True) -> dict:
    """Query via miraged with --node (uses HTTP internally, no home required).

    Args:
        fatal: If True (default), exit on failure. If False, raise QueryError.
    """
    cmd_with_node = cmd + ["--node", rpc_endpoint, "-o", "json"]
    if _is_local_mode:
        full_cmd = ["docker", "exec", LOCAL_CONTAINER, get_local_miraged_path()] + cmd_with_node
    else:
        miraged = get_miraged_path()
        bin_path = str(miraged) if miraged else "miraged"
        full_cmd = [bin_path] + cmd_with_node
    log_debug(f"Query: {' '.join(full_cmd)}")
    result = subprocess.run(full_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "unknown error"
        log(f"RPC query failed: {error_msg}")
        if not fatal:
            raise QueryError(f"query failed (exit {result.returncode}): {error_msg}")
        print(f"ERROR: RPC query failed (exit {result.returncode})", file=sys.stderr)
        print(f"  Command: {' '.join(cmd)}", file=sys.stderr)
        print(f"  {error_msg}", file=sys.stderr)
        sys.exit(1)
    log_debug(f"Response: {result.stdout[:500]}...")
    return json.loads(result.stdout)


def estimate_gas_for_proposal(proposal_json: dict, buffer_percent: float = 50.0) -> tuple[int, int]:
    """Estimate gas needed for a proposal based on message count and byte size.

    Gas cost includes:
    - Base tx overhead: 100,000
    - Per message: 75,000
    - WritePerByte: ~10 gas per byte of serialized JSON

    Returns:
        Tuple of (raw_estimate, buffered_estimate)
    """
    msgs = proposal_json.get("messages", [])
    num_messages = len(msgs) if msgs else 1

    # Calculate byte size of the proposal (include indentation to match file size more closely)
    proposal_bytes = len(json.dumps(proposal_json, ensure_ascii=False, indent=2).encode("utf-8"))

    # Base gas + per-message gas + per-byte gas (WritePerByte cost)
    base_gas = 100_000
    per_message_gas = num_messages * 75_000
    per_byte_gas = proposal_bytes * 100  # ~100 gas per byte (aggressive safety margin)

    estimated_gas = base_gas + per_message_gas + per_byte_gas
    gas_with_buffer = int(estimated_gas * (1 + buffer_percent / 100))
    log_debug(
        f"Gas estimate: base={base_gas} + msgs={per_message_gas} + bytes={per_byte_gas} ({proposal_bytes}B) = {estimated_gas}, +{buffer_percent}% = {gas_with_buffer}"
    )
    return estimated_gas, gas_with_buffer


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
        # Build shell command string for docker exec (more reliable than list for complex args)
        miraged_path = get_local_miraged_path()
        args_str = " ".join(shlex.quote(arg) for arg in cmd[1:])
        shell_cmd = f"docker exec {LOCAL_CONTAINER} {miraged_path} {args_str}"
        log_debug(f"Docker exec: {shell_cmd}")
        result = subprocess.run(shell_cmd, shell=True, capture_output=True, text=True, timeout=timeout)
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
    miraged = get_miraged_path()
    bin_path = str(miraged) if miraged else "miraged"
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
        full_cmd = ["docker", "exec", "-i", LOCAL_CONTAINER, get_local_miraged_path()] + cmd
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
    miraged = get_miraged_path()
    bin_path = str(miraged) if miraged else "miraged"

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
        full_cmd = ["docker", "exec", "-i", LOCAL_CONTAINER, get_local_miraged_path()] + cmd
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
        error_msg = stderr.strip() or stdout.strip() or "unknown error"
        log(f"Key import failed: {error_msg}")
        print(f"ERROR: Key import failed (exit {process.returncode})", file=sys.stderr)
        print(f"  {error_msg}", file=sys.stderr)
        sys.exit(1)

    info(f"Key '{account_name}' imported")
    return account_name


def main():
    # Setup logging first
    setup_logging()
    log(f"Starting submit_proposal.py")

    # Parse args with optional flags
    args = sys.argv[1:]
    dry_run = False
    no_confirm = False
    if "--dry-run" in args:
        args.remove("--dry-run")
        dry_run = True
    if "--no-confirm" in args:
        args.remove("--no-confirm")
        no_confirm = True

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

    if not is_expedited and not dry_run:
        info("WARNING: Proposal is NOT expedited — it will use the standard (slow) voting period.")
        resp = input("Type 'confirm' to proceed with non-expedited proposal, or Ctrl+C to abort: ")
        if resp.strip().lower() != "confirm":
            info("Aborted.")
            return 1

    if dry_run:
        info("\n[DRY RUN] No transactions will be broadcast.")
        info(f"Log file: {_log_file}")
        return 0

    # Initialize keyring
    miraged = get_miraged_path()
    bin_path = str(miraged) if miraged else "miraged"
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
                    delegation_args = [
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
                    if _is_local_mode:
                        delegation_cmd = ["docker", "exec", LOCAL_CONTAINER, get_local_miraged_path()] + delegation_args
                    else:
                        delegation_cmd = [bin_path] + delegation_args
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

    # Check submission account key and balance
    submission_account = get_submission_account()
    if not key_exists(submission_account):
        print(f"Enter seed for '{submission_account}' (for submission): ", end="", flush=True)
        submission_seed = getpass.getpass("").strip()
        if not submission_seed:
            print("ERROR: Submission account seed required", file=sys.stderr)
            return 1
        import_key_from_seed(submission_account, submission_seed)
    else:
        submission_addr_result = run_miraged_cmd(
            [
                "keys",
                "show",
                submission_account,
                "-a",
                "--keyring-backend",
                get_keyring_backend(),
                "--home",
                get_keyring_home(),
            ]
        )
        if submission_addr_result.returncode == 0:
            submission_addr = submission_addr_result.stdout.strip()
            try:
                balance_result = query_json_rpc(rpc_endpoint, ["q", "bank", "balances", submission_addr])
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
                    log_debug(
                        f"Submission account balance: {amt_int/1_000_000:,.2f} MIRAGE, need: {total_needed/1_000_000:,.2f}"
                    )
                    if amt_int < total_needed:
                        info(
                            f"ERROR: Insufficient balance ({amt_int/1_000_000:,.2f} < {total_needed/1_000_000:,.2f} MIRAGE)"
                        )
                        return 1
                else:
                    info(f"ERROR: Submission account has no balance")
                    return 1
            except Exception as e:
                log(f"Balance check error: {e}")

    # Final safety check
    if controlled_pct < 66.67:
        info(f"ERROR: Cannot proceed ({controlled_pct:.1f}% < 66.67%)")
        return 1

    # Show gas estimates before confirmation
    raw_gas, estimated_gas = estimate_gas_for_proposal(proposal_json, buffer_percent=50.0)

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
        # Use exact required deposit (no buffer needed - it's a fixed governance param)
        deposit_amount = required_deposit
        deposit_source = f"auto: {min_deposit_key}"
    else:
        # Use explicit deposit from proposal (but ensure it meets minimum)
        explicit_deposit = int(re.sub(r"[^0-9]", "", proposal_deposit))
        if explicit_deposit < required_deposit:
            deposit_amount = required_deposit
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

    # Fee = gas * gas_price (5000 umirage per gas unit)
    gas_price = 5000
    fee_amount = estimated_gas * gas_price
    total_umirage = fee_amount + deposit_amount  # gas fee + deposit

    print(f"\nEstimated costs:")
    print(f"  Gas: {raw_gas:,} + 50% = {estimated_gas:,} units × {gas_price} = {fee_amount/1_000_000:,.2f} MIRAGE")
    print(f"  Deposit: {deposit_amount/1_000_000:,.2f} MIRAGE ({deposit_source})")
    print(f"  Total: {total_umirage/1_000_000:,.2f} MIRAGE")

    # Confirmation
    try:
        if no_confirm:
            print(f"\n[--no-confirm: skipping confirmation]")
        elif _is_local_mode:
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

    # Fee = gas * gas_price (5000 umirage per gas unit)
    gas_price = 5000
    fee_amount = estimated_gas * gas_price

    submit_cmd = [
        bin_path,
        "tx",
        "gov",
        "submit-proposal",
        proposal_path_for_cmd,
        "--from",
        get_submission_account(),
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
        f"{fee_amount}umirage",
        "--yes",
    ]

    exit_status, output = run_with_pexpect(submit_cmd, timeout=60)
    log(f"Broadcast output:\n{output}")

    # Check for non-zero code in broadcast response (sync mode returns code immediately)
    code_match = re.search(r"code:\s*(\d+)", output)
    if code_match and code_match.group(1) != "0":
        error_code = code_match.group(1)
        # Extract raw_log which contains the actual error message
        raw_log_match = re.search(r"raw_log:\s*['\"]?(.+?)['\"]?\s*(?:\n|$)", output, re.DOTALL)
        raw_log = raw_log_match.group(1).strip() if raw_log_match else "unknown error"
        # Clean up the raw_log (remove trailing quotes, newlines)
        raw_log = raw_log.rstrip("'\"").strip()
        # Convert umirage amounts to MIRAGE for display
        raw_log = _format_umirage_in_text(raw_log)
        info(f"ERROR: TX rejected (code {error_code}): {raw_log}")
        sys.exit(1)

    if exit_status != 0:
        log(f"Submission failed: {output}")
        info(f"ERROR: Proposal submission failed (exit {exit_status})")
        # Show the actual error from output
        if output:
            # Try to extract meaningful error message
            for line in output.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("gas estimate:"):
                    info(f"  {line}")
        sys.exit(1)

    # Verify transaction and extract proposal ID from events
    txhash_match = re.search(r"txhash:\s*([A-F0-9]{64})", output, re.IGNORECASE)
    proposal_id_from_tx: str | None = None

    if txhash_match:
        txhash = txhash_match.group(1)
        log(f"TX hash: {txhash}")
        info(f"TX hash: {txhash}")

        # Retry tx query - it may take a few seconds to be included in a block
        tx_verified = False
        max_attempts = 15
        for attempt in range(1, max_attempts + 1):
            print(f"\rVerifying TX... ({attempt}/{max_attempts})", end="", flush=True)
            time.sleep(1)
            try:
                tx_args = ["q", "tx", txhash, "--node", rpc_endpoint, "-o", "json"]
                if _is_local_mode:
                    tx_cmd = ["docker", "exec", LOCAL_CONTAINER, get_local_miraged_path()] + tx_args
                else:
                    miraged = get_miraged_path()
                    bin_path = str(miraged) if miraged else "miraged"
                    tx_cmd = [bin_path] + tx_args
                log_debug(f"TX verify attempt {attempt}: {' '.join(tx_cmd)}")
                result = subprocess.run(tx_cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0:
                    tx_result = json.loads(result.stdout)
                    tx_code = tx_result.get("code", 0)
                    print()  # newline after progress
                    if tx_code != 0:
                        raw_log = tx_result.get("raw_log", "unknown error")
                        log(f"TX failed on-chain: code={tx_code}, log={raw_log}")
                        info(f"ERROR: Transaction failed on-chain: {raw_log}")
                        sys.exit(1)

                    # Extract proposal_id from tx events
                    for event in tx_result.get("events", []):
                        if event.get("type") == "submit_proposal":
                            for attr in event.get("attributes", []):
                                if attr.get("key") == "proposal_id":
                                    proposal_id_from_tx = attr.get("value")
                                    log(f"Extracted proposal_id from tx events: {proposal_id_from_tx}")
                                    break

                    info("✅ Proposal submitted")
                    tx_verified = True
                    break
                else:
                    # Check if it's just "not found" (still pending)
                    if "not found" in result.stderr.lower():
                        log_debug(f"TX not found yet (attempt {attempt}), retrying...")
                        continue
                    else:
                        print()  # newline after progress
                        log(f"TX query error: {result.stderr}")
                        break
            except Exception as e:
                print()  # newline after progress
                log(f"TX verification error: {e}")
                break

        if not tx_verified:
            print()  # newline after progress
            info("⚠️  Could not verify TX after 15s")
            # Check if tx is in mempool
            try:
                mempool_resp = requests.get(f"{rpc_endpoint}/unconfirmed_txs?limit=100", timeout=5)
                if mempool_resp.status_code == 200:
                    mempool_data = mempool_resp.json()
                    n_txs = mempool_data.get("result", {}).get("n_txs", "0")
                    info(f"   Mempool has {n_txs} pending tx(s)")
            except Exception as e:
                log(f"Could not check mempool: {e}")

            # Show broadcast output for debugging
            info("   Broadcast response was:")
            for line in output.strip().split("\n")[-10:]:  # last 10 lines
                line = line.strip()
                if line:
                    info(f"     {line}")
    else:
        log(f"Could not extract txhash from: {output}")
        info("⚠️  No txhash in output - continuing anyway")
        time.sleep(3)

    # Get proposal by ID (from tx events) or by matching title
    if proposal_json is None:
        print("FATAL: proposal_json not available", file=sys.stderr)
        sys.exit(1)
    expected_title = proposal_json.get("title", "")

    proposal: dict | None = None
    proposal_id: str | None = proposal_id_from_tx

    if proposal_id_from_tx:
        # We have the ID from tx events - query it directly
        try:
            prop_result = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", proposal_id_from_tx], fatal=False)
            proposal = prop_result.get("proposal", prop_result)
            proposal_id = proposal.get("id", proposal_id_from_tx)
        except (QueryError, Exception) as e:
            log(f"Could not query proposal {proposal_id_from_tx} (may be float64 marshal issue): {e}")
            info(f"⚠️  Cannot query proposal details (JSON marshal error), proceeding with ID #{proposal_id_from_tx}")
            proposal = {"id": proposal_id_from_tx, "status": "PROPOSAL_STATUS_VOTING_PERIOD"}
            proposal_id = proposal_id_from_tx

    if not proposal:
        # Fallback: find proposal by matching title (must be exact match and recent)
        proposals_result = query_json_rpc(rpc_endpoint, ["q", "gov", "proposals"])
        proposals_list = proposals_result.get("proposals", [])

        if not proposals_list:
            info("ERROR: No proposals found")
            return 1

        # Search backwards (most recent first) for matching title
        for prop in reversed(proposals_list):
            if prop.get("title") == expected_title:
                proposal = prop
                proposal_id = prop.get("id")
                log(f"Found proposal by title match: #{proposal_id}")
                break

        if not proposal:
            info(f"ERROR: Could not find proposal with title '{expected_title}'")
            info("Recent proposals:")
            for prop in proposals_list[-5:]:
                info(f"  #{prop.get('id')}: {prop.get('title')} ({prop.get('status')})")
            return 1

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
            info(f"Depositing {additional_needed/1_000_000:,.2f} MIRAGE...")

            deposit_gas = estimate_gas_for_deposit(buffer_percent=50.0)
            deposit_fee = deposit_gas * gas_price
            deposit_cmd = [
                bin_path,
                "tx",
                "gov",
                "deposit",
                str(proposal_id),
                f"{additional_needed}umirage",
                "--from",
                get_submission_account(),
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
                f"{deposit_fee}umirage",
                "--yes",
            ]

            exit_status, output = run_with_pexpect(deposit_cmd, timeout=60)
            if exit_status != 0:
                log(f"Deposit failed: {output}")
                info(f"ERROR: Deposit failed (exit {exit_status})")
                if output:
                    for line in output.strip().split("\n"):
                        line = line.strip()
                        if line:
                            info(f"  {line}")
                sys.exit(1)

            info("✅ Deposit submitted")
            time.sleep(5)

            try:
                proposal = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", str(proposal_id)], fatal=False)[
                    "proposal"
                ]
                status = proposal.get("status", "")
            except (QueryError, Exception) as e:
                log(f"Could not query proposal after deposit: {e}")
                status = "PROPOSAL_STATUS_VOTING_PERIOD"

    # Check if already passed (e.g., single validator with >66.67% voting power auto-passes)
    if status == "PROPOSAL_STATUS_PASSED":
        info(f"\n✅ PROPOSAL PASSED (auto-passed with sufficient voting power)")
        info(f"\nLog file: {_log_file}")
        return 0

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
        info(f"   Required deposit ({min_deposit_key}): {min_deposit_amount/1_000_000:,.2f} MIRAGE")
        info(f"   Current deposit: {current_deposit_amount/1_000_000:,.2f} MIRAGE")
        if current_deposit_amount < min_deposit_amount:
            shortfall = min_deposit_amount - current_deposit_amount
            info(f"   Shortfall: {shortfall/1_000_000:,.2f} MIRAGE")
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
                log_debug(f"Validator {account_name}: {umirage_balance/1_000_000:,.2f} MIRAGE (OK)")
            else:
                log_debug(f"Validator {account_name}: {umirage_balance/1_000_000:,.2f} MIRAGE (insufficient)")
        except Exception as e:
            log(f"Error checking validator {account_name}: {e}")

    if not valid_validator_accounts:
        info("ERROR: No valid validators to vote with")
        sys.exit(1)

    info(f"Voting with {len(valid_validator_accounts)} validator(s)...")
    vote_gas = estimate_gas_for_vote(buffer_percent=50.0)
    vote_fee = vote_gas * gas_price

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
            f"{vote_fee}umirage",
            "--yes",
        ]

        exit_status, output = run_with_pexpect(vote_cmd, timeout=60)
        if exit_status != 0:
            log(f"Vote failed for {account_name}: {output}")
            info(f"⚠️ {account_name} vote failed (exit {exit_status})")
            if output:
                info(f"Full output:\n{output}")
            info(f"Command was: {' '.join(vote_cmd)}")
            sys.exit(1)
        else:
            info(f"✅ {account_name} voted YES")

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

    try:
        prop_details = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", proposal_id], fatal=False)
        current_proposal = prop_details["proposal"]
        status = current_proposal.get("status", "UNKNOWN")
        voting_end_time_str = current_proposal.get("voting_end_time", "")
        voting_end_timestamp = parse_time(voting_end_time_str) if voting_end_time_str else 0
    except (QueryError, Exception) as e:
        log(f"Could not query proposal for countdown (marshal error): {e}")
        info("⚠️  Cannot query proposal details, using gov params for vote timing")
        try:
            gov_params = query_json_rpc(rpc_endpoint, ["q", "gov", "params"])
            params = gov_params.get("params", {})
            period_str = params.get("expedited_voting_period", params.get("voting_period", "60s"))
            period_secs = int(period_str.rstrip("s"))
        except Exception:
            period_secs = 60
        voting_end_timestamp = time.time() + period_secs
        status = "PROPOSAL_STATUS_VOTING_PERIOD"

    if voting_end_timestamp > 0:
        sleep_duration = voting_end_timestamp - time.time()
        if sleep_duration > 0:
            total_secs = int(sleep_duration) + 1
            for remaining in range(total_secs, 0, -1):
                mins, secs = divmod(remaining, 60)
                if mins > 0:
                    print(f"\rWaiting for voting to end: {mins}m {secs}s remaining  ", end="", flush=True)
                else:
                    print(f"\rWaiting for voting to end: {secs}s remaining  ", end="", flush=True)
                time.sleep(1)
            print()  # newline after countdown

    # Poll for final result
    info("Polling for result...")
    poll_count = 0
    max_polls = 10

    while poll_count < max_polls:
        try:
            prop_details = query_json_rpc(rpc_endpoint, ["q", "gov", "proposal", proposal_id], fatal=False)
            current_proposal = prop_details["proposal"]
            status = current_proposal.get("status", "UNKNOWN")

            if is_final_status(status):
                if status == "PROPOSAL_STATUS_PASSED":
                    info(f"\n✅ PROPOSAL PASSED")
                else:
                    info(f"\n❌ Proposal {status}")
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
