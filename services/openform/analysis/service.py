import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from openform.analysis.model import diagnostic_messages
from openform.analysis.schemas import AnalysisInput, ReviewInput, ShareInput
from openform.classrooms.service import require_classroom
from openform.classrooms.summary import summary_facts
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, workspace_transaction
from openform.identity.roster import _event, _page
from openform.jobs.service import PUBLIC_COLUMNS, get_owned_job
from openform.models.ark import available
from openform.school.policies import require_model_policy


def require_analysis(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], classroom_id: UUID,
                     *, create: bool = False) -> dict[str, Any]:
    require_object(connection, identity, workspace, classroom_id, "classroom", "records.read")
    if create:
        require_object(connection, identity, workspace, classroom_id, "classroom", "analysis.create")
    return require_classroom(connection, workspace["id"], classroom_id)


def snapshot(connection: Connection, space: UUID, classroom: dict[str, Any]) -> dict[str, Any]:
    version = connection.execute(text("SELECT number,manifest,grading FROM activity_versions WHERE workspace_id=:space AND id=:id"),
                                 {"space": space, "id": classroom["version_id"]}).mappings().one()
    cutoff = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    stats = summary_facts(connection, space, classroom)
    questions = [question for question in version["manifest"]["questions"] if question["kind"] != "image"]
    rows = connection.execute(text("""
        SELECT * FROM (
          SELECT DISTINCT ON (a.actor_kind,a.actor_id) a.id AS record_id,s.data,s.created_at
          FROM activity_attempts a JOIN activity_submissions s ON s.workspace_id=a.workspace_id AND s.attempt_id=a.id
          WHERE a.workspace_id=:space AND a.classroom_id=:id ORDER BY a.actor_kind,a.actor_id,a.number DESC
        ) latest ORDER BY created_at,record_id LIMIT 201
    """), {"space": space, "id": classroom["id"]}).mappings().all()
    records: list[dict[str, Any]] = []
    size = 0
    for row in rows[:200]:
        answers = {}
        for question in questions:
            value: Any = row["data"]
            for segment in question["dataPath"].split("."):
                value = value.get(segment) if isinstance(value, dict) else None
            if value is not None and value != "" and value != [] and value != {}:
                answers[question["id"]] = value
        if not answers:
            continue
        record = {"record_id": str(row["record_id"]), "answers": answers}
        length = len(json.dumps(record, ensure_ascii=False).encode())
        if size + length > 128 * 1024 or length > 16 * 1024:
            continue
        records.append(record)
        size += length
    return {"captured_at": cutoff.isoformat(), "classroom_title": classroom["title"], "version_number": version["number"],
            "objective": version["manifest"]["objective"], "statistics": stats, "grading": version["grading"],
            "questions": [{"id": question["id"], "title": question["title"], "kind": question["kind"]} for question in questions],
            "records": records, "coverage": {"included": len(records), "total_completed": stats["completed"],
              "omitted": stats["completed"] - len(records), "images_analyzed": False,
              "rule": "每个参与身份最近一次有效最终提交；最多 200 份 / 128 KiB，超大记录整份遗漏；图片不分析。"}}


