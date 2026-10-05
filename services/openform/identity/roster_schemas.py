import re
from uuid import UUID

from pydantic import Field, field_validator

from openform.identity.schemas import Input


class ClassInput(Input):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名称不能为空。")
        return value.strip()


class ClassChangeInput(ClassInput):
    active: bool = True
    expected_revision: int = Field(ge=1)


class AssignmentInput(Input):
    subject: str = Field(min_length=1, max_length=40)
    active: bool = True
    expected_revision: int = Field(default=0, ge=0)

    @field_validator("subject")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("任教学科不能为空。")
        return value.strip()


class StudentInput(Input):
    reference: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    class_id: UUID | None = None

    @field_validator("reference", "display_name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("学生编号与姓名不能为空。")
        return value.strip()


class StudentChangeInput(StudentInput):
    active: bool = True
    expected_revision: int = Field(ge=1)


class CredentialInput(Input):
    expected_epoch: int = Field(ge=1)


class StudentCodeInput(Input):
    code: str = Field(min_length=16, max_length=23)

    @field_validator("code")
    @classmethod
    def normalize(cls, value: str) -> str:
        value = value.replace("-", "").replace(" ", "").upper()
        if not re.fullmatch(r"[A-HJ-NP-Z2-9]{16}", value):
            raise ValueError("请输入 16 位个人进入码。")
        return value
