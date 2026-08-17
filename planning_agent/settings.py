from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    environment: str = "development"
    app_name: str = "Prometheus Planning AI"
    app_version: str = "2.0.0"
    planning_workspace: Path = Path("documents")
    planning_workbook: Path = Path("data/planning.xlsx")
    database_url: str = "sqlite:///data/planning_history.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = "kimi"
    allowed_llm_hosts: str = "127.0.0.1,localhost,host.docker.internal,ollama"
    auth_enabled: bool = False
    app_secret_key: str = ""
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = None
    trusted_hosts: str = "127.0.0.1,localhost,testserver"
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    rate_limit_per_minute: int = Field(default=60, ge=1, le=10_000)
    max_request_bytes: int = Field(default=1_048_576, ge=1024)
    job_timeout_seconds: int = Field(default=900, ge=30, le=86_400)
    metrics_enabled: bool = True
    otel_exporter_otlp_endpoint: str | None = None

    @model_validator(mode="after")
    def production_guards(self) -> "Settings":
        if self.environment.casefold() == "production":
            if not self.auth_enabled:
                raise ValueError("AUTH_ENABLED must be true in production")
            if len(self.app_secret_key) < 32:
                raise ValueError("APP_SECRET_KEY must contain at least 32 characters in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("Production requires PostgreSQL; DATABASE_URL cannot use SQLite")
        parsed = urlparse(self.local_llm_base_url)
        if parsed.hostname not in self.allowed_llm_host_set:
            raise ValueError(f"LOCAL_LLM_BASE_URL host is not allow-listed: {parsed.hostname}")
        return self

    @property
    def allowed_llm_host_set(self) -> set[str]:
        return {item.strip().casefold() for item in self.allowed_llm_hosts.split(",") if item.strip()}

    @property
    def trusted_host_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
