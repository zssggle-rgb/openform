import base64
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, text

from openform.activities.service import require_activity
from openform.errors import ApiError
from openform.identity.authorization import require_object
from openform.identity.context import StaffIdentity


def draft_source(connection: Connection, identity: StaffIdentity, workspace: dict[str, Any], activity_id: UUID) -> dict[str, Any]:
    require_object(connection, identity, workspace, activity_id, "activity", "activity.edit")
    activity = require_activity(connection, workspace["id"], activity_id)
    assets = connection.execute(text("SELECT assets FROM activity_sources WHERE workspace_id=:space AND package_digest=:digest"),
                                {"space": workspace["id"], "digest": activity["package_digest"]}).scalar_one()
    return {"manifest": activity["manifest"], "grading": activity["grading"], "assets": assets,
            "expected_revision": activity["draft_revision"]}


def model_source(source: dict[str, Any]) -> dict[str, Any]:
    if sum(len(value) for value in source["assets"].values()) > 128 * 1024:
        raise ApiError(413, "MODEL_INPUT_TOO_LARGE", "当前页面超过模型修改的 128 KiB 上限，请手动修改或导入精简页面。")
    try:
        files = {path: base64.b64decode(value, validate=True).decode("utf-8") for path, value in source["assets"].items()}
    except (ValueError, UnicodeDecodeError):
        raise ApiError(422, "MODEL_UNSUPPORTED_SOURCE", "当前页面含二进制资源，请手动导入修改；模型首版只修改文本页面包。") from None
    manifest = {key: value for key, value in source["manifest"].items() if key != "assets"}
    return {"manifest": manifest, "grading": source["grading"], "files": files}
