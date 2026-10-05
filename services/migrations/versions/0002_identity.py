"""Local accounts, revocable sessions and tenant membership boundaries."""
from alembic import op

revision = "0002_identity"
down_revision = "0001_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE accounts (
            id uuid PRIMARY KEY,
            login text NOT NULL UNIQUE CHECK (length(login) BETWEEN 3 AND 64),
            display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 80),
            password_hash text NOT NULL,
            active boolean NOT NULL DEFAULT true,
            auth_epoch bigint NOT NULL DEFAULT 1 CHECK (auth_epoch > 0)
        );
        CREATE TABLE auth_sessions (
            token_digest char(64) PRIMARY KEY,
            account_id uuid NOT NULL REFERENCES accounts(id),
            auth_epoch bigint NOT NULL,
            expires_at timestamptz NOT NULL,
            revoked boolean NOT NULL DEFAULT false
        );
        CREATE INDEX auth_sessions_account ON auth_sessions(account_id);
        CREATE TABLE auth_limits (
            bucket char(64) PRIMARY KEY,
            window_start timestamptz NOT NULL,
            count integer NOT NULL CHECK (count > 0)
        );
        CREATE TABLE workspaces (
            id uuid PRIMARY KEY,
            name text NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
            kind text NOT NULL CHECK (kind IN ('personal', 'campus')),
            owner_id uuid REFERENCES accounts(id),
            active boolean NOT NULL DEFAULT true,
            CHECK ((kind='personal') = (owner_id IS NOT NULL))
        );
        CREATE UNIQUE INDEX personal_workspace_owner ON workspaces(owner_id) WHERE kind='personal';
        CREATE TABLE memberships (
            workspace_id uuid NOT NULL REFERENCES workspaces(id),
            account_id uuid NOT NULL REFERENCES accounts(id),
            is_teacher boolean NOT NULL DEFAULT false,
            is_admin boolean NOT NULL DEFAULT false,
            active boolean NOT NULL DEFAULT true,
            auth_epoch bigint NOT NULL DEFAULT 1 CHECK (auth_epoch > 0),
            PRIMARY KEY (workspace_id, account_id),
            CHECK (is_teacher OR is_admin)
        );
        CREATE TABLE staff_invites (
            workspace_id uuid NOT NULL REFERENCES workspaces(id),
            id uuid NOT NULL,
            token_digest char(64) NOT NULL UNIQUE,
            is_teacher boolean NOT NULL,
            is_admin boolean NOT NULL,
            target_login text,
            expires_at timestamptz NOT NULL,
            active boolean NOT NULL DEFAULT true,
            used_by uuid REFERENCES accounts(id),
            PRIMARY KEY (workspace_id, id),
            CHECK (is_teacher OR is_admin)
        );
        ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
        CREATE POLICY workspaces_scope ON workspaces TO openform_app
          USING (id::text = current_setting('openform.workspace_id', true)
            OR owner_id::text = current_setting('openform.account_id', true)
            OR id IN (SELECT workspace_id FROM memberships
              WHERE account_id::text = current_setting('openform.account_id', true)))
          WITH CHECK (id::text = current_setting('openform.workspace_id', true)
            OR (kind='personal' AND owner_id::text = current_setting('openform.account_id', true)));
        ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
        CREATE POLICY memberships_scope ON memberships TO openform_app
          USING (workspace_id::text = current_setting('openform.workspace_id', true)
            OR account_id::text = current_setting('openform.account_id', true))
          WITH CHECK (workspace_id::text = current_setting('openform.workspace_id', true));
        ALTER TABLE staff_invites ENABLE ROW LEVEL SECURITY;
        CREATE POLICY invites_scope ON staff_invites TO openform_app
          USING (workspace_id::text = current_setting('openform.workspace_id', true))
          WITH CHECK (workspace_id::text = current_setting('openform.workspace_id', true));
        CREATE FUNCTION locate_invite(digest text) RETURNS TABLE(workspace_id uuid)
          LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public
          AS $$ SELECT i.workspace_id FROM public.staff_invites i
            JOIN public.workspaces w ON w.id=i.workspace_id
            WHERE i.token_digest=digest AND i.active AND i.used_by IS NULL
              AND i.expires_at > now() AND w.active $$;
        REVOKE ALL ON FUNCTION locate_invite(text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION locate_invite(text) TO openform_app;
        CREATE FUNCTION instance_is_locked() RETURNS boolean
          LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, public
          AS $$ SELECT maintenance OR restored_locked FROM public.instance_state WHERE id=true FOR SHARE $$;
        REVOKE ALL ON FUNCTION instance_is_locked() FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION instance_is_locked() TO openform_app;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION locate_invite(text);
        DROP FUNCTION IF EXISTS instance_is_locked();
        DROP TABLE staff_invites, memberships, workspaces, auth_limits, auth_sessions, accounts;
    """)
