import time
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from openform.config import Settings
from openform.identity.context import require_instance, set_context
from openform.transfers.storage import artifact_path


def cleanup_transfers(engine: Engine, settings: Settings) -> int:
    with engine.begin() as connection:
        require_instance(connection)
        spaces = connection.execute(text("SELECT workspace_id FROM transfer_cleanup_spaces(:days)"), {"days": settings.record_retention_days}).scalars().all()
    cleaned = 0
    for space in spaces:
        paths = []
        with engine.begin() as connection:
            require_instance(connection)
            set_context(connection, account_id=UUID(int=0), workspace_id=space)
            connection.execute(text("SELECT id FROM workspaces WHERE id=:space FOR UPDATE"), {"space": space})
            archives = connection.execute(text("""
              SELECT a.id,a.import_id FROM classroom_archives a LEFT JOIN workspace_policies p ON p.workspace_id=a.workspace_id
              WHERE a.workspace_id=:space AND a.deleted_at IS NULL
                AND a.created_at<now()-make_interval(days=>coalesce(p.retention_days,:days)) ORDER BY a.id LIMIT 20
            """), {"space": space, "days": settings.record_retention_days}).mappings().all()
            for archive in archives:
                target = {"space": space, "id": archive["id"]}
                connection.execute(text("UPDATE classroom_archives SET deleted_at=now(),source='{}',version='{}' WHERE workspace_id=:space AND id=:id"), target)
                connection.execute(text("DELETE FROM archive_records WHERE workspace_id=:space AND archive_id=:id"), target)
                connection.execute(text("UPDATE authorization_objects SET active=false,revision=revision+1 WHERE workspace_id=:space AND id=:id"), target)
                connection.execute(text("UPDATE transfer_imports SET status='expired' WHERE workspace_id=:space AND id=:id"), {"space": space, "id": archive["import_id"]})
                connection.execute(text("INSERT INTO identity_events(workspace_id,id,actor_id,action,target_id) VALUES(:space,:event,NULL,'archive.expired',:id)"), {**target, "event": uuid4()})
            exports = connection.execute(text("""
              SELECT e.id FROM transfer_exports e LEFT JOIN classrooms c ON c.workspace_id=e.workspace_id AND c.id=e.object_id
              LEFT JOIN classroom_archives a ON a.workspace_id=e.workspace_id AND a.id=e.object_id
              WHERE e.workspace_id=:space AND (e.expires_at<now() OR e.status='invalidated'
                OR e.kind='archive' AND (c.records_deleted_at IS NOT NULL OR a.deleted_at IS NOT NULL))
                AND (e.byte_size>0 OR e.snapshot IS NOT NULL OR e.status IN ('queued','running')) ORDER BY e.id LIMIT 100
            """), {"space": space}).scalars().all()
            for export_id in exports:
                target = {"space": space, "id": export_id}
                connection.execute(text("UPDATE transfer_dispatch SET phase='done',generation=generation+1,lease_until=NULL WHERE workspace_id=:space AND id=:id"), target)
                connection.execute(text("UPDATE transfer_exports SET status='invalidated',snapshot=NULL,error_code='EXPORT_UNAVAILABLE',error_message='资料已删除或导出已过期，文件不可下载。' WHERE workspace_id=:space AND id=:id"), target)
                paths.append((export_id, "transfer_exports"))
            imports = connection.execute(text("SELECT id FROM transfer_imports WHERE workspace_id=:space AND byte_size>0 "
                                              "AND (status='validated' AND expires_at<now() OR status='expired') ORDER BY id LIMIT 100"), {"space": space}).scalars().all()
            for import_id in imports:
                connection.execute(text("UPDATE transfer_imports SET status='expired' WHERE workspace_id=:space AND id=:id"), {"space": space, "id": import_id})
                paths.append((import_id, "transfer_imports"))
        for artifact_id, table in paths:
            artifact_path(settings, space, artifact_id).unlink(missing_ok=True)
            with engine.begin() as connection:
                require_instance(connection)
                set_context(connection, account_id=UUID(int=0), workspace_id=space)
                connection.execute(text("SELECT id FROM workspaces WHERE id=:space FOR UPDATE"), {"space": space})
                connection.execute(text(f"UPDATE {table} SET byte_size=0 WHERE workspace_id=:space AND id=:id AND status=:status"),
                                   {"space": space, "id": artifact_id, "status": "expired" if table == "transfer_imports" else "invalidated"})
            cleaned += 1
    # Uncertain commits retain bytes. Collect only old files with no durable reference, under the same space lock.
    root = settings.file_directory / "transfers"
    if root.is_dir():
        for path in root.glob("*/*.zip"):
            if path.is_symlink() or not path.is_file() or path.stat().st_mtime > time.time() - 86400:
                continue
            try:
                space, artifact_id = UUID(path.parent.name), UUID(path.stem)
            except ValueError:
                continue
            with engine.begin() as connection:
                require_instance(connection)
                set_context(connection, account_id=UUID(int=0), workspace_id=space)
                connection.execute(text("SELECT id FROM workspaces WHERE id=:space FOR UPDATE"), {"space": space})
                referenced = connection.execute(text("SELECT EXISTS(SELECT 1 FROM transfer_exports WHERE workspace_id=:space AND id=:id) "
                                                     "OR EXISTS(SELECT 1 FROM transfer_imports WHERE workspace_id=:space AND id=:id)"), {"space": space, "id": artifact_id}).scalar_one()
                if not referenced:
                    path.unlink(missing_ok=True)
                    cleaned += 1
    return cleaned
