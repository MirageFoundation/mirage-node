#!/usr/bin/env python3
import sys
import json

d = json.load(sys.stdin)
txs = d.get("txs", [])
print(f"Found {len(txs)} transactions")

for tx in txs:
    txhash = tx.get("txhash", "?")[:40]
    height = tx.get("height", "?")
    print(f"\nTX: {txhash}...")
    print(f"  Height: {height}")

    # Look for events in logs
    for log in tx.get("logs", []):
        for ev in log.get("events", []):
            if ev.get("type") == "transfer":
                attrs = {a["key"]: a["value"] for a in ev.get("attributes", [])}
                sender = attrs.get("sender", "?")
                recipient = attrs.get("recipient", "?")
                amount = attrs.get("amount", "?")
                print(f"  Transfer: {sender[:20]}... -> {recipient[:20]}... : {amount}")
            elif ev.get("type") == "coin_spent":
                attrs = {a["key"]: a["value"] for a in ev.get("attributes", [])}
                spender = attrs.get("spender", "?")
                amount = attrs.get("amount", "?")
                print(f"  Coin spent: {spender[:20]}... : {amount}")
            elif ev.get("type") == "coin_received":
                attrs = {a["key"]: a["value"] for a in ev.get("attributes", [])}
                receiver = attrs.get("receiver", "?")
                amount = attrs.get("amount", "?")
                print(f"  Coin received: {receiver[:20]}... : {amount}")
