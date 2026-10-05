from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text


def shared_content(connection: Connection, space: UUID, classroom: dict[str, Any]) -> dict[str, Any]:
    """Caller must verify participation and current classroom eligibility first."""
    rows = connection.execute(text("""
      SELECT r.shared_text,r.shared_at,s.captured_at,s.payload->'coverage' AS coverage FROM analysis_reports r
      JOIN analysis_snapshots s ON s.workspace_id=r.workspace_id AND s.id=r.snapshot_id
      WHERE s.workspace_id=:space AND s.classroom_id=:id AND s.invalidated_at IS NULL AND s.data_epoch=:epoch
        AND r.reviewed_at IS NOT NULL AND r.shared_text IS NOT NULL ORDER BY r.shared_at DESC LIMIT 10
    """), {"space": space, "id": classroom["id"], "epoch": classroom["data_epoch"]}).mappings().all()
    return {"items": [dict(row) for row in rows]}
