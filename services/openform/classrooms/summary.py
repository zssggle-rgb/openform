from typing import Any
from uuid import UUID

from sqlalchemy import Engine, text

from openform.classrooms.service import require_classroom
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity, workspace_transaction


def classroom_summary(engine: Engine, identity: StaffIdentity, workspace_id: UUID, classroom_id: UUID) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, classroom_id, "classroom", "records.read")
        classroom = require_classroom(connection, workspace_id, classroom_id)
        version = connection.execute(text("SELECT manifest, grading FROM activity_versions WHERE workspace_id=:space AND id=:id"),
                                     {"space": workspace_id, "id": classroom["version_id"]}).mappings().one()
        rows = connection.execute(text("""
            SELECT DISTINCT ON (a.actor_kind, a.actor_id) a.actor_kind, a.actor_id, s.scores, s.data,
              r.student_id IS NOT NULL AS planned
            FROM activity_attempts a JOIN activity_submissions s ON s.workspace_id=a.workspace_id AND s.attempt_id=a.id
            LEFT JOIN classroom_roster r ON r.workspace_id=a.workspace_id AND r.classroom_id=a.classroom_id AND r.student_id=a.student_id
            WHERE a.workspace_id=:space AND a.classroom_id=:id
            ORDER BY a.actor_kind, a.actor_id, a.number DESC
        """), {"space": workspace_id, "id": classroom_id}).mappings().all()
        planned_completed = sum(1 for row in rows if row["planned"])
        planned = classroom["planned_count"]
        counts = connection.execute(text("""
            WITH latest AS (
              SELECT DISTINCT ON (a.actor_kind, a.actor_id) a.state, r.student_id IS NOT NULL AS planned
              FROM activity_attempts a
              LEFT JOIN classroom_roster r ON r.workspace_id=a.workspace_id AND r.classroom_id=a.classroom_id AND r.student_id=a.student_id
              WHERE a.workspace_id=:space AND a.classroom_id=:id
              ORDER BY a.actor_kind, a.actor_id, a.number DESC
            )
            SELECT count(*) AS participated, count(*) FILTER (WHERE state='in_progress') AS in_progress,
              count(*) FILTER (WHERE planned) AS planned_entered,
              (SELECT count(*) FROM activity_attempts WHERE workspace_id=:space AND classroom_id=:id) AS attempt_count,
              (SELECT count(*) FROM activity_submissions s JOIN activity_attempts a ON a.workspace_id=s.workspace_id AND a.id=s.attempt_id
                WHERE a.workspace_id=:space AND a.classroom_id=:id) AS submission_count
            FROM latest
        """), {"space": workspace_id, "id": classroom_id}).mappings().one()
        rules = {rule["questionId"] for rule in version["grading"]}
        questions = []
        for question in version["manifest"]["questions"]:
            scores = [score for row in rows for score in row["scores"] if score["question_id"] == question["id"]]
            answered = 0
            for row in rows:
                value: Any = row["data"]
                for segment in question["dataPath"].split("."):
                    value = value.get(segment) if isinstance(value, dict) else None
                if value is not None and value != "" and value != []:
                    answered += 1
            questions.append({"id": question["id"], "title": question["title"], "data_path": question["dataPath"], "graded": question["id"] in rules,
                              "answered_count": answered, "unanswered_count": len(rows) - answered,
                              "graded_count": len(scores), "correct_count": sum(1 for score in scores if score["correct"]),
                              "accuracy": sum(1 for score in scores if score["correct"]) / len(scores) if scores else None})
        return {"classroom_id": classroom_id, "state": classroom["state"], "mode": classroom["mode"],
                "participated": counts["participated"], "in_progress": counts["in_progress"],
                "not_entered": max(0, planned - counts["planned_entered"]) if planned is not None else None,
                "not_submitted": counts["participated"] - len(rows), "attempt_count": counts["attempt_count"], "submission_count": counts["submission_count"],
                "planned_count": planned, "planned_completed": planned_completed,
                "extra_completed": sum(1 for row in rows if not row["planned"]), "completed": len(rows),
                "completion_rate": planned_completed / planned if planned else None,
                "questions": questions, "rule": "每个参与身份最近一次最终提交；过程保存和重新提交不重复计入完成人数。"}


def classroom_records(engine: Engine, identity: StaffIdentity, workspace_id: UUID, classroom_id: UUID,
                      cursor: UUID | None = None) -> dict[str, Any]:
    with workspace_transaction(engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, classroom_id, "classroom", "records.read")
        require_classroom(connection, workspace_id, classroom_id)
        rows = connection.execute(text("""
            SELECT a.id AS attempt_id, a.number, a.actor_kind, a.actor_id,
              COALESCE(r.display_name, st.display_name, g.display_name) AS display_name,
              r.group_name, r.student_id IS NOT NULL AS planned, s.data, s.receipt, s.scores, s.created_at
            FROM activity_attempts a JOIN activity_submissions s ON s.workspace_id=a.workspace_id AND s.attempt_id=a.id
            LEFT JOIN classroom_roster r ON r.workspace_id=a.workspace_id AND r.classroom_id=a.classroom_id AND r.student_id=a.student_id
            LEFT JOIN students st ON st.workspace_id=a.workspace_id AND st.id=a.student_id
            LEFT JOIN classroom_guests g ON g.workspace_id=a.workspace_id AND g.id=a.guest_id
            WHERE a.workspace_id=:space AND a.classroom_id=:id
              AND (CAST(:cursor AS uuid) IS NULL OR a.id>CAST(:cursor AS uuid)) ORDER BY a.id LIMIT 51
        """), {"space": workspace_id, "id": classroom_id, "cursor": cursor}).mappings().all()
        return {"items": [dict(row) for row in rows[:50]], "next_cursor": str(rows[49]["attempt_id"]) if len(rows) > 50 else None}
