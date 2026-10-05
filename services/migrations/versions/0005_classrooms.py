"""Versioned teaching activities, isolated trials and durable classroom records."""
from alembic import op

revision = "0005_classrooms"
down_revision = "0004_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE activities (
            workspace_id uuid NOT NULL, id uuid NOT NULL, title text NOT NULL,
            draft_revision bigint NOT NULL CHECK (draft_revision>0), manifest jsonb NOT NULL,
            grading jsonb NOT NULL, package_digest char(64) NOT NULL,
            PRIMARY KEY (workspace_id, id),
            FOREIGN KEY (workspace_id, id) REFERENCES authorization_objects(workspace_id, id),
            FOREIGN KEY (workspace_id, package_digest) REFERENCES runtime_packages(workspace_id, digest)
        );
        CREATE TABLE activity_versions (
            workspace_id uuid NOT NULL, id uuid NOT NULL, activity_id uuid NOT NULL,
            number bigint NOT NULL CHECK (number>0), draft_revision bigint NOT NULL,
            manifest jsonb NOT NULL, grading jsonb NOT NULL, package_digest char(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id), UNIQUE (workspace_id, activity_id, number),
            UNIQUE (workspace_id, activity_id, draft_revision),
            FOREIGN KEY (workspace_id, activity_id) REFERENCES activities(workspace_id, id),
            FOREIGN KEY (workspace_id, package_digest) REFERENCES runtime_packages(workspace_id, digest)
        );
        CREATE TABLE activity_trials (
            workspace_id uuid NOT NULL, id uuid NOT NULL, activity_id uuid NOT NULL,
            account_id uuid NOT NULL, draft_revision bigint NOT NULL, package_digest char(64) NOT NULL,
            manifest jsonb NOT NULL, grading jsonb NOT NULL,
            ready boolean NOT NULL DEFAULT false, reread_revision bigint NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id),
            UNIQUE (workspace_id, id, account_id),
            FOREIGN KEY (workspace_id, activity_id) REFERENCES activities(workspace_id, id),
            FOREIGN KEY (workspace_id, account_id) REFERENCES memberships(workspace_id, account_id),
            FOREIGN KEY (workspace_id, package_digest) REFERENCES runtime_packages(workspace_id, digest)
        );
        CREATE TABLE classrooms (
            workspace_id uuid NOT NULL, id uuid NOT NULL, version_id uuid NOT NULL,
            class_id uuid, title text NOT NULL, code char(8) NOT NULL UNIQUE,
            state text NOT NULL DEFAULT 'prepared' CHECK (state IN ('prepared','open','paused','ended')),
            revision bigint NOT NULL DEFAULT 1 CHECK (revision>0),
            mode text NOT NULL CHECK (mode IN ('individual','group','quick')),
            groups jsonb NOT NULL DEFAULT '[]',
            planned_count integer CHECK (planned_count>=0), created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id),
            FOREIGN KEY (workspace_id, id) REFERENCES authorization_objects(workspace_id, id),
            FOREIGN KEY (workspace_id, version_id) REFERENCES activity_versions(workspace_id, id),
            FOREIGN KEY (workspace_id, class_id) REFERENCES classes(workspace_id, id),
            CHECK ((class_id IS NULL AND mode='quick' AND planned_count IS NULL)
                OR (class_id IS NOT NULL AND mode IN ('individual','group') AND planned_count IS NOT NULL))
        );
        CREATE TABLE classroom_roster (
            workspace_id uuid NOT NULL, classroom_id uuid NOT NULL, student_id uuid NOT NULL,
            display_name text NOT NULL, reference text NOT NULL, group_name text,
            members uuid[] NOT NULL DEFAULT '{}',
            PRIMARY KEY (workspace_id, classroom_id, student_id),
            FOREIGN KEY (workspace_id, classroom_id) REFERENCES classrooms(workspace_id, id),
            FOREIGN KEY (workspace_id, student_id) REFERENCES students(workspace_id, id)
        );
        CREATE TABLE classroom_guests (
            workspace_id uuid NOT NULL, classroom_id uuid NOT NULL, id uuid NOT NULL,
            display_name text NOT NULL, active boolean NOT NULL DEFAULT true,
            PRIMARY KEY (workspace_id, id),
            UNIQUE (workspace_id, classroom_id, id),
            FOREIGN KEY (workspace_id, classroom_id) REFERENCES classrooms(workspace_id, id)
        );
        CREATE TABLE guest_sessions (
            workspace_id uuid NOT NULL, token_digest char(64) NOT NULL UNIQUE, guest_id uuid NOT NULL,
            expires_at timestamptz NOT NULL, revoked boolean NOT NULL DEFAULT false,
            PRIMARY KEY (workspace_id, token_digest),
            FOREIGN KEY (workspace_id, guest_id) REFERENCES classroom_guests(workspace_id, id)
        );
        CREATE TABLE activity_attempts (
            workspace_id uuid NOT NULL, id uuid NOT NULL, classroom_id uuid, trial_id uuid,
            actor_kind text NOT NULL CHECK (actor_kind IN ('student','guest','staff')), actor_id uuid NOT NULL,
            parent_attempt_id uuid,
            student_id uuid, guest_id uuid, account_id uuid,
            number bigint NOT NULL CHECK (number>0), revision bigint NOT NULL DEFAULT 0 CHECK (revision>=0),
            state text NOT NULL DEFAULT 'in_progress' CHECK (state IN ('in_progress','submitted')),
            progress jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id),
            UNIQUE (workspace_id, classroom_id, actor_kind, actor_id, number),
            UNIQUE (workspace_id, trial_id),
            UNIQUE (workspace_id, parent_attempt_id),
            FOREIGN KEY (workspace_id, parent_attempt_id) REFERENCES activity_attempts(workspace_id, id),
            FOREIGN KEY (workspace_id, classroom_id) REFERENCES classrooms(workspace_id, id),
            FOREIGN KEY (workspace_id, trial_id, account_id) REFERENCES activity_trials(workspace_id, id, account_id),
            FOREIGN KEY (workspace_id, student_id) REFERENCES students(workspace_id, id),
            FOREIGN KEY (workspace_id, classroom_id, guest_id) REFERENCES classroom_guests(workspace_id, classroom_id, id),
            FOREIGN KEY (workspace_id, account_id) REFERENCES memberships(workspace_id, account_id),
            CHECK ((trial_id IS NOT NULL AND classroom_id IS NULL AND actor_kind='staff' AND account_id IS NOT NULL AND account_id=actor_id AND student_id IS NULL AND guest_id IS NULL)
                OR (trial_id IS NULL AND classroom_id IS NOT NULL AND actor_kind='student' AND student_id IS NOT NULL AND student_id=actor_id AND account_id IS NULL AND guest_id IS NULL)
                OR (trial_id IS NULL AND classroom_id IS NOT NULL AND actor_kind='guest' AND guest_id IS NOT NULL AND guest_id=actor_id AND account_id IS NULL AND student_id IS NULL))
        );
        CREATE TABLE activity_submissions (
            workspace_id uuid NOT NULL, id uuid NOT NULL, attempt_id uuid NOT NULL,
            data jsonb NOT NULL, receipt jsonb NOT NULL, scores jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, id), UNIQUE (workspace_id, attempt_id),
            FOREIGN KEY (workspace_id, attempt_id) REFERENCES activity_attempts(workspace_id, id)
        );
        CREATE TABLE activity_operations (
            workspace_id uuid NOT NULL, actor_kind text NOT NULL, actor_id uuid NOT NULL,
            method text NOT NULL CHECK (method IN ('saveProgress','submit')), idempotency_key text NOT NULL,
            attempt_id uuid NOT NULL, payload_digest char(64) NOT NULL, receipt jsonb NOT NULL,
            PRIMARY KEY (workspace_id, actor_kind, actor_id, method, idempotency_key),
            FOREIGN KEY (workspace_id, attempt_id) REFERENCES activity_attempts(workspace_id, id)
        );
        CREATE TABLE activity_events (
            workspace_id uuid NOT NULL, attempt_id uuid NOT NULL, event_id text NOT NULL,
            kind text NOT NULL, data jsonb NOT NULL,
            PRIMARY KEY (workspace_id, attempt_id, event_id),
            FOREIGN KEY (workspace_id, attempt_id) REFERENCES activity_attempts(workspace_id, id)
        );
        CREATE INDEX attempts_classroom ON activity_attempts(workspace_id, classroom_id, actor_kind, actor_id, number DESC);
    """)
    op.execute("""
        CREATE TABLE activity_sources (
            workspace_id uuid NOT NULL, package_digest char(64) NOT NULL, assets jsonb NOT NULL,
            PRIMARY KEY (workspace_id, package_digest),
            FOREIGN KEY (workspace_id, package_digest) REFERENCES runtime_packages(workspace_id, digest)
        );
    """)
    for table in ("activities", "activity_versions", "activity_trials", "activity_sources", "classrooms", "classroom_roster", "classroom_guests",
                  "guest_sessions", "activity_attempts", "activity_submissions", "activity_operations", "activity_events"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY {table}_scope ON {table} TO openform_app "
                   "USING (workspace_id::text=current_setting('openform.workspace_id', true)) "
                   "WITH CHECK (workspace_id::text=current_setting('openform.workspace_id', true))")
    op.execute("""
        REVOKE UPDATE ON activity_versions, activity_sources, activity_submissions, activity_operations, classroom_roster FROM openform_app;
        CREATE FUNCTION locate_classroom(code_value text) RETURNS TABLE(workspace_id uuid, classroom_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog, public
          AS $$ SELECT c.workspace_id, c.id FROM public.classrooms c
            JOIN public.workspaces w ON w.id=c.workspace_id
            JOIN public.authorization_objects o ON o.workspace_id=c.workspace_id AND o.id=c.id
            WHERE c.code=code_value AND w.active AND o.active $$;
        REVOKE ALL ON FUNCTION locate_classroom(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION locate_classroom(text) TO openform_app;
        CREATE FUNCTION locate_guest_session(digest text) RETURNS TABLE(workspace_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog, public
          AS $$ SELECT t.workspace_id FROM public.guest_sessions t
            JOIN public.classroom_guests g ON g.workspace_id=t.workspace_id AND g.id=t.guest_id
            JOIN public.workspaces w ON w.id=t.workspace_id
            WHERE t.token_digest=digest AND NOT t.revoked AND t.expires_at>now() AND g.active AND w.active $$;
        REVOKE ALL ON FUNCTION locate_guest_session(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION locate_guest_session(text) TO openform_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION locate_classroom(text);
        DROP FUNCTION locate_guest_session(text);
        DROP TABLE activity_events, activity_operations, activity_submissions, activity_attempts,
          guest_sessions, classroom_guests, classroom_roster, classrooms, activity_trials, activity_versions, activities, activity_sources;
    """)
