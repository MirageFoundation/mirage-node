"""
Add lowercase owner constraints to push tables.
"""

MIGRATION_KEY = "v1.21.1_push_owner_constraints"


def run(db, chain, logger):
    with db._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'push_budget_owner_lower'
                    ) THEN
                        ALTER TABLE push_budget
                        ADD CONSTRAINT push_budget_owner_lower CHECK (owner = LOWER(owner));
                    END IF;
                END $$;
                """
            )
            cur.execute(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'push_nonces_owner_lower'
                    ) THEN
                        ALTER TABLE push_nonces
                        ADD CONSTRAINT push_nonces_owner_lower CHECK (owner = LOWER(owner));
                    END IF;
                END $$;
                """
            )
    return "added lowercase owner constraints to push_budget and push_nonces"
