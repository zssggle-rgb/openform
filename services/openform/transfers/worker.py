import json
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text

from openform.assets.storage import file_path, staging_file
from openform.classrooms.service import require_classroom
from openform.config import Settings
from openform.errors import ApiError
from openform.identity.context import StaffIdentity, set_context, workspace_transaction
from openform.transfers.exports import authorize_source, source_kind
from openform.transfers.packages import MAX_CONTENT_BYTES, Package, read_package, write_package
from openform.transfers.storage import artifact_path, persist_file, require_capacity


def claim_export(dispatcher: Engine) -> dict[str, Any] | None:
    with dispatcher.begin() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(713065)"))
        if connection.execute(text("SELECT maintenance OR restored_locked FROM instance_state WHERE id=true")).scalar_one():
            return None
        row = connection.execute(text("""
          SELECT * FROM transfer_dispatch WHERE (phase='queued' OR phase='running' AND lease_until<now())
            AND NOT EXISTS(SELECT 1 FROM transfer_dispatch busy WHERE busy.phase='running' AND busy.lease_until>now())
          ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 1
        """)).mappings().one_or_none()
        if row is None:
            return None
        item = dict(row)
        connection.execute(text("UPDATE transfer_dispatch SET phase='running',generation=generation+1,lease_until=now()+interval '10 minutes' WHERE workspace_id=:workspace_id AND id=:id"), item)
        item["generation"] += 1
        return item


def _lock(connection: Connection, item: dict[str, Any]) -> dict[str, Any] | None:
    dispatch = connection.execute(text("SELECT generation,lease_until>now() AS valid,phase FROM transfer_dispatch WHERE workspace_id=:workspace_id AND id=:id FOR UPDATE"), item).mappings().one()
    if dispatch["generation"] != item["generation"] or not dispatch["valid"] or dispatch["phase"] != "running":
        return None
    return dict(connection.execute(text("SELECT *,expires_at>now() AS unexpired FROM transfer_exports WHERE workspace_id=:workspace_id AND id=:id FOR UPDATE"), item).mappings().one())


