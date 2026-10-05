from typing import Any
from uuid import UUID

from sqlalchemy import Connection, Engine, text

from openform.activities.schemas import DraftInput
from openform.activities.service import prepare_draft, write_draft
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page
from openform.library.schemas import CopyInput, PublicationInput
from openform.runtime.storage import issue_ticket


def require_library(workspace: dict[str, Any], *, copy: bool = False) -> None:
    if workspace["kind"] != "campus" or not (workspace["is_teacher"] or not copy and workspace["is_admin"]):
        raise ApiError(403, "FORBIDDEN", "校内资源仅对当前学校的有效教师开放，资源管理另需管理员职责。")


def _resource(connection: Connection, space: UUID, resource_id: UUID) -> dict[str, Any]:
    row = connection.execute(text("SELECT * FROM library_resources WHERE workspace_id=:space AND id=:id FOR SHARE"),
                             {"space": space, "id": resource_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "校内资源不存在。")
    return dict(row)


def publication_state(engine: Engine, identity: StaffIdentity, space: UUID, activity_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_library(workspace, copy=True)
        require_object(connection, identity, workspace, activity_id, "activity", "resource.publish")
        row = connection.execute(text("SELECT revision,active FROM library_resources WHERE workspace_id=:space AND id=:id"),
                                 {"space": space, "id": activity_id}).mappings().one_or_none()
        versions = connection.execute(text("SELECT source_version_id AS id,subject,grade FROM library_versions "
                                           "WHERE workspace_id=:space AND resource_id=:id ORDER BY number DESC LIMIT 100"),
                                      {"space": space, "id": activity_id}).mappings().all()
        return {**(dict(row) if row else {"revision": 0, "active": False}), "versions": [dict(version) for version in versions]}


def publish_resource(engine: Engine, identity: StaffIdentity, space: UUID, activity_id: UUID, data: PublicationInput) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        require_library(workspace, copy=True)
        require_object(connection, identity, workspace, activity_id, "activity", "resource.publish")
        version = connection.execute(text("SELECT number FROM activity_versions WHERE workspace_id=:space AND id=:version AND activity_id=:id"),
                                     {"space": space, "version": data.version_id, "id": activity_id}).scalar_one_or_none()
        if version is None:
            raise ApiError(422, "PUBLISHED_VERSION_REQUIRED", "请选择已真实试做并发布的固定版本，不能发布未验证草稿。")
        row = connection.execute(text("SELECT * FROM library_resources WHERE workspace_id=:space AND id=:id FOR UPDATE"),
                                 {"space": space, "id": activity_id}).mappings().one_or_none()
        if (row["revision"] if row else 0) != data.expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "资源发布状态已变化，请刷新后操作。")
        tags = connection.execute(text("SELECT subject,grade FROM library_versions WHERE workspace_id=:space AND resource_id=:id AND number=:number"),
                                  {"space": space, "id": activity_id, "number": version}).mappings().one_or_none()
        if tags and (tags["subject"] != data.subject.strip() or tags["grade"] != data.grade.strip()):
            raise ApiError(422, "IMMUTABLE_VERSION", "该固定版本标签已保存，不能覆盖；请发布新固定版本后填写新标签。")
        if row is None:
            connection.execute(text("INSERT INTO library_resources(workspace_id,id,publisher_id) VALUES(:space,:id,:actor)"),
                               {"space": space, "id": activity_id, "actor": identity.account_id})
            revision = 1
        else:
            revision = row["revision"] + 1
            connection.execute(text("UPDATE library_resources SET active=true,revision=:revision,publisher_id=:actor WHERE workspace_id=:space AND id=:id"),
                               {"space": space, "id": activity_id, "actor": identity.account_id, "revision": revision})
        connection.execute(text("""
            INSERT INTO library_versions(workspace_id,resource_id,number,source_version_id,publisher_id,subject,grade)
            VALUES(:space,:id,:number,:version,:actor,:subject,:grade) ON CONFLICT(workspace_id,resource_id,number) DO NOTHING
        """), {"space": space, "id": activity_id, "number": version, "version": data.version_id, "actor": identity.account_id, "subject": data.subject.strip(), "grade": data.grade.strip()})
        _event(connection, space, identity.account_id, "resource.published", activity_id)
        return {"id": activity_id, "number": version, "revision": revision}


def list_resources(engine: Engine, identity: StaffIdentity, space: UUID, cursor: UUID | None,
                   query: str, subject: str, grade: str) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_library(workspace)
        pattern = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        rows = connection.execute(text("""
            SELECT r.id,r.revision,r.active,r.publisher_id,a.display_name AS publisher,
              v.number,v.subject,v.grade,p.manifest->>'title' AS title,p.manifest->>'objective' AS objective
            FROM library_resources r JOIN accounts a ON a.id=r.publisher_id
            JOIN library_versions v ON v.workspace_id=r.workspace_id AND v.resource_id=r.id
            JOIN activity_versions p ON p.workspace_id=v.workspace_id AND p.id=v.source_version_id
            WHERE r.workspace_id=:space AND (r.active OR :admin)
              AND v.number=(SELECT max(latest.number) FROM library_versions latest WHERE latest.workspace_id=r.workspace_id AND latest.resource_id=r.id)
              AND (CAST(:cursor AS uuid) IS NULL OR r.id>CAST(:cursor AS uuid)) AND p.manifest->>'title' ILIKE :pattern
              AND (:subject='' OR v.subject=:subject) AND (:grade='' OR v.grade=:grade) ORDER BY r.id LIMIT 51
        """), {"space": space, "cursor": cursor, "admin": workspace["is_admin"], "pattern": pattern, "subject": subject.strip(), "grade": grade.strip()}).mappings().all()
        return _page([dict(row) for row in rows])


def resource_detail(engine: Engine, identity: StaffIdentity, space: UUID, resource_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_library(workspace)
        resource = _resource(connection, space, resource_id)
        if not resource["active"] and not workspace["is_admin"] and resource["publisher_id"] != identity.account_id:
            raise ApiError(404, "NOT_FOUND", "资源已撤回，已有副本仍可使用。")
        versions = connection.execute(text("""
            SELECT v.number,v.subject,v.grade,v.created_at,p.manifest,p.grading,v.publisher_id
            FROM library_versions v JOIN activity_versions p ON p.workspace_id=v.workspace_id AND p.id=v.source_version_id
            WHERE v.workspace_id=:space AND v.resource_id=:id ORDER BY v.number DESC LIMIT 100
        """), {"space": space, "id": resource_id}).mappings().all()
        return {**resource, "can_withdraw": workspace["is_admin"] or resource["publisher_id"] == identity.account_id,
                "versions": [dict(row) for row in versions]}


def withdraw(engine: Engine, identity: StaffIdentity, space: UUID, resource_id: UUID, revision: int) -> None:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        require_library(workspace)
        resource = _resource(connection, space, resource_id)
        if not workspace["is_admin"] and resource["publisher_id"] != identity.account_id:
            raise ApiError(403, "FORBIDDEN", "只有发布者或学校资源管理员可撤回。")
        if resource["revision"] != revision:
            raise ApiError(409, "REVISION_CONFLICT", "资源状态已变化，请刷新后操作。")
        connection.execute(text("UPDATE library_resources SET active=false,revision=revision+1 WHERE workspace_id=:space AND id=:id"),
                           {"space": space, "id": resource_id})
        _event(connection, space, identity.account_id, "resource.withdrawn", resource_id)


def _copied(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], resource_id: UUID, data: CopyInput) -> dict[str, Any] | None:
    existing = connection.execute(text("SELECT * FROM resource_copies WHERE workspace_id=:space AND requester_id=:actor AND request_key=:key"),
                                  {"space": workspace["id"], "actor": identity.account_id, "key": data.request_key}).mappings().one_or_none()
    if existing:
        if existing["resource_id"] != resource_id or existing["number"] != data.number:
            raise ApiError(409, "OPERATION_CONFLICT", "复制操作键已用于其他资源。")
        require_object(connection, identity, workspace, existing["activity_id"], "activity", "activity.read")
        return {"id": existing["activity_id"], "draft_revision": 1}
    return None


def preview(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, resource_id: UUID, number: int) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_library(workspace)
        if not _resource(connection, space, resource_id)["active"]:
            raise ApiError(409, "RESOURCE_WITHDRAWN", "资源已撤回，不能新预览。")
        source = connection.execute(text("""
            SELECT p.manifest,p.package_digest FROM library_versions v JOIN activity_versions p
            ON p.workspace_id=v.workspace_id AND p.id=v.source_version_id
            WHERE v.workspace_id=:space AND v.resource_id=:id AND v.number=:number
        """), {"space": space, "id": resource_id, "number": number}).mappings().one_or_none()
        if source is None:
            raise ApiError(404, "NOT_FOUND", "资源固定版本不存在。")
        return {"runtime_origin": settings.runtime_origin, "title": source["manifest"]["title"],
                "capabilities": source["manifest"]["capabilities"],
                "runtime_url": issue_ticket(connection, space, source["package_digest"], runtime_origin=settings.runtime_origin)}


def copy_resource(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, resource_id: UUID, data: CopyInput) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_library(workspace, copy=True)
        existing = _copied(connection, identity, workspace, resource_id, data)
        if existing:
            return existing
        resource = _resource(connection, space, resource_id)
        if not resource["active"]:
            raise ApiError(409, "RESOURCE_WITHDRAWN", "资源已撤回，不能新复制；已有副本不受影响。")
        source = connection.execute(text("""
            SELECT p.manifest,p.grading,s.assets FROM library_versions v
            JOIN activity_versions p ON p.workspace_id=v.workspace_id AND p.id=v.source_version_id
            JOIN activity_sources s ON s.workspace_id=p.workspace_id AND s.package_digest=p.package_digest
            WHERE v.workspace_id=:space AND v.resource_id=:id AND v.number=:number
        """), {"space": space, "id": resource_id, "number": data.number}).mappings().one_or_none()
        if source is None:
            raise ApiError(404, "NOT_FOUND", "所选资源固定版本不存在。")
        draft = DraftInput(manifest=source["manifest"], grading=source["grading"], assets=source["assets"], expected_revision=0)
    package = prepare_draft(settings, draft)
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        require_library(workspace, copy=True)
        existing = _copied(connection, identity, workspace, resource_id, data)
        if existing:
            return existing
        if not _resource(connection, space, resource_id)["active"]:
            raise ApiError(409, "RESOURCE_WITHDRAWN", "资源已撤回，不能新复制。")
        result = write_draft(connection, identity, workspace, draft, package)
        connection.execute(text("INSERT INTO resource_copies(workspace_id,activity_id,requester_id,request_key,resource_id,number) "
                                "VALUES(:space,:activity,:actor,:key,:resource,:number)"),
                           {"space": space, "activity": result["id"], "actor": identity.account_id, "key": data.request_key, "resource": resource_id, "number": data.number})
        _event(connection, space, identity.account_id, "resource.copied", resource_id)
        return result
