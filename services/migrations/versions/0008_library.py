"""School resource publication and independent copy provenance."""
from alembic import op

revision = "0008_library"
down_revision = "0007_authoring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE library_resources (
          workspace_id uuid NOT NULL, id uuid NOT NULL, publisher_id uuid NOT NULL,
          active boolean NOT NULL DEFAULT true, revision bigint NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id),
          FOREIGN KEY(workspace_id,id) REFERENCES activities(workspace_id,id),
          FOREIGN KEY(workspace_id,publisher_id) REFERENCES memberships(workspace_id,account_id)
        );
        CREATE TABLE library_versions (
          workspace_id uuid NOT NULL, resource_id uuid NOT NULL, number bigint NOT NULL,
          source_version_id uuid NOT NULL, publisher_id uuid NOT NULL REFERENCES accounts(id), subject text NOT NULL, grade text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,resource_id,number),
          UNIQUE(workspace_id,source_version_id),
          FOREIGN KEY(workspace_id,resource_id) REFERENCES library_resources(workspace_id,id),
          FOREIGN KEY(workspace_id,source_version_id) REFERENCES activity_versions(workspace_id,id)
        );
        CREATE TABLE resource_copies (
          workspace_id uuid NOT NULL, activity_id uuid NOT NULL, requester_id uuid NOT NULL, request_key uuid NOT NULL,
          resource_id uuid NOT NULL, number bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(workspace_id,activity_id), UNIQUE(workspace_id,requester_id,request_key),
          FOREIGN KEY(workspace_id,activity_id) REFERENCES activities(workspace_id,id),
          FOREIGN KEY(workspace_id,resource_id,number) REFERENCES library_versions(workspace_id,resource_id,number)
        );
    """)
    for table in ("library_resources", "library_versions", "resource_copies"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING(workspace_id::text=current_setting('openform.workspace_id',true)) "
                   "WITH CHECK(workspace_id::text=current_setting('openform.workspace_id',true))")
    op.execute("REVOKE UPDATE, DELETE ON library_versions FROM openform_app")


def downgrade() -> None:
    op.execute("DROP TABLE resource_copies, library_versions, library_resources")
