import base64
import hashlib
import json
from typing import Any

from pydantic import Field

from openform.activities.schemas import DraftInput
from openform.identity.schemas import Input


class PageInput(Input):
    manifest: dict[str, Any]
    files: dict[str, str] = Field(min_length=1, max_length=100)
    grading: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


def page_draft(page: PageInput, revision: int) -> DraftInput:
    assets = {path: content.encode("utf-8") for path, content in page.files.items()}
    types = {"html": "text/html", "css": "text/css", "js": "text/javascript"}
    manifest = {**page.manifest, "assets": [{"path": path, "sha256": hashlib.sha256(content).hexdigest(),
                 "mediaType": types.get(path.rsplit(".", 1)[-1], "unsupported")} for path, content in assets.items()]}
    return DraftInput(manifest=manifest, assets={path: base64.b64encode(content).decode() for path, content in assets.items()},
                      grading=page.grading, expected_revision=revision)


def model_page(content: str, revision: int) -> DraftInput:
    value = content.strip()
    if value.startswith("```json") and value.endswith("```"):
        value = value[7:-3].strip()
    return page_draft(PageInput.model_validate(json.loads(value)), revision)
