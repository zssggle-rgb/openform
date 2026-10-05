import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, text

from openform.authoring.source import draft_source, model_source
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _page
from openform.identity.schemas import Input
from openform.models.ark import available
from openform.models.prompts import messages


class GenerateInput(Input):
    prompt: str = Field(min_length=1, max_length=8000)
    activity_id: UUID | None = None
    expected_revision: int = Field(default=0, ge=0)
    request_key: UUID


PUBLIC_COLUMNS = "id, activity_id, expected_revision, status, result, usage, error_code, error_message, created_at, updated_at"


def get_owned_job(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], job_id: UUID,
                  *, lock: bool = False) -> dict[str, Any]:
    row = connection.execute(text("SELECT * FROM jobs WHERE workspace_id=:space AND id=:id"),
                             {"space": workspace["id"], "id": job_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "任务不存在。")
    if row["requester_id"] != identity.account_id or not workspace["is_teacher"]:
        raise ApiError(403, "FORBIDDEN", "你没有该任务的访问权限。")
    if row["activity_id"] is not None:
        require_object(connection, identity, workspace, row["activity_id"], "activity", "activity.edit")
    if lock:
        row = connection.execute(text("SELECT * FROM jobs WHERE workspace_id=:space AND id=:id FOR UPDATE"),
                                 {"space": workspace["id"], "id": job_id}).mappings().one()
    return dict(row)


def enqueue(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, data: GenerateInput) -> dict[str, Any]:
    prompt = data.prompt.strip()
    if not prompt:
        raise ApiError(422, "INVALID_INPUT", "请描述教学目标或修改要求。")
    digest = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要当前空间的教学权限。")
        existing = connection.execute(text("SELECT id,input_digest FROM jobs WHERE workspace_id=:space AND requester_id=:actor AND request_key=:key"),
                                      {"space": space, "actor": identity.account_id, "key": data.request_key}).mappings().one_or_none()
        if existing:
            if existing["input_digest"] != digest:
                raise ApiError(409, "OPERATION_CONFLICT", "该任务操作键已用于其他要求，请恢复原任务或重新创建。")
            row = get_owned_job(connection, identity, workspace, existing["id"])
            return {name: row[name] for name in PUBLIC_COLUMNS.split(", ")}
        if not available(settings):
            raise ApiError(503, "MODEL_UNAVAILABLE", "模型服务未配置；仍可手动导入、试做和发布。")
        source = None
        if data.activity_id:
            current = draft_source(connection, identity, workspace, data.activity_id)
            if current["expected_revision"] != data.expected_revision:
                raise ApiError(409, "REVISION_CONFLICT", "草稿已变化，请刷新后再提出修改。")
            source = model_source(current)
        elif data.expected_revision != 0:
            raise ApiError(409, "REVISION_CONFLICT", "新活动的预期版本必须为零。")
        # A UTF-8 byte upper bound conservatively reserves input plus the configured output limit.
        reserve = len(json.dumps(messages(prompt, source), ensure_ascii=False).encode()) + settings.model_max_tokens
        connection.execute(text("INSERT INTO model_usage(workspace_id) VALUES(:space) ON CONFLICT DO NOTHING"), {"space": space})
        usage = connection.execute(text("SELECT * FROM model_usage WHERE workspace_id=:space FOR UPDATE"), {"space": space}).mappings().one()
        existing = connection.execute(text("SELECT id,input_digest FROM jobs WHERE workspace_id=:space AND requester_id=:actor AND request_key=:key"),
                                      {"space": space, "actor": identity.account_id, "key": data.request_key}).mappings().one_or_none()
        if existing:
            if existing["input_digest"] != digest:
                raise ApiError(409, "OPERATION_CONFLICT", "任务操作键已用于其他要求。")
            row = get_owned_job(connection, identity, workspace, existing["id"])
            return {name: row[name] for name in PUBLIC_COLUMNS.split(", ")}
        if usage["reserved_tokens"] + usage["used_tokens"] + reserve > settings.workspace_model_token_quota:
            raise ApiError(429, "MODEL_QUOTA_EXCEEDED", "当前空间模型额度不足。已发布课堂仍可继续使用。")
        queued = connection.execute(text("SELECT count(*) FROM jobs WHERE workspace_id=:space AND status IN ('queued','running')"), {"space": space}).scalar_one()
        if queued >= 20:
            raise ApiError(429, "MODEL_QUEUE_FULL", "当前空间有 20 个待处理任务，请等任务完成后再生成。")
        job_id = uuid4()
        connection.execute(text("UPDATE model_usage SET reserved_tokens=reserved_tokens+:reserve WHERE workspace_id=:space"), {"space": space, "reserve": reserve})
        connection.execute(text("""
            INSERT INTO jobs(workspace_id,id,requester_id,auth_epoch,session_digest,activity_id,expected_revision,
              request_key,input_digest,prompt,source,reserved_tokens)
            VALUES(:space,:id,:actor,:epoch,:session,:activity,:revision,:key,:digest,:prompt,CAST(:source AS jsonb),:reserve)
        """), {"space": space, "id": job_id, "actor": identity.account_id, "epoch": identity.auth_epoch, "session": identity.session_digest,
               "activity": data.activity_id, "revision": data.expected_revision, "key": data.request_key, "digest": digest,
               "prompt": prompt, "source": json.dumps(source, ensure_ascii=False), "reserve": reserve})
        connection.execute(text("INSERT INTO job_dispatch(workspace_id,id) VALUES(:space,:id)"), {"space": space, "id": job_id})
        return {"id": job_id, "status": "queued", "result": None}


def list_jobs(engine: Engine, identity: StaffIdentity, space: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        if not workspace["is_teacher"]:
            raise ApiError(403, "FORBIDDEN", "需要当前空间的教学权限。")
        rows = connection.execute(text(f"""
            SELECT {', '.join('j.' + column for column in PUBLIC_COLUMNS.split(', '))} FROM jobs j
            WHERE j.workspace_id=:space AND j.requester_id=:actor
              AND (CAST(:cursor AS uuid) IS NULL OR j.id>CAST(:cursor AS uuid))
              AND (j.activity_id IS NULL OR EXISTS(SELECT 1 FROM authorization_objects o
                LEFT JOIN object_grants g ON g.workspace_id=o.workspace_id AND g.object_id=o.id AND g.account_id=:actor
                WHERE o.workspace_id=j.workspace_id AND o.id=j.activity_id AND o.active
                  AND (o.owner_id=:actor OR (g.active AND 'activity.edit'=ANY(g.capabilities)))))
            ORDER BY j.id LIMIT 51
        """), {"space": space, "actor": identity.account_id, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def job_detail(engine: Engine, identity: StaffIdentity, space: UUID, job_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        row = get_owned_job(connection, identity, workspace, job_id)
        return {name: row[name] for name in (*PUBLIC_COLUMNS.split(", "), "prompt", "raw_output")}


def settle(connection: Connection, row: dict[str, Any], usage: dict[str, int], *, unknown: bool) -> None:
    if row["settled"] or unknown:
        return
    # Missing usage is charged at the reservation upper bound, never silently counted as zero.
    charged = usage.get("total_tokens", row["reserved_tokens"] if usage else 0)
    connection.execute(text("UPDATE model_usage SET reserved_tokens=reserved_tokens-:reserve, used_tokens=used_tokens+:charged "
                            "WHERE workspace_id=:space"), {"space": row["workspace_id"], "reserve": row["reserved_tokens"], "charged": charged})
    connection.execute(text("UPDATE jobs SET settled=true WHERE workspace_id=:space AND id=:id"), {"space": row["workspace_id"], "id": row["id"]})
