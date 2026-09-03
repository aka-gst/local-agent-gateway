from __future__ import annotations

from functools import lru_cache

from pydantic import Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GATEWAY_",
        extra="ignore",
    )

    bearer_token: str = Field(min_length=16)
    allowed_backends: str = "ollama"
    allowed_models: str = Field(min_length=1)
    default_backend: str = "ollama"
    ollama_base_url: HttpUrl = HttpUrl("http://127.0.0.1:11434/v1")
    mlx_base_url: HttpUrl = HttpUrl("http://127.0.0.1:8080/v1")
    allow_remote_upstream: bool = False
    upstream_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_request_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)

    @field_validator("allowed_backends", "allowed_models")
    @classmethod
    def nonempty_csv(cls, value: str) -> str:
        if not any(item.strip() for item in value.split(",")):
            raise ValueError("allowlist must not be empty")
        return value

    @model_validator(mode="after")
    def validate_backend_configuration(self) -> Settings:
        if self.ollama_base_url.host not in {"127.0.0.1", "localhost", "::1"} and not self.allow_remote_upstream:
            raise ValueError("Ollama base URL must use a loopback host unless remote upstream is explicitly enabled")
        if self.mlx_base_url.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("MLX base URL must use a loopback host")
        if not self.backend_allowlist.issubset({"ollama", "mlx"}):
            raise ValueError("only local backends are supported")
        if self.default_backend not in self.backend_allowlist:
            raise ValueError("default backend must be allowlisted")
        return self

    @property
    def backend_allowlist(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.allowed_backends.split(",") if item.strip())

    @property
    def model_allowlist(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.allowed_models.split(",") if item.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
