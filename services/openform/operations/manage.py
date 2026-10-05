"""Migrator-only lifecycle operations. JSON input is stdin, never command-line secrets."""
import json
import sys
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from openform.config import Settings
from openform.database import SCHEMA_REVISION, build_engine
from openform.identity.security import hash_password

COUNTS = ("workspaces", "activities", "activity_versions", "classrooms", "activity_attempts",
          "activity_submissions", "image_assets", "classroom_archives", "archive_records")


def inventory(connection: Connection) -> dict[str, int]:
    return {name: int(connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one()) for name in COUNTS}


def restored_lock(connection: Connection, data: dict[str, Any], state: dict[str, Any]) -> None:
    metadata = data["metadata"]
    if (state["restored_locked"] or str(state["instance_id"]) != metadata["instance_id"]
            or inventory(connection) != metadata["counts"] or metadata["schema"] != SCHEMA_REVISION
            or connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != metadata["schema"]):
        raise ValueError("恢复来源、版本或记录数量不一致，实例继续关闭。")
    # Preserve submissions, versions, image references and immutable ownership history.
    for table in ("auth_sessions", "student_sessions", "guest_sessions", "runtime_tickets", "operator_sessions"):
        connection.execute(text(f"UPDATE {table} SET revoked=true"))
    connection.execute(text("UPDATE accounts SET active=false,auth_epoch=auth_epoch+1"))
    connection.execute(text("UPDATE memberships SET active=false,auth_epoch=auth_epoch+1,session_valid_after=clock_timestamp()"))
    connection.execute(text("UPDATE staff_invites SET active=false"))
    connection.execute(text("UPDATE students SET code_digest=NULL,code_expires_at=NULL,auth_epoch=auth_epoch+1"))
    connection.execute(text("UPDATE assignments SET active=false,revision=revision+1"))
    connection.execute(text("UPDATE object_grants SET active=false,revision=revision+1"))
    connection.execute(text("UPDATE classroom_guests SET active=false"))
    connection.execute(text("UPDATE classrooms SET state=CASE WHEN state='open' THEN 'paused' ELSE state END,revision=revision+1"))
    # Rotate every entry code, including quick classes; old code cannot create a new guest.
    for row in connection.execute(text("SELECT workspace_id,id FROM classrooms")).mappings().all():
        connection.execute(text("UPDATE classrooms SET code=:code WHERE workspace_id=:workspace_id AND id=:id"),
                           {**row, "code": uuid4().hex[:8].upper()})
    connection.execute(text("UPDATE analysis_reports SET shared_text=NULL,shared_at=NULL"))
    # Never repeat a potentially billed model call. Unknown reservations remain visible.
    connection.execute(text("""
      WITH released AS (
        UPDATE jobs j SET status='cancelled',settled=true,error_code='INSTANCE_RESTORED',
          error_message='恢复取消了尚未发出的调用。',updated_at=now()
        FROM job_dispatch d WHERE d.workspace_id=j.workspace_id AND d.id=j.id
          AND d.phase IN ('queued','running') AND j.status IN ('queued','running') AND NOT j.settled
        RETURNING j.workspace_id,j.reserved_tokens
      ), totals AS (SELECT workspace_id,sum(reserved_tokens) n FROM released GROUP BY workspace_id)
      UPDATE model_usage u SET reserved_tokens=u.reserved_tokens-t.n FROM totals t WHERE t.workspace_id=u.workspace_id
    """))
    connection.execute(text("UPDATE jobs SET status='outcome_unknown',error_code='INSTANCE_RESTORED',"
                            "error_message='恢复前调用的结果和费用待确认，未自动重试。',updated_at=now() "
                            "WHERE status IN ('queued','running')"))
    connection.execute(text("UPDATE job_dispatch SET phase='done',generation=generation+1,lease_until=NULL"))
    connection.execute(text("UPDATE transfer_exports SET status='invalidated',snapshot=NULL,expires_at=now()"))
    connection.execute(text("UPDATE transfer_dispatch SET phase='done',generation=generation+1,lease_until=NULL"))
    connection.execute(text("UPDATE transfer_imports SET status='expired',expires_at=now() WHERE status='validated'"))
    recovery = {"snapshot_at": metadata["snapshot_at"], "source_instance": metadata["instance_id"],
                "verified": True, "counts": metadata["counts"], "opened_at": None,
                "gap_notice": "备份时间点之后的改动不在此实例，需向原实例核对。"}
    backup = {key: value for key, value in metadata.items() if key != "images"}
    backup.update(local_verified=True, offsite_verified=False, cipher_sha256=data["cipher_sha256"])
    connection.execute(text("UPDATE instance_state SET instance_id=:id,generation=generation+1,"
                            "maintenance=true,restored_locked=true,recovery=CAST(:recovery AS jsonb),"
                            "pending_backup=NULL,backup=CAST(:backup AS jsonb) WHERE id=true"),
                       {"id": uuid4(), "recovery": json.dumps(recovery), "backup": json.dumps(backup)})


