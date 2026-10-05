import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, text

from openform.activities.service import prepare_draft, write_draft
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import register_object, require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page
from openform.identity.schemas import Input
from openform.transfers.packages import Package, read_package
from openform.transfers.storage import artifact_path, persist_file, require_capacity


class CommitInput(Input):
    confirmed: bool
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_number: int | None = Field(default=None, ge=1)


def _summary(package: Package) -> dict[str, Any]:
    return {"format": package.format, "title": package.title, "source": package.source.model_dump(mode="json"),
            "versions": [{"number": item.number, "title": item.draft.manifest["title"]} for item in package.versions],
            "record_count": len(package.records), "image_count": sum(len(record.images) for record in package.records),
            "effect": "创建独立草稿；保留来源版本材料，重新试做后才能发布。" if package.format == "openform.resource/1"
                      else "创建只读历史档案；不关联当前学生、不开课、不纳入当前统计。",
            "credentials_imported": False}


def preflight_import(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, path: Path, request_key: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (_, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要目标空间的教学权限才能导入。")
    package = read_package(path, settings)
    summary = _summary(package)
    import_id = uuid4()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "目标空间教学权限已变化，未保留导入包。")
        existing = connection.execute(text("SELECT id,digest,status,summary,result_id,expires_at FROM transfer_imports WHERE workspace_id=:space AND requester_id=:actor AND request_key=:key"),
                                      {"space": space, "actor": identity.account_id, "key": request_key}).mappings().one_or_none()
        if existing:
            if existing["digest"] != digest:
                raise ApiError(409, "OPERATION_CONFLICT", "此上传操作键已用于另一迁移包，请恢复原预检。")
            if existing["result_id"]:
                require_object(connection, identity, workspace, existing["result_id"], "activity" if package.format == "openform.resource/1" else "archive", "activity.read" if package.format == "openform.resource/1" else "records.read")
            return dict(existing)
        pending = connection.execute(text("SELECT count(*) FROM transfer_imports WHERE workspace_id=:space AND requester_id=:actor AND status='validated' AND expires_at>now()"), {"space": space, "actor": identity.account_id}).scalar_one()
        if pending >= 10:
            raise ApiError(429, "IMPORT_QUEUE_FULL", "已有 10 个未确认迁移包，请先确认或等待其过期。")
        require_capacity(connection, settings, space, path.stat().st_size)
        size, digest = persist_file(path, artifact_path(settings, space, import_id))
        connection.execute(text("""
          INSERT INTO transfer_imports(workspace_id,id,requester_id,kind,title,digest,byte_size,summary,request_key)
          VALUES(:space,:id,:actor,:kind,:title,:digest,:size,CAST(:summary AS jsonb),:key)
        """), {"space": space, "id": import_id, "actor": identity.account_id, "kind": "resource" if package.format == "openform.resource/1" else "archive",
               "title": package.title, "digest": digest, "size": size, "summary": json.dumps(summary, ensure_ascii=False), "key": request_key})
        return {"id": import_id, "status": "validated", "digest": digest, "summary": summary, "result_id": None}


def _owned(connection: Connection, identity: StaffIdentity, space: UUID, import_id: UUID) -> dict[str, Any]:
    row = connection.execute(text("SELECT *,expires_at>now() AS unexpired FROM transfer_imports WHERE workspace_id=:space AND id=:id AND requester_id=:actor"),
                             {"space": space, "id": import_id, "actor": identity.account_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "导入预检不存在或不可访问。")
    return dict(row)


def import_detail(engine: Engine, identity: StaffIdentity, space: UUID, import_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        row = _owned(connection, identity, space, import_id)
        if row["status"] == "committed":
            require_object(connection, identity, workspace, row["result_id"], "activity" if row["kind"] == "resource" else "archive", "activity.read" if row["kind"] == "resource" else "records.read")
        return {name: row[name] for name in ("id", "status", "digest", "summary", "result_id", "expires_at")}


def commit_import(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, import_id: UUID, data: CommitInput) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要目标空间教学权限。")
        row = _owned(connection, identity, space, import_id)
        if row["status"] == "committed":
            desired = data.version_number or max(version["number"] for version in row["summary"]["versions"])
            if data.digest != row["digest"] or desired != row["chosen_version"]:
                raise ApiError(409, "OPERATION_CONFLICT", "预检校验值不符，不能替换原导入。")
            require_object(connection, identity, workspace, row["result_id"], "activity" if row["kind"] == "resource" else "archive", "activity.read" if row["kind"] == "resource" else "records.read")
            return {"id": row["result_id"], "kind": row["kind"], "status": "committed"}
        if not row["unexpired"] or row["status"] != "validated" or data.digest != row["digest"] or not data.confirmed:
            raise ApiError(409, "IMPORT_CONFIRMATION_REQUIRED", "请核对当前预检并明确确认；预检已过期时重新上传。")
    path = artifact_path(settings, space, import_id)
    try:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != data.digest:
                raise ApiError(409, "SOURCE_CHANGED", "预检文件完整性已变化，未导入。")
    except OSError:
        raise ApiError(410, "IMPORT_EXPIRED", "预检暂存文件已过期或暂不可用，请重新上传。") from None
    package = read_package(path, settings)
    selected = next((item for item in package.versions if item.number == (data.version_number or max(version.number for version in package.versions))), None)
    if selected is None:
        raise ApiError(422, "INVALID_VERSION", "所选版本不属于当前预检包。")
    draft = selected.draft.model_copy(update={"expected_revision": 0})
    prepared = prepare_draft(settings, draft) if row["kind"] == "resource" else None
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        row = _owned(connection, identity, space, import_id)
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "目标空间教学权限已变化。")
        if row["status"] == "committed":
            if selected.number != row["chosen_version"]:
                raise ApiError(409, "OPERATION_CONFLICT", "此预检已按另一版本完成导入，请重新上传。")
            require_object(connection, identity, workspace, row["result_id"], "activity" if row["kind"] == "resource" else "archive", "activity.read" if row["kind"] == "resource" else "records.read")
            return {"id": row["result_id"], "kind": row["kind"], "status": "committed"}
        if row["status"] != "validated" or not row["unexpired"] or row["digest"] != data.digest:
            raise ApiError(409, "SOURCE_CHANGED", "预检已变化或到期，未公开新活动或档案。")
        body_size = len(package.model_dump_json().encode())
        require_capacity(connection, settings, space, body_size)
        if prepared is not None:
            result = write_draft(connection, identity, workspace, draft, prepared)
            result_id = result["id"]
            for version in package.versions:
                connection.execute(text("INSERT INTO imported_resource_versions(workspace_id,activity_id,number,source,draft) VALUES(:space,:id,:number,CAST(:source AS jsonb),CAST(:draft AS jsonb))"),
                                   {"space": space, "id": result_id, "number": version.number, "source": package.source.model_dump_json(), "draft": version.draft.model_dump_json()})
        else:
            result_id = uuid4()
            register_object(connection, identity, workspace, result_id, "archive")
            connection.execute(text("INSERT INTO classroom_archives(workspace_id,id,title,source,version,import_id) VALUES(:space,:id,:title,CAST(:source AS jsonb),CAST(:version AS jsonb),:import)"),
                               {"space": space, "id": result_id, "title": package.title, "source": package.source.model_dump_json(), "version": selected.model_dump_json(), "import": import_id})
            for record in package.records:
                connection.execute(text("INSERT INTO archive_records(workspace_id,id,archive_id,body) VALUES(:space,:id,:archive,CAST(:body AS jsonb))"),
                                   {"space": space, "id": uuid4(), "archive": result_id, "body": record.model_dump_json()})
        connection.execute(text("UPDATE transfer_imports SET status='committed',result_id=:result,chosen_version=:version WHERE workspace_id=:space AND id=:id"), {"space": space, "id": import_id, "result": result_id, "version": selected.number})
        _event(connection, space, identity.account_id, "transfer.imported", result_id)
        return {"id": result_id, "kind": row["kind"], "status": "committed"}


def imported_versions(engine: Engine, identity: StaffIdentity, space: UUID, activity_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_object(connection, identity, workspace, activity_id, "activity", "activity.read")
        rows = connection.execute(text("SELECT number,source,draft->'manifest'->>'title' AS title FROM imported_resource_versions WHERE workspace_id=:space AND activity_id=:id ORDER BY number"), {"space": space, "id": activity_id}).mappings().all()
        return {"items": [dict(row) for row in rows]}


def list_imports(engine: Engine, identity: StaffIdentity, space: UUID, cursor: UUID | None, request_key: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要目标空间教学权限。")
        rows = connection.execute(text("""
          SELECT id,request_key,kind,title,status,digest,summary,result_id,expires_at FROM transfer_imports
          WHERE workspace_id=:space AND requester_id=:actor
            AND (CAST(:key AS uuid) IS NULL OR request_key=:key)
            AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT 51
        """), {"space": space, "actor": identity.account_id, "cursor": cursor, "key": request_key}).mappings().all()
        return _page([dict(row) for row in rows])
