import hashlib
from pathlib import Path
from typing import Any, Literal, cast
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, text

from openform.classrooms.service import require_classroom
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import ObjectKind, require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page
from openform.identity.schemas import Input
from openform.transfers.archives import require_archive
from openform.transfers.storage import artifact_path


class ExportInput(Input):
    kind: Literal["resource", "archive"]
    object_id: UUID
    request_key: UUID
    version_number: int | None = Field(default=None, ge=1)
    expected_data_epoch: int | None = Field(default=None, ge=0)


PUBLIC_COLUMNS = "id,kind,object_id,status,byte_size,error_code,error_message,created_at,expires_at"


def authorize_source(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], row: dict[str, Any]) -> None:
    kind = source_kind(connection, workspace["id"], row["object_id"])
    if (row["kind"] == "resource" and kind != "activity") or (row["kind"] == "archive" and kind not in {"classroom", "archive"}):
        raise ApiError(422, "INVALID_EXPORT_SCOPE", "包类型与源对象不匹配。")
    require_object(connection, identity, workspace, row["object_id"], kind, "export.create")
    require_object(connection, identity, workspace, row["object_id"], kind, "activity.read" if kind == "activity" else "records.read")
    if kind == "classroom":
        classroom = require_classroom(connection, workspace["id"], row["object_id"])
        if classroom["data_epoch"] != row["data_epoch"]:
            raise ApiError(410, "SOURCE_INVALIDATED", "源课堂资料已变化，原导出文件不可用。")
    elif kind == "archive":
        require_archive(connection, identity, workspace, row["object_id"])


def source_kind(connection: Connection, space: UUID, object_id: UUID) -> ObjectKind:
    kind = connection.execute(text("SELECT kind FROM authorization_objects WHERE workspace_id=:space AND id=:id"), {"space": space, "id": object_id}).scalar_one_or_none()
    if kind is None:
        raise ApiError(404, "NOT_FOUND", "导出源对象不存在。")
    return cast(ObjectKind, kind)


def owned_export(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], export_id: UUID) -> dict[str, Any]:
    row = connection.execute(text("SELECT *,expires_at>now() AS unexpired FROM transfer_exports WHERE workspace_id=:space AND id=:id"),
                             {"space": workspace["id"], "id": export_id}).mappings().one_or_none()
    if row is None or row["requester_id"] != identity.account_id:
        raise ApiError(404, "NOT_FOUND", "导出任务不存在或不可访问。")
    authorize_source(connection, identity, workspace, dict(row))
    return dict(row)


def enqueue_export(engine: Engine, identity: StaffIdentity, space: UUID, data: ExportInput) -> dict[str, Any]:
    digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        existing = connection.execute(text("SELECT id,input_digest FROM transfer_exports WHERE workspace_id=:space AND requester_id=:actor AND request_key=:key"),
                                      {"space": space, "actor": identity.account_id, "key": data.request_key}).mappings().one_or_none()
        if existing:
            if existing["input_digest"] != digest:
                raise ApiError(409, "OPERATION_CONFLICT", "导出操作键已用于另一范围，请恢复原任务。")
            row = owned_export(connection, identity, workspace, existing["id"])
            return {name: row[name] for name in PUBLIC_COLUMNS.split(",")}
        kind = source_kind(connection, space, data.object_id)
        require_object(connection, identity, workspace, data.object_id, kind, "export.create")
        epoch = None
        if data.kind == "archive":
            epoch = require_classroom(connection, space, data.object_id)["data_epoch"] if kind == "classroom" else 0
            if data.expected_data_epoch is None or data.expected_data_epoch != epoch:
                raise ApiError(409, "SOURCE_CHANGED", "请刷新课堂资料代次，再确认导出当前课堂记录。")
        else:
            number = connection.execute(text("SELECT max(number) FROM activity_versions WHERE workspace_id=:space AND activity_id=:id"),
                                        {"space": space, "id": data.object_id}).scalar_one()
            if number is None or data.version_number is not None and data.version_number > number:
                raise ApiError(422, "VERSION_REQUIRED", "请先发布固定版本，或选择已有版本。")
        scope = {"kind": data.kind, "object_id": data.object_id, "data_epoch": epoch}
        authorize_source(connection, identity, workspace, scope)
        queued = connection.execute(text("SELECT count(*) FROM transfer_exports WHERE workspace_id=:space AND status IN ('queued','running')"), {"space": space}).scalar_one()
        if queued >= 20:
            raise ApiError(429, "EXPORT_QUEUE_FULL", "当前空间已有 20 个待处理导出，请等待完成。")
        export_id = uuid4()
        connection.execute(text("""
          INSERT INTO transfer_exports(workspace_id,id,requester_id,auth_epoch,session_digest,request_key,input_digest,kind,object_id,data_epoch,version_number)
          VALUES(:space,:id,:actor,:auth,:session,:key,:digest,:kind,:object,:epoch,:version)
        """), {"space": space, "id": export_id, "actor": identity.account_id, "auth": identity.auth_epoch, "session": identity.session_digest,
               "key": data.request_key, "digest": digest, "kind": data.kind, "object": data.object_id, "epoch": epoch, "version": data.version_number})
        connection.execute(text("INSERT INTO transfer_dispatch(workspace_id,id) VALUES(:space,:id)"), {"space": space, "id": export_id})
        _event(connection, space, identity.account_id, "export.requested", data.object_id)
        return {"id": export_id, "kind": data.kind, "object_id": data.object_id, "status": "queued", "byte_size": 0}


def list_exports(engine: Engine, identity: StaffIdentity, space: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要教学权限。")
        rows = connection.execute(text(f"SELECT {PUBLIC_COLUMNS} FROM transfer_exports WHERE workspace_id=:space AND requester_id=:actor "
                                       "AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT 51"),
                                  {"space": space, "actor": identity.account_id, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def export_detail(engine: Engine, identity: StaffIdentity, space: UUID, export_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        row = owned_export(connection, identity, workspace, export_id)
        return {name: row[name] for name in PUBLIC_COLUMNS.split(",")}


def export_file(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, export_id: UUID) -> Path:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        row = owned_export(connection, identity, workspace, export_id)
        if row["status"] != "succeeded" or not row["unexpired"]:
            raise ApiError(410, "EXPORT_UNAVAILABLE", "导出尚未完成、已失效或已过期，请查看任务状态。")
        path = artifact_path(settings, space, export_id)
        if not path.is_file() or path.stat().st_size != row["byte_size"]:
            raise ApiError(503, "STORAGE_UNAVAILABLE", "导出文件暂不可用，请重新导出。")
        return path
