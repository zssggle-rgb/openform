"""Tombstone and epoch commit first; cleanup retries without reopening records.

workspace UPDATE -> classroom UPDATE -> dispatch -> job -> usage
readers/writers share the workspace lock; stale workers cannot publish old bodies.
"""
from typing import Any
from uuid import UUID, uuid4

from pydantic import Field
from sqlalchemy import Connection, Engine, text

from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, require_instance, set_context, workspace_transaction
from openform.identity.schemas import Input
from openform.jobs.service import settle


class DeleteInput(Input):
    expected_data_epoch: int = Field(ge=0)
    confirmed: bool


def _mark_deleted(connection: Connection, space: UUID, classroom: dict[str, Any], actor_id: UUID | None) -> None:
    target = {"space": space, "id": classroom["id"]}
    connection.execute(text("UPDATE classrooms SET records_deleted_at=now(),data_epoch=data_epoch+1,revision=revision+1 WHERE workspace_id=:space AND id=:id"), target)
    connection.execute(text("UPDATE analysis_snapshots SET invalidated_at=now() WHERE workspace_id=:space AND classroom_id=:id"), target)
    connection.execute(text("""
      UPDATE analysis_reports SET shared_text=NULL,shared_at=NULL,revision=revision+1
      WHERE workspace_id=:space AND snapshot_id IN(SELECT id FROM analysis_snapshots WHERE workspace_id=:space AND classroom_id=:id)
    """), target)
    rows = connection.execute(text("SELECT d.id,d.phase FROM job_dispatch d JOIN jobs j ON j.workspace_id=d.workspace_id AND j.id=d.id "
                                   "WHERE j.workspace_id=:space AND j.classroom_id=:id ORDER BY d.id FOR UPDATE OF d"), target).mappings().all()
    for item in rows:
        job = dict(connection.execute(text("SELECT * FROM jobs WHERE workspace_id=:space AND id=:job FOR UPDATE"), {**target, "job": item["id"]}).mappings().one())
        if job["status"] in {"queued", "running"}:
            unknown = item["phase"] == "calling"
            settle(connection, job, {}, unknown=unknown)
            connection.execute(text("UPDATE jobs SET status=:status,error_code='SOURCE_INVALIDATED',error_message=:message,updated_at=now() WHERE workspace_id=:space AND id=:job"),
                               {**target, "job": item["id"], "status": "outcome_unknown" if unknown else "cancelled",
                                "message": "课堂资料已删除，结果不再发布。" + ("已发出模型请求，费用仍待确认。" if unknown else "未发出的任务额度已释放。")})
        connection.execute(text("UPDATE job_dispatch SET generation=generation+1,phase='done',lease_until=NULL WHERE workspace_id=:space AND id=:job"), {**target, "job": item["id"]})
    connection.execute(text("UPDATE transfer_dispatch SET generation=generation+1,phase='done',lease_until=NULL WHERE workspace_id=:space "
                            "AND id IN(SELECT id FROM transfer_exports WHERE workspace_id=:space AND kind='archive' AND object_id=:id)"), target)
    connection.execute(text("UPDATE transfer_exports SET status='invalidated',snapshot=NULL,error_code='SOURCE_INVALIDATED',error_message='课堂资料已删除，原导出已失效。' "
                            "WHERE workspace_id=:space AND kind='archive' AND object_id=:id"), target)
    connection.execute(text("INSERT INTO identity_events(workspace_id,id,actor_id,action,target_id) VALUES(:space,:event,:actor,:action,:id)"),
                       {**target, "event": uuid4(), "actor": actor_id, "action": "records.deleted" if actor_id else "records.expired"})


def delete_records(engine: Engine, identity: StaffIdentity, space: UUID, classroom_id: UUID, data: DeleteInput) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        require_object(connection, identity, workspace, classroom_id, "classroom", "records.delete")
        classroom = connection.execute(text("SELECT * FROM classrooms WHERE workspace_id=:space AND id=:id FOR UPDATE"), {"space": space, "id": classroom_id}).mappings().one()
        if classroom["records_deleted_at"] is not None:
            return {"status": "deleted", "data_epoch": classroom["data_epoch"], "cleanup_complete": classroom["records_cleaned_at"] is not None}
        if not data.confirmed:
            raise ApiError(422, "CONFIRMATION_REQUIRED", "请确认删除此课堂资料；关联报告和共享立即失效，已下载及备份副本无法自动召回。")
        if classroom["state"] != "ended" or classroom["data_epoch"] != data.expected_data_epoch:
            raise ApiError(409, "STATE_CONFLICT", "请先结束课堂并刷新资料状态，再确认删除。")
        _mark_deleted(connection, space, dict(classroom), identity.account_id)
        return {"status": "deleted", "data_epoch": classroom["data_epoch"] + 1, "cleanup_complete": False}


