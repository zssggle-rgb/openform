from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from openform.identity.schemas import Input


class DraftInput(Input):
    manifest: dict[str, Any]
    assets: dict[str, str] = Field(max_length=500)
    grading: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    expected_revision: int = Field(ge=0)


class PublishInput(Input):
    expected_revision: int = Field(ge=1)
    trial_id: UUID
    content_confirmed: Literal[True]


class TrialInput(Input):
    expected_revision: int = Field(ge=1)


class SampleInput(Input):
    kind: Literal["quiz", "words", "lab"]
