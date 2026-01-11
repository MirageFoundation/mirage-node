#!/usr/bin/env python3
"""
List burn-causing activity over the last N days (default: 7).

Categorizes burns by source:
- fee_collector_burn: Gas fees paid by tx submitters (validators for PoW users)
- subscriber_relay_burn: Relay gas from subscriber reserves
- subscription_fee_burn: Period fee burns on subscribe/renew
- leftover_reserve_burn: Unused reserve burned on expiry/renewal

Outputs JSONL to stdout, summary to stderr.

Usage:
  python3 scripts/list_burns.py
  python3 scripts/list_burns.py --days 3
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------------
# Config
# ----------------------------


def get_node_home():
    home_base = os.path.expanduser("~/.mirage")
    return os.path.join(home_base, "node")


def read_toml_simple(path):
    result = {}
    section = None
    with open(path, "r", encoding="utf-8") as f:
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
    return result


def get_local_rpc_url():
    home = get_node_home()
    config_path = os.path.join(home, "config", "config.toml")
    if not os.path.isfile(config_path):
        return "http://127.0.0.1:26657"
    cfg = read_toml_simple(config_path)
    laddr = (cfg.get("rpc") or {}).get("laddr", "tcp://127.0.0.1:26657")
    laddr = laddr.replace("tcp://", "http://").replace("0.0.0.0", "127.0.0.1")
    return laddr


# ----------------------------
# Bech32
# ----------------------------

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _bech32_polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = ((chk & 0x1FFFFFF) << 5) ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp, data):
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _bech32_encode(hrp, data):
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in combined)


def _convertbits(data, frombits, tobits, pad=True):
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    for b in data:
        acc = (acc << frombits) | b
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def module_address(hrp, module_name):
    h = hashlib.sha256(module_name.encode("utf-8")).digest()[:20]
    data = _convertbits(h, 8, 5, pad=True)
    return _bech32_encode(hrp, data)


# ----------------------------
# HTTP
# ----------------------------


def http_json(url, timeout=60.0):
    req = urllib.request.Request(url, headers={"User-Agent": "list-burns"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def b64_decode(s):
    if not s:
        return ""
    # If it looks like a normal string, don't decode
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


def parse_umirage(s):
    if not s:
        return 0
    total = 0
    for part in str(s).split(","):
        part = part.strip()
        if part.endswith("umirage"):
            n = part[:-7].strip()
            if n.isdigit():
                total += int(n)
    return total


def iso_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_rfc3339(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


# ----------------------------
# RPC
# ----------------------------


def rpc_status(rpc):
    return http_json(f"{rpc}/status")


def rpc_block(rpc, height):
    return http_json(f"{rpc}/block?height={height}")


def rpc_block_results(rpc, height):
    return http_json(f"{rpc}/block_results?height={height}")


def get_height_range(rpc):
    st = rpc_status(rpc)
    sync = st["result"]["sync_info"]
    latest = int(sync["latest_block_height"])
    earliest = int(sync.get("earliest_block_height") or 1)
    return earliest, latest


def get_block_time(rpc, height):
    b = rpc_block(rpc, height)
    t = b["result"]["block"]["header"]["time"]
    return parse_rfc3339(t)


def find_start_height(rpc, cutoff_dt, earliest, latest):
    lo, hi = earliest, latest
    while lo < hi:
        mid = (lo + hi) // 2
        t = get_block_time(rpc, mid)
        if t < cutoff_dt:
            lo = mid + 1
        else:
            hi = mid
    return lo


# ----------------------------
# Event extraction
# ----------------------------


def decode_attrs(attrs):
    out = {}
    for a in attrs:
        k = b64_decode(a.get("key", ""))
        v = b64_decode(a.get("value", ""))
        out[k] = v
    return out


def analyze_block_events(events, fee_collector_addr, core_addr):
    """
    Analyze a sequence of events to categorize burns.
    
    Returns list of categorized burns with:
    - category: fee_collector_burn, subscriber_relay_burn, subscription_fee_burn, etc.
    - amount_umirage
    - details
    """
    results = []
    
    # Track transfers and burns
    fee_collector_transfers = []  # Amounts transferred from fee_collector to core
    subscription_events = []
    burns = []
    
    for ev in events:
        et = b64_decode(ev.get("type", ""))
        attrs = decode_attrs(ev.get("attributes") or [])
        
        # Track transfers from fee_collector to core
        if et == "transfer":
            sender = attrs.get("sender", "")
            recipient = attrs.get("recipient", "")
            amount = attrs.get("amount", "")
            if sender == fee_collector_addr and recipient == core_addr:
                fee_collector_transfers.append(parse_umirage(amount))
        
        # Track subscription events
        if et in ("subscription_expired", "subscription_renewed"):
            subscription_events.append({"type": et, "attrs": attrs})
        
        # Track burns
        if et in ("burn", "coin_burn"):
            amt = parse_umirage(attrs.get("amount", ""))
            if amt > 0:
                burns.append({
                    "burner": attrs.get("burner", ""),
                    "amount_umirage": amt,
                    "amount_raw": attrs.get("amount", ""),
                })
    
    # Now categorize burns
    fee_collector_total = sum(fee_collector_transfers)
    remaining_fee_collector = fee_collector_total
    
    for burn in burns:
        amt = burn["amount_umirage"]
        
        # Check if this burn matches a fee_collector transfer
        if remaining_fee_collector >= amt and amt > 0:
            # This burn came from fee_collector (gas fees paid by tx submitters)
            results.append({
                "category": "fee_collector_burn",
                "reason": "gas_fee_from_tx_submitter",
                "amount_umirage": amt,
                "burner": burn["burner"],
            })
            remaining_fee_collector -= amt
        elif subscription_events:
            # Burns during subscription processing
            # Large burns (>10000) are likely period fee burns
            # Smaller burns are leftover reserve burns
            if amt >= 100000:  # 0.1 MIRAGE threshold for period fee
                results.append({
                    "category": "subscription_fee_burn",
                    "reason": "period_fee_burn_on_renewal",
                    "amount_umirage": amt,
                    "burner": burn["burner"],
                    "subscription_events": subscription_events,
                })
            else:
                results.append({
                    "category": "leftover_reserve_burn",
                    "reason": "unused_reserve_burned_on_renewal",
                    "amount_umirage": amt,
                    "burner": burn["burner"],
                    "subscription_events": subscription_events,
                })
        else:
            # Burns from core without fee_collector transfer or subscription
            # This is subscriber relay gas
            results.append({
                "category": "subscriber_relay_burn",
                "reason": "relay_gas_from_subscriber_reserve",
                "amount_umirage": amt,
                "burner": burn["burner"],
            })
    
    # Also emit subscription events without burns (for tracking)
    if subscription_events and not burns:
        results.append({
            "category": "subscription_event",
            "reason": "subscription_processed_no_burn",
            "amount_umirage": 0,
            "subscription_events": subscription_events,
        })
    
    return results


def extract_tx_events(tx_res, fee_collector_addr, core_addr):
    """Extract and categorize events from a transaction result."""
    events = tx_res.get("events") or []
    
    # Get basic tx info
    fee = 0
    actions = []
    for ev in events:
        et = b64_decode(ev.get("type", ""))
        attrs = decode_attrs(ev.get("attributes") or [])
        if et == "tx":
            fee = parse_umirage(attrs.get("fee", ""))
        if et == "message":
            action = attrs.get("action", "")
            if action:
                actions.append(action)
    
    # Analyze burns in this tx
    burns = analyze_block_events(events, fee_collector_addr, core_addr)
    
    return {"fee": fee, "actions": actions, "burns": burns}


# ----------------------------
# Output
# ----------------------------


def emit(obj):
    sys.stdout.write(json.dumps(obj, sort_keys=False) + "\n")


def log(obj):
    sys.stderr.write(json.dumps(obj, sort_keys=False) + "\n")


# ----------------------------
# Main
# ----------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    args = ap.parse_args()

    if args.days <= 0:
        sys.exit("--days must be > 0")

    rpc = get_local_rpc_url()
    fee_collector_addr = module_address("mirage", "fee_collector")
    core_addr = module_address("mirage", "core")

    log({
        "time": iso_now(),
        "rpc": rpc,
        "days": args.days,
        "fee_collector": fee_collector_addr,
        "core": core_addr,
    })

    earliest, latest = get_height_range(rpc)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=args.days)
    
    # Check if requested range exceeds available blocks
    earliest_time = get_block_time(rpc, earliest)
    if cutoff < earliest_time:
        # Requested time is before earliest available block - clamp to earliest
        actual_days = (datetime.datetime.now(datetime.timezone.utc) - earliest_time).days
        log({
            "warning": "requested_range_exceeds_available_blocks",
            "requested_days": args.days,
            "available_days": actual_days,
            "earliest_block_time": earliest_time.isoformat(),
        })
        start = earliest
    else:
        start = find_start_height(rpc, cutoff, earliest, latest)
    
    # Safety clamp - never go below earliest available block
    start = max(start, earliest)

    log({
        "earliest_height": earliest,
        "latest_height": latest,
        "start_height": start,
        "cutoff": cutoff.isoformat(),
    })

    heights = list(range(start, latest + 1))
    total_blocks = len(heights)
    log({"total_blocks_to_scan": total_blocks})

    # Stats by category
    stats = {
        "fee_collector_burn": 0,
        "subscriber_relay_burn": 0,
        "subscription_fee_burn": 0,
        "leftover_reserve_burn": 0,
    }
    tx_count = 0

    # Block time cache
    block_times = {}

    def scan_block(h):
        nonlocal tx_count
        results = []
        try:
            br = rpc_block_results(rpc, h)
            res = br.get("result") or {}

            # Get block time
            if h not in block_times:
                blk = rpc_block(rpc, h)
                t = blk["result"]["block"]["header"]["time"]
                block_times[h] = parse_rfc3339(t).isoformat()
            ts = block_times[h]

            # Process txs
            txs_results = res.get("txs_results") or []
            for idx, tx_res in enumerate(txs_results):
                tx_count += 1
                tx_info = extract_tx_events(tx_res, fee_collector_addr, core_addr)
                txhash = f"block_{h}_tx_{idx}"
                
                for burn in tx_info["burns"]:
                    if burn["amount_umirage"] > 0:
                        results.append({
                            "source": "tx",
                            "category": burn["category"],
                            "reason": burn["reason"],
                            "time": ts,
                            "height": h,
                            "txhash": txhash,
                            "amount_umirage": burn["amount_umirage"],
                            "actions": tx_info["actions"],
                        })

            # Process begin/end block events
            block_events = res.get("begin_block_events") or []
            block_events += res.get("end_block_events") or res.get("finalize_block_events") or []
            
            if block_events:
                burns = analyze_block_events(block_events, fee_collector_addr, core_addr)
                for burn in burns:
                    if burn.get("amount_umirage", 0) > 0:
                        results.append({
                            "source": "block",
                            "category": burn["category"],
                            "reason": burn["reason"],
                            "time": ts,
                            "height": h,
                            "amount_umirage": burn["amount_umirage"],
                            "subscription_events": burn.get("subscription_events"),
                        })

            return results
        except Exception as e:
            return [{"error": str(e), "height": h}]

    workers = 8  # Parallel workers for burn scanning

    scanned = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_block, h): h for h in heights}
        for fut in as_completed(futs):
            scanned += 1
            for r in fut.result():
                if "error" in r:
                    continue
                cat = r.get("category", "")
                amt = r.get("amount_umirage", 0)
                if cat in stats:
                    stats[cat] += amt
                emit(r)
            if scanned % 2000 == 0:
                log({"progress": f"{scanned}/{total_blocks}"})

    total = sum(stats.values())
    log({
        "done": True,
        "tx_count": tx_count,
        "burns_by_category": stats,
        "grand_total_umirage": total,
        "grand_total_mirage": total / 1_000_000,
    })

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
