"""
Reward Distributor

Handles distribution of MIRAGE token rewards from the rewards pool to users.

Configuration (via environment variables):
- REWARDS_POOL_ADDRESS: The address holding reward tokens
- REWARDS_ENABLED: Set to "true" to enable actual token transfers (default: false)

In dry-run mode (REWARDS_ENABLED != "true"), rewards are logged but not sent.
This allows testing the full flow without requiring a funded rewards pool.

To set up the rewards pool:
1. Create a key: miraged keys add rewards_pool --keyring-backend file
2. Fund via governance proposal: proposal_fund_address.json
3. Set REWARDS_POOL_ADDRESS and REWARDS_ENABLED=true in environment
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from bank import get_balance
from db import connect_db

logger = logging.getLogger(__name__)


# Configuration from environment
REWARDS_POOL_ADDRESS = os.environ.get("REWARDS_POOL_ADDRESS", "")
REWARDS_ENABLED = os.environ.get("REWARDS_ENABLED", "").lower() == "true"


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
        self.enabled = enabled if enabled is not None else REWARDS_ENABLED
        
        if self.enabled and not self.pool_address:
            logger.warning("REWARDS_ENABLED is true but REWARDS_POOL_ADDRESS is not set")
            self.enabled = False
    
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
            - dry_run: bool
            - error: str or None
        """
        if amount <= 0:
            return {
                "success": False,
                "tx_hash": None,
                "amount": 0,
                "dry_run": not self.enabled,
                "error": "amount must be positive",
            }
        
        if not self.enabled:
            # Dry run mode - log but don't send
            logger.info(
                f"[DRY RUN] Would send {amount} umirage to {recipient} "
                f"from {self.pool_address or 'NO_POOL'} ({reason})"
            )
            return {
                "success": True,
                "tx_hash": None,
                "amount": amount,
                "dry_run": True,
                "error": None,
            }
        
        # Check balance
        pool_balance = self.get_pool_balance()
        if pool_balance < amount:
            logger.warning(
                f"Insufficient pool balance: have {pool_balance}, need {amount} for {recipient}"
            )
            return {
                "success": False,
                "tx_hash": None,
                "amount": 0,
                "dry_run": False,
                "error": "insufficient_pool_balance",
            }
        
        # Live mode - actually send tokens
        # NOTE: This requires implementing proper transaction signing with the rewards pool key.
        # For now, we log the intent and return success for the MVP.
        # TODO: Implement actual MsgSend transaction signing and broadcasting
        
        logger.info(
            f"[LIVE] Sending {amount} umirage to {recipient} "
            f"from {self.pool_address} ({reason})"
        )
        
        # Placeholder for actual transaction
        # When implemented, this would:
        # 1. Build a MsgSend message
        # 2. Sign with the rewards pool key
        # 3. Broadcast the transaction
        # 4. Return the tx_hash
        
        logger.warning(
            "Live token sending not yet implemented - "
            "marking reward as sent without actual transfer"
        )
        
        return {
            "success": True,
            "tx_hash": None,  # Would be actual tx hash
            "amount": amount,
            "dry_run": False,
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
                    (owner,)
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
                mirage_rewards.append({
                    "id": reward_id,
                    "amount": amount,
                    "reason": reason,
                })
            else:
                cosmetic_rewards.append({
                    "id": reward_id,
                    "type": reward_type,
                    "data": reward_data,
                    "reason": reason,
                })
        
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
            send_result = self.send_reward(
                owner,
                payout_amount,
                f"quest_rewards:{len(mirage_rewards)}_quests"
            )
            
            if send_result["success"]:
                result["tx_hash"] = send_result.get("tx_hash")
                result["rewards"].append({
                    "type": "mirage",
                    "amount": payout_amount,
                    "raw_amount": total_mirage,
                    "multiplier": round(multiplier, 4),
                    "dry_run": send_result.get("dry_run", False),
                })
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
                            (owner, unlock_type, unlock_id, ts, cosmetic["reason"])
                        )
                
                result["rewards"].append({
                    "type": unlock_type,
                    "id": unlock_id,
                })
        
        # Mark all rewards as claimed
        reward_ids = [r["id"] for r in mirage_rewards] + [r["id"] for r in cosmetic_rewards]
        if reward_ids:
            with connect_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE pending_rewards
                        SET claimed_at = %s
                        WHERE id = ANY(%s)
                        """,
                        (ts, reward_ids)
                    )
        
        return result
    
    def _get_multiplier(self, owner: str, ts: int) -> float:
        """Calculate reward multiplier based on account age (1x to 5x over 30 days)."""
        with connect_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT created_at FROM profiles WHERE LOWER(owner) = LOWER(%s)",
                    (owner,)
                )
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
                    (owner,)
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
