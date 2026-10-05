import base64
import binascii
import json
from typing import Any
from uuid import UUID, uuid4

from openform_contracts.validation import ContractViolation, validate_grading
from sqlalchemy import Connection, Engine, text

from openform.activities.schemas import DraftInput, PublishInput
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import register_object, require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page
from openform.runtime.packages import MAX_PACKAGE_BYTES, prepare_package
from openform.runtime.storage import issue_ticket, store_package


def require_activity(connection: Connection, workspace_id: UUID, activity_id: UUID, *, write: bool = False) -> dict[str, Any]:
    lock = "UPDATE" if write else "SHARE"
    row = connection.execute(text(f"SELECT * FROM activities WHERE workspace_id=:space AND id=:id FOR {lock}"),
                             {"space": workspace_id, "id": activity_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "活动不存在。")
    return dict(row)


def save_draft(engine: Engine, settings: Settings, identity: StaffIdentity, workspace_id: UUID,
               data: DraftInput, activity_id: UUID | None = None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要当前空间的教学权限。")
        if activity_id is not None:
            require_object(connection, identity, workspace, activity_id, "activity", "activity.edit")
    if sum(len(value) for value in data.assets.values()) > 12 * 1024 * 1024:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "页面包超过 8 MiB 资源上限。")
    try:
        assets = {path: base64.b64decode(value, validate=True) for path, value in data.assets.items()}
    except (binascii.Error, ValueError):
        raise ApiError(422, "INVALID_INPUT", "页面包资源编码无效。") from None
    if sum(map(len, assets.values())) > MAX_PACKAGE_BYTES:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "页面包超过 8 MiB 资源上限。")
    package = prepare_package(data.manifest, assets, app_origin=settings.app_origin)
    try:
        validate_grading(package.manifest, data.grading)
    except ContractViolation:
        raise ApiError(422, "INVALID_CONTRACT", "评分标准与已声明题目不匹配。") from None
    target_id = activity_id or uuid4()
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        if activity_id is None:
            if data.expected_revision != 0:
                raise ApiError(409, "REVISION_CONFLICT", "新活动的预期版本必须为零。")
            register_object(connection, identity, workspace, target_id, "activity")
            revision = 1
        else:
            require_object(connection, identity, workspace, target_id, "activity", "activity.edit")
            activity = require_activity(connection, workspace_id, target_id, write=True)
            if activity["draft_revision"] != data.expected_revision:
                raise ApiError(409, "REVISION_CONFLICT", "草稿已更新，请读取当前版本后再修改。")
            revision = activity["draft_revision"] + 1
        store_package(connection, workspace_id, package)
        connection.execute(text("INSERT INTO activity_sources (workspace_id, package_digest, assets) "
                                "VALUES (:space, :digest, CAST(:assets AS jsonb)) ON CONFLICT DO NOTHING"),
                           {"space": workspace_id, "digest": package.digest, "assets": json.dumps(data.assets)})
        values = {"space": workspace_id, "id": target_id, "title": package.manifest["title"], "revision": revision,
                  "manifest": json.dumps(package.manifest, ensure_ascii=False), "grading": json.dumps(data.grading, ensure_ascii=False),
                  "digest": package.digest}
        if activity_id is None:
            connection.execute(text("""
                INSERT INTO activities (workspace_id, id, title, draft_revision, manifest, grading, package_digest)
                VALUES (:space, :id, :title, :revision, CAST(:manifest AS jsonb), CAST(:grading AS jsonb), :digest)
            """), values)
        else:
            connection.execute(text("""
                UPDATE activities SET title=:title, draft_revision=:revision, manifest=CAST(:manifest AS jsonb),
                  grading=CAST(:grading AS jsonb), package_digest=:digest WHERE workspace_id=:space AND id=:id
            """), values)
        _event(connection, workspace_id, identity.account_id, "activity.draft-saved", target_id)
    return {"id": target_id, "draft_revision": revision}


