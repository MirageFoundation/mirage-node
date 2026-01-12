#!/usr/bin/env python3
"""
Calculate gas usage statistics for the last N transactions.

Queries CometBFT RPC to get recent transactions and extracts gas information.

Usage:
  # Remote node (no local setup required)
  python3 scripts/gas_usage.py --rpc https://mirage.talk:26657

  # Local node (auto-detects from config)
  python3 scripts/gas_usage.py

  # Options
  python3 scripts/gas_usage.py --rpc https://mirage.talk:26657 --count 50
  python3 scripts/gas_usage.py --rpc https://mirage.talk:26657 --json

  # Daily stats (for minting calculations)
  python3 scripts/gas_usage.py --rpc http://mirage.talk:26657 --daily --days 14
"""

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone


# Default public RPC endpoint (port 26657 is HTTP, not HTTPS)
DEFAULT_RPC = "http://mirage.talk:26657"

# Permissive SSL context for production servers
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def get_local_rpc_url():
    """Try to get RPC URL from local config, fall back to default."""
    home_base = os.path.expanduser("~/.mirage")
    config_path = os.path.join(home_base, "node", "config", "config.toml")

    if not os.path.isfile(config_path):
        return None

    # Simple TOML parsing
    result = {}
    section = None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section = line[1:-1].strip()
                    result[section] = {}
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if section:
                        result[section][k] = v
                    else:
                        result[k] = v
    except Exception:
        return None

    laddr = (result.get("rpc") or {}).get("laddr", "")
    if not laddr:
        return None

    laddr = laddr.replace("tcp://", "http://").replace("0.0.0.0", "127.0.0.1")
    return laddr


