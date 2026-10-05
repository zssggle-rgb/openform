import os

import pytest
from openform.config import Settings
from openform.database import build_engine, probe_database
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


@pytest.mark.postgres
def test_real_postgresql_boot_and_separated_roles():
    url = os.environ.get("OPENFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set a dedicated PostgreSQL 18 test database; never substitute SQLite.")
    settings = Settings(database_url=url)
    engine = build_engine(settings)
    try:
        probe_database(engine)
        with engine.begin() as connection:
            assert connection.execute(text("SELECT generation FROM instance_state WHERE id=true")).scalar_one() == 1
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE instance_state SET maintenance=true WHERE id=true"))
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE alembic_version SET version_num='untrusted'"))
    finally:
        engine.dispose()
