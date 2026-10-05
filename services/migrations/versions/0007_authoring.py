"""Durable authoring jobs, isolated dispatch metadata and token reservations."""
from alembic import op

revision = "0007_authoring"
down_revision = "0006_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE model_usage (
          workspace_id uuid PRIMARY KEY REFERENCES workspaces(id),
          reserved_tokens bigint NOT NULL DEFAULT 0 CHECK(reserved_tokens>=0),
          used_tokens bigint NOT NULL DEFAULT 0 CHECK(used_tokens>=0)
        );
        CREATE TABLE jobs (
          workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL,
          requester_id uuid NOT NULL REFERENCES accounts(id), auth_epoch bigint NOT NULL, session_digest text NOT NULL,
          activity_id uuid, expected_revision bigint NOT NULL CHECK(expected_revision>=0),
          request_key uuid NOT NULL, input_digest char(64) NOT NULL, prompt text NOT NULL,
          source jsonb, status text NOT NULL DEFAULT 'queued'
            CHECK(status IN ('queued','running','succeeded','failed','outcome_unknown','cancelled')),
          reserved_tokens bigint NOT NULL CHECK(reserved_tokens>0), settled boolean NOT NULL DEFAULT false,
          result jsonb, raw_output text, usage jsonb, error_code text, error_message text,
          created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,requester_id,request_key),
          FOREIGN KEY(workspace_id,activity_id) REFERENCES activities(workspace_id,id),
          CHECK(octet_length(prompt)<=32768), CHECK(octet_length(raw_output)<=2097152)
        );
        CREATE TABLE job_dispatch (
          workspace_id uuid NOT NULL, id uuid NOT NULL, generation bigint NOT NULL DEFAULT 0,
          phase text NOT NULL DEFAULT 'queued' CHECK(phase IN ('queued','running','calling','done')),
          available_at timestamptz NOT NULL DEFAULT now(), lease_until timestamptz,
          attempts int NOT NULL DEFAULT 0, PRIMARY KEY(workspace_id,id),
          FOREIGN KEY(workspace_id,id) REFERENCES jobs(workspace_id,id)
        );
        CREATE INDEX job_queue ON job_dispatch(phase,available_at);
        CREATE TABLE authoring_imports (
          workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL, requester_id uuid NOT NULL REFERENCES accounts(id),
          request_key uuid NOT NULL, input_digest char(64) NOT NULL, activity_id uuid, draft jsonb NOT NULL,
          status text NOT NULL CHECK(status IN ('succeeded','failed')), result jsonb, error_code text, error_message text,
          created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id),
          UNIQUE(workspace_id,requester_id,request_key), FOREIGN KEY(workspace_id,activity_id) REFERENCES activities(workspace_id,id)
        );
    """)
    for table in ("model_usage", "jobs", "job_dispatch", "authoring_imports"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING(workspace_id::text=current_setting('openform.workspace_id',true)) "
                   "WITH CHECK(workspace_id::text=current_setting('openform.workspace_id',true))")
    op.execute("""
        GRANT USAGE ON SCHEMA public TO openform_dispatch;
        GRANT SELECT, UPDATE ON job_dispatch TO openform_dispatch;
        CREATE POLICY dispatch_metadata ON job_dispatch TO openform_dispatch USING(true) WITH CHECK(true);
        GRANT SELECT ON instance_state TO openform_dispatch;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE authoring_imports, job_dispatch, jobs, model_usage")
