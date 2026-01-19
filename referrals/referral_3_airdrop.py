#!/usr/bin/env python3
"""
Referral airdrop script: process referral reward decisions (pay approved, mark denied).

Usage:
    python referrals/referral_3_airdrop.py [csv_file] [--backend URL] [--dry-run]

CSV format (header required):
    referee_username,referee_address,beneficiary_username,beneficiary_address,level,amount,status
    alice,mirage1abc...,bob,mirage1xyz...,1,1.500000,approved
    alice,mirage1abc...,charlie,mirage1def...,2,0.750000,approved
    dave,mirage1ghi...,bob,mirage1xyz...,1,2.000000,denied

Each row represents a (referee, beneficiary) pair. When a referee is approved,
ALL their upstream beneficiaries (L1, L2, L3...) get paid.

Example:
    # Use default export file (referrals/airdrop_pending.csv)
    python referrals/referral_3_airdrop.py

    # Local with custom file
    python referrals/referral_3_airdrop.py referrals/airdrop_pending.csv --backend http://127.0.0.1

    # Dry run (shows what would happen without sending)
    python referrals/referral_3_airdrop.py --dry-run

    # Production
    python referrals/referral_3_airdrop.py --backend https://mirage.talk

The script will:
- Send tokens to ALL beneficiaries for approved referees (L1, L2, L3...)
- Mark denied referees in the database (no payment to any beneficiary)
- Prompt for a seed phrase to derive the sender wallet
"""

import argparse
import csv
import getpass
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

CHAIN_ID = "mirage-1"
DENOM = "umirage"
DEFAULT_AIRDROP_FILE = SCRIPT_DIR / "airdrop_pending.csv"
PAYOUT_HISTORY_FILE = SCRIPT_DIR / "payout_history.csv"
DB_URL = "postgresql://mirage:mirage@127.0.0.1:5432/mirage"


def connect_db():
    """Connect to the database."""
    try:
        import psycopg
    except ImportError:
        raise RuntimeError("psycopg not installed. Run: pip install 'psycopg[binary]'")
    return psycopg.connect(DB_URL, autocommit=True)


def mark_rewards_paid(cur, referrer_address: str, referee_address: str, amount: float, tx_hash: str) -> None:
    """Mark pending rewards as paid in the database for a specific referee."""
    # Move pending to paid in referral_user_accruals for this specific referee
    cur.execute(
        """
        UPDATE referral_user_accruals
        SET paid = paid + pending,
            pending = 0,
            last_updated = EXTRACT(EPOCH FROM NOW())::bigint
        WHERE LOWER(beneficiary_address) = LOWER(%s) 
          AND LOWER(referee_address) = LOWER(%s)
          AND pending > 0
        """,
        (referrer_address, referee_address),
    )


def mark_rewards_denied(cur, referrer_address: str, referee_address: str) -> None:
    """Mark pending rewards as denied in the database for a specific referee."""
    # Move pending to denied in referral_user_accruals
    cur.execute(
        """
        UPDATE referral_user_accruals
        SET denied = COALESCE(denied, 0) + pending,
            pending = 0,
            last_updated = EXTRACT(EPOCH FROM NOW())::bigint
        WHERE LOWER(beneficiary_address) = LOWER(%s) 
          AND LOWER(referee_address) = LOWER(%s)
          AND pending > 0
        """,
        (referrer_address, referee_address),
    )


def recalculate_referrer_pending(cur, referrer_address: str) -> None:
    """Recalculate total pending for a referrer after individual updates."""
    # Sum remaining pending from referral_user_accruals
    cur.execute(
        """
        SELECT COALESCE(SUM(pending), 0)
        FROM referral_user_accruals
        WHERE LOWER(beneficiary_address) = LOWER(%s)
        """,
        (referrer_address,),
    )
    total_pending = float(cur.fetchone()[0])

    # Update referral_pending_rewards
    if total_pending > 0:
        cur.execute(
            """
            UPDATE referral_pending_rewards
            SET total_pending = %s,
                referral_reward = %s
            WHERE LOWER(user_address) = LOWER(%s) AND status = 'pending'
            """,
            (total_pending, total_pending, referrer_address),
        )
    else:
        # No pending left, mark as processed
        cur.execute(
            """
            UPDATE referral_pending_rewards
            SET status = 'paid',
                total_pending = 0,
                referral_reward = 0
            WHERE LOWER(user_address) = LOWER(%s) AND status = 'pending'
            """,
            (referrer_address,),
        )


