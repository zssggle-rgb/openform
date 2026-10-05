"""Private image reservations and atomic attachment references."""
from alembic import op

revision = "0006_assets"
down_revision = "0005_classrooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE image_assets (
          workspace_id uuid NOT NULL, id uuid NOT NULL, attempt_id uuid NOT NULL, field text NOT NULL,
          status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','ready','deleted')),
          media_type text CHECK(media_type IN ('image/png','image/jpeg')), byte_size bigint NOT NULL DEFAULT 0 CHECK(byte_size>=0),
          digest char(64), created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL DEFAULT now()+interval '1 hour',
          PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,attempt_id,id),
          FOREIGN KEY(workspace_id,attempt_id) REFERENCES activity_attempts(workspace_id,id),
          CHECK(status!='ready' OR (media_type IS NOT NULL AND digest IS NOT NULL AND byte_size>0))
        );
        CREATE TABLE image_references (
          workspace_id uuid NOT NULL, attempt_id uuid NOT NULL, file_id uuid NOT NULL,
          kind text NOT NULL CHECK(kind IN ('progress','submission')),
          PRIMARY KEY(workspace_id,attempt_id,file_id,kind),
          FOREIGN KEY(workspace_id,attempt_id,file_id) REFERENCES image_assets(workspace_id,attempt_id,id)
        );
        CREATE TABLE image_usage (
          workspace_id uuid PRIMARY KEY REFERENCES workspaces(id), byte_size bigint NOT NULL DEFAULT 0 CHECK(byte_size>=0)
        );
        CREATE INDEX images_cleanup ON image_assets(status,created_at);
    """)
    for table in ("image_assets", "image_references", "image_usage"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING(workspace_id::text=current_setting('openform.workspace_id',true)) "
                   "WITH CHECK(workspace_id::text=current_setting('openform.workspace_id',true))")
    op.execute("""
        CREATE FUNCTION image_cleanup_spaces() RETURNS TABLE(workspace_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public
          AS $$ SELECT DISTINCT f.workspace_id FROM public.image_assets f
            WHERE f.status='pending' AND f.expires_at<now()
               OR f.status='ready' AND f.created_at<now()-interval '24 hours'
                 AND NOT EXISTS(SELECT 1 FROM public.image_references r WHERE r.workspace_id=f.workspace_id AND r.file_id=f.id)
               OR f.status='deleted' $$;
        REVOKE ALL ON FUNCTION image_cleanup_spaces() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION image_cleanup_spaces() TO openform_app;
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION image_cleanup_spaces(); DROP TABLE image_references, image_assets, image_usage")