def list_activities(engine: Engine, identity: StaffIdentity, workspace_id: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要当前空间的教学权限。")
        rows = connection.execute(text("""
            SELECT a.id, a.title, a.draft_revision,
              (SELECT max(v.number) FROM activity_versions v WHERE v.workspace_id=a.workspace_id AND v.activity_id=a.id) AS published_number
            FROM activities a JOIN authorization_objects o ON o.workspace_id=a.workspace_id AND o.id=a.id
            LEFT JOIN object_grants g ON g.workspace_id=a.workspace_id AND g.object_id=a.id AND g.account_id=:actor
            WHERE a.workspace_id=:space AND o.active AND (o.owner_id=:actor OR (g.active AND 'activity.read'=ANY(g.capabilities)))
              AND (CAST(:cursor AS uuid) IS NULL OR a.id>CAST(:cursor AS uuid)) ORDER BY a.id LIMIT 51
        """), {"space": workspace_id, "actor": identity.account_id, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def activity_detail(engine: Engine, identity: StaffIdentity, workspace_id: UUID, activity_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, activity_id, "activity", "activity.read")
        activity = require_activity(connection, workspace_id, activity_id)
        versions = connection.execute(text("SELECT id, number, draft_revision, created_at FROM activity_versions "
                                           "WHERE workspace_id=:space AND activity_id=:id ORDER BY number DESC LIMIT 50"),
                                      {"space": workspace_id, "id": activity_id}).mappings().all()
        return {**activity, "versions": [dict(row) for row in versions]}


def start_trial(engine: Engine, settings: Settings, identity: StaffIdentity, workspace_id: UUID,
                activity_id: UUID, expected_revision: int) -> dict[str, Any]:
    trial_id, attempt_id = uuid4(), uuid4()
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, activity_id, "activity", "activity.edit")
        activity = require_activity(connection, workspace_id, activity_id)
        if activity["draft_revision"] != expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "草稿已更新，请刷新后试做当前版本。")
        connection.execute(text("""
            INSERT INTO activity_trials (workspace_id, id, activity_id, account_id, draft_revision, package_digest, manifest, grading)
            SELECT workspace_id, :trial, id, :actor, draft_revision, package_digest, manifest, grading
            FROM activities WHERE workspace_id=:space AND id=:id
        """), {"space": workspace_id, "id": activity_id, "trial": trial_id, "actor": identity.account_id})
        connection.execute(text("""
            INSERT INTO activity_attempts (workspace_id, id, trial_id, actor_kind, actor_id, account_id, number)
            VALUES (:space, :attempt, :trial, 'staff', :actor, :actor, 1)
        """), {"space": workspace_id, "attempt": attempt_id, "trial": trial_id, "actor": identity.account_id})
        return {"trial_id": trial_id, "attempt_id": attempt_id, "workspace_id": workspace_id,
                "runtime_origin": settings.runtime_origin,
                "runtime_url": issue_ticket(connection, workspace_id, activity["package_digest"], runtime_origin=settings.runtime_origin),
                "title": activity["title"], "capabilities": activity["manifest"]["capabilities"]}


def publish(engine: Engine, identity: StaffIdentity, workspace_id: UUID, activity_id: UUID, data: PublishInput) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, activity_id, "activity", "activity.publish")
        activity = require_activity(connection, workspace_id, activity_id, write=True)
        if activity["draft_revision"] != data.expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "草稿已变化，之前的试做证据已失效。")
        proof = connection.execute(text("""
            SELECT t.ready, t.reread_revision, t.draft_revision, t.package_digest, a.revision, a.state
            FROM activity_trials t JOIN activity_attempts a ON a.workspace_id=t.workspace_id AND a.trial_id=t.id
            JOIN activity_submissions s ON s.workspace_id=a.workspace_id AND s.attempt_id=a.id
            WHERE t.workspace_id=:space AND t.id=:trial AND t.activity_id=:activity AND t.account_id=:actor
            FOR SHARE OF t, a
        """), {"space": workspace_id, "trial": data.trial_id, "activity": activity_id, "actor": identity.account_id}).mappings().one_or_none()
        if (proof is None or not proof["ready"] or proof["state"] != "submitted" or proof["reread_revision"] < 1
                or proof["draft_revision"] != activity["draft_revision"] or proof["package_digest"] != activity["package_digest"]):
            raise ApiError(409, "TRIAL_REQUIRED", "请先完成当前草稿的真实保存、读取和提交试做，再确认内容发布。")
        existing = connection.execute(text("SELECT id, number FROM activity_versions WHERE workspace_id=:space "
                                           "AND activity_id=:id AND draft_revision=:revision"),
                                      {"space": workspace_id, "id": activity_id, "revision": data.expected_revision}).mappings().one_or_none()
        if existing:
            return dict(existing)
        version_id = uuid4()
        number = connection.execute(text("SELECT coalesce(max(number),0)+1 FROM activity_versions "
                                         "WHERE workspace_id=:space AND activity_id=:id"),
                                    {"space": workspace_id, "id": activity_id}).scalar_one()
        connection.execute(text("""
            INSERT INTO activity_versions (workspace_id, id, activity_id, number, draft_revision, manifest, grading, package_digest)
            SELECT workspace_id, :version, id, :number, draft_revision, manifest, grading, package_digest
            FROM activities WHERE workspace_id=:space AND id=:activity
        """), {"space": workspace_id, "activity": activity_id, "version": version_id, "number": number})
        _event(connection, workspace_id, identity.account_id, "activity.published", version_id)
        return {"id": version_id, "number": number}
