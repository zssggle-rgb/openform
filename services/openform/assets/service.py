from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Connection, text

from openform.assets.storage import file_path
from openform.config import Settings
from openform.errors import ApiError


def reserve_image(connection: Connection, attempt: dict[str, Any], context: dict[str, Any], field: str) -> dict[str, Any]:
    question = next((item for item in context["manifest"]["questions"] if item["dataPath"] == field and item["kind"] == "image"), None)
    if question is None:
        raise ApiError(422, "INVALID_FIELD", "该活动没有此图片收集字段。")
    count = connection.execute(text("SELECT count(*) FROM image_assets WHERE workspace_id=:space AND attempt_id=:attempt "
                                   "AND (status='ready' OR status='pending' AND expires_at>now())"),
                               {"space": attempt["workspace_id"], "attempt": attempt["id"]}).scalar_one()
    if count >= 20:
        raise ApiError(409, "UPLOAD_LIMIT", "该尝试已有较多图片，先删除未使用的图片再上传。")
    file_id = uuid4()
    connection.execute(text("INSERT INTO image_assets(workspace_id,id,attempt_id,field) VALUES(:space,:id,:attempt,:field)"),
                       {"space": attempt["workspace_id"], "id": file_id, "attempt": attempt["id"], "field": field})
    return {"fileId": str(file_id), "field": field, "status": "select_in_host", "maxBytes": 10 * 1024 * 1024}


def validate_images(connection: Connection, settings: Settings, attempt: dict[str, Any], manifest: dict[str, Any], data: dict[str, Any], *, final: bool) -> None:
    references: dict[UUID, str] = {}
    for question in manifest["questions"]:
        if question["kind"] != "image":
            continue
        value: Any = data
        for segment in question["dataPath"].split("."):
            value = value.get(segment) if isinstance(value, dict) else None
        if value is None:
            continue
        if not isinstance(value, list):
            raise ApiError(422, "INVALID_IMAGE_REFERENCE", "图片字段必须使用已上传文件的标识列表。")
        for item in value:
            try:
                file_id = UUID(item) if isinstance(item, str) else None
            except ValueError:
                file_id = None
            if file_id is None or file_id in references:
                raise ApiError(422, "INVALID_IMAGE_REFERENCE", "图片标识无效或重复。")
            references[file_id] = question["dataPath"]
    if len(references) > 5:
        raise ApiError(422, "UPLOAD_LIMIT", "一次作答最多引用 5 张图片。")
    for file_id, field in references.items():
        row = connection.execute(text("SELECT field, status, byte_size FROM image_assets WHERE workspace_id=:space AND attempt_id=:attempt AND id=:id FOR SHARE"),
                                 {"space": attempt["workspace_id"], "attempt": attempt["id"], "id": file_id}).mappings().one_or_none()
        if row is None or row["status"] != "ready" or row["field"] != field:
            raise ApiError(422, "INVALID_IMAGE_REFERENCE", "图片尚未完成上传，或不属于本次身份、尝试和字段。")
        path = file_path(settings, attempt["workspace_id"], file_id)
        if not path.is_file() or path.stat().st_size != row["byte_size"]:
            raise ApiError(503, "STORAGE_UNAVAILABLE", "引用图片的存储尚未确认，本次作答未接收，请重新上传。")
    connection.execute(text("DELETE FROM image_references WHERE workspace_id=:space AND attempt_id=:attempt AND kind='progress'"),
                       {"space": attempt["workspace_id"], "attempt": attempt["id"]})
    for file_id in references:
        for kind in (["progress", "submission"] if final else ["progress"]):
            connection.execute(text("INSERT INTO image_references(workspace_id,attempt_id,file_id,kind) VALUES(:space,:attempt,:id,:kind) "
                                    "ON CONFLICT DO NOTHING"),
                               {"space": attempt["workspace_id"], "attempt": attempt["id"], "id": file_id, "kind": kind})
