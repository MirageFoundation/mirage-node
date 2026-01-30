"""
Reward Distributor

Handles distribution of MIRAGE token rewards from the rewards pool to users.

Configuration (via environment variables):
- REWARDS_POOL_ADDRESS: The address holding reward tokens
- PAYOUTS_ENABLED: Set to "true" to enable actual token transfers (default: false)

When PAYOUTS_ENABLED != "true", rewards are logged but not sent.
This allows testing the full flow without requiring a funded rewards pool.

To set up the rewards pool:
1. Add key from seed phrase:
   miraged keys add rewards_pool --recover --keyring-backend test
2. Get the address:
   miraged keys show rewards_pool --keyring-backend test -a
3. Fund the address (governance proposal or direct transfer)
4. Set REWARDS_POOL_ADDRESS and PAYOUTS_ENABLED=true in environment
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Optional, Tuple

from bank import get_balance
from db import connect_db
from node import min_gas_price_umirage

logger = logging.getLogger(__name__)


# Configuration from environment
REWARDS_POOL_ADDRESS = os.environ.get("REWARDS_POOL_ADDRESS", "")
PAYOUTS_ENABLED = os.environ.get("PAYOUTS_ENABLED", "").lower() == "true"

# Node configuration
NODE_HOME = os.environ.get("NODE_HOME", os.path.expanduser("~/.mirage/node"))
KEYRING_BACKEND = "test"
REWARDS_POOL_KEY_NAME = "rewards_pool"


def _get_miraged_path() -> str:
    """Get the path to the miraged binary."""
    # Check if it's in PATH first
    try:
        result = subprocess.run(["which", "miraged"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # Fallback to expected location
    return "/opt/mirage/blockchain/bin/miraged"




def _send_tokens_via_cli(
    from_key: str,
    to_address: str,
    amount: int,
    node_home: str,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Send tokens using miraged CLI.
    
    Returns:
        (success, tx_hash, error_message)
    """
    miraged = _get_miraged_path()
    amount_str = f"{amount}umirage"
    
    # Get the actual minimum gas price from the node config
    try:
        gas_price = int(min_gas_price_umirage())
    except Exception:
        gas_price = 5000  # Fallback to reasonable default
    
    cmd = [
        miraged,
        "tx", "bank", "send",
        from_key,
        to_address,
        amount_str,
        "--home", node_home,
        "--keyring-backend", KEYRING_BACKEND,
        "--chain-id", "mirage-1",
        "--gas", "auto",
        "--gas-adjustment", "1.5",
        "--gas-prices", f"{gas_price}umirage",
        "--yes",  # Skip confirmation
        "--output", "json",
    ]
    
    logger.info(f"Executing: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        
        logger.info(f"miraged exit code: {result.returncode}")
        logger.info(f"miraged stdout: {result.stdout[:500] if result.stdout else 'empty'}")
        if result.stderr:
            logger.warning(f"miraged stderr: {result.stderr[:500]}")
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            return False, None, error_msg
        
        # Parse the JSON output to get tx_hash
        try:
            output = json.loads(result.stdout)
            tx_hash = output.get("txhash")
            code = output.get("code", 0)
            
            if code != 0:
                raw_log = output.get("raw_log", "Transaction failed")
                return False, tx_hash, raw_log
            
            return True, tx_hash, None
        except json.JSONDecodeError:
            # If not JSON, try to extract tx hash from output
            if "txhash" in result.stdout.lower():
                # Try to find tx hash in output
                for line in result.stdout.split("\n"):
                    if "txhash" in line.lower():
                        parts = line.split(":")
                        if len(parts) >= 2:
                            return True, parts[1].strip(), None
            return True, None, None  # Assume success if no error code
            
    except subprocess.TimeoutExpired:
        return False, None, "Transaction timed out"
    except Exception as e:
        return False, None, str(e)


class RewardDistributor:
    """
    Distributes MIRAGE token rewards to users.

    Operates in two modes:
    - Dry run (default): Logs would-be transfers, marks rewards as claimed
    - Live mode: Actually sends tokens from the rewards pool
    """

    def __init__(self, pool_address: Optional[str] = None, enabled: Optional[bool] = None):
        """
        Initialize the reward distributor.

        Args:
            pool_address: Override rewards pool address (uses env var if not provided)
            enabled: Override enabled flag (uses env var if not provided)
        """
        self.pool_address = pool_address or REWARDS_POOL_ADDRESS
        self.enabled = enabled if enabled is not None else PAYOUTS_ENABLED

        if self.enabled and not self.pool_address:
            logger.warning("PAYOUTS_ENABLED is true but REWARDS_POOL_ADDRESS is not set")
            self.enabled = False

    def is_configured(self) -> bool:
        """Check if the distributor is properly configured to send rewards."""
        return self.enabled and bool(self.pool_address)

    def get_pool_balance(self) -> int:
        """Get the current balance of the rewards pool."""
        if not self.pool_address:
            return 0
        return get_balance(self.pool_address)

    def can_send(self, amount: int) -> bool:
        """Check if the pool has sufficient balance to send the amount."""
        if not self.enabled:
            return True  # Dry run always succeeds
        return self.get_pool_balance() >= amount

    def send_reward(self, recipient: str, amount: int, reason: str) -> dict:
        """
        Send tokens from the rewards pool to a recipient.

        Args:
            recipient: Recipient address
            amount: Amount in umirage
            reason: Human-readable reason (for logging)

        Returns:
            dict with:
            - success: bool
            - tx_hash: str or None
            - amount: int (actual amount sent)
            - error: str or None
        """
        if amount <= 0:
            return {
                "success": False,
                "tx_hash": None,
                "amount": 0,
                "error": "amount must be positive",
            }

        if not self.enabled:
            # Payouts disabled - log but don't send
            logger.info(
                f"[PAYOUTS DISABLED] Would send {amount} umirage to {recipient} "
                f"from {self.pool_address or 'NO_POOL'} ({reason})"
            )
            return {
                "success": True,
                "tx_hash": None,
                "amount": amount,
                "error": None,
            }

        # Check balance
        pool_balance = self.get_pool_balance()
        if pool_balance < amount:
            logger.warning(f"Insufficient pool balance: have {pool_balance}, need {amount} for {recipient}")
            return {
                "success": False,
                "tx_hash": None,
                "amount": 0,
                "error": "insufficient_pool_balance",
            }

        # Live mode - actually send tokens via miraged CLI
        logger.info(f"[LIVE] Sending {amount} umirage to {recipient} from {self.pool_address} ({reason})")

        success, tx_hash, error = _send_tokens_via_cli(
            from_key=REWARDS_POOL_KEY_NAME,
            to_address=recipient,
            amount=amount,
            node_home=NODE_HOME,
        )

        if not success:
            logger.error(f"Failed to send tokens: {error}")
            return {
                "success": False,
                "tx_hash": tx_hash,
                "amount": 0,
                "error": error or "transaction_failed",
            }

        logger.info(f"[LIVE] Successfully sent {amount} umirage to {recipient}, tx_hash={tx_hash}")

        return {
            "success": True,
            "tx_hash": tx_hash,
            "amount": amount,
            "error": None,
        }

    def claim_rewards(self, owner: str, ts: int) -> dict:
        """
        Process a reward claim for a user.

        This is called from the /api/rewards/claim endpoint.

        Args:
            owner: User address
            ts: Current timestamp

        Returns:
            dict with:
            - success: bool
            - rewards: list of claimed rewards
            - tx_hash: str or None (for MIRAGE rewards)
            - error: str or None
        """
        # Get pending rewards
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, reward_type, reward_data, reason
                    FROM pending_rewards
                    WHERE LOWER(owner) = LOWER(%s) AND claimed_at IS NULL
                    """,
                    (owner,),
                )
                rows = cur.fetchall()

        if not rows:
            return {
                "success": False,
                "rewards": [],
                "tx_hash": None,
                "error": "no_rewards",
            }

        # Separate by type
        mirage_rewards = []
        cosmetic_rewards = []
        total_mirage = 0

        for row in rows:
            reward_id, reward_type, reward_data, reason = row
            reward_data = reward_data if isinstance(reward_data, dict) else {}

            if reward_type == "mirage":
                amount = reward_data.get("amount", 0)
                total_mirage += amount
                mirage_rewards.append(
                    {
                        "id": reward_id,
                        "amount": amount,
                        "reason": reason,
                    }
                )
            else:
                cosmetic_rewards.append(
                    {
                        "id": reward_id,
                        "type": reward_type,
                        "data": reward_data,
                        "reason": reason,
                    }
                )

        # Get reward multiplier
        multiplier = self._get_multiplier(owner, ts)
        payout_amount = int(total_mirage * multiplier)

        result = {
            "success": True,
            "rewards": [],
            "tx_hash": None,
            "error": None,
        }

        # Process MIRAGE rewards
        if mirage_rewards and payout_amount > 0:
            send_result = self.send_reward(owner, payout_amount, f"quest_rewards:{len(mirage_rewards)}_quests")

            if send_result["success"]:
                result["tx_hash"] = send_result.get("tx_hash")
                result["rewards"].append(
                    {
                        "type": "mirage",
                        "amount": payout_amount,
                        "raw_amount": total_mirage,
                        "multiplier": round(multiplier, 4),
                    }
                )
            else:
                # Failed to send - don't mark as claimed
                logger.error(f"Failed to send MIRAGE rewards to {owner}: {send_result.get('error')}")
                result["success"] = False
                result["error"] = send_result.get("error")
                return result

        # Process cosmetic rewards
        for cosmetic in cosmetic_rewards:
            unlock_type = cosmetic["type"]
            unlock_id = cosmetic["data"].get("id")

            if unlock_id:
                with connect_db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO user_unlocks (owner, unlock_type, unlock_id, unlocked_at, source)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (owner, unlock_type, unlock_id) DO NOTHING
                            """,
                            (owner, unlock_type, unlock_id, ts, cosmetic["reason"]),
                        )

                result["rewards"].append(
                    {
                        "type": unlock_type,
                        "id": unlock_id,
                    }
                )

        # Mark all rewards as claimed and store payout amounts
        mirage_ids = [r["id"] for r in mirage_rewards]
        cosmetic_ids = [r["id"] for r in cosmetic_rewards]

        with connect_db() as conn:
            with conn.cursor() as cur:
                # For MIRAGE rewards, calculate and store per-reward payout amounts
                if mirage_ids:
                    for reward in mirage_rewards:
                        # Each reward gets its share of the multiplier
                        reward_payout = int(reward["amount"] * multiplier)
                        cur.execute(
                            """
                            UPDATE pending_rewards
                            SET claimed_at = %s, payout_amount = %s
                            WHERE id = %s
                            """,
                            (ts, reward_payout, reward["id"]),
                        )

                # Cosmetic rewards don't have payout amounts
                if cosmetic_ids:
                    cur.execute(
                        """
                        UPDATE pending_rewards
                        SET claimed_at = %s
                        WHERE id = ANY(%s)
                        """,
                        (ts, cosmetic_ids),
                    )

        return result

    def _get_multiplier(self, owner: str, ts: int) -> float:
        """Calculate reward multiplier based on account age (1x to 5x over 30 days)."""
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT created_at FROM profiles WHERE LOWER(owner) = LOWER(%s)", (owner,))
                row = cur.fetchone()
                if not row or not row[0]:
                    return 1.0  # Default to 1x for unknown accounts

                created_at = row[0]
                age_days = (ts - created_at) / 86400

                # Linear ramp from 1x to 5x over 30 days
                progress = min(1.0, max(0.0, age_days / 30))
                return 1.0 + (progress * 4.0)  # 1x to 5x

    def void_pending_rewards(self, owner: str) -> int:
        """
        Void (delete) all pending rewards for a user.

        Used by admins when unsuspending with void_pending=true.

        Returns number of rewards voided.
        """
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM pending_rewards
                    WHERE LOWER(owner) = LOWER(%s) AND claimed_at IS NULL
                    RETURNING id
                    """,
                    (owner,),
                )
                return cur.rowcount


# Singleton instance
_distributor: Optional[RewardDistributor] = None


def get_distributor() -> RewardDistributor:
    """Get the singleton RewardDistributor instance."""
    global _distributor
    if _distributor is None:
        _distributor = RewardDistributor()
    return _distributor


__all__ = ["RewardDistributor", "get_distributor"]
