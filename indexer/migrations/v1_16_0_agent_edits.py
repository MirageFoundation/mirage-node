"""
Create agent_edits table for MsgAnnotate agent overlays.

Agent edits are stored separately from the canonical posts table.
Each agent gets one active edit per post (latest wins via upsert).
NULL = no change for that field; empty string = clear.
"""

MIGRATION_KEY = "v1.16.0_agent_edits"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_edits (
                    post_txhash TEXT NOT NULL,
                    agent_address TEXT NOT NULL,
                    edit_txhash TEXT NOT NULL,
                    topic TEXT,
                    title TEXT,
                    content TEXT,
                    tag TEXT,
                    media TEXT,
                    appendix TEXT,
                    edited_at BIGINT NOT NULL,
                    PRIMARY KEY (post_txhash, agent_address)
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_edits_post ON agent_edits(post_txhash)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_agent_edits_agent ON agent_edits(LOWER(agent_address))")
            cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_edits_txhash ON agent_edits(edit_txhash)")
    return "created agent_edits table"
