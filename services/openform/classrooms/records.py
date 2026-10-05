import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import UUID, uuid4

from openform_contracts.validation import ContractViolation, validate, validate_data, validate_message
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from openform.activities.service import require_activity
from openform.classrooms.participants import Participant, actor, participant_transaction
from openform.classrooms.service import eligible, require_classroom
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, workspace_transaction

Actor = StaffIdentity | Participant


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def score_submission(manifest: dict[str, Any], grading: list[dict[str, Any]], data: dict[str, Any]) -> list[dict[str, Any]]:
    paths = {question["id"]: question["dataPath"].split(".") for question in manifest["questions"]}
    results = []
    missing = object()
    for rule in grading:
        value: Any = data
        for segment in paths[rule["questionId"]]:
            value = value.get(segment, missing) if isinstance(value, dict) else missing
        if value is missing:
            continue  # Unanswered optional questions are not automatically wrong.
        expected = rule["expected"]
        correct = value == expected and (isinstance(value, bool) == isinstance(expected, bool))
        results.append({"question_id": rule["questionId"], "correct": correct,
                        "points": rule["points"] if correct else 0, "max_points": rule["points"]})
    return results


def _attempt(connection: Connection, workspace_id: UUID, kind: str, actor_id: UUID, attempt_id: UUID,
             *, locked: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if locked else ""
    row = connection.execute(text("SELECT * FROM activity_attempts WHERE workspace_id=:space AND id=:id "
                                  "AND actor_kind=:kind AND actor_id=:actor" + suffix),
                             {"space": workspace_id, "id": attempt_id, "kind": kind, "actor": actor_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "当前身份没有该尝试。")
    return dict(row)


@contextmanager
def record_transaction(engine: Engine, identity: Actor, attempt_id: UUID, workspace_id: UUID | None = None) -> Iterator[tuple[Connection, dict[str, Any], dict[str, Any], dict[str, Any]]]:
    if isinstance(identity, StaffIdentity):
        if workspace_id is None:
            raise ApiError(403, "FORBIDDEN", "需要已核验的空间。")
        with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
            attempt = _attempt(connection, workspace_id, "staff", identity.account_id, attempt_id)
            trial = connection.execute(text("SELECT activity_id FROM activity_trials WHERE workspace_id=:space AND id=:id AND account_id=:actor"),
                                       {"space": workspace_id, "id": attempt["trial_id"], "actor": identity.account_id}).scalar_one_or_none()
            if trial is None:
                raise ApiError(404, "NOT_FOUND", "试做不存在。")
            require_object(connection, identity, workspace, trial, "activity", "activity.edit")
            current = require_activity(connection, workspace_id, trial)
            context = connection.execute(text("SELECT * FROM activity_trials WHERE workspace_id=:space AND id=:id FOR UPDATE"),
                                         {"space": workspace_id, "id": attempt["trial_id"]}).mappings().one()
            attempt = _attempt(connection, workspace_id, "staff", identity.account_id, attempt_id, locked=True)
            yield connection, workspace, attempt, {**dict(context), "current_draft_revision": current["draft_revision"], "trial": True}
    else:
        kind, actor_id = actor(identity)
        with participant_transaction(engine, identity) as (connection, workspace):
            attempt = _attempt(connection, workspace["id"], kind, actor_id, attempt_id)
            classroom = require_classroom(connection, workspace["id"], attempt["classroom_id"])
            version = connection.execute(text("SELECT manifest, grading, activity_id FROM activity_versions WHERE workspace_id=:space AND id=:id"),
                                         {"space": workspace["id"], "id": classroom["version_id"]}).mappings().one()
            attempt = _attempt(connection, workspace["id"], kind, actor_id, attempt_id, locked=True)
            yield connection, workspace, attempt, {**classroom, **dict(version), "trial": False}


def _writable(connection: Connection, attempt: dict[str, Any], context: dict[str, Any]) -> None:
    if context["trial"]:
        if context["draft_revision"] != context["current_draft_revision"]:
            raise ApiError(409, "TRIAL_STALE", "草稿已变化，请重新试做当前版本。")
        if not context["ready"]:
            raise ApiError(409, "BRIDGE_NOT_READY", "试做尚未完成协议初始化。")
    else:
        eligible(connection, attempt["workspace_id"], context, attempt["actor_kind"], attempt["actor_id"])
        if context["state"] != "open":
            raise ApiError(409, "CLASSROOM_NOT_OPEN", "课堂尚未开放、已暂停或已结束，未接收本次新写入。")
    if attempt["state"] != "in_progress":
        raise ApiError(409, "ALREADY_SUBMITTED", "该尝试已提交，请查看原回执或明确开始新尝试。")


def _operation(connection: Connection, attempt: dict[str, Any], method: str, key: str) -> dict[str, Any] | None:
    row = connection.execute(text("SELECT payload_digest, receipt FROM activity_operations WHERE workspace_id=:space "
                                  "AND actor_kind=:kind AND actor_id=:actor AND method=:method AND idempotency_key=:key"),
                             {"space": attempt["workspace_id"], "kind": attempt["actor_kind"], "actor": attempt["actor_id"],
                              "method": method, "key": key}).mappings().one_or_none()
    return dict(row) if row else None


def _remember(connection: Connection, attempt: dict[str, Any], method: str, key: str, digest: str, receipt: dict[str, Any]) -> None:
    connection.execute(text("""
        INSERT INTO activity_operations (workspace_id, actor_kind, actor_id, method, idempotency_key, attempt_id, payload_digest, receipt)
        VALUES (:space, :kind, :actor, :method, :key, :attempt, :digest, CAST(:receipt AS jsonb))
    """), {"space": attempt["workspace_id"], "kind": attempt["actor_kind"], "actor": attempt["actor_id"],
           "method": method, "key": key, "attempt": attempt["id"], "digest": digest, "receipt": json.dumps(receipt)})


def _write(connection: Connection, attempt: dict[str, Any], context: dict[str, Any], method: str, params: dict[str, Any]) -> dict[str, Any]:
    digest = _digest({"attempt": str(attempt["id"]), "method": method, "params": params})
    previous = _operation(connection, attempt, method, params["idempotencyKey"])
    if previous:
        if previous["payload_digest"] != digest:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "同一操作键已用于不同内容，不能覆盖原操作。")
        return dict(previous["receipt"])
    if method == "submit" and attempt["state"] == "submitted":
        submitted = connection.execute(text("SELECT data, receipt FROM activity_submissions WHERE workspace_id=:space AND attempt_id=:id"),
                                       {"space": attempt["workspace_id"], "id": attempt["id"]}).mappings().one()
        if _digest(submitted["data"]) != _digest(params["data"]):
            raise ApiError(409, "ALREADY_SUBMITTED", "该尝试已有不同内容的最终提交，修改作答须开始新尝试。")
        receipt = dict(submitted["receipt"])
        _remember(connection, attempt, method, params["idempotencyKey"], digest, receipt)
        return receipt
    _writable(connection, attempt, context)
    if attempt["revision"] != params["expectedRevision"]:
        raise ApiError(409, "REVISION_CONFLICT", "另一设备已更新进度，请先读取当前版本，不要直接覆盖。")
    if len(json.dumps(params["data"], ensure_ascii=False).encode("utf-8")) > 60000:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "作答内容超过可保存上限，请缩短文字。图片通过上传服务提交。")
    try:
        validate_data(context["manifest"], params["data"], final=method == "submit")
    except ContractViolation:
        raise ApiError(422, "INVALID_CONTRACT", "作答字段不符合活动要求，请检查必填项和内容长度。") from None
    if any(question["kind"] == "image" for question in context["manifest"]["questions"]):
        raise ApiError(409, "UPLOAD_NOT_READY", "图片收集尚未接通，不能把图片字段标记为已接收。")
    if method == "submit" and context["trial"] and (context["reread_revision"] != attempt["revision"] or attempt["revision"] < 1):
        raise ApiError(409, "TRIAL_READ_REQUIRED", "请先保存，并重新读取收到回执的版本，再完成试做提交。")
    revision = attempt["revision"] + 1
    receipt = {"receiptId": str(uuid4()), "attemptId": str(attempt["id"]), "revision": revision,
               "state": "submitted" if method == "submit" else "saved",
               "receivedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    validate("receipt", receipt)
    values = {"space": attempt["workspace_id"], "id": attempt["id"], "revision": revision,
              "state": "submitted" if method == "submit" else "in_progress", "data": json.dumps(params["data"], ensure_ascii=False)}
    connection.execute(text("UPDATE activity_attempts SET revision=:revision, state=:state, progress=CAST(:data AS jsonb) "
                            "WHERE workspace_id=:space AND id=:id"), values)
    if method == "submit":
        scores = score_submission(context["manifest"], context["grading"], params["data"])
        connection.execute(text("INSERT INTO activity_submissions (workspace_id, id, attempt_id, data, receipt, scores) "
                                "VALUES (:space, :submission, :id, CAST(:data AS jsonb), CAST(:receipt AS jsonb), CAST(:scores AS jsonb))"),
                           {**values, "submission": UUID(receipt["receiptId"]), "receipt": json.dumps(receipt), "scores": json.dumps(scores)})
    _remember(connection, attempt, method, params["idempotencyKey"], digest, receipt)
    return receipt


def _dispatch(connection: Connection, attempt: dict[str, Any], context: dict[str, Any], request: dict[str, Any]) -> Any:
    method, params = request["method"], request["params"]
    if method not in context["manifest"]["capabilities"]:
        raise ApiError(403, "FORBIDDEN", "该活动没有声明此数据能力。")
    if method == "ready":
        if set(params["capabilities"]) != set(context["manifest"]["capabilities"]):
            raise ApiError(422, "INVALID_CONTRACT", "页面能力与固定版本不匹配。")
        if context["trial"]:
            connection.execute(text("UPDATE activity_trials SET ready=true WHERE workspace_id=:space AND id=:id"),
                               {"space": attempt["workspace_id"], "id": context["id"]})
        return {"protocolVersion": "openform.activity/1", "capabilities": context["manifest"]["capabilities"]}
    if method == "loadProgress":
        if context["trial"] and context["ready"] and attempt["revision"] > 0:
            connection.execute(text("UPDATE activity_trials SET reread_revision=:revision WHERE workspace_id=:space AND id=:id"),
                               {"space": attempt["workspace_id"], "id": context["id"], "revision": attempt["revision"]})
        submission = connection.execute(text("SELECT receipt FROM activity_submissions WHERE workspace_id=:space AND attempt_id=:id"),
                                        {"space": attempt["workspace_id"], "id": attempt["id"]}).scalar_one_or_none()
        return {"data": attempt["progress"], "revision": attempt["revision"], "state": attempt["state"], "receipt": submission}
    if method in {"saveProgress", "submit"}:
        return _write(connection, attempt, context, method, params)
    if method == "appendEvents":
        _writable(connection, attempt, context)
        count = connection.execute(text("SELECT count(*) FROM activity_events WHERE workspace_id=:space AND attempt_id=:id"),
                                   {"space": attempt["workspace_id"], "id": attempt["id"]}).scalar_one()
        accepted = 0
        for event in params["events"]:
            existing = connection.execute(text("SELECT kind, data FROM activity_events WHERE workspace_id=:space AND attempt_id=:id AND event_id=:event"),
                                          {"space": attempt["workspace_id"], "id": attempt["id"], "event": event["eventId"]}).mappings().one_or_none()
            if existing:
                if existing["kind"] != event["kind"] or _digest(existing["data"]) != _digest(event["data"]):
                    raise ApiError(409, "EVENT_CONFLICT", "同一事件标识已用于其他内容。")
                continue
            if count + accepted >= 5000:
                raise ApiError(429, "RATE_LIMITED", "该尝试的过程事件达到上限，保存和提交仍可使用。")
            connection.execute(text("INSERT INTO activity_events (workspace_id, attempt_id, event_id, kind, data) "
                                    "VALUES (:space, :id, :event, :kind, CAST(:data AS jsonb))"),
                               {"space": attempt["workspace_id"], "id": attempt["id"], "event": event["eventId"],
                                "kind": event["kind"], "data": json.dumps(event["data"], ensure_ascii=False)})
            accepted += 1
        return {"accepted": accepted}
    if method == "getOwnHistory":
        if context["trial"]:
            return {"items": []}
        rows = connection.execute(text("""
            SELECT s.data, s.receipt FROM activity_submissions s
            JOIN activity_attempts a ON a.workspace_id=s.workspace_id AND a.id=s.attempt_id
            JOIN classrooms c ON c.workspace_id=a.workspace_id AND c.id=a.classroom_id
            JOIN activity_versions v ON v.workspace_id=c.workspace_id AND v.id=c.version_id
            WHERE a.workspace_id=:space AND a.actor_kind=:kind AND a.actor_id=:actor AND v.activity_id=:activity
            ORDER BY s.created_at DESC LIMIT 10
        """), {"space": attempt["workspace_id"], "kind": attempt["actor_kind"], "actor": attempt["actor_id"], "activity": context["activity_id"]}).mappings().all()
        # Receipts identify accepted history; full answers remain available through loadProgress.
        return {"items": [{"receipt": row["receipt"]} for row in rows]}
    if method == "requestUpload":
        raise ApiError(409, "UPLOAD_NOT_READY", "当前活动暂不能上传图片，请联系教师。")
    raise ApiError(403, "SHARING_NOT_AVAILABLE", "当前活动没有教师发布的共享摘要。")


def execute_bridge(engine: Engine, identity: Actor, attempt_id: UUID, request: dict[str, Any], *, workspace_id: UUID | None = None) -> Any:
    try:
        validate_message(request)
    except ContractViolation:
        raise ApiError(422, "INVALID_CONTRACT", "页面消息不符合当前协议。") from None
    for retry in range(2):
        try:
            with record_transaction(engine, identity, attempt_id, workspace_id) as (connection, _, attempt, context):
                return _dispatch(connection, attempt, context, request)
        except IntegrityError as error:
            if getattr(error.orig, "sqlstate", None) != "23505" or retry == 1:
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "操作键或尝试已存在，请读取原状态后重试。") from None
    raise ApiError(503, "SERVICE_UNAVAILABLE", "操作暂不可用。")


def find_operation(engine: Engine, identity: Actor, attempt_id: UUID, method: str, key: str, *, workspace_id: UUID | None = None) -> dict[str, Any]:
    if method not in {"saveProgress", "submit"} or not 16 <= len(key) <= 128:
        raise ApiError(422, "INVALID_INPUT", "操作标识无效。")
    with record_transaction(engine, identity, attempt_id, workspace_id) as (connection, _, attempt, _):
        operation = connection.execute(text("SELECT receipt FROM activity_operations WHERE workspace_id=:space AND actor_kind=:kind "
                                           "AND actor_id=:actor AND attempt_id=:id AND method=:method AND idempotency_key=:key"),
                                      {"space": attempt["workspace_id"], "kind": attempt["actor_kind"], "actor": attempt["actor_id"],
                                       "id": attempt_id, "method": method, "key": key}).scalar_one_or_none()
        if operation is None:
            raise ApiError(404, "OPERATION_NOT_FOUND", "尚未找到该操作回执，可使用原操作键和原内容重试。")
        return dict(operation)
