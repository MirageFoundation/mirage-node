#!/usr/bin/env python3
"""Check MIRAGE token balance on Osmosis for given addresses."""

import json
import sys
from typing import Optional

import requests


OSMOSIS_LCD = "https://lcd.osmosis.zone"
IBC_DENOM = "ibc/FD0C5BF3009F3300961E52E4E0160D6901B1B3E7D0475766C5D960A9D3999B32"


def query_balance(address: str, denom: str) -> Optional[int]:
    """Query balance for a specific denom on Osmosis."""
    url = f"{OSMOSIS_LCD}/cosmos/bank/v1beta1/balances/{address}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        balances = data.get("balances", [])
        for bal in balances:
            if bal.get("denom") == denom:
                return int(bal.get("amount", 0))
        return 0
    except Exception as e:
        print(f"Error querying balance for {address}: {e}", file=sys.stderr)
        return None


def get_all_balances(address: str) -> dict:
    """Get all balances for an address."""
    url = f"{OSMOSIS_LCD}/cosmos/bank/v1beta1/balances/{address}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return {bal.get("denom"): int(bal.get("amount", 0)) for bal in data.get("balances", [])}
    except Exception as e:
        print(f"Error querying balances for {address}: {e}", file=sys.stderr)
        return {}


def main():
    tx_receiver = "osmo1ug4fu9mc3xthgc9q24uzef3xwecl7939e4uesg"
    user_address = "osmo1f9w0htdgcl9t7672vv9x9sgkluv486vdjmzmyr"
    
    print("=" * 60)
    print("Checking MIRAGE token balances on Osmosis")
    print("=" * 60)
    print()
    
    print(f"Transaction receiver address: {tx_receiver}")
    print(f"Your address: {user_address}")
    print()
    
    # Check balance at transaction receiver address
    print(f"Checking balance at transaction receiver ({tx_receiver})...")
    balance_tx = query_balance(tx_receiver, IBC_DENOM)
    if balance_tx is not None:
        print(f"  MIRAGE balance: {balance_tx:,} umirage ({balance_tx / 1_000_000:.6f} MIRAGE)")
    else:
        print("  Error querying balance")
    
    all_balances_tx = get_all_balances(tx_receiver)
    if all_balances_tx:
        print(f"  Total denoms: {len(all_balances_tx)}")
        print(f"  Other balances: {', '.join([f'{amt:,} {denom[:20]}...' for denom, amt in list(all_balances_tx.items())[:5]])}")
    print()
    
    # Check balance at user address
    print(f"Checking balance at your address ({user_address})...")
    balance_user = query_balance(user_address, IBC_DENOM)
    if balance_user is not None:
        print(f"  MIRAGE balance: {balance_user:,} umirage ({balance_user / 1_000_000:.6f} MIRAGE)")
    else:
        print("  Error querying balance")
    
    all_balances_user = get_all_balances(user_address)
    if all_balances_user:
        print(f"  Total denoms: {len(all_balances_user)}")
        print(f"  Other balances: {', '.join([f'{amt:,} {denom[:20]}...' for denom, amt in list(all_balances_user.items())[:5]])}")
    print()
    
    # Summary
    print("=" * 60)
    print("Summary:")
    print("=" * 60)
    if balance_tx and balance_tx > 0:
        print(f"✓ MIRAGE tokens found at transaction receiver: {balance_tx:,} umirage")
        if balance_user == 0:
            print("✗ No MIRAGE tokens found at your address")
            print()
            print("ACTION REQUIRED: The tokens are at a different address.")
            print("You may need to transfer them from the transaction receiver")
            print("address to your address, or verify that address is yours.")
        else:
            print(f"✓ MIRAGE tokens also found at your address: {balance_user:,} umirage")
    elif balance_user and balance_user > 0:
        print(f"✓ MIRAGE tokens found at your address: {balance_user:,} umirage")
        print("  (Tokens are at the correct address)")
    else:
        print("✗ No MIRAGE tokens found at either address")
        print("  The tokens may have been transferred elsewhere or spent.")


if __name__ == "__main__":
    main()
