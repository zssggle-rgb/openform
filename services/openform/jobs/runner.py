import json
import logging
import time
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from openform.activities.service import prepare_draft, require_activity, write_draft
from openform.authoring.packages import model_page
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, set_context, workspace_transaction
from openform.jobs.service import settle
from openform.models.ark import ModelFailure, complete
from openform.models.prompts import messages


def dispatch_engine(settings: Settings) -> Engine:
    if settings.dispatch_database_url is None or settings.dispatch_database_password_file is None:
        raise ValueError("需要独立的任务调度数据库凭据。")
    url = make_url(settings.dispatch_database_url.get_secret_value())
    if url.drivername != "postgresql+psycopg" or url.username != "openform_dispatch":
        raise ValueError("任务调度必须使用受限 openform_dispatch 角色。")
    return create_engine(url.set(password=settings.dispatch_database_password_file.read_text().strip()),
                         pool_size=2, max_overflow=0, pool_pre_ping=True, hide_parameters=True,
                         connect_args={"connect_timeout": 5, "options": "-c statement_timeout=5000"})


def claim(engine: Engine) -> dict[str, Any] | None:
    with engine.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(713064)"))
        locked = connection.execute(text("SELECT maintenance OR restored_locked FROM instance_state WHERE id=true")).scalar_one()
        if locked:
            return None
        row = connection.execute(text("""
            SELECT d.* FROM job_dispatch d
            WHERE (d.phase='queued' AND d.available_at<=now() OR d.phase IN ('running','calling') AND d.lease_until<now())
              AND NOT EXISTS(SELECT 1 FROM job_dispatch busy WHERE busy.workspace_id=d.workspace_id
                AND busy.id<>d.id AND busy.phase IN ('running','calling') AND busy.lease_until>now())
              AND (SELECT count(*) FROM job_dispatch busy WHERE busy.phase IN ('running','calling') AND busy.lease_until>now())<2
            ORDER BY d.available_at,d.id FOR UPDATE OF d SKIP LOCKED LIMIT 1
        """)).mappings().one_or_none()
        if row is None:
            return None
        item = dict(row)
        connection.execute(text("""
            UPDATE job_dispatch SET phase='running',generation=generation+1,lease_until=now()+interval '10 minutes',
              attempts=attempts+CASE WHEN phase='calling' THEN 0 ELSE 1 END WHERE workspace_id=:workspace_id AND id=:id
        """), item)
        item["generation"] += 1
        item["attempts"] += 0 if item["phase"] == "calling" else 1
        return item


def _lock_job(connection: Connection, item: dict[str, Any]) -> dict[str, Any] | None:
    dispatch = connection.execute(text("SELECT generation,lease_until>now() AS valid FROM job_dispatch "
                                       "WHERE workspace_id=:workspace_id AND id=:id FOR UPDATE"), item).mappings().one()
    if dispatch["generation"] != item["generation"] or not dispatch["valid"]:
        return None
    return dict(connection.execute(text("SELECT * FROM jobs WHERE workspace_id=:workspace_id AND id=:id FOR UPDATE"), item).mappings().one())


def _finish(connection: Connection, item: dict[str, Any], row: dict[str, Any], *, status: str,
            code: str | None = None, message: str | None = None, usage: dict[str, int] | None = None,
            raw: str | None = None, result: dict[str, Any] | None = None, unknown: bool = False) -> None:
    counters = usage or {}
    settle(connection, row, counters, unknown=unknown)
    connection.execute(text("""
        UPDATE jobs SET status=:status,error_code=:code,error_message=:message,usage=CAST(:usage AS jsonb),
          raw_output=:raw,result=CAST(:result AS jsonb),activity_id=coalesce(activity_id,CAST(:result_activity AS uuid)),
          updated_at=now() WHERE workspace_id=:workspace_id AND id=:id
    """), {**item, "status": status, "code": code, "message": message, "usage": json.dumps(counters), "raw": raw,
           "result": json.dumps(result, default=str), "result_activity": result["id"] if result else None})
    connection.execute(text("UPDATE job_dispatch SET phase='done',lease_until=NULL WHERE workspace_id=:workspace_id AND id=:id"), item)


def _permission_failure(engine: Engine, item: dict[str, Any], *, called: bool) -> None:
    # Cleanup must be possible after revocation; never publish content or write an activity here.
    with engine.begin() as connection:
        set_context(connection, account_id=UUID(int=0), workspace_id=item["workspace_id"])
        connection.execute(text("SELECT id FROM workspaces WHERE id=:workspace_id FOR SHARE"), item)
        row = _lock_job(connection, item)
        if row is not None:
            _finish(connection, item, row, status="outcome_unknown" if called else "cancelled", code="AUTHORIZATION_CHANGED",
                    message="任务权限或会话已变化，未写入活动。" + ("模型费用未确认。" if called else "额度已释放。"), unknown=called)


