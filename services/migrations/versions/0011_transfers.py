"""Private export jobs, staged imports and isolated classroom archives."""
from alembic import op

revision = "0011_transfers"
down_revision = "0010_school"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      CREATE TABLE transfer_exports (
        workspace_id uuid NOT NULL REFERENCES workspaces(id),id uuid NOT NULL,
        requester_id uuid NOT NULL REFERENCES accounts(id),auth_epoch bigint NOT NULL,session_digest text NOT NULL,
        request_key uuid NOT NULL,input_digest char(64) NOT NULL,kind text NOT NULL CHECK(kind IN ('resource','archive')),
        object_id uuid NOT NULL,data_epoch bigint,version_number bigint,
        status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed','invalidated')),
        byte_size bigint NOT NULL DEFAULT 0 CHECK(byte_size>=0),file_digest char(64),snapshot jsonb,
        error_code text,error_message text,created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '24 hours',
        PRIMARY KEY(workspace_id,id),UNIQUE(workspace_id,requester_id,request_key),
        FOREIGN KEY(workspace_id,object_id) REFERENCES authorization_objects(workspace_id,id)
      );
      CREATE TABLE transfer_dispatch (
        workspace_id uuid NOT NULL,id uuid NOT NULL,generation bigint NOT NULL DEFAULT 0,
        phase text NOT NULL DEFAULT 'queued' CHECK(phase IN ('queued','running','done')),
        lease_until timestamptz,available_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(workspace_id,id),FOREIGN KEY(workspace_id,id) REFERENCES transfer_exports(workspace_id,id)
      );
      CREATE INDEX transfer_queue ON transfer_dispatch(phase,available_at);
      CREATE TABLE transfer_imports (
        workspace_id uuid NOT NULL REFERENCES workspaces(id),id uuid NOT NULL,requester_id uuid NOT NULL REFERENCES accounts(id),
        kind text NOT NULL CHECK(kind IN ('resource','archive')),title text NOT NULL,request_key uuid NOT NULL,
        digest char(64) NOT NULL,byte_size bigint NOT NULL CHECK(byte_size>=0),summary jsonb NOT NULL,chosen_version bigint,
        status text NOT NULL DEFAULT 'validated' CHECK(status IN ('validated','committed','expired')),
        result_id uuid,created_at timestamptz NOT NULL DEFAULT now(),expires_at timestamptz NOT NULL DEFAULT now()+interval '1 hour',
        PRIMARY KEY(workspace_id,id),UNIQUE(workspace_id,requester_id,request_key)
      );
      CREATE TABLE classroom_archives (
        workspace_id uuid NOT NULL,id uuid NOT NULL,title text NOT NULL,source jsonb NOT NULL,version jsonb NOT NULL,
        import_id uuid NOT NULL,deleted_at timestamptz,created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(workspace_id,id),FOREIGN KEY(workspace_id,id) REFERENCES authorization_objects(workspace_id,id),
        FOREIGN KEY(workspace_id,import_id) REFERENCES transfer_imports(workspace_id,id)
      );
      CREATE TABLE archive_records (
        workspace_id uuid NOT NULL,id uuid NOT NULL,archive_id uuid NOT NULL,body jsonb NOT NULL,
        PRIMARY KEY(workspace_id,id),FOREIGN KEY(workspace_id,archive_id) REFERENCES classroom_archives(workspace_id,id)
      );
      CREATE TABLE imported_resource_versions (
        workspace_id uuid NOT NULL,activity_id uuid NOT NULL,number bigint NOT NULL,source jsonb NOT NULL,draft jsonb NOT NULL,
        PRIMARY KEY(workspace_id,activity_id,number),FOREIGN KEY(workspace_id,activity_id) REFERENCES activities(workspace_id,id)
      );
    """)
    for table in ("transfer_exports", "transfer_dispatch", "transfer_imports", "classroom_archives", "archive_records", "imported_resource_versions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING(workspace_id::text=current_setting('openform.workspace_id',true)) "
                   "WITH CHECK(workspace_id::text=current_setting('openform.workspace_id',true))")
    op.execute("""
      REVOKE UPDATE ON archive_records,imported_resource_versions FROM openform_app;
      GRANT SELECT,UPDATE ON transfer_dispatch TO openform_dispatch;
      CREATE POLICY transfer_dispatch_metadata ON transfer_dispatch TO openform_dispatch USING(true) WITH CHECK(true);
      CREATE FUNCTION transfer_cleanup_spaces(default_days int) RETURNS TABLE(workspace_id uuid)
        LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public
        AS $$ SELECT e.workspace_id FROM public.transfer_exports e LEFT JOIN public.classrooms c ON c.workspace_id=e.workspace_id AND c.id=e.object_id
          LEFT JOIN public.classroom_archives a ON a.workspace_id=e.workspace_id AND a.id=e.object_id
          WHERE (e.byte_size>0 OR e.snapshot IS NOT NULL OR e.status IN ('queued','running')) AND
            (e.expires_at<now() OR e.status='invalidated' OR e.kind='archive' AND (c.records_deleted_at IS NOT NULL OR a.deleted_at IS NOT NULL))
          UNION SELECT i.workspace_id FROM public.transfer_imports i
          WHERE i.byte_size>0 AND (i.status='validated' AND i.expires_at<now() OR i.status='expired')
          UNION SELECT a.workspace_id FROM public.classroom_archives a LEFT JOIN public.workspace_policies p ON p.workspace_id=a.workspace_id
            WHERE a.deleted_at IS NULL AND a.created_at<now()-make_interval(days=>coalesce(p.retention_days,default_days)) $$;
      REVOKE ALL ON FUNCTION transfer_cleanup_spaces(int) FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION transfer_cleanup_spaces(int) TO openform_app;
    """)


def downgrade() -> None:
    raise RuntimeError("归档迁移仅支持前滚；请在新实例恢复已核验备份。")
