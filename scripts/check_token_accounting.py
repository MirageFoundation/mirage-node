#!/usr/bin/env python3
"""Check token accounting for a user."""
import subprocess
import json
import sys

TARGET = "mirage1jumurrqh20evy4zu027jrg363a4rtm6qw2kqs8"

# Get all transfer.recipient txs
result = subprocess.run(
    ["miraged", "q", "txs", "--query", f"transfer.recipient='{TARGET}'", "--limit", "100", "--output", "json"],
    capture_output=True,
    text=True,
)

print("=== Token Accounting ===\n")

if result.returncode != 0:
    print(f"Query failed: {result.stderr}")
    sys.exit(1)

try:
    data = json.loads(result.stdout)
except:
    print(f"JSON parse failed. Raw output:\n{result.stdout[:1000]}")
    sys.exit(1)

total = data.get("total_count", "0")
print(f"Total transfer transactions to user: {total}\n")

total_received = 0
for tx in data.get("txs", []):
    height = tx.get("height")
    timestamp = tx.get("timestamp")
    txhash = tx.get("txhash", "")[:32]

    # Find transfer amount from this user
    for ev in tx.get("events", []):
        if ev.get("type") == "transfer":
            attrs = {a["key"]: a["value"] for a in ev.get("attributes", [])}
            if attrs.get("recipient") == TARGET:
                amount_str = attrs.get("amount", "0")
                sender = attrs.get("sender", "unknown")
                print(f"Height {height} | {timestamp}")
                print(f"  From: {sender}")
                print(f"  Amount: {amount_str}")
                if "umirage" in amount_str:
                    amt = int(amount_str.replace("umirage", ""))
                    total_received += amt
                    print(f"  = {amt/1_000_000:.2f} MIRAGE")
                print()

print(f"Total received from visible transfers: {total_received} umirage ({total_received/1_000_000:.2f} MIRAGE)\n")

# Current balance
result2 = subprocess.run(
    ["miraged", "q", "bank", "balance", TARGET, "umirage", "--output", "json"], capture_output=True, text=True
)
if result2.returncode == 0:
    bal_data = json.loads(result2.stdout)
    current = int(bal_data.get("balance", {}).get("amount", "0"))
    print(f"Current balance: {current} umirage ({current/1_000_000:.2f} MIRAGE)")
    diff = current - total_received
    print(f"Unaccounted balance: {diff} umirage ({diff/1_000_000:.2f} MIRAGE)")
    if diff > 0:
        print(f"\nThe {diff/1_000_000:.2f} MIRAGE likely came from transactions that have been pruned from the node.")
