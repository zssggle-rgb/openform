import os
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from openform.assets.storage import file_path
from openform.classrooms.records import Actor, _writable, record_transaction
from openform.config import Settings
from openform.errors import ApiError


def image_metadata(connection: Connection, workspace_id: UUID, attempt_id: UUID, file_id: UUID, *, write: bool = False) -> dict[str, Any]:
    row = connection.execute(text("SELECT *, expires_at>now() AS unexpired FROM image_assets "
                                  "WHERE workspace_id=:space AND attempt_id=:attempt AND id=:id FOR " + ("UPDATE" if write else "SHARE")),
                             {"space": workspace_id, "attempt": attempt_id, "id": file_id}).mappings().one_or_none()
    if row is None or row["status"] == "deleted":
        raise ApiError(404, "NOT_FOUND", "该图片不属于当前尝试，或已删除。")
    return dict(row)


def begin_upload(engine: Engine, identity: Actor, attempt_id: UUID, file_id: UUID, workspace_id: UUID | None) -> None:
    with record_transaction(engine, identity, attempt_id, workspace_id) as (connection, _, attempt, context):
        _writable(connection, attempt, context)
        asset = image_metadata(connection, attempt["workspace_id"], attempt_id, file_id)
        if asset["status"] == "pending" and not asset["unexpired"]:
            raise ApiError(409, "UPLOAD_EXPIRED", "上传入口已过期，请重新选择图片。")


def finish_upload(engine: Engine, settings: Settings, identity: Actor, attempt_id: UUID, file_id: UUID,
                  normalized: Path, media_type: str, byte_size: int, digest: str, workspace_id: UUID | None) -> dict[str, Any]:
    # A lost commit response is uncertain: never delete potentially committed bytes on failure.
    # Expired unreferenced reservations are collected by the lifecycle job.
    with record_transaction(engine, identity, attempt_id, workspace_id) as (connection, _, attempt, context):
        _writable(connection, attempt, context)
        space = attempt["workspace_id"]
        asset = image_metadata(connection, space, attempt_id, file_id, write=True)
        if asset["status"] == "ready":
            if asset["digest"] != digest:
                raise ApiError(409, "UPLOAD_CONFLICT", "该文件标识已经接收另一张图片，不能覆盖。")
            return {"fileId": str(file_id), "status": "ready", "mediaType": asset["media_type"], "bytes": asset["byte_size"]}
        if not asset["unexpired"]:
            raise ApiError(409, "UPLOAD_EXPIRED", "上传入口已过期，本次未附加图片。")
        connection.execute(text("INSERT INTO image_usage(workspace_id) VALUES(:space) ON CONFLICT DO NOTHING"), {"space": space})
        used = connection.execute(text("SELECT byte_size FROM image_usage WHERE workspace_id=:space FOR UPDATE"), {"space": space}).scalar_one()
        if used + byte_size > settings.workspace_file_quota:
            raise ApiError(507, "STORAGE_FULL", "当前空间图片额度不足，本次图片未接收。")
        destination = file_path(settings, space, file_id)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Pending rows can have orphaned bytes after a previous transaction failed.
        destination.unlink(missing_ok=True)
        os.link(normalized, destination)
        # Persist the link and both newly created directory entries before receipt.
        for directory in (destination.parent, destination.parent.parent, settings.file_directory):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        connection.execute(text("UPDATE image_assets SET status='ready', media_type=:type, byte_size=:size, digest=:digest "
                                "WHERE workspace_id=:space AND id=:id"),
                           {"space": space, "id": file_id, "type": media_type, "size": byte_size, "digest": digest})
        connection.execute(text("UPDATE image_usage SET byte_size=byte_size+:size WHERE workspace_id=:space"), {"space": space, "size": byte_size})
    return {"fileId": str(file_id), "status": "ready", "mediaType": media_type, "bytes": byte_size}


def own_image(engine: Engine, settings: Settings, identity: Actor, attempt_id: UUID, file_id: UUID,
              workspace_id: UUID | None) -> tuple[Path, str]:
    with record_transaction(engine, identity, attempt_id, workspace_id) as (connection, _, attempt, _):
        asset = image_metadata(connection, attempt["workspace_id"], attempt_id, file_id)
        path = file_path(settings, attempt["workspace_id"], file_id)
        if asset["status"] != "ready" or not path.is_file() or path.stat().st_size != asset["byte_size"]:
            raise ApiError(503, "STORAGE_UNAVAILABLE", "图片尚未完整持久化或存储暂不可用，请重试。")
        return path, asset["media_type"]


def remove_unused(engine: Engine, settings: Settings, identity: Actor, attempt_id: UUID, file_id: UUID,
                  workspace_id: UUID | None) -> None:
    with record_transaction(engine, identity, attempt_id, workspace_id) as (connection, _, attempt, context):
        _writable(connection, attempt, context)
        asset = image_metadata(connection, attempt["workspace_id"], attempt_id, file_id, write=True)
        referenced = connection.execute(text("SELECT EXISTS(SELECT 1 FROM image_references WHERE workspace_id=:space AND file_id=:id)"),
                                        {"space": attempt["workspace_id"], "id": file_id}).scalar_one()
        if referenced:
            raise ApiError(409, "FILE_REFERENCED", "图片仍在当前进度或最终提交中使用，不能直接删除。")
        path = file_path(settings, attempt["workspace_id"], file_id)
        connection.execute(text("UPDATE image_assets SET status='deleted' WHERE workspace_id=:space AND id=:id"),
                           {"space": attempt["workspace_id"], "id": file_id})
        if asset["status"] == "ready":
            connection.execute(text("UPDATE image_usage SET byte_size=byte_size-:size WHERE workspace_id=:space"),
                               {"space": attempt["workspace_id"], "size": asset["byte_size"]})
    path.unlink(missing_ok=True)
