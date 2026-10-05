from pathlib import Path
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENFORM_", hide_input_in_errors=True)

    database_url: SecretStr
    database_password_file: Path | None = None
    web_directory: Path | None = None
    app_origin: str = "http://localhost:5173"
    runtime_origin: str = "http://localhost:5174"
    environment: str = "development"

    @field_validator("app_origin", "runtime_origin")
    @classmethod
    def origin_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("域名配置必须是完整 origin，不含路径或凭据。")
        return value

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("需要有效的 PostgreSQL 连接配置。") from None
        if url.drivername != "postgresql+psycopg" or not url.host or not url.database:
            raise ValueError("需要 PostgreSQL + psycopg，不能用 SQLite 代替。")
        return value

    def connection_url(self) -> URL:
        url = make_url(self.database_url.get_secret_value())
        if self.database_password_file is not None:
            password = self.database_password_file.read_text().strip()
            if not password:
                raise ValueError("数据库凭据文件为空。")
            url = url.set(password=password)
        return url
