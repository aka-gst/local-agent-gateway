from __future__ import annotations

import pytest

from local_agent_gateway import main

pytestmark = pytest.mark.api


def test_cli_binds_only_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    captured = {}
    monkeypatch.setattr(main, "create_app", lambda: sentinel)
    monkeypatch.setattr(main.uvicorn, "run", lambda app, **kwargs: captured.update({"app": app, **kwargs}))
    main.run()
    assert captured == {"app": sentinel, "host": "127.0.0.1", "port": 8642, "access_log": False}
