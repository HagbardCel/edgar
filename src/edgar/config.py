"""Application settings (pydantic-settings)."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    sec_user_agent: str = Field(default="", alias="SEC_USER_AGENT")
    edgar_data_root: Path = Field(default=Path("var"), alias="EDGAR_DATA_ROOT")
    sec_requests_per_second: float = Field(default=5.0, alias="SEC_REQUESTS_PER_SECOND")
    sec_timeout_seconds: float = Field(default=60.0, alias="SEC_TIMEOUT_SECONDS")
    sec_max_retries: int = Field(default=4, alias="SEC_MAX_RETRIES")
    max_redirects: int = Field(default=5, alias="MAX_REDIRECTS")
    max_file_bytes: int = Field(default=104_857_600, alias="MAX_FILE_BYTES")
    max_bundle_bytes: int = Field(default=524_288_000, alias="MAX_BUNDLE_BYTES")
    max_external_dependency_bytes: int = Field(
        default=524_288_000, alias="MAX_EXTERNAL_DEPENDENCY_BYTES"
    )
    edgar_database_url: str | None = Field(default=None, alias="EDGAR_DATABASE_URL")

    @property
    def sec_min_interval_seconds(self) -> float:
        if self.sec_requests_per_second <= 0:
            return 0.2
        return 1.0 / self.sec_requests_per_second

    @field_validator("sec_user_agent")
    @classmethod
    def _ua_optional_until_live(cls, value: str) -> str:
        return value.strip()

    def require_user_agent(self) -> str:
        if not self.sec_user_agent or "@" not in self.sec_user_agent:
            raise ValueError(
                "SEC_USER_AGENT must identify the requester, e.g. 'Name email@example.com'"
            )
        return self.sec_user_agent

    def require_database_url(self) -> str:
        url = (self.edgar_database_url or "").strip()
        if not url:
            raise ValueError(
                "EDGAR_DATABASE_URL is required for database operations "
                "(e.g. postgresql+psycopg://edgar:edgar@localhost:5432/edgar)"
            )
        return url
