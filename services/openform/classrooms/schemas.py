from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from openform.identity.schemas import Input


class GroupInput(Input):
    name: str = Field(min_length=1, max_length=80)
    recorder_id: UUID
    members: list[UUID] = Field(min_length=1, max_length=50)


class ClassroomInput(Input):
    version_id: UUID
    title: str = Field(min_length=1, max_length=80)
    class_id: UUID | None = None
    groups: list[GroupInput] = Field(default_factory=list, max_length=100)

    @field_validator("title")
    @classmethod
    def title_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("课堂名称不能为空。")
        return value.strip()


class StateInput(Input):
    state: Literal["open", "paused", "ended"]
    expected_revision: int = Field(ge=1)


class JoinInput(Input):
    code: str = Field(pattern=r"^[A-Z2-9]{8}$")


class AttemptInput(Input):
    previous_attempt_id: UUID


class GuestInput(JoinInput):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def name_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("显示名称不能为空。")
        return value.strip()
