#!/usr/bin/env python3
"""
Generate mint proposal for Economics v2.0 Phase 1.

Queries current validators and generates a governance proposal to mint
tokens to each validator's account address.

Usage:
    python3 scripts/generate_mint_proposal.py
    python3 scripts/generate_mint_proposal.py --rpc http://mirage.talk:26657
    python3 scripts/generate_mint_proposal.py --output /tmp/mint_proposal.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Constants
DEFAULT_RPC = "http://mirage.talk:26657"
GOV_MODULE_ADDRESS = "mirage10d07y265gmmuvt4z0w9aw880jnsr700jvealeg"

# Target: 5,000,000,000 MIRAGE per validator (flat 5B)
# In umirage: 5,000,000,000 * 1,000,000 = 5,000,000,000,000,000
MINT_AMOUNT_UMIRAGE = 5_000_000_000_000_000
MINT_AMOUNT_MIRAGE = MINT_AMOUNT_UMIRAGE // 1_000_000

# Paths
ROOT = Path(__file__).resolve().parents[1]
BLOCKCHAIN_DIR = ROOT / "blockchain"
MIRAGED = BLOCKCHAIN_DIR / "miraged"


def get_miraged_bin() -> str:
    """Get path to miraged binary."""
    if MIRAGED.exists():
        return str(MIRAGED)
    return "miraged"


def query_validators(rpc: str) -> list[dict]:
    """Query all bonded validators from the chain."""
    bin_path = get_miraged_bin()
    cmd = [
        bin_path, "q", "staking", "validators",
        "--node", rpc,
        "-o", "json"
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error querying validators: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    
    data = json.loads(result.stdout)
    validators = data.get("validators", [])
    
    # Filter to only bonded validators
    bonded = [v for v in validators if v.get("status") == "BOND_STATUS_BONDED"]
    return bonded


def valoper_to_account(valoper: str) -> str:
    """Convert validator operator address to account address.
    
    miragevaloper1... -> mirage1...
    
    The account address is derived from the same pubkey as the valoper address.
    """
    # The valoper and account addresses share the same underlying bytes,
    # just with different prefixes. We can use miraged to convert.
    bin_path = get_miraged_bin()
    
    # miraged debug addr <address> shows the hex bytes
    # Then we can convert back with the account prefix
    # 
    # Simpler approach: query the validator's self-delegation to get the delegator address
    # which is the account address
    #
    # Actually, the easiest way is to note that:
    # miragevaloper1<rest> has the same bech32 data as mirage1<rest>
    # So we just need to change the prefix
    
    if not valoper.startswith("miragevaloper1"):
        print(f"Warning: unexpected valoper format: {valoper}", file=sys.stderr)
        return valoper
    
    # Extract the bech32 data part (everything after the prefix)
    # and reconstruct with mirage1 prefix
    #
    # Note: This is a simplification. In reality, bech32 encoding means
    # the same data bytes will produce different character sequences
    # with different prefixes. We need to properly decode/re-encode.
    #
    # Let's use a subprocess to convert properly
    
    try:
        # Use miraged debug addr to get the hex, then convert back
        # Or better: query delegations to this validator and find self-delegation
        pass
    except Exception:
        pass
    
    # Fallback: use the bech32 library directly
    try:
        import bech32
        hrp, data = bech32.bech32_decode(valoper)
        if data is None:
            raise ValueError(f"Failed to decode {valoper}")
        account = bech32.bech32_encode("mirage", data)
        return account
    except ImportError:
        # If bech32 not available, try a different approach
        pass
    
    # Manual bech32 conversion (simplified, may not work for all cases)
    # The valoper address is: miragevaloper1 + <bech32_data>
    # The account address is: mirage1 + <same_bech32_data>
    # 
    # This won't work directly because bech32 checksum includes the prefix.
    # We need to re-encode.
    
    print(f"Warning: Cannot convert valoper to account without bech32 library.", file=sys.stderr)
    print(f"Install with: pip install bech32", file=sys.stderr)
    print(f"Or manually provide account addresses.", file=sys.stderr)
    return valoper


def generate_proposal(validators: list[dict], output_path: Path | None = None) -> dict:
    """Generate the mint proposal JSON."""
    
    messages = []
    
    for v in validators:
        valoper = v.get("operator_address", "")
        moniker = v.get("description", {}).get("moniker", "unknown")
        tokens = int(v.get("tokens", "0"))
        tokens_mirage = tokens // 1_000_000
        
        # Convert valoper to account address
        account = valoper_to_account(valoper)
        
        print(f"Validator: {moniker}")
        print(f"  Operator: {valoper}")
        print(f"  Account:  {account}")
        print(f"  Current stake: {tokens_mirage:,} MIRAGE")
        print(f"  Will mint: {MINT_AMOUNT_MIRAGE:,} MIRAGE")
        print()
        
        messages.append({
            "@type": "/mirage.core.v1.MsgMintTokens",
            "authority": GOV_MODULE_ADDRESS,
            "target": account,
            "amount": str(MINT_AMOUNT_UMIRAGE),
            "reason": f"Economics v2.0: Mint to {moniker} - increase stake to 5B MIRAGE ($50,000 at $0.00001/MIRAGE)"
        })
    
    proposal = {
        "messages": messages,
        "metadata": "ipfs://economics-v2-phase1-mint",
        "deposit": "10000000umirage",
        "title": "Economics v2.0 Phase 1: Mint tokens to validators",
        "summary": (
            f"Mint {MINT_AMOUNT_MIRAGE:,} MIRAGE (~5B) to each of the {len(validators)} validators "
            "to establish proper stake levels for the new tokenomics. "
            "This increases each validator's holdings to $50,000 equivalent at the target price of $0.00001/MIRAGE. "
            "See docs/economics_v2_upgrade.md for the full upgrade plan."
        ),
        "expedited": True
    }
    
    if output_path:
        with open(output_path, "w") as f:
            json.dump(proposal, f, indent=2)
        print(f"Proposal written to: {output_path}")
    
    return proposal


def main():
    parser = argparse.ArgumentParser(
        description="Generate mint proposal for Economics v2.0 Phase 1"
    )
    parser.add_argument(
        "--rpc", 
        default=DEFAULT_RPC,
        help=f"RPC endpoint (default: {DEFAULT_RPC})"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output file path (default: print to stdout)"
    )
    args = parser.parse_args()
    
    print(f"Querying validators from {args.rpc}...")
    print()
    
    validators = query_validators(args.rpc)
    
    if not validators:
        print("No bonded validators found!", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found {len(validators)} bonded validator(s)")
    print("=" * 60)
    print()
    
    # Calculate totals
    total_mint = MINT_AMOUNT_MIRAGE * len(validators)
    total_mint_usd = total_mint * 0.00001
    
    print(f"Mint per validator: {MINT_AMOUNT_MIRAGE:,} MIRAGE")
    print(f"Total to mint:      {total_mint:,} MIRAGE")
    print(f"USD value (@ $0.00001): ${total_mint_usd:,.2f}")
    print()
    print("=" * 60)
    print()
    
    proposal = generate_proposal(validators, args.output)
    
    if not args.output:
        print("=" * 60)
        print("PROPOSAL JSON:")
        print("=" * 60)
        print(json.dumps(proposal, indent=2))
    
    print()
    print("=" * 60)
    print("NEXT STEPS:")
    print("=" * 60)
    print("1. Review the proposal above")
    print("2. Save to file if needed: --output scripts/proposals/economics_v2_mint_final.json")
    print("3. Submit with: python3 scripts/submit_proposal.py remote <proposal_file>")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
