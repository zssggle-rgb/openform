"""School ownership, bounded policies and classroom record tombstones."""
from alembic import op

revision = "0010_school"
down_revision = "0009_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE auth_sessions ADD COLUMN created_at timestamptz NOT NULL DEFAULT clock_timestamp();
        ALTER TABLE memberships ADD COLUMN session_valid_after timestamptz NOT NULL DEFAULT '1970-01-01 00:00:00+00';
        ALTER TABLE authorization_objects ADD COLUMN creator_id uuid REFERENCES accounts(id);
        UPDATE authorization_objects SET creator_id=owner_id;
        ALTER TABLE authorization_objects ALTER COLUMN creator_id SET NOT NULL;
        ALTER TABLE classrooms ADD COLUMN ended_at timestamptz;
        UPDATE classrooms SET ended_at=now() WHERE state='ended';
        ALTER TABLE classrooms ADD COLUMN records_deleted_at timestamptz;
        ALTER TABLE classrooms ADD COLUMN records_cleaned_at timestamptz;
        ALTER TABLE identity_events ALTER COLUMN actor_id DROP NOT NULL;
        CREATE TABLE workspace_policies (
          workspace_id uuid PRIMARY KEY REFERENCES workspaces(id),
          revision bigint NOT NULL DEFAULT 1 CHECK(revision>0),
          retention_days int NOT NULL CHECK(retention_days BETWEEN 1 AND 3650),
          model_token_limit bigint NOT NULL CHECK(model_token_limit>=0),
          image_byte_limit bigint NOT NULL CHECK(image_byte_limit>=0),
          generation_enabled boolean NOT NULL DEFAULT true,
          analysis_enabled boolean NOT NULL DEFAULT true
        );
        CREATE TABLE ownership_transfers (
          workspace_id uuid NOT NULL, id uuid NOT NULL, object_id uuid NOT NULL,
          previous_owner uuid NOT NULL REFERENCES accounts(id), new_owner uuid NOT NULL REFERENCES accounts(id),
          actor_id uuid NOT NULL REFERENCES accounts(id), created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(workspace_id,id), FOREIGN KEY(workspace_id,object_id) REFERENCES authorization_objects(workspace_id,id)
        );
        CREATE INDEX classrooms_retention ON classrooms(workspace_id,ended_at)
          WHERE records_deleted_at IS NULL AND state='ended';
    """)
    for table in ("workspace_policies", "ownership_transfers"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING(workspace_id::text=current_setting('openform.workspace_id',true)) "
                   "WITH CHECK(workspace_id::text=current_setting('openform.workspace_id',true))")
    op.execute("""
        REVOKE UPDATE, DELETE ON ownership_transfers FROM openform_app;
        CREATE FUNCTION classroom_cleanup_spaces(default_days int) RETURNS TABLE(workspace_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public
          AS $$ SELECT DISTINCT c.workspace_id FROM public.classrooms c
            LEFT JOIN public.workspace_policies p ON p.workspace_id=c.workspace_id
            WHERE (c.records_deleted_at IS NOT NULL AND c.records_cleaned_at IS NULL)
              OR (c.state='ended' AND c.records_deleted_at IS NULL
                AND c.ended_at<now()-make_interval(days=>coalesce(p.retention_days,default_days))) $$;
        REVOKE ALL ON FUNCTION classroom_cleanup_spaces(int) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION classroom_cleanup_spaces(int) TO openform_app;
    """)


def downgrade() -> None:
    raise RuntimeError("资料删除不能降级恢复，请使用已核验的备份在新实例恢复。")
