from sqlalchemy import Engine, create_engine, text

from openform.config import Settings

SCHEMA_REVISION = "0010_school"


class DatabaseNotReady(RuntimeError):
    pass


def build_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.connection_url(), pool_pre_ping=True, pool_size=10, max_overflow=10,
        pool_timeout=5, hide_parameters=True,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"},
    )


def probe_database(engine: Engine) -> None:
    """Readiness requires the supported server, migrations and a restricted role."""
    with engine.connect() as connection:
        version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
        role = connection.execute(text(
            "SELECT rolsuper, rolbypassrls, "
            "EXISTS (SELECT 1 FROM pg_namespace WHERE nspname='public' AND nspowner=r.oid) "
            "FROM pg_roles r WHERE rolname=current_user"
        )).one()
        if not 180000 <= version < 190000 or any(role):
            raise DatabaseNotReady("数据库版本或业务角色不符合部署要求。")
        revision = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one()
        if revision != SCHEMA_REVISION:
            raise DatabaseNotReady("数据库迁移版本不一致。")
        locked = connection.execute(text(
            "SELECT maintenance OR restored_locked FROM public.instance_state WHERE id=true"
        )).scalar_one()
        if locked:
            raise DatabaseNotReady("实例处于维护或恢复锁定状态。")
