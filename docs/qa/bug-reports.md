# Regression-oriented bug reports

These are portfolio defect reports derived from concrete automated regression
scenarios. “Guarded” means the current implementation passes a test that would
fail if the defect were introduced; it does not claim the defect occurred in a
production environment.

## BUG-001 — Upstream details can leak through gateway failures

- Severity: Critical
- Status: Guarded by automated tests
- Preconditions: Authenticated request; upstream returns an exception, private
  error body, or malformed JSON.
- Steps: Send a valid chat request while forcing each upstream failure mode.
- Expected: Client receives a neutral `502`; token, prompt, filesystem path,
  traceback, and upstream body are absent from response and logs.
- Regression evidence: connection, timeout, upstream HTTP, invalid JSON, and
  sensitive-output tests in `tests/test_gateway.py`.

## BUG-002 — Disallowed model reaches local inference backend

- Severity: Critical
- Status: Guarded by automated tests
- Steps: Authenticate, select a model outside `GATEWAY_ALLOWED_MODELS`, and
  submit a valid message.
- Expected: `400 model not allowed`; mock upstream records no network call.
- Risk: Unapproved model use, unexpected resource consumption, or policy bypass.
- Regression evidence: `test_disallowed_model_is_rejected_before_network_call`.

## BUG-003 — Streaming response is buffered, truncated, or not closed

- Severity: Blocker
- Status: Guarded at integration and real-HTTP levels
- Steps: Submit `stream=true` and consume events through `[DONE]`.
- Expected: SSE content type is preserved, every delta arrives in order, request
  ID is retained, `[DONE]` is present, and upstream closes.
- Regression evidence: mock stream lifecycle test and real HTTP streaming E2E.

## BUG-004 — Oversized payload reaches application/upstream

- Severity: High
- Status: Guarded by middleware boundary test
- Steps: Send a body larger than `GATEWAY_MAX_REQUEST_BYTES` with a valid token.
- Expected: Immediate `413 request too large`; no upstream call.
- Risk: unnecessary memory use and denial-of-service amplification.
- Regression evidence: `test_oversized_request_is_rejected_by_middleware`.

## BUG-005 — User sees success while authentication actually failed

- Severity: High
- Status: Guarded in Chromium
- Steps: Open `/demo`, enter an invalid token, and submit a prompt.
- Expected: UI displays `HTTP 401: unauthorized`, not an empty or successful
  assistant response.
- Regression evidence: `test_demo_rejects_invalid_token`.

## BUG-006 — One Ollama disconnect destroys the complete live report

- Severity: High
- Status: Found by live testing; fixed and regression-guarded
- Observed: A shared Ollama process disconnected during a nine-run evaluation.
  The CLI printed a traceback and lost completed measurements.
- Expected: Retry a transient transport failure; if it persists, record a
  neutral failed run, continue remaining cases, and write the report.
- Fix: bounded exponential retries and per-run neutral error records.
- Regression evidence: transient and persistent disconnect tests in
  `tests/test_live_evaluation.py`.

## BUG-007 — Thinking model can make a short evaluation run indefinitely

- Severity: High
- Status: Found by live testing; fixed and regression-guarded
- Observed: qwen3:8b spent several minutes on short prompts because generation
  length and reasoning mode were not controlled.
- Expected: Regression profile is bounded and reproducible.
- Fix: defaults of `max_tokens=256`, `temperature=0`, `seed=42`, and
  `reasoning_effort=none`; each remains configurable for separate benchmarks.
- Regression evidence: request-contract assertions in live evaluator tests.
