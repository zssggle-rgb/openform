"""Independent operator sessions and non-content instance metadata."""
from alembic import op

revision = "0012_operations"
down_revision = "0011_transfers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
      ALTER TABLE instance_state ADD COLUMN instance_id uuid NOT NULL DEFAULT gen_random_uuid();
      ALTER TABLE instance_state ADD COLUMN backup jsonb;
      ALTER TABLE instance_state ADD COLUMN pending_backup jsonb;
      ALTER TABLE instance_state ADD COLUMN recovery jsonb;
      CREATE TABLE operator_sessions (
        token_digest char(64) PRIMARY KEY, credential_digest char(64) NOT NULL,
        expires_at timestamptz NOT NULL, revoked boolean NOT NULL DEFAULT false
      );
      CREATE FUNCTION operator_status() RETURNS jsonb
        LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public
        AS $$ SELECT jsonb_build_object(
          'instance_id',s.instance_id,'generation',s.generation,'maintenance',s.maintenance,
          'restored_locked',s.restored_locked,'backup',s.backup,'pending_backup',s.pending_backup,'recovery',s.recovery,
          'schema',(SELECT version_num FROM public.alembic_version),
          'jobs',(SELECT coalesce(jsonb_object_agg(status,n),'{}'::jsonb)
                  FROM (SELECT status,count(*) n FROM public.jobs GROUP BY status) j),
          'exports',(SELECT coalesce(jsonb_object_agg(status,n),'{}'::jsonb)
                  FROM (SELECT status,count(*) n FROM public.transfer_exports GROUP BY status) e)
        ) FROM public.instance_state s WHERE s.id=true $$;
      REVOKE ALL ON FUNCTION operator_status() FROM PUBLIC;
      GRANT EXECUTE ON FUNCTION operator_status() TO openform_app;
    """)


def downgrade() -> None:
    raise RuntimeError("实例恢复元数据不能降级，请在新实例恢复已核验的备份。")
