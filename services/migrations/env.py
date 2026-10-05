from alembic import context
from openform.config import Settings
from sqlalchemy import create_engine, pool, text

engine = create_engine(Settings().connection_url(), poolclass=pool.NullPool, hide_parameters=True)
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
        connection.execute(text("REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM openform_app"))
        connection.execute(text("GRANT SELECT ON alembic_version TO openform_app"))
engine.dispose()
