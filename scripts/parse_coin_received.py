#!/usr/bin/env python3
import sys
import json

TARGET = "mirage1jumurrqh20evy4zu027jrg363a4rtm6qw2kqs8"

d = json.load(sys.stdin)
total = d.get("total_count", 0)
print(f"Total transactions with coins received: {total}")
print()

for tx in d.get("txs", []):
    height = tx.get("height")
    timestamp = tx.get("timestamp")
    txhash = tx.get("txhash", "")[:40]

    # Find amounts in events
    for ev in tx.get("events", []):
        if ev.get("type") == "coin_received":
            attrs = {a["key"]: a["value"] for a in ev.get("attributes", [])}
            if attrs.get("receiver") == TARGET:
                amount = attrs.get("amount", "0")
                # Parse amount
                if "umirage" in amount:
                    umirage = int(amount.replace("umirage", ""))
                    mirage = umirage / 1_000_000
                    print(f"Height {height} | {timestamp}")
                    print(f"  Received: {amount} ({mirage:.2f} MIRAGE)")
                    print(f"  TX: {txhash}...")
                    print()
