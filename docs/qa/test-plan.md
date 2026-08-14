# Test plan: Local Agent Gateway

## Objective

Verify that the loopback-only gateway safely accepts OpenAI-compatible chat
requests, enforces its security boundaries, proxies valid traffic to a local
Ollama-compatible upstream, and fails without exposing secrets.

## Scope

- configuration validation and loopback enforcement;
- bearer authentication and allowlists;
- JSON validation and request-size boundaries;
- non-streaming and streaming proxy behavior;
- upstream timeout, network, HTTP, and malformed-response failures;
- request-ID creation and propagation;
- browser interaction with the QA console;
- deterministic response-quality and secret-leak rules;
- CLI startup parameters and generated reports.

## Out of scope for the deterministic CI suite

- quality of a particular downloaded Ollama model;
- GPU performance and model installation;
- public internet exposure (the product explicitly rejects this deployment);
- authentication protocols other than the configured bearer token;
- high-volume load and long-running soak tests.

Live-model, performance, and stability evaluations are optional suites because
their results depend on hardware, model, provider, and network availability.

## Test levels

| Level | Purpose | Isolation |
|---|---|---|
| Unit | Scoring, configuration, and CLI decisions | No network |
| API integration | FastAPI middleware, validation, proxy, and error mapping | In-process mock transport |
| HTTP E2E | Real gateway and fake Ollama processes, including SSE streaming | Loopback network only |
| Browser E2E | User submits success and failure scenarios in Chromium | Loopback network only |
| LLM evaluation | Required content, forbidden content, similarity, and thresholds | Deterministic dataset |

## Environments

- local macOS ARM with a uv-managed Python environment and Chromium;
- GitHub-hosted Ubuntu runner with Python 3.12 and Chromium;
- optional real Ollama/OpenRouter evaluation environment.

No real token is stored in source control. CI tests use synthetic credentials.

## Entry criteria

- dependencies resolve from `uv.lock`;
- Chromium is installed for Playwright;
- synthetic ports are available on loopback;
- no populated `.env` file is committed.

## Exit criteria

- all deterministic tests pass;
- Python coverage is at least 90%;
- no critical or blocker regression remains open;
- Allure and evaluation artifacts are generated;
- build succeeds and GitHub Pages publishes the report.

## Primary risks

1. Authentication bypass or secret leakage.
2. A disallowed model/backend reaching the upstream.
3. Streaming responses being buffered, truncated, or left open.
4. Internal upstream details reaching a client or logs.
5. UI success while the actual API contract is broken.
6. Non-reproducible tests that require a real model or paid provider.

## Test data strategy

Synthetic values deliberately resemble production-shaped data but are not real
credentials or personal information. Golden responses are small and reviewed.
Live outputs are saved only to ignored report directories.

## Reporting

- pytest is the pass/fail source of truth;
- coverage prevents untested regressions below the 90% threshold;
- Allure groups tests by API, E2E, and LLM evaluation and retains trends;
- Markdown/JSON LLM reports support both human and machine review.
