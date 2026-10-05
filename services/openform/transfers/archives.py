from typing import Any
from uuid import UUID
from zipfile import BadZipFile, ZipFile

from sqlalchemy import Connection, Engine, text

from openform.activities.schemas import DraftInput
from openform.activities.service import prepare_draft, write_draft
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page
from openform.school.lifecycle import DeleteInput
from openform.transfers.storage import artifact_path


def require_archive(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], archive_id: UUID,
                    action: str = "records.read") -> dict[str, Any]:
    require_object(connection, identity, workspace, archive_id, "archive", action)
    row = connection.execute(text("SELECT * FROM classroom_archives WHERE workspace_id=:space AND id=:id"), {"space": workspace["id"], "id": archive_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "历史档案不存在。")
    if row["deleted_at"] is not None:
        raise ApiError(410, "RECORDS_DELETED", "历史档案已删除或保留到期，正文与图片不可读。")
    return dict(row)


def list_archives(engine: Engine, identity: StaffIdentity, space: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "历史档案需要明确教学授权。")
        rows = connection.execute(text("""
          SELECT a.id,a.title,a.source,a.created_at,a.deleted_at,
            (SELECT count(*) FROM archive_records r WHERE r.workspace_id=a.workspace_id AND r.archive_id=a.id) AS record_count
          FROM classroom_archives a JOIN authorization_objects o ON o.workspace_id=a.workspace_id AND o.id=a.id
          LEFT JOIN object_grants g ON g.workspace_id=o.workspace_id AND g.object_id=o.id AND g.account_id=:actor
          WHERE a.workspace_id=:space AND (o.owner_id=:actor OR (o.active AND g.active AND 'records.read'=ANY(g.capabilities)))
            AND (CAST(:cursor AS uuid) IS NULL OR a.id>CAST(:cursor AS uuid)) ORDER BY a.id LIMIT 51
        """), {"space": space, "actor": identity.account_id, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def archive_detail(engine: Engine, identity: StaffIdentity, space: UUID, archive_id: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        archive = require_archive(connection, identity, workspace, archive_id)
        records = connection.execute(text("SELECT id,body FROM archive_records WHERE workspace_id=:space AND archive_id=:id "
                                          "AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT 51"), {"space": space, "id": archive_id, "cursor": cursor}).mappings().all()
        return {"id": archive_id, "title": archive["title"], "source": archive["source"], "version_number": archive["version"]["number"],
                "data_epoch": 0, "read_only": True, "records": _page([dict(row) for row in records])}


def archive_image(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, archive_id: UUID, record_id: UUID, file_id: UUID) -> tuple[bytes, str]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        archive = require_archive(connection, identity, workspace, archive_id)
        body = connection.execute(text("SELECT body FROM archive_records WHERE workspace_id=:space AND archive_id=:archive AND id=:id"), {"space": space, "archive": archive_id, "id": record_id}).scalar_one_or_none()
        image = next((item for item in body["images"] if item["source_file_id"] == str(file_id)), None) if body else None
        if image is None:
            raise ApiError(404, "NOT_FOUND", "此图片不属于指定档案记录。")
        try:
            with ZipFile(artifact_path(settings, space, archive["import_id"])) as package:
                info = package.getinfo(image["path"])
                if info.file_size != image["byte_size"] or info.file_size > 10 * 1024 * 1024:
                    raise ApiError(503, "STORAGE_UNAVAILABLE", "档案图片完整性已变化。")
                return package.read(info), image["media_type"]
        except (OSError, ValueError, KeyError, BadZipFile):
            raise ApiError(503, "STORAGE_UNAVAILABLE", "档案图片存储暂不可用。") from None


def delete_archive(engine: Engine, identity: StaffIdentity, space: UUID, archive_id: UUID, data: DeleteInput) -> None:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        archive = require_archive(connection, identity, workspace, archive_id, "records.delete")
        if not data.confirmed or data.expected_data_epoch != 0:
            raise ApiError(409, "CONFIRMATION_REQUIRED", "请确认删除此历史档案，已下载与备份副本无法自动召回。")
        connection.execute(text("UPDATE classroom_archives SET deleted_at=now(),source='{}',version='{}' WHERE workspace_id=:space AND id=:id"), {"space": space, "id": archive_id})
        connection.execute(text("DELETE FROM archive_records WHERE workspace_id=:space AND archive_id=:id"), {"space": space, "id": archive_id})
        connection.execute(text("UPDATE authorization_objects SET active=false,revision=revision+1 WHERE workspace_id=:space AND id=:id"), {"space": space, "id": archive_id})
        connection.execute(text("UPDATE transfer_imports SET status='expired' WHERE workspace_id=:space AND id=:id"), {"space": space, "id": archive["import_id"]})
        _event(connection, space, identity.account_id, "archive.deleted", archive_id)


def restore_imported_version(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID,
                             activity_id: UUID, number: int, expected_revision: int) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_object(connection, identity, workspace, activity_id, "activity", "activity.edit")
        source = connection.execute(text("SELECT draft FROM imported_resource_versions WHERE workspace_id=:space AND activity_id=:id AND number=:number"), {"space": space, "id": activity_id, "number": number}).scalar_one_or_none()
        if source is None:
            raise ApiError(404, "NOT_FOUND", "来源版本材料不存在。")
    draft = DraftInput.model_validate({**source, "expected_revision": expected_revision})
    package = prepare_draft(settings, draft)
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        return write_draft(connection, identity, workspace, draft, package, activity_id)