def authorize(connection: Connection, data: dict[str, Any], state: dict[str, Any]) -> None:
    if not state["restored_locked"]:
        raise ValueError("重新授权命令只适用于锁定的恢复实例。")
    workspace = UUID(data["workspace_id"])
    if not isinstance(data["teacher"], bool) or not isinstance(data["admin"], bool) or not (data["teacher"] or data["admin"]):
        raise ValueError("必须明确指定教师或校园管理员职责。")
    password = data["password"]
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("恢复账号必须设置 12–128 字符的新密码。")
    member = connection.execute(text("SELECT m.account_id FROM memberships m JOIN accounts a ON a.id=m.account_id "
                                     "WHERE m.workspace_id=:space AND a.login=:login"),
                                {"space": workspace, "login": data["login"]}).scalar_one_or_none()
    if member is None:
        raise ValueError("恢复点中没有该账号与空间关系，请核对。")
    connection.execute(text("UPDATE accounts SET active=true,password_hash=:hash,auth_epoch=auth_epoch+1 WHERE id=:id"),
                       {"id": member, "hash": hash_password(password)})
    connection.execute(text("UPDATE memberships SET active=true,is_teacher=:teacher,is_admin=:admin,"
                            "auth_epoch=auth_epoch+1,session_valid_after=clock_timestamp() WHERE workspace_id=:space AND account_id=:id"),
                       {"id": member, "space": workspace, "teacher": data["teacher"], "admin": data["admin"]})


def execute(connection: Connection, data: dict[str, Any]) -> dict[str, Any]:
    if connection.execute(text("SELECT current_user")).scalar_one() != "openform_migrate":
        raise ValueError("必须使用独立运维迁移角色。")
    state = dict(connection.execute(text("SELECT * FROM instance_state WHERE id=true FOR UPDATE")).mappings().one())
    action = data["action"]
    if action == "maintenance-on":
        connection.execute(text("UPDATE instance_state SET maintenance=true WHERE id=true"))
    elif action == "maintenance-off":
        if state["restored_locked"]:
            raise ValueError("恢复实例必须核对及重新授权后使用 recovery-open。")
        connection.execute(text("UPDATE instance_state SET maintenance=false WHERE id=true"))
    elif action == "snapshot":
        if not state["maintenance"] or state["restored_locked"]:
            raise ValueError("备份需要普通实例维护状态，不能备份尚未核对的恢复实例。")
        if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != SCHEMA_REVISION:
            raise ValueError("应用与数据库版本不同，不能建立恢复点。")
        metadata = {"snapshot_at": datetime.now(timezone.utc).isoformat(), "instance_id": str(state["instance_id"]),
                    "generation": state["generation"], "schema": SCHEMA_REVISION, "counts": inventory(connection),
                    "id": str(uuid4()), "local_verified": False, "offsite_verified": False,
                    "images": {f"files/images/{row['workspace_id']}/{row['id']}.image":
                               {"bytes": row["byte_size"], "sha256": row["digest"]}
                               for row in connection.execute(text(
                                   "SELECT workspace_id,id,byte_size,digest FROM image_assets WHERE status='ready'"
                               )).mappings()}}
        connection.execute(text("UPDATE instance_state SET pending_backup=CAST(:metadata AS jsonb) WHERE id=true"),
                           {"metadata": json.dumps({key: value for key, value in metadata.items() if key != "images"})})
        return metadata
    elif action in {"backup-verified", "backup-offsite"}:
        backup = state["pending_backup"] if action == "backup-verified" else state["backup"]
        if not backup or backup["id"] != data["id"]:
            raise ValueError("备份编号不一致。")
        if action == "backup-verified":
            backup.update(local_verified=True, cipher_sha256=data["cipher_sha256"])
        else:
            if not backup.get("local_verified") or backup.get("cipher_sha256") != data["cipher_sha256"]:
                raise ValueError("需要先核对加密文件摘要。")
            backup["offsite_verified"] = True
        connection.execute(text("UPDATE instance_state SET backup=CAST(:backup AS jsonb),pending_backup=NULL WHERE id=true"),
                           {"backup": json.dumps(backup)})
    elif action == "restore-lock":
        restored_lock(connection, data, state)
    elif action == "authorize":
        authorize(connection, data, state)
    elif action == "recovery-open":
        if not state["restored_locked"] or not state["recovery"] or not state["recovery"].get("verified"):
            raise ValueError("实例尚未完成受控恢复核对。")
        missing = connection.execute(text("SELECT count(*) FROM workspaces w WHERE w.active AND w.kind='campus' "
                                          "AND NOT EXISTS(SELECT 1 FROM memberships m JOIN accounts a ON a.id=m.account_id "
                                          "WHERE m.workspace_id=w.id AND m.active AND m.is_admin AND a.active)")).scalar_one()
        if missing or not connection.execute(text("SELECT count(*) FROM memberships WHERE active")).scalar_one():
            raise ValueError("每个启用校园需至少一名重新授权的管理员；至少需要一个明确授权。")
        recovery = {**state["recovery"], "opened_at": datetime.now(timezone.utc).isoformat()}
        connection.execute(text("UPDATE instance_state SET maintenance=false,restored_locked=false,recovery=CAST(:r AS jsonb) WHERE id=true"),
                           {"r": json.dumps(recovery)})
    elif action != "status":
        raise ValueError("未知运维操作。")
    result: dict[str, Any] = connection.execute(text("SELECT operator_status()")).scalar_one()
    return {**result, "counts": inventory(connection), "inflight": int(connection.execute(text(
        "SELECT (SELECT count(*) FROM job_dispatch WHERE phase IN ('running','calling'))+"
        "(SELECT count(*) FROM transfer_dispatch WHERE phase='running')")).scalar_one())}


def main() -> int:
    engine = build_engine(Settings())
    try:
        data = json.load(sys.stdin)
        with engine.begin() as connection:
            result = execute(connection, data)
        print(json.dumps(result, default=str))
        return 0
    except (OSError, ValueError, KeyError, TypeError, SQLAlchemyError):
        print("运维输入或实例状态不符合要求，事务未提交。", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
