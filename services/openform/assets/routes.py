import asyncio
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import text

from openform.assets import uploads
from openform.assets.storage import MAX_IMAGE_BYTES, file_path, normalize_image, staging_file
from openform.classrooms.records import Actor
from openform.classrooms.routes import Guest
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import workspace_transaction
from openform.identity.roster_routes import Student
from openform.identity.routes import Identity

router = APIRouter(prefix="/api")


async def receive_upload(request: Request, identity: Actor, attempt_id: UUID, file_id: UUID,
                         workspace_id: UUID | None = None) -> dict[str, Any]:
    declared = request.headers.get("content-type", "")
    if declared not in {"image/png", "image/jpeg"}:
        raise ApiError(422, "INVALID_IMAGE", "只支持 PNG/JPEG 图片。")
    engine, settings = request.app.state.engine, request.app.state.settings
    await asyncio.to_thread(uploads.begin_upload, engine, identity, attempt_id, file_id, workspace_id)
    original = staging_file(settings)
    normalized = staging_file(settings)
    try:
        total = 0
        with original.open("xb") as stream:
            os.chmod(original, 0o600)
            async for chunk in request.stream():
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise ApiError(413, "IMAGE_TOO_LARGE", "单张图片不能超过 10 MiB，本次图片未接收。")
                await asyncio.to_thread(stream.write, chunk)
        if not total:
            raise ApiError(422, "INVALID_IMAGE", "没有收到图片内容，请重新选择。")
        media_type, size, digest = await asyncio.to_thread(normalize_image, original, normalized, declared)
        return await asyncio.to_thread(uploads.finish_upload, engine, settings, identity, attempt_id, file_id,
                                       normalized, media_type, size, digest, workspace_id)
    except OSError:
        raise ApiError(503, "STORAGE_UNAVAILABLE", "图片存储失败，当前未完成上传，请重试。") from None
    finally:
        original.unlink(missing_ok=True)
        normalized.unlink(missing_ok=True)


def download_own(request: Request, identity: Actor, attempt_id: UUID, file_id: UUID, workspace_id: UUID | None = None) -> FileResponse:
    path, media_type = uploads.own_image(request.app.state.engine, request.app.state.settings, identity, attempt_id, file_id, workspace_id)
    return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})


@router.put("/workspaces/{workspace_id}/attempts/{attempt_id}/uploads/{file_id}")
async def trial_upload(workspace_id: UUID, attempt_id: UUID, file_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return await receive_upload(request, identity, attempt_id, file_id, workspace_id)


@router.put("/student/attempts/{attempt_id}/uploads/{file_id}")
async def student_upload(attempt_id: UUID, file_id: UUID, request: Request, identity: Student) -> dict[str, Any]:
    return await receive_upload(request, identity, attempt_id, file_id)


@router.put("/guest/attempts/{attempt_id}/uploads/{file_id}")
async def guest_upload(attempt_id: UUID, file_id: UUID, request: Request, identity: Guest) -> dict[str, Any]:
    return await receive_upload(request, identity, attempt_id, file_id)


@router.get("/workspaces/{workspace_id}/attempts/{attempt_id}/files/{file_id}")
def trial_image(workspace_id: UUID, attempt_id: UUID, file_id: UUID, request: Request, identity: Identity) -> FileResponse:
    return download_own(request, identity, attempt_id, file_id, workspace_id)


@router.get("/student/attempts/{attempt_id}/files/{file_id}")
def student_image(attempt_id: UUID, file_id: UUID, request: Request, identity: Student) -> FileResponse:
    return download_own(request, identity, attempt_id, file_id)


@router.get("/guest/attempts/{attempt_id}/files/{file_id}")
def guest_image(attempt_id: UUID, file_id: UUID, request: Request, identity: Guest) -> FileResponse:
    return download_own(request, identity, attempt_id, file_id)


@router.delete("/workspaces/{workspace_id}/attempts/{attempt_id}/files/{file_id}", status_code=204)
def trial_remove(workspace_id: UUID, attempt_id: UUID, file_id: UUID, request: Request, identity: Identity) -> None:
    uploads.remove_unused(request.app.state.engine, request.app.state.settings, identity, attempt_id, file_id, workspace_id)


@router.delete("/student/attempts/{attempt_id}/files/{file_id}", status_code=204)
def student_remove(attempt_id: UUID, file_id: UUID, request: Request, identity: Student) -> None:
    uploads.remove_unused(request.app.state.engine, request.app.state.settings, identity, attempt_id, file_id, None)


@router.delete("/guest/attempts/{attempt_id}/files/{file_id}", status_code=204)
def guest_remove(attempt_id: UUID, file_id: UUID, request: Request, identity: Guest) -> None:
    uploads.remove_unused(request.app.state.engine, request.app.state.settings, identity, attempt_id, file_id, None)


@router.get("/workspaces/{workspace_id}/classrooms/{classroom_id}/files/{file_id}")
def teacher_image(workspace_id: UUID, classroom_id: UUID, file_id: UUID, request: Request, identity: Identity) -> FileResponse:
    with workspace_transaction(request.app.state.engine, identity, workspace_id) as (connection, workspace):
        require_object(connection, identity, workspace, classroom_id, "classroom", "records.read")
        asset = connection.execute(text("""
            SELECT f.media_type, f.byte_size FROM image_assets f
            JOIN activity_attempts a ON a.workspace_id=f.workspace_id AND a.id=f.attempt_id
            WHERE f.workspace_id=:space AND f.id=:id AND f.status='ready' AND a.classroom_id=:classroom
              AND EXISTS(SELECT 1 FROM image_references r WHERE r.workspace_id=f.workspace_id AND r.file_id=f.id AND r.kind='submission')
            FOR SHARE OF f
        """), {"space": workspace_id, "id": file_id, "classroom": classroom_id}).mappings().one_or_none()
        if asset is None:
            raise ApiError(404, "NOT_FOUND", "当前课堂没有可查看的该图片提交。")
        path = file_path(request.app.state.settings, workspace_id, file_id)
        if not path.is_file() or path.stat().st_size != asset["byte_size"]:
            raise ApiError(503, "STORAGE_UNAVAILABLE", "图片存储暂不可用。")
        return FileResponse(path, media_type=asset["media_type"], headers={"Content-Disposition": "inline", "Cache-Control": "no-store"})
