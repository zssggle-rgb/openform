from uuid import UUID

from pydantic import Field

from openform.identity.schemas import Input


class PublicationInput(Input):
    version_id: UUID
    subject: str = Field(max_length=40)
    grade: str = Field(max_length=40)
    expected_revision: int = Field(ge=0)


class CopyInput(Input):
    number: int = Field(ge=1)
    request_key: UUID


class WithdrawalInput(Input):
    expected_revision: int = Field(ge=1)
