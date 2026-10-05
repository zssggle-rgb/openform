import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from openform.activities.schemas import DraftInput
from openform.activities.service import prepare_draft, require_activity, write_draft
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.schemas import Input


class ImportInput(Input):
    draft: DraftInput
    activity_id: UUID | None = None
    request_key: UUID


def import_page(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, data: ImportInput) -> dict[str, Any]:
    digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要教学权限。")
        if data.activity_id:
            require_object(connection, identity, workspace, data.activity_id, "activity", "activity.edit")
    failure = None
    package = None
    try:
        package = prepare_draft(settings, data.draft)
    except ApiError as error:
        failure = error
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "教学权限已变化。")
        if data.activity_id:
            require_object(connection, identity, workspace, data.activity_id, "activity", "activity.edit")
            require_activity(connection, space, data.activity_id, write=True)
        existing = connection.execute(text("SELECT * FROM authoring_imports WHERE workspace_id=:space AND requester_id=:actor AND request_key=:key"),
                                      {"space": space, "actor": identity.account_id, "key": data.request_key}).mappings().one_or_none()
        if existing:
            if existing["input_digest"] != digest:
                raise ApiError(409, "OPERATION_CONFLICT", "导入操作键已用于其他内容。")
            return {name: existing[name] for name in ("id", "status", "result", "error_code", "error_message")}
        retained = connection.execute(text("SELECT coalesce(sum(pg_column_size(draft)),0) FROM authoring_imports WHERE workspace_id=:space"),
                                      {"space": space}).scalar_one()
        if retained + len(data.draft.model_dump_json().encode()) > 100 * 1024 * 1024:
            raise ApiError(429, "IMPORT_QUOTA_EXCEEDED", "当前空间导入草稿保留量达到 100 MiB，未写入新文件。请保留本地文件并联系管理员。")
        result = None
        if package is not None:
            try:
                result = write_draft(connection, identity, workspace, data.draft, package, data.activity_id)
            except ApiError as error:
                failure = error
        import_id = uuid4()
        connection.execute(text("""
            INSERT INTO authoring_imports(workspace_id,id,requester_id,request_key,input_digest,activity_id,draft,status,result,error_code,error_message)
            VALUES(:space,:id,:actor,:key,:digest,:activity,CAST(:draft AS jsonb),:status,CAST(:result AS jsonb),:code,:message)
        """), {"space": space, "id": import_id, "actor": identity.account_id, "key": data.request_key, "digest": digest,
               "activity": data.activity_id, "draft": data.draft.model_dump_json(), "status": "failed" if failure else "succeeded",
               "result": json.dumps(result, default=str), "code": failure.code if failure else None, "message": failure.message if failure else None})
        return {"id": import_id, "status": "failed" if failure else "succeeded", "result": result,
                "error_code": failure.code if failure else None, "error_message": failure.message if failure else None}


def import_detail(engine: Engine, identity: StaffIdentity, space: UUID, import_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        row = connection.execute(text("SELECT * FROM authoring_imports WHERE workspace_id=:space AND id=:id AND requester_id=:actor"),
                                 {"space": space, "id": import_id, "actor": identity.account_id}).mappings().one_or_none()
        if row is None or not workspace["is_teacher"]:
            raise ApiError(404, "NOT_FOUND", "导入记录不存在或不可访问。")
        if row["activity_id"]:
            require_object(connection, identity, workspace, row["activity_id"], "activity", "activity.edit")
        return {name: row[name] for name in ("id", "draft", "status", "result", "error_code", "error_message")}
