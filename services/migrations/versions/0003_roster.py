"""Stable school roster, revocable student credentials and object capabilities."""
from alembic import op

revision = "0003_roster"
down_revision = "0002_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE classes (
            workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL,
            name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
            active boolean NOT NULL DEFAULT true, revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
            PRIMARY KEY (workspace_id, id), UNIQUE (workspace_id, name)
        );
        CREATE TABLE assignments (
            workspace_id uuid NOT NULL, class_id uuid NOT NULL, account_id uuid NOT NULL,
            subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 40),
            active boolean NOT NULL DEFAULT true, revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
            PRIMARY KEY (workspace_id, class_id, account_id),
            FOREIGN KEY (workspace_id, class_id) REFERENCES classes(workspace_id, id),
            FOREIGN KEY (workspace_id, account_id) REFERENCES memberships(workspace_id, account_id)
        );
        CREATE TABLE students (
            workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL,
            reference text NOT NULL CHECK (length(reference) BETWEEN 1 AND 64),
            display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 80), class_id uuid,
            active boolean NOT NULL DEFAULT true, revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
            auth_epoch bigint NOT NULL DEFAULT 1 CHECK (auth_epoch>0),
            code_digest char(64) UNIQUE, code_expires_at timestamptz,
            PRIMARY KEY (workspace_id, id), UNIQUE (workspace_id, reference),
            FOREIGN KEY (workspace_id, class_id) REFERENCES classes(workspace_id, id),
            CHECK ((code_digest IS NULL) = (code_expires_at IS NULL))
        );
        CREATE INDEX students_class ON students(workspace_id, class_id, id);
        CREATE TABLE student_sessions (
            workspace_id uuid NOT NULL, token_digest char(64) NOT NULL UNIQUE, student_id uuid NOT NULL,
            auth_epoch bigint NOT NULL, expires_at timestamptz NOT NULL,
            revoked boolean NOT NULL DEFAULT false,
            PRIMARY KEY (workspace_id, token_digest),
            FOREIGN KEY (workspace_id, student_id) REFERENCES students(workspace_id, id)
        );
        CREATE INDEX student_sessions_identity ON student_sessions(workspace_id, student_id);
        CREATE TABLE authorization_objects (
            workspace_id uuid NOT NULL, id uuid NOT NULL, kind text NOT NULL,
            owner_id uuid NOT NULL, active boolean NOT NULL DEFAULT true,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
            PRIMARY KEY (workspace_id, id), UNIQUE (workspace_id, id, kind),
            FOREIGN KEY (workspace_id, owner_id) REFERENCES memberships(workspace_id, account_id),
            CHECK (kind IN ('activity', 'classroom', 'archive'))
        );
        CREATE TABLE object_grants (
            workspace_id uuid NOT NULL, object_id uuid NOT NULL, account_id uuid NOT NULL,
            capabilities text[] NOT NULL, active boolean NOT NULL DEFAULT true,
            revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
            PRIMARY KEY (workspace_id, object_id, account_id),
            FOREIGN KEY (workspace_id, object_id) REFERENCES authorization_objects(workspace_id, id),
            FOREIGN KEY (workspace_id, account_id) REFERENCES memberships(workspace_id, account_id)
        );
        CREATE TABLE identity_events (
            workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL,
            actor_id uuid NOT NULL REFERENCES accounts(id), action text NOT NULL, target_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (workspace_id, id)
        );
    """)
    for table in ("classes", "assignments", "students", "student_sessions", "authorization_objects", "object_grants", "identity_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING (workspace_id::text=current_setting('openform.workspace_id', true)) "
                   "WITH CHECK (workspace_id::text=current_setting('openform.workspace_id', true))")
    op.execute("""
        CREATE FUNCTION locate_student_code(digest text) RETURNS TABLE(workspace_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog, public
          AS $$ SELECT s.workspace_id FROM public.students s JOIN public.workspaces w ON w.id=s.workspace_id
            WHERE s.code_digest=digest AND s.code_expires_at>now() AND s.active AND w.active $$;
        REVOKE ALL ON FUNCTION locate_student_code(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION locate_student_code(text) TO openform_app;
        CREATE FUNCTION locate_student_session(digest text) RETURNS TABLE(workspace_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog, public
          AS $$ SELECT t.workspace_id FROM public.student_sessions t
            JOIN public.students s ON s.workspace_id=t.workspace_id AND s.id=t.student_id
            JOIN public.workspaces w ON w.id=t.workspace_id
            WHERE t.token_digest=digest AND NOT t.revoked AND t.expires_at>now()
              AND s.active AND s.auth_epoch=t.auth_epoch AND w.active $$;
        REVOKE ALL ON FUNCTION locate_student_session(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION locate_student_session(text) TO openform_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION locate_student_code(text);
        DROP FUNCTION locate_student_session(text);
        DROP TABLE identity_events, object_grants, authorization_objects, student_sessions, students, assignments, classes;
    """)
