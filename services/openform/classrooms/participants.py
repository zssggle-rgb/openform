from contextlib import contextmanager
from typing import Any, Iterator
from uuid import UUID, uuid4

from sqlalchemy import Connection, Engine, text

from openform.classrooms.guests import GuestIdentity, guest_transaction
from openform.classrooms.service import eligible, participant_lock, require_classroom
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.students import StudentIdentity, student_transaction
from openform.runtime.storage import issue_ticket

Participant = StudentIdentity | GuestIdentity


def actor(identity: Participant) -> tuple[str, UUID]:
    return ("student", identity.student_id) if isinstance(identity, StudentIdentity) else ("guest", identity.guest_id)


@contextmanager
def participant_transaction(engine: Engine, identity: Participant) -> Iterator[tuple[Connection, dict[str, Any]]]:
    if isinstance(identity, StudentIdentity):
        with student_transaction(engine, identity) as (connection, workspace, _):
            yield connection, workspace
    else:
        with guest_transaction(engine, identity) as (connection, workspace, _):
            yield connection, workspace


def _attempt_info(connection: Connection, settings: Settings, workspace_id: UUID, attempt: dict[str, Any], classroom: dict[str, Any]) -> dict[str, Any]:
    version = connection.execute(text("SELECT manifest, package_digest FROM activity_versions WHERE workspace_id=:space AND id=:version"),
                                 {"space": workspace_id, "version": classroom["version_id"]}).mappings().one()
    return {"workspace_id": workspace_id, "attempt_id": attempt["id"], "classroom_id": classroom["id"],
            "title": classroom["title"], "state": attempt["state"], "classroom_state": classroom["state"],
            "number": attempt["number"], "revision": attempt["revision"], "capabilities": version["manifest"]["capabilities"],
            "runtime_origin": settings.runtime_origin,
            "image_fields": [{"path": item["dataPath"], "title": item["title"]} for item in version["manifest"]["questions"] if item["kind"] == "image"],
            "runtime_url": issue_ticket(connection, workspace_id, version["package_digest"], runtime_origin=settings.runtime_origin)}


def join_classroom(engine: Engine, settings: Settings, identity: Participant, *, code: str | None = None,
                   classroom_id: UUID | None = None, previous_attempt_id: UUID | None = None) -> dict[str, Any]:
    kind, actor_id = actor(identity)
    with participant_transaction(engine, identity) as (connection, workspace):
        space = workspace["id"]
        if code is not None:
            locator = connection.execute(text("SELECT workspace_id, classroom_id FROM locate_classroom(:code)"),
                                         {"code": code}).mappings().one_or_none()
            if locator is None or locator["workspace_id"] != space:
                raise ApiError(404, "NOT_FOUND", "课堂码错误或不属于当前身份所在空间。")
            classroom_id = locator["classroom_id"]
        if classroom_id is None:
            raise ApiError(422, "INVALID_INPUT", "需要有效课堂入口。")
        classroom = require_classroom(connection, space, classroom_id)
        participant_lock(connection, space, classroom_id, kind, actor_id)
        if previous_attempt_id is not None:
            retried = connection.execute(text("SELECT * FROM activity_attempts WHERE workspace_id=:space AND classroom_id=:classroom "
                                              "AND actor_kind=:kind AND actor_id=:actor AND parent_attempt_id=:parent"),
                                         {"space": space, "classroom": classroom_id, "kind": kind, "actor": actor_id,
                                          "parent": previous_attempt_id}).mappings().one_or_none()
            if retried:
                return _attempt_info(connection, settings, space, dict(retried), classroom)
        latest = connection.execute(text("SELECT * FROM activity_attempts WHERE workspace_id=:space AND classroom_id=:classroom "
                                         "AND actor_kind=:kind AND actor_id=:actor ORDER BY number DESC LIMIT 1 FOR UPDATE"),
                                    {"space": space, "classroom": classroom_id, "kind": kind, "actor": actor_id}).mappings().one_or_none()
        if previous_attempt_id is None and latest:
            # Returning an already accepted attempt remains possible after classroom pause/end.
            return _attempt_info(connection, settings, space, dict(latest), classroom)
        eligible(connection, space, classroom, kind, actor_id)
        if classroom["state"] != "open":
            raise ApiError(409, "CLASSROOM_NOT_OPEN", "课堂尚未开放、已暂停或已结束，不能开始新尝试。")
        if previous_attempt_id is not None and (latest is None or latest["id"] != previous_attempt_id or latest["state"] != "submitted"):
            raise ApiError(409, "REVISION_CONFLICT", "请先查看最近一次已完成尝试，再明确选择重新作答。")
        attempt_id = uuid4()
        number = latest["number"] + 1 if latest else 1
        connection.execute(text("""
            INSERT INTO activity_attempts (workspace_id, id, classroom_id, actor_kind, actor_id, student_id, guest_id, number, parent_attempt_id)
            VALUES (:space, :id, :classroom, :kind, :actor, :student, :guest, :number, :parent)
        """), {"space": space, "id": attempt_id, "classroom": classroom_id, "kind": kind, "actor": actor_id,
               "student": actor_id if kind == "student" else None, "guest": actor_id if kind == "guest" else None,
               "number": number, "parent": previous_attempt_id})
        return _attempt_info(connection, settings, space, {"id": attempt_id, "state": "in_progress", "revision": 0, "number": number}, classroom)


def own_history(engine: Engine, identity: Participant, cursor: UUID | None = None) -> dict[str, Any]:
    kind, actor_id = actor(identity)
    with participant_transaction(engine, identity) as (connection, workspace):
        rows = connection.execute(text("""
            SELECT a.id AS attempt_id, a.classroom_id, a.number, c.title, s.receipt, s.created_at
            FROM activity_attempts a JOIN activity_submissions s ON s.workspace_id=a.workspace_id AND s.attempt_id=a.id
            JOIN classrooms c ON c.workspace_id=a.workspace_id AND c.id=a.classroom_id
            WHERE a.workspace_id=:space AND a.actor_kind=:kind AND a.actor_id=:actor
              AND (CAST(:cursor AS uuid) IS NULL OR a.id>CAST(:cursor AS uuid)) ORDER BY a.id LIMIT 51
        """), {"space": workspace["id"], "kind": kind, "actor": actor_id, "cursor": cursor}).mappings().all()
        return {"items": [dict(row) for row in rows[:50]], "next_cursor": str(rows[49]["attempt_id"]) if len(rows) > 50 else None}
