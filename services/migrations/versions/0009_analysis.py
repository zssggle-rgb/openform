"""Fixed diagnostic snapshots, evidence-backed reports and teacher-approved sharing."""
from alembic import op

revision = "0009_analysis"
down_revision = "0008_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE classrooms ADD COLUMN data_epoch bigint NOT NULL DEFAULT 0;
        ALTER TABLE jobs ADD COLUMN kind text NOT NULL DEFAULT 'authoring' CHECK(kind IN ('authoring','analysis'));
        ALTER TABLE jobs ADD COLUMN classroom_id uuid;
        ALTER TABLE jobs ADD FOREIGN KEY(workspace_id,classroom_id) REFERENCES classrooms(workspace_id,id);
        ALTER TABLE jobs ADD CONSTRAINT jobs_kind_target CHECK((kind='authoring' AND classroom_id IS NULL) OR (kind='analysis' AND classroom_id IS NOT NULL AND activity_id IS NULL));
        CREATE TABLE analysis_snapshots (
          workspace_id uuid NOT NULL, id uuid NOT NULL, classroom_id uuid NOT NULL, version_id uuid NOT NULL,
          data_epoch bigint NOT NULL, captured_at timestamptz NOT NULL DEFAULT now(),
          payload jsonb NOT NULL, invalidated_at timestamptz,
          PRIMARY KEY(workspace_id,id), FOREIGN KEY(workspace_id,classroom_id) REFERENCES classrooms(workspace_id,id),
          FOREIGN KEY(workspace_id,version_id) REFERENCES activity_versions(workspace_id,id)
        );
        CREATE TABLE analysis_reports (
          workspace_id uuid NOT NULL, id uuid NOT NULL, snapshot_id uuid NOT NULL, job_id uuid NOT NULL,
          body jsonb NOT NULL, revision bigint NOT NULL DEFAULT 1,
          reviewed_by uuid REFERENCES accounts(id), reviewed_at timestamptz,
          shared_text text, shared_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,job_id),
          FOREIGN KEY(workspace_id,snapshot_id) REFERENCES analysis_snapshots(workspace_id,id),
          FOREIGN KEY(workspace_id,job_id) REFERENCES jobs(workspace_id,id), CHECK(char_length(shared_text)<=2000)
        );
    """)
    for table in ("analysis_snapshots", "analysis_reports"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING(workspace_id::text=current_setting('openform.workspace_id',true)) "
                   "WITH CHECK(workspace_id::text=current_setting('openform.workspace_id',true))")


def downgrade() -> None:
    op.execute("DROP TABLE analysis_reports, analysis_snapshots")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT jobs_kind_target, DROP COLUMN classroom_id, DROP COLUMN kind")
    op.execute("ALTER TABLE classrooms DROP COLUMN data_epoch")
