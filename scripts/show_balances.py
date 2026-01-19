#!/usr/bin/env python3
"""
Display liquid and staked balances for ALL live accounts on-chain (no local files),
with username (profile) when available.

Optimized for speed: uses CLI commands directly with high concurrency.

Usage:
    python3 scripts/show_balances.py                    # Show all accounts
    python3 scripts/show_balances.py --min 100          # Only show accounts with >= 100 MIRAGE total
    python3 scripts/show_balances.py --min 1000         # Only show accounts with >= 1000 MIRAGE total
"""

import argparse
import json
import base64
import hashlib
import requests
import re
import sys
import os
import subprocess
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg

# 1 MIRAGE = 1,000,000 umirage
UMIRAGE_PER_MIRAGE = 1_000_000

# Ensure shared/ is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.append(ROOT)


def normalize_username(username: str) -> str:
    try:
        return (username or "").replace("_", "-")
    except Exception:
        return username


def normalize_moniker(moniker: str) -> str:
    """Normalize validator monikers to 'mirage-node-X' when they contain an index."""
    try:
        m = re.match(
            r"^(?:node|mirage[-_]?node|mirage[-_]?validator)[-_]?(\d+)$", (moniker or "").strip(), re.IGNORECASE
        )
        if m:
            return f"mirage-node-{int(m.group(1))}"
        return moniker or ""
    except Exception:
        return moniker or ""


def is_valid_address(address: str) -> bool:
    """Validate Cosmos address format."""
    pattern = r"^[a-z0-9]+1[ac-hj-np-z02-9]+$"
    return bool(re.match(pattern, address))


def format_number(num_str: str) -> str:
    """Format number with commas for readability."""
    try:
        return f"{int(num_str):,}"
    except ValueError:
        return num_str


def format_mirage(umirage: int) -> str:
    """Format umirage amount as MIRAGE with 1 decimal place."""
    mirage = umirage / UMIRAGE_PER_MIRAGE
    return f"{mirage:,.1f}"


