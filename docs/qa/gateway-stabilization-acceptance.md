# Gateway stabilization: read-only acceptance brief

## Boundary

Review the `codex/gateway-stabilization` branch without editing files, creating
commits, reading `.env`, or contacting a real model. The tests start only fake
loopback backends and use synthetic credentials.

## Commands

```sh
uv run ruff check .
uv run mypy src
uv run pytest --cov=local_agent_gateway --cov-fail-under=90
uv run pytest -q -s tests/e2e/test_recovery.py tests/e2e/test_stability.py
```

## Required evidence

- `main.run()` binds only to `127.0.0.1`; the configured local port must not
  change that host.
- Missing bearer, non-allowlisted backend/model, and oversized body must stop
  before an upstream call. The chunked-body test must show that the second body
  chunk is not read.
- `/health` is process liveness. `/ready` must return `200` only with the fake
  backend reachable and neutral `503 backend not ready` after it stops.
- Timeout and non-SSE upstream response must be neutral `502`. An incomplete
  or invalid SSE response must contain no backend detail and finish with a
  `gateway_error` plus `[DONE]`.
- Concurrent requests must retain their own request IDs and response bodies.
  The output must report 12 successful requests, 12 backend calls, p50/p95,
  and successful restart after both Ctrl+C and SIGKILL.

## Report format

Return `PASS` or `FAIL`, the exact command outputs/counts, and one concrete
reproduction for every failure. A completed empty turn is not an acceptance.
