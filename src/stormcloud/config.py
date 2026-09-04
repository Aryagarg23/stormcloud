from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STORMCLOUD_", env_file=".env", extra="ignore")
    env: str = "development"
    cors_origins: str = "http://localhost:5173"
    allowed_hosts: str = "localhost,127.0.0.1,testserver"
    public_docs: bool = True
    auth_rate_limit_per_minute: int = Field(default=30, ge=5, le=1000)
    database_url: str = "postgresql+psycopg://stormcloud:change-me@postgres:5432/stormcloud"
    nats_url: str = "nats://nats:4222"
    nats_stream: str = "STORMCLOUD"
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = "stormcloud"
    s3_secret_key: SecretStr = SecretStr("change-me-object-store")
    s3_region: str = "us-east-1"
    s3_bucket_raw: str = "stormcloud-source-raw"
    s3_bucket_normalized: str = "stormcloud-source-normalized"
    s3_bucket_derived: str = "stormcloud-derived"
    jwt_secret: SecretStr = SecretStr("development-secret-change-me-at-least-32-chars")
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    invitation_hours: int = 72
    invite_accept_url: str = "http://localhost:3000/accept-invite"
    debug_return_invite_token: bool = False
    smtp_host: str = "mailpit"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str = "stormcloud@localhost"
    smtp_starttls: bool = False
    fetcher_base_url: str = "http://source-extractor:8090"
    fetcher_token: SecretStr = SecretStr("development-fetcher-token-change-me")
    fetcher_timeout_seconds: float = 120
    fetcher_max_bytes: int = 20 * 1024 * 1024
    model_gateway_url: str = "http://model-gateway:8085"
    model_config_path: Path = Path("config/models.yaml")
    prompt_root: Path = Path("config/prompts")
    model_gateway_fake: bool = False
    embedding_profile: str = "qwen3-embed-fast-v1"
    similarity_threshold: float = Field(default=0.72, ge=-1, le=1)
    similarity_top_k: int = Field(default=20, ge=1, le=500)
    worker_role: str = "controller"
    worker_batch_size: int = 20
    worker_poll_seconds: float = 1.0
    max_attempts: int = 5
    log_level: str = "INFO"
    code_version: str = "0.1.0"

    @property
    def cors_origin_list(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [value.strip() for value in self.allowed_hosts.split(",") if value.strip()]

    @model_validator(mode="after")
    def production_security(self):
        if self.env.lower() == "production":
            secrets = (
                self.database_url,
                self.s3_secret_key.get_secret_value(),
                self.jwt_secret.get_secret_value(),
                self.fetcher_token.get_secret_value(),
            )
            if any("change-me" in value or "development-secret" in value for value in secrets):
                raise ValueError("production secrets must be replaced")
            if "*" in self.cors_origin_list:
                raise ValueError("wildcard CORS is forbidden in production")
            if self.debug_return_invite_token:
                raise ValueError("invitation tokens cannot be returned in production")
            if not self.allowed_host_list:
                raise ValueError("at least one allowed host is required in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
