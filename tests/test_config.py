from __future__ import annotations

import pytest
from pydantic import ValidationError

from local_agent_gateway.config import Settings, get_settings

pytestmark = pytest.mark.api


def settings(**overrides) -> Settings:
    values = {"bearer_token": "test-token-at-least-sixteen-characters", "allowed_models": "model-a, model-b"}
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("field", ["allowed_backends", "allowed_models"])
def test_allowlist_must_not_be_empty(field: str) -> None:
    with pytest.raises(ValidationError, match="allowlist must not be empty"):
        settings(**{field: " , "})


@pytest.mark.parametrize("url", ["https://example.com/v1", "http://192.168.1.10:11434/v1"])
def test_upstream_must_be_loopback(url: str) -> None:
    with pytest.raises(ValidationError, match="loopback"):
        settings(ollama_base_url=url)


def test_remote_upstream_requires_explicit_opt_in() -> None:
    configured = settings(ollama_base_url="http://ollama:11434/v1", allow_remote_upstream=True)
    assert configured.ollama_base_url.host == "ollama"


def test_only_local_backends_are_supported() -> None:
    with pytest.raises(ValidationError, match="only local backends"):
        settings(allowed_backends="ollama,openrouter")


def test_mlx_backend_is_supported_on_loopback() -> None:
    configured = settings(
        allowed_backends="ollama,mlx",
        mlx_base_url="http://127.0.0.1:8080/v1",
    )
    assert configured.backend_allowlist == frozenset({"ollama", "mlx"})


def test_mlx_upstream_must_remain_loopback_even_when_remote_ollama_is_enabled() -> None:
    with pytest.raises(ValidationError, match="MLX base URL must use a loopback host"):
        settings(
            allowed_backends="ollama,mlx",
            mlx_base_url="http://example.com/v1",
            allow_remote_upstream=True,
        )


def test_default_backend_must_be_allowlisted() -> None:
    with pytest.raises(ValidationError, match="default backend must be allowlisted"):
        settings(default_backend="other")


def test_allowlist_properties_trim_and_deduplicate() -> None:
    configured = settings(allowed_backends=" ollama,ollama ", allowed_models=" model-a, model-b,model-a ")
    assert configured.backend_allowlist == frozenset({"ollama"})
    assert configured.model_allowlist == frozenset({"model-a", "model-b"})


def test_get_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("GATEWAY_BEARER_TOKEN", "environment-token-at-least-sixteen")
    monkeypatch.setenv("GATEWAY_ALLOWED_MODELS", "environment-model")
    assert get_settings().model_allowlist == frozenset({"environment-model"})
    get_settings.cache_clear()
