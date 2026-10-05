import hashlib
import os
from pathlib import Path
from uuid import UUID

from sqlalchemy import Connection, text

from openform.config import Settings
from openform.errors import ApiError


def artifact_path(settings: Settings, space: UUID, artifact_id: UUID) -> Path:
    return settings.file_directory / "transfers" / str(space) / f"{artifact_id}.zip"


def persist_file(source: Path, destination: Path) -> tuple[int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(source, 0o600)
    with source.open("rb") as stream:
        os.fsync(stream.fileno())
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    # Each artifact has a server-generated UUID; never replace a committed artifact.
    os.link(source, destination)
    for directory in (destination.parent, destination.parent.parent, destination.parent.parent.parent):
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return destination.stat().st_size, digest


def require_capacity(connection: Connection, settings: Settings, space: UUID, byte_size: int) -> None:
    used = connection.execute(text("""
      SELECT (SELECT coalesce(sum(byte_size),0) FROM transfer_imports WHERE workspace_id=:space AND status<>'expired')+
             (SELECT coalesce(sum(byte_size),0) FROM transfer_exports WHERE workspace_id=:space AND status='succeeded')+
             (SELECT coalesce(sum(pg_column_size(body)),0) FROM archive_records WHERE workspace_id=:space)+
             (SELECT coalesce(sum(pg_column_size(draft)),0) FROM imported_resource_versions WHERE workspace_id=:space)
    """), {"space": space}).scalar_one()
    if used + byte_size > settings.workspace_transfer_byte_quota:
        raise ApiError(507, "TRANSFER_STORAGE_FULL", "当前空间迁移包存储额度不足，未公开新活动或档案。")
