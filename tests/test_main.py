from __future__ import annotations

import pytest

from local_agent_gateway import main
from local_agent_gateway.config import Settings

pytestmark = pytest.mark.api


def test_cli_binds_only_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    captured = {}
    settings = Settings(
        bearer_token="test-token-at-least-sixteen-characters",
        allowed_models="local-test-model",
    )
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    monkeypatch.setattr(main, "create_app", lambda configured: sentinel)
    monkeypatch.setattr(main.uvicorn, "run", lambda app, **kwargs: captured.update({"app": app, **kwargs}))
    main.run()
    assert captured == {
        "app": sentinel,
        "host": "127.0.0.1",
        "port": 8642,
        "access_log": False,
        "timeout_graceful_shutdown": 5,
    }