def enqueue_analysis(engine: Engine, settings: Settings, identity: StaffIdentity, space: UUID,
                     classroom_id: UUID, data: AnalysisInput) -> dict[str, Any]:
    if not data.prompt.strip():
        raise ApiError(422, "INVALID_INPUT", "请输入分析要求。")
    digest = hashlib.sha256(json.dumps({"kind": "analysis", "classroom": str(classroom_id), **data.model_dump(mode="json")},
                                      sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        require_analysis(connection, identity, workspace, classroom_id, create=True)
        existing = connection.execute(text("SELECT id,input_digest FROM jobs WHERE workspace_id=:space AND requester_id=:actor AND request_key=:key"),
                                      {"space": space, "actor": identity.account_id, "key": data.request_key}).mappings().one_or_none()
        if existing:
            if existing["input_digest"] != digest:
                raise ApiError(409, "OPERATION_CONFLICT", "原分析操作键已用于其他要求。")
            row = get_owned_job(connection, identity, workspace, existing["id"])
            return {name: row[name] for name in PUBLIC_COLUMNS.split(", ")}
        if not available(settings):
            raise ApiError(503, "MODEL_UNAVAILABLE", "模型服务未配置；课堂原始记录与统计仍可查看。")
        policy = require_model_policy(connection, settings, space, "analysis")
        # Classroom UPDATE waits for existing writes, and blocks new ones until the fixed snapshot commits.
        classroom = require_classroom(connection, space, classroom_id, write=True)
        payload = snapshot(connection, space, classroom)
        if not payload["records"]:
            raise ApiError(422, "NO_ANALYZABLE_RECORDS", "尚无大小范围内的有效最终提交，不能生成教学结论。")
        reserve = len(json.dumps(diagnostic_messages(data.prompt, payload), ensure_ascii=False).encode()) + settings.model_max_tokens
        connection.execute(text("INSERT INTO model_usage(workspace_id) VALUES(:space) ON CONFLICT DO NOTHING"), {"space": space})
        usage = connection.execute(text("SELECT * FROM model_usage WHERE workspace_id=:space FOR UPDATE"), {"space": space}).mappings().one()
        if usage["reserved_tokens"] + usage["used_tokens"] + reserve > policy["model_token_limit"]:
            raise ApiError(429, "MODEL_QUOTA_EXCEEDED", "模型额度不足，统计和课堂继续可用。")
        queued = connection.execute(text("SELECT count(*) FROM jobs WHERE workspace_id=:space AND status IN ('queued','running')"), {"space": space}).scalar_one()
        if queued >= 20:
            raise ApiError(429, "MODEL_QUEUE_FULL", "当前空间待处理任务已达上限。")
        snapshot_id, job_id = uuid4(), uuid4()
        connection.execute(text("INSERT INTO analysis_snapshots(workspace_id,id,classroom_id,version_id,data_epoch,payload,captured_at) "
                                "VALUES(:space,:id,:classroom,:version,:epoch,CAST(:payload AS jsonb),:cutoff)"),
                           {"space": space, "id": snapshot_id, "classroom": classroom_id, "version": classroom["version_id"],
                            "epoch": classroom["data_epoch"], "payload": json.dumps(payload, ensure_ascii=False, default=str), "cutoff": payload["captured_at"]})
        source = {"snapshot_id": str(snapshot_id), "data_epoch": classroom["data_epoch"], "payload": payload}
        connection.execute(text("UPDATE model_usage SET reserved_tokens=reserved_tokens+:reserve WHERE workspace_id=:space"), {"space": space, "reserve": reserve})
        connection.execute(text("""
          INSERT INTO jobs(workspace_id,id,requester_id,auth_epoch,session_digest,expected_revision,request_key,input_digest,prompt,source,reserved_tokens,kind,classroom_id)
          VALUES(:space,:id,:actor,:auth,:session,0,:key,:digest,:prompt,CAST(:source AS jsonb),:reserve,'analysis',:classroom)
        """), {"space": space, "id": job_id, "actor": identity.account_id, "auth": identity.auth_epoch, "session": identity.session_digest,
               "key": data.request_key, "digest": digest, "prompt": data.prompt.strip(), "source": json.dumps(source, ensure_ascii=False, default=str),
               "reserve": reserve, "classroom": classroom_id})
        connection.execute(text("INSERT INTO job_dispatch(workspace_id,id) VALUES(:space,:id)"), {"space": space, "id": job_id})
        _event(connection, space, identity.account_id, "analysis.requested", classroom_id)
        return {"id": job_id, "status": "queued", "result": None}


def validate_source(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], job: dict[str, Any]) -> None:
    classroom = require_analysis(connection, identity, workspace, job["classroom_id"], create=True)
    if not isinstance(job["source"], dict):
        raise ApiError(410, "SOURCE_INVALIDATED", "原始资料已删除，旧任务不可继续。")
    source = connection.execute(text("SELECT invalidated_at,data_epoch FROM analysis_snapshots WHERE workspace_id=:space AND id=:id FOR SHARE"),
                                {"space": workspace["id"], "id": UUID(job["source"]["snapshot_id"])}).mappings().one_or_none()
    if source is None or source["invalidated_at"] is not None or source["data_epoch"] != classroom["data_epoch"]:
        raise ApiError(409, "SOURCE_INVALIDATED", "原始资料已删除或变更，旧诊断不可用。")


def store_report(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], job: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    validate_source(connection, identity, workspace, job)
    report_id = uuid4()
    connection.execute(text("INSERT INTO analysis_reports(workspace_id,id,snapshot_id,job_id,body) VALUES(:space,:id,:snapshot,:job,CAST(:body AS jsonb))"),
                       {"space": workspace["id"], "id": report_id, "snapshot": UUID(job["source"]["snapshot_id"]), "job": job["id"], "body": json.dumps(body, ensure_ascii=False)})
    return {"id": report_id, "classroom_id": job["classroom_id"], "kind": "analysis"}


def _report(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], report_id: UUID) -> dict[str, Any]:
    row = connection.execute(text("""
      SELECT r.*,s.classroom_id,s.version_id,s.data_epoch,s.captured_at,s.payload,s.invalidated_at
      FROM analysis_reports r JOIN analysis_snapshots s ON s.workspace_id=r.workspace_id AND s.id=r.snapshot_id
      WHERE r.workspace_id=:space AND r.id=:id FOR SHARE OF r,s
    """), {"space": workspace["id"], "id": report_id}).mappings().one_or_none()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "诊断报告不存在。")
    classroom = require_analysis(connection, identity, workspace, row["classroom_id"])
    if row["invalidated_at"] is not None or classroom["data_epoch"] != row["data_epoch"]:
        raise ApiError(410, "SOURCE_INVALIDATED", "原始资料已删除，报告及共享已失效。")
    return dict(row)