def backend_to_rpc(backend_url: str) -> str:
    """Derive RPC URL from backend URL. Same host, port 26657."""
    parsed = urlparse(backend_url)
    host = parsed.hostname or "127.0.0.1"
    return f"tcp://{host}:26657"


def get_miraged_path() -> str:
    bin_path = ROOT / "blockchain" / "bin" / "miraged"
    if bin_path.exists():
        return str(bin_path)
    return "miraged"


def run_cmd(cmd: list[str], timeout: int = 30, input_text: str = None) -> Optional[str]:
    """Run a command and return stdout, or None on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=input_text)
        if result.returncode == 0:
            return result.stdout.strip()
        print(f"[ERROR] Command failed (code {result.returncode}): {result.stderr}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Command timed out after {timeout}s", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[ERROR] Command exception: {e}", file=sys.stderr)
        return None


def import_key_from_seed(bin_path: str, home: str, seed_phrase: str, key_name: str = "airdrop") -> Optional[str]:
    """Import a key from seed phrase into a temporary keyring. Returns the address."""
    # Use test keyring backend for non-interactive operation
    cmd = [
        bin_path, "keys", "add", key_name,
        "--home", home,
        "--keyring-backend", "test",
        "--recover",
    ]
    output = run_cmd(cmd, timeout=30, input_text=seed_phrase + "\n")
    if output is None:
        return None

    # Get the address
    addr_cmd = [
        bin_path, "keys", "show", key_name,
        "--home", home,
        "--keyring-backend", "test",
        "--address",
    ]
    addr_output = run_cmd(addr_cmd, timeout=10)
    return addr_output.strip() if addr_output else None


def delete_key(bin_path: str, home: str, key_name: str = "airdrop") -> None:
    """Delete a key from the keyring."""
    cmd = [
        bin_path, "keys", "delete", key_name,
        "--home", home,
        "--keyring-backend", "test",
        "--yes",
    ]
    run_cmd(cmd, timeout=10)


def get_balance(bin_path: str, address: str, rpc_url: str) -> Optional[int]:
    """Get balance in umirage for an address."""
    output = run_cmd([bin_path, "query", "bank", "balances", address, "--node", rpc_url, "--output", "json"])
    if not output:
        return None
    try:
        data = json.loads(output)
        for bal in data.get("balances", []):
            if bal.get("denom") == DENOM:
                return int(bal.get("amount", 0))
        return 0
    except Exception as e:
        print(f"[ERROR] Failed to parse balance: {e}", file=sys.stderr)
        return None


def send_tokens(
    bin_path: str, home: str, key_name: str, from_addr: str, to_addr: str, amount_umirage: int, rpc_url: str
) -> Optional[str]:
    """Send tokens to recipient. Returns tx_hash on success."""
    cmd = [
        bin_path,
        "tx",
        "bank",
        "send",
        from_addr,
        to_addr,
        f"{amount_umirage}{DENOM}",
        "--from",
        key_name,
        "--home",
        home,
        "--keyring-backend",
        "test",
        "--chain-id",
        CHAIN_ID,
        "--node",
        rpc_url,
        "--broadcast-mode",
        "sync",
        "--yes",
        "--unordered",
        "--timeout-duration",
        "60s",
        "--gas",
        "200000",
        "--gas-prices",
        "1.0umirage",
        "--output",
        "json",
    ]
    output = run_cmd(cmd, timeout=30)
    if not output:
        return None
    try:
        data = json.loads(output)
        code = data.get("code", 0)
        if code != 0:
            raw_log = data.get("raw_log", "unknown error")
            print(f"[ERROR] Transaction failed with code {code}: {raw_log}", file=sys.stderr)
            return None
        return data.get("txhash")
    except Exception as e:
        print(f"[ERROR] Failed to parse tx response: {e}", file=sys.stderr)
        return None


def load_decisions_csv(filepath: str) -> list[dict]:
    """Load referee decisions from CSV file.

    CSV format: referee_username,referee_address,beneficiary_username,beneficiary_address,level,amount,status
    Returns list of decision dicts.
    """
    decisions = []
    with open(filepath, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            referee_username = row.get("referee_username", "").strip()
            referee_address = row.get("referee_address", "").strip()
            beneficiary_username = row.get("beneficiary_username", "").strip()
            beneficiary_address = row.get("beneficiary_address", "").strip()
            level = int(row.get("level", 1))
            amount = float(row.get("amount", 0))
            status = row.get("status", "").strip().lower()
            if referee_address and beneficiary_address and status in ("approved", "denied"):
                decisions.append({
                    "referee_username": referee_username,
                    "referee_address": referee_address,
                    "beneficiary_username": beneficiary_username,
                    "beneficiary_address": beneficiary_address,
                    "level": level,
                    "amount": amount,
                    "status": status,
                })
    return decisions


def write_payout_history(payouts: list[dict], history_file: Path = PAYOUT_HISTORY_FILE) -> None:
    """Append successful payouts to history CSV file."""
    filepath = history_file
    file_exists = filepath.exists()

    with open(filepath, "a", encoding="utf-8", newline="") as f:
        fieldnames = ["timestamp", "username", "address", "amount", "tx_hash"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        for payout in payouts:
            writer.writerow(payout)


def main():
    parser = argparse.ArgumentParser(description="Process referral reward decisions (pay approved, mark denied)")
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=DEFAULT_AIRDROP_FILE,
        help=f"CSV file containing decisions (default: {DEFAULT_AIRDROP_FILE})",
    )
    parser.add_argument("--backend", default="http://127.0.0.1", help="Backend API URL")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without sending")
    parser.add_argument(
        "--timeout", type=float, default=15.0, dest="delay", help="Timeout for tx confirmation (seconds)"
    )
    args = parser.parse_args()

    if not os.path.exists(args.csv_file):
        print(f"ERROR: CSV file not found: {args.csv_file}", file=sys.stderr)
        sys.exit(1)

    # Load decisions from CSV
    decisions = load_decisions_csv(args.csv_file)
    if not decisions:
        print("ERROR: No valid decisions found in CSV", file=sys.stderr)
        sys.exit(1)

    approved = [d for d in decisions if d["status"] == "approved"]
    denied = [d for d in decisions if d["status"] == "denied"]

    # Count unique referees
    approved_referees = set(d["referee_address"] for d in approved)
    denied_referees = set(d["referee_address"] for d in denied)

    print(f"Loaded {len(decisions)} decisions from CSV")
    print(f"  Approved: {len(approved_referees)} referee(s), {len(approved)} beneficiary payments")
    print(f"  Denied: {len(denied_referees)} referee(s), {len(denied)} entries")
    print(f"Backend: {args.backend}")

    rpc_url = backend_to_rpc(args.backend)
    print(f"RPC: {rpc_url}")

    bin_path = get_miraged_path()
    print(f"Binary: {bin_path}")

    # Aggregate approved payments by beneficiary (each beneficiary may receive from multiple referees)
    beneficiary_payments: dict[str, dict] = {}
    for d in approved:
        addr = d["beneficiary_address"]
        if addr not in beneficiary_payments:
            beneficiary_payments[addr] = {
                "beneficiary_username": d["beneficiary_username"],
                "beneficiary_address": addr,
                "amount": 0.0,
                "entries": [],
            }
        beneficiary_payments[addr]["amount"] += d["amount"]
        beneficiary_payments[addr]["entries"].append(d)

    recipients = list(beneficiary_payments.values())
    total_mirage = sum(r["amount"] for r in recipients)

    if not recipients and not denied:
        print("\nNo decisions to process.")
        return

    # Show plan before asking for seed
    print("\n" + "=" * 80)
    print("EXECUTION PLAN")
    print("=" * 80)

    if recipients:
        print(f"\nAPPROVED PAYMENTS: {total_mirage:.6f} MIRAGE to {len(recipients)} beneficiary(ies)")
        for r in recipients:
            referee_names = ", ".join(f"{d['referee_username']}(L{d['level']})" for d in r["entries"])
            print(f"  {r['beneficiary_username']} ({r['beneficiary_address'][:20]}...): {r['amount']:.6f} MIRAGE")
            print(f"    From referees: {referee_names}")

    if denied:
        denied_total = sum(d["amount"] for d in denied)
        print(f"\nDENIED (will mark in DB after payments): {len(denied_referees)} referee(s), {denied_total:.6f} MIRAGE blocked")
        for d in denied:
            print(f"  {d['referee_username']} -> no payment to {d['beneficiary_username']} (L{d['level']})")

    print()

    if args.dry_run:
        print("==> DRY RUN - No transactions will be sent, no DB changes")
        return

    if not recipients:
        # Only denied entries, no payments needed
        print("No approved payments. Processing denied entries...")
        try:
            with connect_db() as conn:
                with conn.cursor() as cur:
                    beneficiaries_updated = set()
                    for d in denied:
                        print(f"  Denying: {d['referee_username']} -> {d['beneficiary_username']} (L{d['level']})")
                        mark_rewards_denied(cur, d["beneficiary_address"], d["referee_address"])
                        beneficiaries_updated.add(d["beneficiary_address"])
                    for beneficiary_addr in beneficiaries_updated:
                        recalculate_referrer_pending(cur, beneficiary_addr)
            print(f"Marked {len(denied)} entries as denied in database")
            try:
                os.remove(args.csv_file)
                print(f"Deleted: {args.csv_file}")
            except OSError as e:
                print(f"Warning: Could not delete {args.csv_file}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"ERROR: Could not update database: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # Prompt for seed phrase
    print("=" * 60)
    print("Enter the seed phrase for the sender wallet.")
    print("(The seed will be used temporarily and not stored)")
    print("=" * 60)
    try:
        seed_phrase = getpass.getpass("Seed phrase: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(1)

    if not seed_phrase:
        print("ERROR: Seed phrase cannot be empty", file=sys.stderr)
        sys.exit(1)

    # Validate seed phrase (basic check - should be 12, 18, or 24 words)
    word_count = len(seed_phrase.split())
    if word_count not in (12, 18, 24):
        print(f"ERROR: Invalid seed phrase (expected 12, 18, or 24 words, got {word_count})", file=sys.stderr)
        sys.exit(1)

    # Create temporary home directory for keyring
    temp_home = tempfile.mkdtemp(prefix="mirage_airdrop_")
    key_name = "airdrop"

    try:
        print(f"\nImporting key from seed phrase...")
        sender_addr = import_key_from_seed(bin_path, temp_home, seed_phrase, key_name)
        if not sender_addr:
            print("ERROR: Could not import key from seed phrase", file=sys.stderr)
            sys.exit(1)
        print(f"Sender address: {sender_addr}")

        sender_balance = get_balance(bin_path, sender_addr, rpc_url)
        if sender_balance is None:
            print("ERROR: Could not query sender balance", file=sys.stderr)
            sys.exit(1)
        print(f"Sender balance: {sender_balance / 1_000_000:.6f} MIRAGE")

        # Calculate total needed
        total_needed = int(total_mirage * 1_000_000)
        gas_buffer = 500_000 * len(recipients)
        if sender_balance < total_needed + gas_buffer:
            print(
                f"ERROR: Insufficient balance. Need {(total_needed + gas_buffer) / 1_000_000:.6f} MIRAGE",
                file=sys.stderr,
            )
            sys.exit(1)

        # Execute airdrops
        print("\n" + "=" * 80)
        print("EXECUTING AIRDROP")
        print("=" * 80 + "\n")

        success_count = 0
        fail_count = 0
        total_sent = 0.0
        results: list[dict] = []

        for i, r in enumerate(recipients, 1):
            username = r["beneficiary_username"]
            address = r["beneficiary_address"]
            amount = r["amount"]
            amount_umirage = int(amount * 1_000_000)
            referee_names = ", ".join(f"{d['referee_username']}(L{d['level']})" for d in r["entries"])
            print(f"\n[{i}/{len(recipients)}] Sending {amount:.6f} MIRAGE to {username} ({address})...")
            print(f"    For referees: {referee_names}")

            before_balance = get_balance(bin_path, address, rpc_url)
            if before_balance is None:
                before_balance = 0
            print(f"  Balance before: {before_balance / 1_000_000:.6f} MIRAGE")

            tx_hash = send_tokens(bin_path, temp_home, key_name, sender_addr, address, amount_umirage, rpc_url)
            if not tx_hash:
                print(f"  FAILED: Transaction failed")
                fail_count += 1
                results.append({"username": username, "address": address, "status": "FAILED", "tx_hash": None})
                time.sleep(args.delay)
                continue

            print(f"  TX Hash: {tx_hash}")
            print(f"  Waiting for confirmation (up to {args.delay}s)...", end="", flush=True)

            # Poll for confirmation - balance must increase
            confirmed = False
            start_time = time.time()
            poll_interval = 2.0
            after_balance = before_balance

            while time.time() - start_time < args.delay:
                time.sleep(poll_interval)
                after_balance = get_balance(bin_path, address, rpc_url)
                if after_balance is None:
                    print(".", end="", flush=True)
                    continue
                if after_balance >= before_balance + amount_umirage:
                    confirmed = True
                    break
                print(".", end="", flush=True)

            print()

            if not confirmed:
                elapsed = time.time() - start_time
                print(f"  FAILED: Transaction not confirmed after {elapsed:.1f}s")
                print(f"  Balance before: {before_balance / 1_000_000:.6f}, after: {(after_balance or 0) / 1_000_000:.6f}")
                print(f"\nABORTING: Transaction {tx_hash} did not confirm. Fix the issue before retrying.")
                fail_count += 1
                results.append({"username": username, "address": address, "status": "FAILED", "tx_hash": tx_hash})
                break

            print(f"  CONFIRMED: Balance {before_balance / 1_000_000:.6f} -> {after_balance / 1_000_000:.6f} MIRAGE")
            success_count += 1
            total_sent += amount
            results.append(
                {
                    "username": username,
                    "address": address,
                    "amount": amount,
                    "status": "SUCCESS",
                    "tx_hash": tx_hash,
                    "balance_before": before_balance,
                    "balance_after": after_balance,
                    "entries": r["entries"],
                }
            )

        # Summary
        print("\n" + "=" * 80)
        print("PAYMENT SUMMARY")
        print("=" * 80)
        print(f"Beneficiaries paid: {success_count}")
        print(f"Failed: {fail_count}")
        print(f"Total sent: {total_sent:.6f} MIRAGE")
        if denied:
            print(f"Denied entries to process: {len(denied)}")

        final_sender_balance = get_balance(bin_path, sender_addr, rpc_url)
        if final_sender_balance is not None:
            print(f"Sender remaining balance: {final_sender_balance / 1_000_000:.6f} MIRAGE")

        # Print failed recipients
        failed = [r for r in results if r["status"] == "FAILED"]
        if failed:
            print("\nFailed recipients:")
            for r in failed:
                print(f"  - {r['username']} ({r['address']})")

        # Write successful payouts to history and update database
        successful = [r for r in results if r["status"] == "SUCCESS"]
        if successful:
            now = datetime.now(timezone.utc).isoformat()
            payouts = [
                {
                    "timestamp": now,
                    "username": r["username"],
                    "address": r["address"],
                    "amount": r["amount"],
                    "tx_hash": r["tx_hash"],
                }
                for r in successful
            ]
            write_payout_history(payouts)
            print(f"\nRecorded {len(payouts)} payouts to {PAYOUT_HISTORY_FILE}")

            # Update database to mark rewards as paid for each (beneficiary, referee) pair
            try:
                with connect_db() as conn:
                    with conn.cursor() as cur:
                        beneficiaries_updated = set()
                        entry_count = 0
                        for r in successful:
                            beneficiary_addr = r["address"]
                            beneficiaries_updated.add(beneficiary_addr)
                            for entry in r["entries"]:
                                mark_rewards_paid(
                                    cur,
                                    beneficiary_addr,
                                    entry["referee_address"],
                                    entry["amount"],
                                    r["tx_hash"],
                                )
                                entry_count += 1
                        # Recalculate totals for affected beneficiaries
                        for beneficiary_addr in beneficiaries_updated:
                            recalculate_referrer_pending(cur, beneficiary_addr)
                print(f"Updated database: {entry_count} reward entries marked as paid")
            except Exception as e:
                print(f"WARNING: Could not update database: {e}", file=sys.stderr)
                print("Rewards were sent but database not updated. Manual fix may be required.")

        if fail_count > 0:
            print("\nNOT processing denied entries due to payment failures.")
            sys.exit(1)

        # Process denied entries LAST (only if all payments succeeded)
        if denied and success_count > 0:
            print(f"\nProcessing {len(denied)} denied entries...")
            try:
                with connect_db() as conn:
                    with conn.cursor() as cur:
                        beneficiaries_updated = set()
                        for d in denied:
                            print(f"  Denying: {d['referee_username']} -> {d['beneficiary_username']} (L{d['level']})")
                            mark_rewards_denied(cur, d["beneficiary_address"], d["referee_address"])
                            beneficiaries_updated.add(d["beneficiary_address"])
                        for beneficiary_addr in beneficiaries_updated:
                            recalculate_referrer_pending(cur, beneficiary_addr)
                print(f"Marked {len(denied)} entries as denied in database")
            except Exception as e:
                print(f"WARNING: Could not mark denied entries: {e}", file=sys.stderr)
                print("Payments were sent but denied entries not marked. Manual fix may be required.")

        # Delete the input file after successful airdrop
        if success_count > 0 and fail_count == 0:
            try:
                os.remove(args.csv_file)
                print(f"Deleted: {args.csv_file}")
            except OSError as e:
                print(f"\nWarning: Could not delete {args.csv_file}: {e}", file=sys.stderr)

    finally:
        # Clean up temporary keyring
        if os.path.exists(temp_home):
            shutil.rmtree(temp_home, ignore_errors=True)
            print(f"\nCleaned up temporary keyring")


if __name__ == "__main__":
    main()
