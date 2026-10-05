import asyncio
import os
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response

from openform.activities.schemas import TrialInput
from openform.assets.storage import staging_file
from openform.errors import ApiError
from openform.identity.routes import Identity
from openform.school.lifecycle import DeleteInput
from openform.transfers import archives, exports, imports
from openform.transfers.packages import MAX_ZIP_BYTES

router = APIRouter(prefix="/api/workspaces/{workspace_id}")


@router.post("/transfers/exports", status_code=201)
def export_create(workspace_id: UUID, data: exports.ExportInput, request: Request, identity: Identity) -> dict[str, Any]:
    return exports.enqueue_export(request.app.state.engine, identity, workspace_id, data)


@router.get("/transfers/exports")
def export_list(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return exports.list_exports(request.app.state.engine, identity, workspace_id, cursor)


@router.get("/transfers/exports/{export_id}")
def export_detail(workspace_id: UUID, export_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return exports.export_detail(request.app.state.engine, identity, workspace_id, export_id)


@router.get("/transfers/exports/{export_id}/file")
def export_download(workspace_id: UUID, export_id: UUID, request: Request, identity: Identity) -> FileResponse:
    path = exports.export_file(request.app.state.engine, request.app.state.settings, identity, workspace_id, export_id)
    return FileResponse(path, media_type="application/zip", filename=f"openform-{export_id}.zip", headers={"Cache-Control": "no-store"})


@router.put("/transfers/uploads/{request_key}", status_code=201)
async def import_upload(workspace_id: UUID, request_key: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    settings = request.app.state.settings
    # Authorize target before consuming a possibly large request body.
    def authorize() -> None:
        from openform.identity.context import workspace_transaction
        with workspace_transaction(request.app.state.engine, identity, workspace_id) as (_, workspace):
            if not workspace["is_teacher"]:
                raise ApiError(403, "FORBIDDEN", "需要目标空间教学权限。")
    await asyncio.to_thread(authorize)
    path = await asyncio.to_thread(staging_file, settings)
    try:
        size = 0
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_ZIP_BYTES:
                    raise ApiError(413, "PACKAGE_TOO_LARGE", "迁移包不得超过 20 MiB。")
                await asyncio.to_thread(stream.write, chunk)
        if not size:
            raise ApiError(422, "INVALID_PACKAGE", "未收到迁移包内容。")
        return await asyncio.to_thread(imports.preflight_import, request.app.state.engine, settings, identity, workspace_id, path, request_key)
    except OSError:
        raise ApiError(503, "STORAGE_UNAVAILABLE", "迁移包存储不可用，未创建活动或档案。") from None
    finally:
        path.unlink(missing_ok=True)


@router.get("/transfers/imports/{import_id}")
def import_detail(workspace_id: UUID, import_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return imports.import_detail(request.app.state.engine, identity, workspace_id, import_id)


@router.get("/transfers/imports")
def import_list(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None, request_key: UUID | None = None) -> dict[str, Any]:
    return imports.list_imports(request.app.state.engine, identity, workspace_id, cursor, request_key)


@router.post("/transfers/imports/{import_id}/commit")
def import_commit(workspace_id: UUID, import_id: UUID, data: imports.CommitInput, request: Request, identity: Identity) -> dict[str, Any]:
    return imports.commit_import(request.app.state.engine, request.app.state.settings, identity, workspace_id, import_id, data)


@router.get("/activities/{activity_id}/imported-versions")
def versions(workspace_id: UUID, activity_id: UUID, request: Request, identity: Identity) -> dict[str, Any]:
    return imports.imported_versions(request.app.state.engine, identity, workspace_id, activity_id)


@router.post("/activities/{activity_id}/imported-versions/{number}/restore")
def version_restore(workspace_id: UUID, activity_id: UUID, number: int, data: TrialInput, request: Request, identity: Identity) -> dict[str, Any]:
    return archives.restore_imported_version(request.app.state.engine, request.app.state.settings, identity, workspace_id, activity_id, number, data.expected_revision)


@router.get("/archives")
def archive_list(workspace_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return archives.list_archives(request.app.state.engine, identity, workspace_id, cursor)


@router.get("/archives/{archive_id}")
def archive_detail(workspace_id: UUID, archive_id: UUID, request: Request, identity: Identity, cursor: UUID | None = None) -> dict[str, Any]:
    return archives.archive_detail(request.app.state.engine, identity, workspace_id, archive_id, cursor)


@router.get("/archives/{archive_id}/records/{record_id}/files/{file_id}")
def archive_image(workspace_id: UUID, archive_id: UUID, record_id: UUID, file_id: UUID, request: Request, identity: Identity) -> Response:
    content, media_type = archives.archive_image(request.app.state.engine, request.app.state.settings, identity, workspace_id, archive_id, record_id, file_id)
    return Response(content, media_type=media_type, headers={"Cache-Control": "no-store", "Content-Disposition": "inline"})


@router.delete("/archives/{archive_id}", status_code=204)
def archive_delete(workspace_id: UUID, archive_id: UUID, data: DeleteInput, request: Request, identity: Identity) -> None:
    archives.delete_archive(request.app.state.engine, identity, workspace_id, archive_id, data)
