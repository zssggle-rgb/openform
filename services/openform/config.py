import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
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
    file_directory: Path = Path(".local/files")
    workspace_file_quota: int = Field(default=1024 * 1024 * 1024, ge=10 * 1024 * 1024)
    record_retention_days: int = Field(default=365, ge=1, le=3650)
    workspace_transfer_byte_quota: int = Field(default=500 * 1024 * 1024, ge=20 * 1024 * 1024)
    minimum_free_disk_bytes: int = Field(default=256 * 1024 * 1024, ge=10 * 1024 * 1024)
    model_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    model_id: str = "deepseek-v4-flash-ga-260731"
    model_api_key_file: Path | None = None
    operator_key_file: Path | None = None
    model_max_tokens: int = Field(default=16384, ge=1024, le=32768)
    model_timeout: int = Field(default=180, ge=10, le=300)
    workspace_model_token_quota: int = Field(default=1000000, ge=32768)
    dispatch_database_url: SecretStr | None = None
    dispatch_database_password_file: Path | None = None

    @field_validator("model_base_url")
    @classmethod
    def approved_model_address(cls, value: str) -> str:
        # Initial adapter supports only the endpoint explicitly approved by the instance owner.
        if value != "https://ark.cn-beijing.volces.com/api/v3":
            raise ValueError("当前仅支持已批准的火山引擎方舟地址。")
        return value

    @field_validator("app_origin", "runtime_origin")
    @classmethod
    def origin_only(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (not re.fullmatch(r"https?://(?:[A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]{1,5})?", value)
                or parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError("域名配置必须是完整 origin，不含路径或凭据。")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("域名配置端口无效。")
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
