#!/usr/bin/env bash
set -euo pipefail

# Orchestrator setup - imports Solana wallet from mnemonic
# Usage: ./setup_orchestrator.sh

ORCHESTRATOR_HOME="${HOME}/.mirage/orchestrator"
KEYPAIR_PATH="${ORCHESTRATOR_HOME}/solana-keypair.json"

echo "==> Orchestrator Solana Wallet Setup"
mkdir -p "$ORCHESTRATOR_HOME"

if [ -f "$KEYPAIR_PATH" ]; then
    echo "    Keypair already exists: $KEYPAIR_PATH"
    echo -n "    Overwrite? [y/N]: "
    read -r CONFIRM
    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        echo "    Aborted."
        exit 0
    fi
fi

echo ""
echo "Enter your 12-word Solana seed phrase."
echo "(Create one at https://solflare.com or any Solana wallet)"
echo ""
echo -n "Enter 12-word mnemonic: "
read -rs MNEMONIC
echo ""

WORD_COUNT=$(echo "$MNEMONIC" | wc -w)
if [ "$WORD_COUNT" -ne 12 ]; then
    echo "ERROR: Expected 12 words, got $WORD_COUNT" >&2
    exit 1
fi

# Use Python to derive keypair from mnemonic
ADDR=$(python3 -c "
import sys
import json
import hashlib
import hmac

mnemonic = '''$MNEMONIC'''

# BIP39 seed derivation (PBKDF2)
password = mnemonic.encode('utf-8')
salt = b'mnemonic'
seed = hashlib.pbkdf2_hmac('sha512', password, salt, 2048, 64)

# Use first 32 bytes as ed25519 seed
from nacl.signing import SigningKey
signing_key = SigningKey(seed[:32])
verify_key = signing_key.verify_key

# Solana keypair format: [32-byte seed, 32-byte pubkey]
keypair = list(seed[:32]) + list(bytes(verify_key))

# Save keypair
with open('$KEYPAIR_PATH', 'w') as f:
    json.dump(keypair, f)

# Output base58 address
import base58
print(base58.b58encode(bytes(verify_key)).decode())
")

echo ""
echo "==========================================="
echo "SOLANA WALLET IMPORTED"
echo "==========================================="
echo ""
echo "  Address: $ADDR"
echo "  Keypair: $KEYPAIR_PATH"
echo ""
echo "  Fund this address with ~0.1 SOL for transaction fees."
echo ""
echo "==========================================="
