"""Immutable compiled packages and expiring document-only capabilities."""
from alembic import op

revision = "0004_runtime"
down_revision = "0003_roster"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE runtime_packages (
            workspace_id uuid NOT NULL REFERENCES workspaces(id), digest char(64) NOT NULL,
            manifest jsonb NOT NULL, document text NOT NULL, policy text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (workspace_id, digest),
            CHECK (digest ~ '^[a-f0-9]{64}$'),
            CHECK (octet_length(document) <= 12582912)
        );
        CREATE TABLE runtime_tickets (
            workspace_id uuid NOT NULL, token_digest char(64) NOT NULL UNIQUE,
            package_digest char(64) NOT NULL, expires_at timestamptz NOT NULL,
            revoked boolean NOT NULL DEFAULT false,
            PRIMARY KEY (workspace_id, token_digest),
            FOREIGN KEY (workspace_id, package_digest) REFERENCES runtime_packages(workspace_id, digest)
        );
    """)
    for table in ("runtime_packages", "runtime_tickets"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING (workspace_id::text=current_setting('openform.workspace_id', true)) "
                   "WITH CHECK (workspace_id::text=current_setting('openform.workspace_id', true))")
    op.execute("""
        REVOKE UPDATE ON runtime_packages FROM openform_app;
        CREATE FUNCTION locate_runtime_ticket(digest text) RETURNS TABLE(workspace_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog, public
          AS $$ SELECT t.workspace_id FROM public.runtime_tickets t
            JOIN public.workspaces w ON w.id=t.workspace_id
            WHERE t.token_digest=digest AND NOT t.revoked AND t.expires_at>now() AND w.active $$;
        REVOKE ALL ON FUNCTION locate_runtime_ticket(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION locate_runtime_ticket(text) TO openform_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION locate_runtime_ticket(text);
        DROP TABLE runtime_tickets, runtime_packages;
    """)
