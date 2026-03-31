from __future__ import annotations

from db import connect_backend_db


def get_reward_multiplier(owner: str) -> float:
    """Calculate reward multiplier based on completed quest count (1x at 0, 5x at 50)."""
    with connect_backend_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM user_daily_quests WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL)
                  + (SELECT COUNT(*) FROM user_flash_quests WHERE LOWER(owner) = LOWER(%s) AND completed_at IS NOT NULL)
                  + (SELECT COUNT(*) FROM user_achievements WHERE LOWER(owner) = LOWER(%s) AND unlocked_at IS NOT NULL)
                """,
                (owner, owner, owner),
            )
            completed = (cur.fetchone() or [0])[0]
            return 1.0 + min(4.0, completed * 4.0 / 50.0)
