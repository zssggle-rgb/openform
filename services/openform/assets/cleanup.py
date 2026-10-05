import logging
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy import Engine, text

from openform.assets.storage import file_path
from openform.config import Settings
from openform.database import build_engine
from openform.identity.context import require_instance


def cleanup_images(engine: Engine, settings: Settings) -> int:
    with engine.begin() as connection:
        require_instance(connection)
        spaces = connection.execute(text("SELECT workspace_id FROM image_cleanup_spaces()")).scalars().all()
    cleaned = 0
    for space in spaces:
        with engine.begin() as connection:
            require_instance(connection)
            connection.execute(text("SELECT set_config('openform.workspace_id',:space,true), set_config('openform.account_id','',true)"), {"space": str(space)})
            connection.execute(text("SELECT id FROM workspaces WHERE id=:space FOR SHARE"), {"space": space})
            rows = connection.execute(text("""
                SELECT id,attempt_id FROM image_assets f WHERE workspace_id=:space AND (
                  status='pending' AND expires_at<now() OR status='deleted' OR
                  status='ready' AND created_at<now()-interval '24 hours'
                    AND NOT EXISTS(SELECT 1 FROM image_references r WHERE r.workspace_id=f.workspace_id AND r.file_id=f.id))
                ORDER BY attempt_id,id LIMIT 100
            """), {"space": space}).mappings().all()
        for row in rows:
            path: Path | None = None
            with engine.begin() as connection:
                require_instance(connection)
                connection.execute(text("SELECT set_config('openform.workspace_id',:space,true), set_config('openform.account_id','',true)"), {"space": str(space)})
                connection.execute(text("SELECT id FROM workspaces WHERE id=:space FOR SHARE"), {"space": space})
                connection.execute(text("SELECT id FROM activity_attempts WHERE workspace_id=:space AND id=:id FOR UPDATE"),
                                   {"space": space, "id": row["attempt_id"]})
                asset = connection.execute(text("""
                    SELECT status,byte_size,expires_at<now() AS expired,created_at<now()-interval '24 hours' AS old
                    FROM image_assets WHERE workspace_id=:space AND id=:id FOR UPDATE
                """), {"space": space, "id": row["id"]}).mappings().one_or_none()
                if asset is None:
                    continue
                referenced = connection.execute(text("SELECT EXISTS(SELECT 1 FROM image_references WHERE workspace_id=:space AND file_id=:id)"),
                                                {"space": space, "id": row["id"]}).scalar_one()
                if referenced or asset["status"] == "pending" and not asset["expired"] or asset["status"] == "ready" and not asset["old"]:
                    continue
                if asset["status"] == "ready":
                    connection.execute(text("UPDATE image_usage SET byte_size=byte_size-:size WHERE workspace_id=:space"),
                                       {"space": space, "size": asset["byte_size"]})
                connection.execute(text("UPDATE image_assets SET status='deleted' WHERE workspace_id=:space AND id=:id"), {"space": space, "id": row["id"]})
                path = file_path(settings, UUID(str(space)), row["id"])
            if path is not None:
                path.unlink(missing_ok=True)
                with engine.begin() as connection:
                    require_instance(connection)
                    connection.execute(text("SELECT set_config('openform.workspace_id',:space,true)"), {"space": str(space)})
                    connection.execute(text("DELETE FROM image_assets WHERE workspace_id=:space AND id=:id AND status='deleted'"), {"space": space, "id": row["id"]})
                cleaned += 1
    directory = settings.file_directory / "staging"
    if directory.is_dir():
        cutoff = time.time() - 3600
        for path in directory.iterdir():
            if path.is_file() and not path.is_symlink() and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    return cleaned


def main() -> None:
    settings = Settings()
    engine = build_engine(settings)
    try:
        while True:
            try:
                cleanup_images(engine, settings)
            except Exception as error:
                logging.getLogger("openform").error("image_cleanup_failed category=%s", type(error).__name__)
            time.sleep(3600)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