def report_detail(engine: Engine, identity: StaffIdentity, space: UUID, report_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        return _report(connection, identity, workspace, report_id)


def evidence_record(engine: Engine, identity: StaffIdentity, space: UUID, report_id: UUID, record_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        report = _report(connection, identity, workspace, report_id)
        if not any(row["record_id"] == str(record_id) for row in report["payload"]["records"]):
            raise ApiError(404, "NOT_FOUND", "记录不属于当前报告快照。")
        row = connection.execute(text("SELECT a.id AS record_id,a.number,s.data,s.receipt,s.created_at FROM activity_attempts a "
                                      "JOIN activity_submissions s ON s.workspace_id=a.workspace_id AND s.attempt_id=a.id "
                                      "WHERE a.workspace_id=:space AND a.classroom_id=:classroom AND a.id=:id"),
                                 {"space": space, "classroom": report["classroom_id"], "id": record_id}).mappings().one_or_none()
        if row is None:
            raise ApiError(410, "SOURCE_INVALIDATED", "原始记录已删除，不能再作为诊断依据。")
        return dict(row)


def list_reports(engine: Engine, identity: StaffIdentity, space: UUID, classroom_id: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        require_analysis(connection, identity, workspace, classroom_id)
        rows = connection.execute(text("""
          SELECT r.id,r.revision,r.reviewed_at,r.shared_at,s.captured_at,s.invalidated_at,s.payload->'coverage' AS coverage
          FROM analysis_reports r JOIN analysis_snapshots s ON s.workspace_id=r.workspace_id AND s.id=r.snapshot_id
          WHERE s.workspace_id=:space AND s.classroom_id=:id AND (CAST(:cursor AS uuid) IS NULL OR r.id>CAST(:cursor AS uuid))
          ORDER BY r.id LIMIT 51
        """), {"space": space, "id": classroom_id, "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def list_tasks(engine: Engine, identity: StaffIdentity, space: UUID, classroom_id: UUID, cursor: UUID | None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, space) as (connection, workspace):
        classroom = require_analysis(connection, identity, workspace, classroom_id, create=True)
        rows = connection.execute(text(f"SELECT {PUBLIC_COLUMNS} FROM jobs WHERE workspace_id=:space AND classroom_id=:id "
                                       "AND requester_id=:actor AND kind='analysis' AND source->>'data_epoch'=:epoch "
                                       "AND (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) ORDER BY id LIMIT 51"),
                                  {"space": space, "id": classroom_id, "actor": identity.account_id,
                                   "epoch": str(classroom["data_epoch"]), "cursor": cursor}).mappings().all()
        return _page([dict(row) for row in rows])


def review_report(engine: Engine, identity: StaffIdentity, space: UUID, report_id: UUID, data: ReviewInput) -> None:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        row = _report(connection, identity, workspace, report_id)
        require_analysis(connection, identity, workspace, row["classroom_id"], create=True)
        if row["revision"] != data.expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "报告状态已变化，请刷新。")
        connection.execute(text("UPDATE analysis_reports SET reviewed_by=:actor,reviewed_at=now(),revision=revision+1 WHERE workspace_id=:space AND id=:id"),
                           {"space": space, "id": report_id, "actor": identity.account_id})
        _event(connection, space, identity.account_id, "analysis.reviewed", report_id)


def share_report(engine: Engine, identity: StaffIdentity, space: UUID, report_id: UUID, data: ShareInput) -> None:
    with workspace_transaction(engine, identity, space, authorization_write=True) as (connection, workspace):
        row = _report(connection, identity, workspace, report_id)
        require_object(connection, identity, workspace, row["classroom_id"], "classroom", "classroom.manage")
        if row["reviewed_at"] is None:
            raise ApiError(409, "REVIEW_REQUIRED", "先核对原始依据并复核报告，再发布课堂摘要。")
        if row["revision"] != data.expected_revision:
            raise ApiError(409, "REVISION_CONFLICT", "报告状态已变化，请刷新。")
        content = data.text.strip() or None
        connection.execute(text("UPDATE analysis_reports SET shared_text=:content,shared_at=CASE WHEN CAST(:content AS text) IS NULL THEN NULL ELSE clock_timestamp() END,"
                                "revision=revision+1 WHERE workspace_id=:space AND id=:id"), {"space": space, "id": report_id, "content": content})
        _event(connection, space, identity.account_id, "analysis.shared" if content else "analysis.unshared", report_id)