def run_cli_command(cmd: List[str], timeout: int = 30) -> Optional[str]:
    """Run a CLI command and return stdout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except Exception:
        return None


def query_denom_owners_cli(bin_path: str, rpc_url: str, denom: str) -> List[Dict[str, str]]:
    """Get all denom owners using CLI directly."""
    owners: List[Dict[str, str]] = []
    next_key = ""

    while True:
        cmd = [bin_path, "query", "bank", "denom-owners", denom, "--node", rpc_url, "-o", "json"]
        if next_key:
            cmd.extend(["--page-key", next_key])

        output = run_cli_command(cmd, timeout=30)
        if not output:
            break

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            break

        for item in data.get("denom_owners", []) or []:
            if isinstance(item, dict):
                addr = item.get("address") or ""
                bal = (item.get("balance") or {}).get("amount", "0")
                if addr:
                    owners.append({"address": addr, "amount": bal})

        pagination = data.get("pagination", {})
        next_key = pagination.get("next_key", "")
        if not next_key:
            break

    return owners


def query_validators_cli(bin_path: str, rpc_url: str) -> List[Dict[str, str]]:
    """Query validators using CLI directly."""
    validators: List[Dict[str, str]] = []
    next_key = ""

    while True:
        cmd = [bin_path, "query", "staking", "validators", "--node", rpc_url, "-o", "json"]
        if next_key:
            cmd.extend(["--page-key", next_key])

        output = run_cli_command(cmd, timeout=30)
        if not output:
            break

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            break

        for v in data.get("validators", []) or []:
            op = v.get("operator_address") or ""
            moniker = normalize_moniker((v.get("description", {}) or {}).get("moniker", ""))
            if op:
                acc = recode_valoper_to_acc(op)
                validators.append({"operator": op, "account": acc or "", "moniker": moniker})

        pagination = data.get("pagination", {})
        next_key = pagination.get("next_key", "")
        if not next_key:
            break

    return validators


def query_delegations_cli(bin_path: str, rpc_url: str, delegator: str) -> int:
    """Query total staked balance for a delegator using CLI directly."""
    total_staked = 0
    next_key = ""

    while True:
        cmd = [bin_path, "query", "staking", "delegations", delegator, "--node", rpc_url, "-o", "json"]
        if next_key:
            cmd.extend(["--page-key", next_key])

        output = run_cli_command(cmd, timeout=10)
        if not output:
            break

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            break

        for dr in data.get("delegation_responses", []) or []:
            balance = dr.get("balance", {})
            amount_str = balance.get("amount", "0")
            try:
                total_staked += int(amount_str)
            except ValueError:
                pass

        pagination = data.get("pagination", {})
        next_key = pagination.get("next_key", "")
        if not next_key:
            break

    return total_staked


def query_delegations_to_validator_cli(bin_path: str, rpc_url: str, validator_operator: str) -> Dict[str, int]:
    """Query all delegations TO a validator and return delegator -> amount mapping."""
    delegator_amounts: Dict[str, int] = {}
    next_key = ""

    while True:
        cmd = [bin_path, "query", "staking", "delegations-to", validator_operator, "--node", rpc_url, "-o", "json"]
        if next_key:
            cmd.extend(["--page-key", next_key])

        output = run_cli_command(cmd, timeout=15)
        if not output:
            break

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            break

        for dr in data.get("delegation_responses", []) or []:
            delegation = dr.get("delegation", {}) or {}
            delegator = delegation.get("delegator_address", "")
            balance = dr.get("balance", {})
            amount_str = balance.get("amount", "0")
            if delegator:
                try:
                    amount = int(amount_str)
                    delegator_lower = delegator.lower()
                    delegator_amounts[delegator_lower] = delegator_amounts.get(delegator_lower, 0) + amount
                except ValueError:
                    pass

        pagination = data.get("pagination", {})
        next_key = pagination.get("next_key", "")
        if not next_key:
            break

    return delegator_amounts


def fetch_staked_balances_cli(
    bin_path: str, rpc_url: str, addresses: List[str], validators: List[Dict[str, str]], max_workers: int = 16
) -> Dict[str, int]:
    """Fetch staked balances by querying delegations-to for each validator (much faster)."""
    results: Dict[str, int] = {}

    if not validators:
        return results

    validator_operators = [v.get("operator") for v in validators if v.get("operator")]
    if not validator_operators:
        return results

    try:
        workers = max(1, min(max_workers, len(validator_operators)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(query_delegations_to_validator_cli, bin_path, rpc_url, valop): valop
                for valop in validator_operators
            }
            for fut in as_completed(futs):
                try:
                    delegator_amounts = fut.result() or {}
                    for delegator, amount in delegator_amounts.items():
                        results[delegator] = results.get(delegator, 0) + amount
                except Exception:
                    pass
    except Exception:
        for valop in validator_operators:
            try:
                delegator_amounts = query_delegations_to_validator_cli(bin_path, rpc_url, valop)
                for delegator, amount in delegator_amounts.items():
                    results[delegator] = results.get(delegator, 0) + amount
            except Exception:
                pass

    return results


def load_profiles_from_chain(rpc_url: str) -> Dict[str, str]:
    """Fetch all profiles via ABCI subspace query."""
    out: Dict[str, str] = {}
    try:
        prefix = "profiles/".encode().hex()
        r = requests.get(
            f"{rpc_url}/abci_query",
            params={"path": '"/store/core/subspace"', "data": f"0x{prefix}"},
            timeout=30,
        )
        r.raise_for_status()
        resp = r.json().get("result", {}).get("response", {})
        kvs = resp.get("kvs") or []
        if kvs:
            for kv in kvs:
                k = kv.get("key")
                v = kv.get("value")
                if not k or not v:
                    continue
                try:
                    kraw = base64.b64decode(k)
                    vraw = base64.b64decode(v)
                except Exception:
                    continue
                if not kraw.startswith(b"profiles/"):
                    continue
                addr = kraw[len(b"profiles/") :].decode(errors="ignore").strip()
                if not addr:
                    continue
                try:
                    prof = json.loads(vraw.decode("utf-8"))
                    uname = str(prof.get("username", ""))
                except Exception:
                    uname = ""
                if uname:
                    out[addr.lower()] = uname
    except Exception:
        pass
    return out


def _bech32_hrp_expand(hrp: str) -> List[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_polymod(values: List[int]) -> int:
    GENERATORS = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= GENERATORS[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_verify_checksum(hrp: str, data: List[int]) -> bool:
    return _bech32_polymod(_bech32_hrp_expand(hrp) + data) == 1


def _bech32_create_checksum(hrp: str, data: List[int]) -> List[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def bech32_decode(bech: str) -> tuple[str, List[int]]:
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        return "", []
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech) or len(bech) > 90:
        return "", []
    hrp = bech[:pos]
    data = []
    for c in bech[pos + 1 :]:
        if c not in BECH32_CHARSET:
            return "", []
        data.append(BECH32_CHARSET.find(c))
    if not _bech32_verify_checksum(hrp, data):
        return "", []
    return hrp, data[:-6]


def bech32_encode(hrp: str, data: List[int]) -> str:
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join([BECH32_CHARSET[d] for d in combined])


def convertbits(data: bytes, frombits: int, tobits: int, pad: bool = True) -> Optional[List[int]]:
    acc = 0
    bits = 0
    ret: List[int] = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def recode_valoper_to_acc(valoper_addr: str, acc_hrp: str = "mirage") -> Optional[str]:
    """Re-encode validator operator address to account address."""
    hrp, data = bech32_decode(valoper_addr)
    if not hrp or not data:
        return None
    acc8 = convertbits(bytes(data), 5, 8, pad=False)
    if acc8 is None:
        return None
    data5 = convertbits(bytes(acc8), 8, 5, pad=True)
    if not data5:
        return None
    return bech32_encode(acc_hrp, data5)


def _to_5bit(data8: bytes) -> Optional[List[int]]:
    return convertbits(data8, 8, 5, pad=True)


def _module_address(module_name: str, hrp: str = "mirage") -> Optional[str]:
    try:
        h = hashlib.sha256(module_name.encode("utf-8")).digest()[:20]
        data5 = _to_5bit(h)
        if not data5:
            return None
        return bech32_encode(hrp, data5)
    except Exception:
        return None


def build_well_known_usernames(hrp: str = "mirage") -> Dict[str, str]:
    """Derive well-known module account addresses -> friendly usernames."""
    names = [
        "fee_collector",
        "distribution",
        "mint",
        "bonded_tokens_pool",
        "not_bonded_tokens_pool",
        "gov",
        "transfer",
        "ica",
        "icahost",
        "icacontroller",
        "core",
    ]
    out: Dict[str, str] = {}
    for mod in names:
        addr = _module_address(mod, hrp)
        if addr:
            uname = f"mirage-{mod.replace('_', '-')}"
            out[addr] = uname
    return out


def main():
    parser = argparse.ArgumentParser(
        description="Display liquid and staked balances for all accounts on-chain"
    )
    parser.add_argument(
        "--min", 
        type=float, 
        default=0,
        help="Minimum total balance in MIRAGE to display (default: 0, show all)"
    )
    parser.add_argument(
        "--rpc",
        type=str,
        default="tcp://127.0.0.1:26657",
        help="RPC endpoint (default: tcp://127.0.0.1:26657)"
    )
    args = parser.parse_args()
    
    min_balance_umirage = int(args.min * UMIRAGE_PER_MIRAGE)
    
    if args.min > 0:
        print(f"Showing accounts with >= {args.min:,.1f} MIRAGE", file=sys.stderr)

    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bin_path = os.path.join(root_dir, "blockchain", "bin", "miraged")
    if not os.path.exists(bin_path):
        bin_path = "/opt/mirage/blockchain/bin/miraged"
    if not os.path.exists(bin_path):
        bin_path = "miraged"

    rpc_url = args.rpc
    denom = "umirage"

    owners = query_denom_owners_cli(bin_path, rpc_url, denom)
    owners = [o for o in owners if is_valid_address(o.get("address", ""))]
    owners.sort(key=lambda x: x["address"])

    if not owners:
        print("No accounts found.", file=sys.stderr)
        sys.exit(0)

    validators = query_validators_cli(bin_path, rpc_url)
    validator_moniker_by_account = {
        v["account"].lower(): normalize_moniker(v.get("moniker") or "") for v in validators if v.get("account")
    }

    # Determine which addresses still need usernames (no moniker available)
    need_username_lower: set[str] = set()
    for o in owners:
        addr = (o.get("address") or "").lower()
        if not addr:
            continue
        moniker = validator_moniker_by_account.get(addr, "")
        if not moniker:
            need_username_lower.add(addr)

    usernames: Dict[str, str] = {}
    try:
        db_url = os.environ.get("MIRAGE_INDEXER_DB_URL", "").strip()
        if db_url and need_username_lower:
            conn = psycopg.connect(db_url, autocommit=True)
            cur = conn.cursor()
            chunk: List[str] = []

            def _flush_chunk() -> None:
                nonlocal chunk
                if not chunk:
                    return
                placeholders = ",".join(["%s"] * len(chunk))
                cur.execute(
                    f"SELECT LOWER(owner), COALESCE(username, '') FROM profiles WHERE LOWER(owner) IN ({placeholders})",
                    [a.lower() for a in chunk],
                )
                for addr, uname in cur.fetchall():
                    if isinstance(addr, str):
                        try:
                            uname_str = str(uname).strip() if uname else ""
                            if uname_str:
                                usernames[addr.lower()] = uname_str
                        except Exception:
                            pass
                chunk = []

            for o in owners:
                a = o.get("address", "")
                if a and a.lower() in need_username_lower:
                    chunk.append(a)
                    if len(chunk) >= 500:
                        _flush_chunk()
            _flush_chunk()
            conn.close()
    except Exception:
        pass

    onchain = load_profiles_from_chain("http://127.0.0.1:26657")
    if onchain and need_username_lower:
        for a, u in onchain.items():
            if a in need_username_lower and a not in usernames and u:
                usernames[a] = str(u).strip()

    official_names_by_addr = build_well_known_usernames()
    official_lower = {k.lower(): v for k, v in official_names_by_addr.items()}
    # Only validators can stake, so only query delegations for validator accounts
    validator_accounts = {v["account"].lower() for v in validators if v.get("account")}
    validator_addresses = [v["account"] for v in validators if v.get("account") and is_valid_address(v["account"])]

    staked_map = {}
    if validator_addresses:
        with ThreadPoolExecutor(max_workers=min(16, len(validator_addresses))) as ex:
            futs = {ex.submit(query_delegations_cli, bin_path, rpc_url, addr): addr for addr in validator_addresses}
            for fut in as_completed(futs):
                addr = futs[fut]
                try:
                    amt = int(fut.result() or 0)
                    staked_map[addr.lower()] = amt
                except Exception:
                    staked_map[addr.lower()] = 0

    account_data: List[Dict[str, Any]] = []
    for item in owners:
        address = item.get("address", "")
        amount = item.get("amount", "0")
        addr_l = address.lower()
        moniker = validator_moniker_by_account.get(addr_l, "")
        if moniker:
            display_name = moniker
        else:
            uname_db = usernames.get(addr_l, "")
            uname_official = official_lower.get(addr_l, "")
            uname = uname_db or uname_official
            display_name = normalize_username(uname)
        staked_amt = int(staked_map.get(addr_l, 0) or 0)
        account_data.append(
            {
                "address": address,
                "username": display_name,
                "liquid": amount,
                "staked": staked_amt,
            }
        )

    # Filter by minimum balance
    if min_balance_umirage > 0:
        account_data = [
            a for a in account_data 
            if (int(a["liquid"]) + int(a["staked"])) >= min_balance_umirage
        ]
    
    # Sort by total balance descending
    account_data.sort(key=lambda x: int(x["liquid"]) + int(x["staked"]), reverse=True)

    print()
    print(f"{'Address':<45} | {'Username':<35} | {'Liquid (MIRAGE)':>18} | {'Staked (MIRAGE)':>18} | {'Total':>18}")
    print("-" * 140)

    total_liquid = 0
    total_staked = 0
    for account in account_data:
        liquid = int(account["liquid"])
        staked = int(account["staked"])
        total = liquid + staked
        total_liquid += liquid
        total_staked += staked
        
        liquid_formatted = format_mirage(liquid)
        staked_formatted = format_mirage(staked)
        total_formatted = format_mirage(total)
        display_name = account["username"] or "-"
        print(
            f"{account['address']:<45} | "
            f"{display_name:<35} | "
            f"{liquid_formatted:>18} | "
            f"{staked_formatted:>18} | "
            f"{total_formatted:>18}"
        )

    print("-" * 140)
    print(
        f"{'TOTAL':<45} | "
        f"{'':<35} | "
        f"{format_mirage(total_liquid):>18} | "
        f"{format_mirage(total_staked):>18} | "
        f"{format_mirage(total_liquid + total_staked):>18}"
    )
    print("=" * 140)
    print(f"Accounts shown: {len(account_data)}")


if __name__ == "__main__":
    main()