def run_job(engine: Engine, settings: Settings, item: dict[str, Any]) -> None:
    with engine.begin() as connection:
        set_context(connection, account_id=UUID(int=0), workspace_id=item["workspace_id"])
        original = dict(connection.execute(text("SELECT * FROM jobs WHERE workspace_id=:workspace_id AND id=:id"), item).mappings().one())
    identity = StaffIdentity(original["requester_id"], original["auth_epoch"], original["session_digest"], "")
    called = item["phase"] == "calling"
    raw: str | None = None
    counters: dict[str, int] = {}
    try:
        with workspace_transaction(engine, identity, item["workspace_id"]) as (connection, workspace):
            if not workspace["is_teacher"]:
                raise ApiError(403, "FORBIDDEN", "教学权限已变化。")
            if original["activity_id"]:
                require_object(connection, identity, workspace, original["activity_id"], "activity", "activity.edit")
                activity = require_activity(connection, workspace["id"], original["activity_id"])
                if activity["draft_revision"] != original["expected_revision"]:
                    row = _lock_job(connection, item)
                    if row:
                        _finish(connection, item, row, status="failed", code="REVISION_CONFLICT", message="草稿已变化，未替换当前草稿。", unknown=called)
                    return
            row = _lock_job(connection, item)
            if row is None:
                return
            if called:
                _finish(connection, item, row, status="outcome_unknown", code="MODEL_OUTCOME_UNKNOWN",
                        message="上次调用后 worker 中断，结果和费用未知；未自动重复调用。", unknown=True)
                return
            connection.execute(text("UPDATE jobs SET status='running',updated_at=now() WHERE workspace_id=:workspace_id AND id=:id"), item)
            connection.execute(text("UPDATE job_dispatch SET phase='calling' WHERE workspace_id=:workspace_id AND id=:id"), item)
        called = True
        failure: ModelFailure | None = None
        draft = None
        package = None
        try:
            raw, counters = complete(settings, messages(original["prompt"], original["source"]))
            if "total_tokens" not in counters:
                counters["total_tokens"] = original["reserved_tokens"]
            draft = model_page(raw, original["expected_revision"])
            package = prepare_draft(settings, draft)
        except ModelFailure as error:
            failure = error
        except (ValueError, ValidationError, ApiError, UnicodeError) as error:
            failure = ModelFailure(error.code if isinstance(error, ApiError) else "MODEL_INVALID_PACKAGE",
                                   "生成的页面或数据约定不兼容，原草稿保留；可查看原输出后调整要求。")
        with workspace_transaction(engine, identity, item["workspace_id"]) as (connection, workspace):
            if not workspace["is_teacher"]:
                raise ApiError(403, "FORBIDDEN", "教学权限已变化。")
            if original["activity_id"]:
                require_object(connection, identity, workspace, original["activity_id"], "activity", "activity.edit")
                activity = require_activity(connection, workspace["id"], original["activity_id"], write=True)
                if activity["draft_revision"] != original["expected_revision"]:
                    failure = ModelFailure("REVISION_CONFLICT", "生成期间草稿已更新，未覆盖当前草稿；本次输出已保留。")
            row = _lock_job(connection, item)
            if row is None:
                return
            if failure and failure.retry_after and item["attempts"] < 3:
                connection.execute(text("UPDATE jobs SET status='queued',error_code='MODEL_RATE_LIMITED',error_message=:message,updated_at=now() "
                                        "WHERE workspace_id=:workspace_id AND id=:id"), {**item, "message": failure.message})
                connection.execute(text("UPDATE job_dispatch SET phase='queued',lease_until=NULL,available_at=now()+:seconds*interval '1 second' "
                                        "WHERE workspace_id=:workspace_id AND id=:id"), {**item, "seconds": failure.retry_after})
            elif failure:
                _finish(connection, item, row, status="outcome_unknown" if failure.unknown else "failed", code=failure.code,
                        message=failure.message, raw=raw, usage=counters, unknown=failure.unknown)
            elif draft is not None and package is not None:
                result = write_draft(connection, identity, workspace, draft, package, original["activity_id"])
                _finish(connection, item, row, status="succeeded", usage=counters, raw=raw, result=result)
    except ApiError:
        _permission_failure(engine, item, called=called)


def serve(engine: Engine, dispatcher: Engine, settings: Settings) -> None:
    while True:
        try:
            item = claim(dispatcher)
            if item is None:
                time.sleep(2)
            else:
                run_job(engine, settings, item)
        except SQLAlchemyError:
            logging.getLogger("openform.worker").error("job_database_unavailable")
            time.sleep(5)