def _snapshot(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    space, target = workspace["id"], row["object_id"]
    exported_at = connection.execute(text("SELECT clock_timestamp()")).scalar_one().isoformat()
    source = {"workspace_id": str(space), "object_id": str(target), "exported_at": exported_at, "data_epoch": row["data_epoch"]}
    records = []
    if row["kind"] == "resource":
        amount = connection.execute(text("""
          SELECT count(*),coalesce(sum(octet_length(v.manifest::text)+octet_length(v.grading::text)+octet_length(s.assets::text)),0)
          FROM activity_versions v JOIN activity_sources s ON s.workspace_id=v.workspace_id AND s.package_digest=v.package_digest
          WHERE v.workspace_id=:space AND v.activity_id=:id AND (CAST(:number AS bigint) IS NULL OR v.number=:number)
        """), {"space": space, "id": target, "number": row["version_number"]}).one()
        if amount[0] > 50 or amount[1] > MAX_CONTENT_BYTES:
            raise ApiError(413, "EXPORT_VERSION_LIMIT", "单包最多 50 个版本或 50 MiB 正文，请选择一个固定版本。")
        versions = connection.execute(text("""
          SELECT v.number,v.manifest,v.grading,s.assets FROM activity_versions v
          JOIN activity_sources s ON s.workspace_id=v.workspace_id AND s.package_digest=v.package_digest
          WHERE v.workspace_id=:space AND v.activity_id=:id AND (CAST(:number AS bigint) IS NULL OR v.number=:number)
          ORDER BY v.number LIMIT 51
        """), {"space": space, "id": target, "number": row["version_number"]}).mappings().all()
        if not versions or len(versions) > 50:
            raise ApiError(413, "EXPORT_VERSION_LIMIT", "请选择存在的固定版本；单包最多 50 个版本。")
        title = versions[-1]["manifest"]["title"]
    else:
        classroom = require_classroom(connection, space, target, write=True)
        title = classroom["title"]
        versions = connection.execute(text("SELECT v.number,v.manifest,v.grading,s.assets FROM activity_versions v JOIN activity_sources s ON s.workspace_id=v.workspace_id AND s.package_digest=v.package_digest WHERE v.workspace_id=:space AND v.id=:id"), {"space": space, "id": classroom["version_id"]}).mappings().all()
        amount = connection.execute(text("SELECT count(*),coalesce(sum(octet_length(s.data::text)),0) FROM activity_submissions s JOIN activity_attempts a ON a.workspace_id=s.workspace_id AND a.id=s.attempt_id WHERE a.workspace_id=:space AND a.classroom_id=:id"), {"space": space, "id": target}).one()
        if amount[0] > 10000 or amount[1] > MAX_CONTENT_BYTES:
            raise ApiError(413, "EXPORT_RECORD_LIMIT", "所选课堂超过单包 10000 份或 50 MiB 正文范围。")
        answers = connection.execute(text("""
          SELECT a.id,a.actor_id,a.actor_kind,a.number,s.data,s.receipt,s.created_at,
            coalesce(r.display_name,st.display_name,g.display_name) AS display_name
          FROM activity_attempts a JOIN activity_submissions s ON s.workspace_id=a.workspace_id AND s.attempt_id=a.id
          LEFT JOIN classroom_roster r ON r.workspace_id=a.workspace_id AND r.classroom_id=a.classroom_id AND r.student_id=a.student_id
          LEFT JOIN students st ON st.workspace_id=a.workspace_id AND st.id=a.student_id
          LEFT JOIN classroom_guests g ON g.workspace_id=a.workspace_id AND g.id=a.guest_id
          WHERE a.workspace_id=:space AND a.classroom_id=:id ORDER BY s.created_at,a.id
        """), {"space": space, "id": target}).mappings().all()
        images = connection.execute(text("""
          SELECT r.attempt_id,f.id,f.media_type,f.byte_size,f.digest FROM image_references r
          JOIN image_assets f ON f.workspace_id=r.workspace_id AND f.id=r.file_id
          JOIN activity_attempts a ON a.workspace_id=r.workspace_id AND a.id=r.attempt_id
          WHERE r.workspace_id=:space AND a.classroom_id=:id AND r.kind='submission' AND f.status='ready' ORDER BY r.attempt_id,f.id
        """), {"space": space, "id": target}).mappings().all()
        by_attempt: dict[UUID, list[dict[str, Any]]] = {}
        for image in images:
            by_attempt.setdefault(image["attempt_id"], []).append({"source_file_id": str(image["id"]), "path": f"images/{image['id']}.image",
                                                                 "media_type": image["media_type"], "byte_size": image["byte_size"], "sha256": image["digest"]})
        for answer in answers:
            records.append({"source_record_id": str(answer["id"]), "source_actor_id": str(answer["actor_id"]), "actor_kind": answer["actor_kind"],
                            "display_name": answer["display_name"], "attempt_number": answer["number"], "created_at": answer["created_at"].isoformat(),
                            "data": answer["data"], "receipt_id": answer["receipt"]["receiptId"], "images": by_attempt.get(answer["id"], [])})
    return {"format": "openform.resource/1" if row["kind"] == "resource" else "openform.archive/1", "title": title, "source": source,
            "versions": [{"number": version["number"], "draft": {"manifest": version["manifest"], "grading": version["grading"], "assets": version["assets"], "expected_revision": 0}} for version in versions], "records": records}


def run_export(engine: Engine, settings: Settings, item: dict[str, Any]) -> None:
    temporary: Path | None = None
    with engine.begin() as connection:
        set_context(connection, account_id=UUID(int=0), workspace_id=item["workspace_id"])
        original = dict(connection.execute(text("SELECT * FROM transfer_exports WHERE workspace_id=:workspace_id AND id=:id"), item).mappings().one())
    identity = StaffIdentity(original["requester_id"], original["auth_epoch"], original["session_digest"], "")
    try:
        with workspace_transaction(engine, identity, item["workspace_id"], authorization_write=True) as (connection, workspace):
            authorize_source(connection, identity, workspace, original)
            row = _lock(connection, item)
            if row is None:
                return
            if not row["unexpired"] or row["status"] not in {"queued", "running"}:
                raise ApiError(410, "EXPORT_EXPIRED", "任务已过期或失效，请重新导出。")
            archive_copy = source_kind(connection, workspace["id"], row["object_id"]) == "archive"
            source_path = None
            if archive_copy:
                import_id = connection.execute(text("SELECT import_id FROM classroom_archives WHERE workspace_id=:space AND id=:id"), {"space": workspace["id"], "id": row["object_id"]}).scalar_one()
                source_path = artifact_path(settings, workspace["id"], import_id)
                payload = None
            else:
                payload = row["snapshot"] or _snapshot(connection, identity, workspace, row)
            connection.execute(text("UPDATE transfer_exports SET status='running',snapshot=CAST(:snapshot AS jsonb) WHERE workspace_id=:workspace_id AND id=:id"), {**item, "snapshot": json.dumps(payload, ensure_ascii=False) if payload else None})
        temporary = staging_file(settings)
        if source_path is not None:
            shutil.copyfile(source_path, temporary)
        else:
            package = Package.model_validate(payload)
            files = {image.path: file_path(settings, item["workspace_id"], image.source_file_id) for record in package.records for image in record.images}
            write_package(temporary, package, files)
        # Real artifact validation is part of producing the export, not a test invocation.
        read_package(temporary, settings)
        with workspace_transaction(engine, identity, item["workspace_id"], authorization_write=True) as (connection, workspace):
            authorize_source(connection, identity, workspace, original)
            row = _lock(connection, item)
            if row is None:
                return
            if not row["unexpired"] or row["status"] != "running":
                raise ApiError(410, "EXPORT_EXPIRED", "导出期间任务已失效。")
            require_capacity(connection, settings, workspace["id"], temporary.stat().st_size)
            destination = artifact_path(settings, workspace["id"], row["id"])
            destination.unlink(missing_ok=True)  # Only an uncommitted artifact of this active lease can exist here.
            size, digest = persist_file(temporary, destination)
            connection.execute(text("UPDATE transfer_exports SET status='succeeded',byte_size=:size,file_digest=:digest,snapshot=NULL WHERE workspace_id=:workspace_id AND id=:id"), {**item, "size": size, "digest": digest})
            connection.execute(text("UPDATE transfer_dispatch SET phase='done',lease_until=NULL WHERE workspace_id=:workspace_id AND id=:id"), item)
    except (ApiError, OSError, ValidationError) as error:
        with engine.begin() as connection:
            set_context(connection, account_id=UUID(int=0), workspace_id=item["workspace_id"])
            connection.execute(text("SELECT id FROM workspaces WHERE id=:workspace_id FOR UPDATE"), item)
            row = _lock(connection, item)
            if row is not None:
                connection.execute(text("UPDATE transfer_exports SET status='failed',snapshot=NULL,error_code=:code,error_message=:message WHERE workspace_id=:workspace_id AND id=:id"),
                                   {**item, "code": error.code if isinstance(error, ApiError) else "EXPORT_STORAGE_FAILED",
                                    "message": error.message if isinstance(error, ApiError) else "导出内容或存储不可用，未提供下载文件。"})
                connection.execute(text("UPDATE transfer_dispatch SET phase='done',lease_until=NULL WHERE workspace_id=:workspace_id AND id=:id"), item)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
