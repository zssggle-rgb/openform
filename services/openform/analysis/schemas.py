from typing import Literal
from uuid import UUID

from pydantic import Field

from openform.identity.schemas import Input


class AnalysisInput(Input):
    prompt: str = Field(default="围绕教学目标归纳错误、开放回答与再次讲解建议。", min_length=1, max_length=4000)
    request_key: UUID


class Evidence(Input):
    record_id: UUID
    question_id: str = Field(min_length=1, max_length=80)


class Finding(Input):
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=1500)
    evidence: list[Evidence] = Field(min_length=1, max_length=10)


class Diagnosis(Input):
    overview: str = Field(min_length=1, max_length=3000)
    findings: list[Finding] = Field(max_length=20)
    suggestions: list[Finding] = Field(max_length=20)
    limitations: list[str] = Field(max_length=20)


class ReviewInput(Input):
    expected_revision: int = Field(ge=1)
    confirmed: Literal[True]


class ShareInput(ReviewInput):
    text: str = Field(max_length=2000)
