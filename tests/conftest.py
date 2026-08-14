from __future__ import annotations

import allure
import pytest


@pytest.fixture(autouse=True)
def readable_allure_metadata(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("e2e"):
        allure.dynamic.feature("End-to-end")
        allure.dynamic.severity(allure.severity_level.BLOCKER)
    elif request.node.get_closest_marker("llm_eval"):
        allure.dynamic.feature("LLM evaluation")
        allure.dynamic.severity(allure.severity_level.NORMAL)
    else:
        allure.dynamic.feature("Gateway API")
        allure.dynamic.severity(allure.severity_level.CRITICAL)
    allure.dynamic.story(request.node.name.replace("test_", "").replace("_", " "))


def pytest_sessionfinish(session: pytest.Session) -> None:
    allure_dir = session.config.getoption("--alluredir")
    if not allure_dir:
        return
    from pathlib import Path
    import platform

    destination = Path(allure_dir)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "environment.properties").write_text(
        f"Python={platform.python_version()}\nPlatform={platform.system()} {platform.machine()}\nSuite=local-agent-gateway\n",
        encoding="utf-8",
    )