def http_json(url, timeout=30.0):
    req = urllib.request.Request(url, headers={"User-Agent": "gas-usage"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as r:
        return json.load(r)


def b64_decode(s):
    if not s:
        return ""
    if all(c.isalnum() or c in "_-. /@:" for c in s):
        return s
    try:
        raw = base64.b64decode(s, validate=True)
        decoded = raw.decode("utf-8", errors="strict")
        if decoded.isprintable():
            return decoded
        return s
    except Exception:
        return s


def decode_attrs(attrs):
    out = {}
    for a in attrs:
        k = b64_decode(a.get("key", ""))
        v = b64_decode(a.get("value", ""))
        out[k] = v
    return out


def parse_fee_umirage(fee_str: str) -> int:
    """Parse fee string like '1234umirage' to integer umirage amount."""
    if not fee_str:
        return 0
    fee_str = fee_str.strip()
    if fee_str.endswith("umirage"):
        try:
            return int(fee_str[:-7])
        except ValueError:
            return 0
    # Try to parse as plain number
    try:
        return int(fee_str)
    except ValueError:
        return 0


@dataclass
class TxGasInfo:
    height: int
    tx_index: int
    tx_hash: str
    gas_wanted: int
    gas_used: int
    fee_str: str
    fee_umirage: int
    actions: list
    timestamp: datetime = None  # Block timestamp

    @property
    def fee_mirage(self) -> float:
        """Fee in MIRAGE (1 MIRAGE = 1,000,000 umirage)."""
        return self.fee_umirage / 1_000_000

    @property
    def gas_price(self) -> float:
        """Gas price in umirage per gas unit (fee / gas_wanted)."""
        if self.gas_wanted == 0:
            return 0.0
        return self.fee_umirage / self.gas_wanted

    @property
    def date_str(self) -> str:
        """Date string YYYY-MM-DD."""
        if self.timestamp:
            return self.timestamp.strftime("%Y-%m-%d")
        return "unknown"


def get_height_range(rpc):
    st = http_json(f"{rpc}/status")
    sync = st["result"]["sync_info"]
    latest = int(sync["latest_block_height"])
    earliest = int(sync.get("earliest_block_height") or 1)
    return earliest, latest


# Cache for block timestamps to avoid repeated requests
_block_timestamp_cache = {}


def get_block_timestamp(rpc, height: int) -> datetime:
    """Get the timestamp of a block."""
    if height in _block_timestamp_cache:
        return _block_timestamp_cache[height]

    try:
        blk = http_json(f"{rpc}/block?height={height}")
        time_str = blk.get("result", {}).get("block", {}).get("header", {}).get("time", "")
        # Parse ISO format: 2024-01-15T10:30:00.123456789Z
        if time_str:
            # Truncate nanoseconds to microseconds for Python
            if "." in time_str:
                base, frac = time_str.split(".")
                frac = frac.rstrip("Z")[:6]  # Keep only 6 digits
                time_str = f"{base}.{frac}+00:00"
            else:
                time_str = time_str.rstrip("Z") + "+00:00"
            ts = datetime.fromisoformat(time_str)
            _block_timestamp_cache[height] = ts
            return ts
    except Exception:
        pass
    return None


def get_block_txs(rpc, height) -> list[TxGasInfo]:
    """Get transaction gas info from a block."""
    results = []
    try:
        br = http_json(f"{rpc}/block_results?height={height}")
        res = br.get("result") or {}
        txs_results = res.get("txs_results") or []

        for idx, tx_res in enumerate(txs_results):
            # Gas info is directly in tx_result
            gas_wanted = int(tx_res.get("gas_wanted", 0) or 0)
            gas_used = int(tx_res.get("gas_used", 0) or 0)

            # Extract fee and action from events
            # Fee is in coin_spent event going to fee_collector (mirage17xpfvakm2amg962yls6f84z3kell8c5lxzd6yx)
            fee_umirage = 0
            actions = []
            for ev in tx_res.get("events") or []:
                et = b64_decode(ev.get("type", ""))
                attrs = decode_attrs(ev.get("attributes") or [])

                # Look for coin_received by fee_collector - this is the tx fee
                if et == "coin_received":
                    receiver = attrs.get("receiver", "")
                    # fee_collector module address
                    if receiver == "mirage17xpfvakm2amg962yls6f84z3kell8c5lxzd6yx":
                        fee_umirage += parse_fee_umirage(attrs.get("amount", ""))

                if et == "message":
                    action = attrs.get("action", "")
                    if action:
                        actions.append(action)

            # Get tx hash from block
            blk = http_json(f"{rpc}/block?height={height}")
            txs = blk.get("result", {}).get("block", {}).get("data", {}).get("txs", [])
            tx_hash = ""
            if idx < len(txs):
                import hashlib

                tx_bytes = base64.b64decode(txs[idx])
                tx_hash = hashlib.sha256(tx_bytes).hexdigest().upper()

            results.append(
                TxGasInfo(
                    height=height,
                    tx_index=idx,
                    tx_hash=tx_hash,
                    gas_wanted=gas_wanted,
                    gas_used=gas_used,
                    fee_str=f"{fee_umirage}umirage",
                    fee_umirage=fee_umirage,
                    actions=actions,
                )
            )
    except Exception as e:
        print(f"Error fetching block {height}: {e}", file=sys.stderr)

    return results


def collect_txs_via_search(rpc, count: int, fetch_timestamps: bool = False) -> list[TxGasInfo]:
    """Collect the last N transactions using tx_search (fast method)."""
    print(f"Fetching last {count} transactions via tx_search...", file=sys.stderr)

    txs = []
    page = 1
    per_page = min(100, count)  # CometBFT max is 100 per page
    heights_to_fetch = set()

    while len(txs) < count:
        # Query txs ordered by height desc
        url = f'{rpc}/tx_search?query="tx.height>0"' f'&per_page={per_page}&page={page}&order_by="desc"'
        try:
            data = http_json(url)
            result = data.get("result", {})
            total = int(result.get("total_count", 0))
            tx_results = result.get("txs", [])

            if not tx_results:
                break

            for tx_data in tx_results:
                if len(txs) >= count:
                    break

                height = int(tx_data.get("height", 0))
                tx_result = tx_data.get("tx_result", {})
                tx_hash = tx_data.get("hash", "")

                gas_wanted = int(tx_result.get("gas_wanted", 0) or 0)
                gas_used = int(tx_result.get("gas_used", 0) or 0)

                # Extract fee and actions from events
                fee_umirage = 0
                actions = []
                for ev in tx_result.get("events") or []:
                    et = ev.get("type", "")
                    attrs = {a.get("key", ""): a.get("value", "") for a in ev.get("attributes", [])}

                    # Fee is in coin_received by fee_collector
                    if et == "coin_received":
                        receiver = attrs.get("receiver", "")
                        if receiver == "mirage17xpfvakm2amg962yls6f84z3kell8c5lxzd6yx":
                            fee_umirage += parse_fee_umirage(attrs.get("amount", ""))

                    if et == "message":
                        action = attrs.get("action", "")
                        if action:
                            actions.append(action)

                txs.append(
                    TxGasInfo(
                        height=height,
                        tx_index=0,  # Not available in tx_search
                        tx_hash=tx_hash,
                        gas_wanted=gas_wanted,
                        gas_used=gas_used,
                        fee_str=f"{fee_umirage}umirage",
                        fee_umirage=fee_umirage,
                        actions=actions,
                    )
                )
                heights_to_fetch.add(height)

            print(f"  Page {page}: {len(tx_results)} txs (total available: {total})", file=sys.stderr)

            if len(tx_results) < per_page:
                break
            page += 1

        except Exception as e:
            print(f"Error in tx_search: {e}", file=sys.stderr)
            break

    txs = txs[:count]

    # Fetch timestamps if requested
    if fetch_timestamps and txs:
        print(f"  Fetching timestamps for {len(heights_to_fetch)} unique blocks...", file=sys.stderr)
        for i, tx in enumerate(txs):
            tx.timestamp = get_block_timestamp(rpc, tx.height)
            if (i + 1) % 100 == 0:
                print(f"    Processed {i + 1}/{len(txs)} timestamps...", file=sys.stderr)

    return txs


def collect_txs(rpc, count: int) -> list[TxGasInfo]:
    """Collect the last N transactions - tries tx_search first, falls back to block scan."""
    # Try fast method first
    txs = collect_txs_via_search(rpc, count)

    if txs:
        return txs

    # Fallback to block scanning
    print("tx_search unavailable, falling back to block scanning...", file=sys.stderr)
    earliest, latest = get_height_range(rpc)

    txs = []
    height = latest

    print(f"Scanning blocks from height {latest}...", file=sys.stderr)

    while len(txs) < count and height >= earliest:
        block_txs = get_block_txs(rpc, height)

        # Add in reverse order (most recent first within block)
        for tx in reversed(block_txs):
            txs.append(tx)
            if len(txs) >= count:
                break

        height -= 1

        # Progress indicator
        if (latest - height) % 100 == 0 and len(txs) < count:
            print(f"  Scanned {latest - height} blocks, found {len(txs)} txs...", file=sys.stderr)

    # Sort by height desc, then tx_index desc (most recent first)
    txs.sort(key=lambda t: (t.height, t.tx_index), reverse=True)

    return txs[:count]


def format_gas(gas: int) -> str:
    """Format gas with commas."""
    return f"{gas:,}"


def print_daily_stats(txs: list[TxGasInfo], gas_price_umirage: int = 5000):
    """Print daily transaction statistics for minting calculations."""

    # Group transactions by date
    daily_txs = defaultdict(list)
    for tx in txs:
        if tx.timestamp:
            date_key = tx.timestamp.strftime("%Y-%m-%d")
            daily_txs[date_key].append(tx)

    if not daily_txs:
        print("No transactions with timestamps found!", file=sys.stderr)
        return

    # Sort dates
    sorted_dates = sorted(daily_txs.keys(), reverse=True)

    # Calculate daily stats
    daily_stats = []
    for date in sorted_dates:
        day_txs = daily_txs[date]
        tx_count = len(day_txs)
        total_gas = sum(tx.gas_used for tx in day_txs)
        total_fee = sum(tx.fee_umirage for tx in day_txs)
        avg_gas = total_gas / tx_count if tx_count else 0

        # Calculate MIRAGE burned at the specified gas price
        mirage_burned = (total_gas * gas_price_umirage) / 1_000_000

        daily_stats.append(
            {
                "date": date,
                "txs": tx_count,
                "total_gas": total_gas,
                "avg_gas": avg_gas,
                "total_fee_umirage": total_fee,
                "mirage_burned": mirage_burned,
            }
        )

    # Overall averages (excluding partial days - first and last)
    full_days = daily_stats[1:-1] if len(daily_stats) > 2 else daily_stats
    avg_txs_per_day = sum(d["txs"] for d in full_days) / len(full_days) if full_days else 0
    avg_gas_per_day = sum(d["total_gas"] for d in full_days) / len(full_days) if full_days else 0
    avg_mirage_burned = sum(d["mirage_burned"] for d in full_days) / len(full_days) if full_days else 0

    # Calculate recommended minting
    # MintInterval = 200 blocks ≈ 10 minutes
    # 144 mint events per day (24 * 60 / 10)
    mints_per_day = 144
    recommended_mint_per_interval = avg_mirage_burned / mints_per_day if mints_per_day else 0
    recommended_mint_umirage = int(recommended_mint_per_interval * 1_000_000)

    # Print report
    print()
    print("=" * 80)
    print("  Daily Transaction Statistics (for Minting Calculations)")
    print("=" * 80)
    print()
    print(f"  Gas Price Used:        {gas_price_umirage:,} umirage/gas")
    print(f"  MIRAGE Price Target:   $0.00001/MIRAGE")
    print()
    print("  " + "-" * 76)
    print(f"  {'Date':<12} {'Txs':>8} {'Total Gas':>14} {'Avg Gas':>10} {'MIRAGE Burned':>16}")
    print("  " + "-" * 76)

    for stat in daily_stats:
        print(
            f"  {stat['date']:<12} "
            f"{stat['txs']:>8,} "
            f"{stat['total_gas']:>14,} "
            f"{stat['avg_gas']:>10,.0f} "
            f"{stat['mirage_burned']:>16,.2f}"
        )

    print("  " + "-" * 76)
    print()
    print("  Summary (excluding first/last partial days):")
    print(f"    Average Txs/Day:           {avg_txs_per_day:,.1f}")
    print(f"    Average Gas/Day:           {avg_gas_per_day:,.0f}")
    print(f"    Average MIRAGE Burned/Day: {avg_mirage_burned:,.2f}")
    print()
    print("  " + "=" * 76)
    print("  Recommended Minting Parameters")
    print("  " + "=" * 76)
    print()
    print(f"    To cover current usage:")
    print(f"      MintInterval:  200 (every ~10 min)")
    print(f"      MintQuantity:  {recommended_mint_umirage:,} umirage ({recommended_mint_per_interval:,.2f} MIRAGE)")
    print()
    print(f"    Minting scenarios (MIRAGE/day):")
    print()
    print(f"    {'Scenario':<15} {'MintQuantity':>18} {'MIRAGE/Day':>14} {'Covers':>12}")
    print("    " + "-" * 62)

    scenarios = [
        ("Current Usage", recommended_mint_umirage, "100%"),
        ("1.5x Buffer", int(recommended_mint_umirage * 1.5), "150%"),
        ("2x Buffer", int(recommended_mint_umirage * 2), "200%"),
        ("Conservative", int(recommended_mint_umirage * 0.5), "50%"),
    ]

    for name, mint_qty, coverage in scenarios:
        mirage_per_day = (mint_qty / 1_000_000) * mints_per_day
        print(f"    {name:<15} {mint_qty:>18,} {mirage_per_day:>14,.2f} {coverage:>12}")

    print()
    print("  " + "-" * 76)
    print()
    print("  Action Breakdown (for tuning):")
    print()

    # Action stats
    action_counts = defaultdict(int)
    action_gas = defaultdict(int)
    for tx in txs:
        for action in tx.actions:
            action_counts[action] += 1
            action_gas[action] += tx.gas_used

    print(f"    {'Action':<45} {'Count':>8} {'Avg Gas':>12} {'MIRAGE/Action':>14}")
    print("    " + "-" * 80)

    for action in sorted(action_gas.keys(), key=lambda a: action_counts[a], reverse=True):
        count = action_counts[action]
        avg = action_gas[action] / count
        mirage_per_action = (avg * gas_price_umirage) / 1_000_000
        # Shorten action name
        short_action = action.split(".")[-1] if "/" in action else action
        print(f"    {short_action:<45} {count:>8,} {avg:>12,.0f} {mirage_per_action:>14,.2f}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description="Calculate gas usage for recent transactions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  %(prog)s --rpc http://mirage.talk:26657
  %(prog)s --rpc http://mirage.talk:26657 --count 50
  %(prog)s --rpc http://mirage.talk:26657 --json
  
  # Daily stats for minting calculations
  %(prog)s --rpc http://mirage.talk:26657 --daily
  %(prog)s --rpc http://mirage.talk:26657 --daily --days 14
  %(prog)s --rpc http://mirage.talk:26657 --daily --gas-price 2500
  
Default RPC: {DEFAULT_RPC}
        """,
    )
    parser.add_argument("--rpc", type=str, default=None, help=f"RPC URL (default: {DEFAULT_RPC})")
    parser.add_argument("--count", "-n", type=int, default=100, help="Number of transactions to analyze (default: 100)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument(
        "--daily", action="store_true", help="Show daily transaction statistics for minting calculations"
    )
    parser.add_argument("--days", type=int, default=7, help="Number of days to analyze for --daily mode (default: 7)")
    parser.add_argument(
        "--gas-price", type=int, default=5000, help="Gas price in umirage for calculations (default: 5000)"
    )
    args = parser.parse_args()

    # Determine RPC URL: explicit arg > local config > default
    if args.rpc:
        rpc = args.rpc
        print(f"Using RPC: {rpc}", file=sys.stderr)
    else:
        local_rpc = get_local_rpc_url()
        if local_rpc:
            rpc = local_rpc
            print(f"Using local RPC: {rpc}", file=sys.stderr)
        else:
            rpc = DEFAULT_RPC
            print(f"Using default RPC: {rpc}", file=sys.stderr)

    # For daily mode, we need more transactions and timestamps
    if args.daily:
        # Estimate: need roughly 100-500 txs per day, fetch more to be safe
        estimated_count = args.days * 500
        print(f"Daily mode: fetching up to {estimated_count} txs for {args.days} days...", file=sys.stderr)
        txs = collect_txs_via_search(rpc, estimated_count, fetch_timestamps=True)

        if not txs:
            print("No transactions found!", file=sys.stderr)
            sys.exit(1)

        print_daily_stats(txs, gas_price_umirage=args.gas_price)
        return

    txs = collect_txs(rpc, args.count)

    if not txs:
        print("No transactions found!", file=sys.stderr)
        sys.exit(1)

    # Calculate stats
    total_gas_used = sum(tx.gas_used for tx in txs)
    total_gas_wanted = sum(tx.gas_wanted for tx in txs)
    avg_gas_used = total_gas_used / len(txs)
    avg_gas_wanted = total_gas_wanted / len(txs) if total_gas_wanted > 0 else 0
    min_gas_used = min(tx.gas_used for tx in txs)
    max_gas_used = max(tx.gas_used for tx in txs)

    # Fee/cost stats
    total_fee_umirage = sum(tx.fee_umirage for tx in txs)
    total_fee_mirage = total_fee_umirage / 1_000_000
    avg_fee_umirage = total_fee_umirage / len(txs)
    avg_fee_mirage = avg_fee_umirage / 1_000_000

    # Gas price (umirage per gas unit) - calculated from gas_wanted, not gas_used
    avg_gas_price = total_fee_umirage / total_gas_wanted if total_gas_wanted > 0 else 0
    gas_prices = [tx.gas_price for tx in txs if tx.gas_wanted > 0]
    min_gas_price = min(gas_prices) if gas_prices else 0
    max_gas_price = max(gas_prices) if gas_prices else 0

    # Efficiency (how much of wanted gas was actually used)
    efficiency = (total_gas_used / total_gas_wanted * 100) if total_gas_wanted > 0 else 0

    # Height range
    heights = [tx.height for tx in txs]
    min_height = min(heights)
    max_height = max(heights)

    # Action breakdown (now with fees)
    action_gas = {}
    action_fees = {}
    action_counts = {}
    for tx in txs:
        for action in tx.actions:
            action_gas[action] = action_gas.get(action, 0) + tx.gas_used
            action_fees[action] = action_fees.get(action, 0) + tx.fee_umirage
            action_counts[action] = action_counts.get(action, 0) + 1

    if args.json:
        output = {
            "transaction_count": len(txs),
            "height_range": {
                "min": min_height,
                "max": max_height,
            },
            "gas_stats": {
                "total_used": total_gas_used,
                "total_wanted": total_gas_wanted,
                "average_used": round(avg_gas_used, 2),
                "average_wanted": round(avg_gas_wanted, 2),
                "min_used": min_gas_used,
                "max_used": max_gas_used,
                "efficiency_percent": round(efficiency, 2),
            },
            "fee_stats": {
                "total_umirage": total_fee_umirage,
                "total_mirage": round(total_fee_mirage, 6),
                "average_umirage": round(avg_fee_umirage, 2),
                "average_mirage": round(avg_fee_mirage, 6),
            },
            "gas_price_stats": {
                "average_umirage_per_gas": round(avg_gas_price, 4),
                "min_umirage_per_gas": round(min_gas_price, 4),
                "max_umirage_per_gas": round(max_gas_price, 4),
            },
            "by_action": {
                action: {
                    "count": action_counts[action],
                    "total_gas": action_gas[action],
                    "avg_gas": round(action_gas[action] / action_counts[action], 2),
                    "total_fee_umirage": action_fees[action],
                    "avg_fee_mirage": round((action_fees[action] / action_counts[action]) / 1_000_000, 6),
                }
                for action in sorted(action_gas.keys())
            },
            "transactions": [
                {
                    "height": tx.height,
                    "tx_index": tx.tx_index,
                    "tx_hash": tx.tx_hash,
                    "gas_wanted": tx.gas_wanted,
                    "gas_used": tx.gas_used,
                    "fee_umirage": tx.fee_umirage,
                    "fee_mirage": round(tx.fee_mirage, 6),
                    "gas_price": round(tx.gas_price, 4),
                    "actions": tx.actions,
                }
                for tx in txs
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        # Pretty print
        print()
        print("=" * 70)
        print(f"  Gas Usage Report - Last {len(txs)} Transactions")
        print("=" * 70)
        print()
        print(f"  Height Range: {min_height:,} - {max_height:,}")
        print()
        print("  Gas Statistics:")
        print(f"    Total Gas Used:    {format_gas(total_gas_used)}")
        print(f"    Total Gas Wanted:  {format_gas(total_gas_wanted)}")
        print(f"    Average Gas Used:  {format_gas(int(avg_gas_used))}")
        print(f"    Min Gas Used:      {format_gas(min_gas_used)}")
        print(f"    Max Gas Used:      {format_gas(max_gas_used)}")
        print(f"    Efficiency:        {efficiency:.1f}%")
        print()
        print("  Fee/Cost Statistics:")
        print(f"    Total Fees:        {total_fee_umirage:,} umirage ({total_fee_mirage:.6f} MIRAGE)")
        print(f"    Average Fee/Tx:    {avg_fee_umirage:,.2f} umirage ({avg_fee_mirage:.6f} MIRAGE)")
        print()
        print("  Gas Price (umirage per gas unit):")
        print(f"    Average:           {avg_gas_price:.4f}")
        print(f"    Min:               {min_gas_price:.4f}")
        print(f"    Max:               {max_gas_price:.4f}")
        print()

        if action_gas:
            print("  Gas & Cost by Action Type:")
            for action in sorted(action_gas.keys()):
                count = action_counts[action]
                avg_gas = action_gas[action] / count
                avg_fee = (action_fees[action] / count) / 1_000_000
                print(f"    {action}:")
                print(f"      {count} txs, " f"{format_gas(int(avg_gas))} avg gas, " f"{avg_fee:.6f} MIRAGE avg")
            print()

        print("  Recent Transactions (showing first 10):")
        print("  " + "-" * 66)
        print(f"  {'Height':>10}  {'Gas Used':>10}  {'Fee (umirage)':>14}  " f"{'MIRAGE':>10}  Action")
        print("  " + "-" * 66)
        for tx in txs[:10]:
            action_str = tx.actions[0] if tx.actions else "?"
            # Shorten action names
            if "/" in action_str:
                action_str = action_str.split(".")[-1]
            if len(action_str) > 12:
                action_str = action_str[:9] + "..."
            print(
                f"  {tx.height:>10}  {tx.gas_used:>10,}  {tx.fee_umirage:>14,}  "
                f"{tx.fee_mirage:>10.6f}  {action_str}"
            )
        if len(txs) > 10:
            print(f"  ... and {len(txs) - 10} more transactions")
        print()


if __name__ == "__main__":
    main()
