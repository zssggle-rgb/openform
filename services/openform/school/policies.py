from typing import Any
from uuid import UUID

from pydantic import Field
from sqlalchemy import Connection, Engine, text

from openform.config import Settings
from openform.errors import ApiError
from openform.identity.context import StaffIdentity, require_admin, workspace_transaction
from openform.identity.roster import _event, _page
from openform.identity.schemas import Input
from openform.models.ark import available


class PolicyInput(Input):
    expected_revision: int = Field(ge=0)
    retention_days: int = Field(ge=1, le=3650)
    model_token_limit: int = Field(ge=0)
    image_byte_limit: int = Field(ge=0)
    generation_enabled: bool
    analysis_enabled: bool


def effective_policy(connection: Connection, settings: Settings, space: UUID) -> dict[str, Any]:
    row = connection.execute(text("SELECT * FROM workspace_policies WHERE workspace_id=:space"), {"space": space}).mappings().one_or_none()
    policy: dict[str, Any] = dict(row) if row else {"workspace_id": space, "revision": 0, "retention_days": settings.record_retention_days,
                                   "model_token_limit": settings.workspace_model_token_quota, "image_byte_limit": settings.workspace_file_quota,
                                   "generation_enabled": True, "analysis_enabled": True}
    policy["model_token_limit"] = min(policy["model_token_limit"], settings.workspace_model_token_quota)
    policy["image_byte_limit"] = min(policy["image_byte_limit"], settings.workspace_file_quota)
    return policy


def require_model_policy(connection: Connection, settings: Settings, space: UUID, kind: str) -> dict[str, Any]:
    policy = effective_policy(connection, settings, space)
    if not policy["analysis_enabled" if kind == "analysis" else "generation_enabled"]:
        raise ApiError(503, "MODEL_DISABLED", "当前空间已暂停此类模型任务；已发布课堂仍可继续使用。")
    return policy


def policy_detail(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, _):
        return effective_policy(connection, settings, space)


def change_policy(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID, data: PolicyInput) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        require_admin(workspace)
        policy = effective_policy(connection, settings, space)
        if data.expected_revision != policy["revision"]:
            raise ApiError(409, "REVISION_CONFLICT", "空间配置已变化，请刷新后重试。")
        if data.model_token_limit > settings.workspace_model_token_quota or data.image_byte_limit > settings.workspace_file_quota:
            raise ApiError(422, "POLICY_LIMIT_EXCEEDED", "学校额度不能超过实例已配置的上限。")
        connection.execute(text("""
          INSERT INTO workspace_policies(workspace_id,retention_days,model_token_limit,image_byte_limit,generation_enabled,analysis_enabled)
          VALUES(:space,:retention_days,:model_token_limit,:image_byte_limit,:generation_enabled,:analysis_enabled)
          ON CONFLICT(workspace_id) DO UPDATE SET revision=workspace_policies.revision+1,
            retention_days=EXCLUDED.retention_days,model_token_limit=EXCLUDED.model_token_limit,
            image_byte_limit=EXCLUDED.image_byte_limit,generation_enabled=EXCLUDED.generation_enabled,analysis_enabled=EXCLUDED.analysis_enabled
        """), {"space": space, **data.model_dump()})
        _event(connection, space, identity.account_id, "workspace.policy-changed", space)
        return effective_policy(connection, settings, space)


def workspace_status(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_admin(workspace)
        usage = connection.execute(text("SELECT reserved_tokens,used_tokens FROM model_usage WHERE workspace_id=:space"), {"space": space}).mappings().one_or_none()
        images = connection.execute(text("SELECT byte_size FROM image_usage WHERE workspace_id=:space"), {"space": space}).scalar_one_or_none()
        jobs = connection.execute(text("SELECT status,count(*) AS count FROM jobs WHERE workspace_id=:space GROUP BY status"), {"space": space}).mappings().all()
        pending = connection.execute(text("SELECT count(*) FROM classrooms WHERE workspace_id=:space AND records_deleted_at IS NOT NULL AND records_cleaned_at IS NULL"), {"space": space}).scalar_one()
        backup = connection.execute(text("SELECT backup->>'snapshot_at' AS time,backup->>'local_verified' AS local,"
                                         "backup->>'offsite_verified' AS offsite FROM instance_state WHERE id=true")).mappings().one()
        backup_status = (f"最近备份时间点 {backup['time']}；本机已核验，实例外副本"
                         + ("已确认。" if backup["offsite"] == "true" else "尚未确认。")) if backup["local"] == "true" else "由实例运维管理；尚无已核验备份。"
        return {"policy": effective_policy(connection, settings, space), "model_configured": available(settings),
                "model_id": settings.model_id, "model_usage": dict(usage) if usage else {"reserved_tokens": 0, "used_tokens": 0},
                "image_bytes": images or 0, "jobs": [dict(row) for row in jobs], "pending_record_cleanup": pending,
                "instance_model_token_limit": settings.workspace_model_token_quota, "instance_image_byte_limit": settings.workspace_file_quota,
                "backup_status": backup_status}


def list_events(engine: Engine, identity: StaffIdentity, space: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_admin(workspace)
        rows = connection.execute(text("""
          SELECT e.id,e.action,e.target_id,e.created_at,a.display_name AS actor_name
          FROM identity_events e LEFT JOIN accounts a ON a.id=e.actor_id
          WHERE e.workspace_id=:space AND (CAST(:cursor AS uuid) IS NULL OR e.id>CAST(:cursor AS uuid))
          ORDER BY e.id LIMIT 51
        """), {"space": space, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])
