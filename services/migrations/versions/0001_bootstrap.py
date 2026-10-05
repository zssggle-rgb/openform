"""Create the singleton instance readiness state, writable only by migrations/ops."""
from alembic import op

revision = "0001_bootstrap"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE instance_state (
            id boolean PRIMARY KEY DEFAULT true CHECK (id),
            maintenance boolean NOT NULL DEFAULT false,
            restored_locked boolean NOT NULL DEFAULT false,
            generation bigint NOT NULL DEFAULT 1 CHECK (generation > 0)
        );
        INSERT INTO instance_state (id) VALUES (true);
        REVOKE INSERT, UPDATE, DELETE ON instance_state FROM openform_app;
        GRANT SELECT ON instance_state TO openform_app;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE instance_state")