def _clean_records(connection: Connection, space: UUID, classroom_id: UUID) -> None:
    target = {"space": space, "id": classroom_id}
    # The exclusive workspace lock excludes uploads, progress, downloads and report publication.
    attempt_scope = "SELECT id FROM activity_attempts WHERE workspace_id=:space AND classroom_id=:id"
    connection.execute(text(f"DELETE FROM image_references WHERE workspace_id=:space AND attempt_id IN({attempt_scope})"), target)
    size = connection.execute(text(f"SELECT coalesce(sum(byte_size),0) FROM image_assets WHERE workspace_id=:space AND status='ready' AND attempt_id IN({attempt_scope})"), target).scalar_one()
    connection.execute(text("UPDATE image_usage SET byte_size=byte_size-:size WHERE workspace_id=:space"), {**target, "size": size})
    connection.execute(text(f"UPDATE image_assets SET status='deleted' WHERE workspace_id=:space AND attempt_id IN({attempt_scope})"), target)
    for table in ("activity_submissions", "activity_operations", "activity_events"):
        connection.execute(text(f"DELETE FROM {table} WHERE workspace_id=:space AND attempt_id IN({attempt_scope})"), target)
    connection.execute(text("UPDATE activity_attempts SET progress='{}' WHERE workspace_id=:space AND classroom_id=:id"), target)
    connection.execute(text("DELETE FROM classroom_roster WHERE workspace_id=:space AND classroom_id=:id"), target)
    connection.execute(text("UPDATE guest_sessions SET revoked=true WHERE workspace_id=:space AND guest_id IN(SELECT id FROM classroom_guests WHERE workspace_id=:space AND classroom_id=:id)"), target)
    connection.execute(text("UPDATE classroom_guests SET active=false,display_name='已删除' WHERE workspace_id=:space AND classroom_id=:id"), target)
    connection.execute(text("UPDATE analysis_reports SET body='{}',shared_text=NULL,shared_at=NULL WHERE workspace_id=:space AND snapshot_id IN(SELECT id FROM analysis_snapshots WHERE workspace_id=:space AND classroom_id=:id)"), target)
    connection.execute(text("UPDATE analysis_snapshots SET payload='{}' WHERE workspace_id=:space AND classroom_id=:id"), target)
    connection.execute(text("UPDATE jobs SET prompt='',source=NULL,raw_output=NULL,result=NULL WHERE workspace_id=:space AND classroom_id=:id"), target)
    connection.execute(text("UPDATE classrooms SET groups='[]',records_cleaned_at=now() WHERE workspace_id=:space AND id=:id"), target)


def cleanup_records(engine: Engine, settings: Settings) -> int:
    with engine.begin() as connection:
        require_instance(connection)
        spaces = connection.execute(text("SELECT workspace_id FROM classroom_cleanup_spaces(:days)"), {"days": settings.record_retention_days}).scalars().all()
    cleaned = 0
    for space in spaces:
        with engine.begin() as connection:
            require_instance(connection)
            set_context(connection, account_id=UUID(int=0), workspace_id=space)
            rows = connection.execute(text("""
              SELECT c.id FROM classrooms c LEFT JOIN workspace_policies p ON p.workspace_id=c.workspace_id
              WHERE c.workspace_id=:space AND ((c.records_deleted_at IS NOT NULL AND c.records_cleaned_at IS NULL)
                OR (c.state='ended' AND c.records_deleted_at IS NULL AND c.ended_at<now()-make_interval(days=>coalesce(p.retention_days,:days))))
              ORDER BY c.id LIMIT 20
            """), {"space": space, "days": settings.record_retention_days}).scalars().all()
        for classroom_id in rows:
            with engine.begin() as connection:
                require_instance(connection)
                set_context(connection, account_id=UUID(int=0), workspace_id=space)
                connection.execute(text("SELECT id FROM workspaces WHERE id=:space FOR UPDATE"), {"space": space})
                row = connection.execute(text("""
                  SELECT c.*,c.ended_at<now()-make_interval(days=>coalesce(p.retention_days,:days)) AS expired
                  FROM classrooms c LEFT JOIN workspace_policies p ON p.workspace_id=c.workspace_id
                  WHERE c.workspace_id=:space AND c.id=:id FOR UPDATE OF c
                """), {"space": space, "id": classroom_id, "days": settings.record_retention_days}).mappings().one_or_none()
                if row is None or row["records_cleaned_at"] is not None:
                    continue
                if row["records_deleted_at"] is None:
                    if row["state"] != "ended" or row["expired"] is not True:
                        continue
                    _mark_deleted(connection, space, dict(row), None)
            # Separate commit makes invalidation survive cleanup failure; retry only outstanding bodies.
            with engine.begin() as connection:
                require_instance(connection)
                set_context(connection, account_id=UUID(int=0), workspace_id=space)
                connection.execute(text("SELECT id FROM workspaces WHERE id=:space FOR UPDATE"), {"space": space})
                row = connection.execute(text("SELECT records_deleted_at,records_cleaned_at FROM classrooms WHERE workspace_id=:space AND id=:id FOR UPDATE"), {"space": space, "id": classroom_id}).mappings().one()
                if row["records_deleted_at"] is not None and row["records_cleaned_at"] is None:
                    _clean_records(connection, space, classroom_id)
                    cleaned += 1
    return cleaned
