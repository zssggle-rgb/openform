from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginInput(Input):
    login: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")
    password: str = Field(min_length=1, max_length=256)

    @field_validator("login")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        return value.lower()

class RegistrationInput(LoginInput):
    display_name: str = Field(min_length=1, max_length=80)

    @field_validator("display_name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("显示名称不能为空。")
        return value.strip()

    @field_validator("password")
    @classmethod
    def strong_enough(cls, value: str) -> str:
        if len(value) < 12:
            raise ValueError("密码至少需要 12 个字符。")
        return value


class RoleInput(Input):
    is_teacher: bool = False
    is_admin: bool = False

    @model_validator(mode="after")
    def some_role(self) -> "RoleInput":
        if not self.is_teacher and not self.is_admin:
            raise ValueError("至少需要一个成员职责。")
        return self


class MemberInput(RoleInput):
    active: bool = True
    expected_epoch: int = Field(ge=1)


class InviteInput(RoleInput):
    target_login: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9._-]+$")


class InviteAcceptInput(Input):
    token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
