#!/bin/sh
# Existing installations: run inside postgres as bootstrap before 0007 migration.
set -eu
OPENFORM_DISPATCH_PASSWORD=$(cat /run/secrets/database_dispatch)
export OPENFORM_DISPATCH_PASSWORD
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv dispatch_password OPENFORM_DISPATCH_PASSWORD
SELECT 'CREATE ROLE openform_dispatch LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS'
WHERE NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='openform_dispatch') \gexec
ALTER ROLE openform_dispatch PASSWORD :'dispatch_password';
GRANT CONNECT ON DATABASE openform TO openform_dispatch;
SQL
unset OPENFORM_DISPATCH_PASSWORD
