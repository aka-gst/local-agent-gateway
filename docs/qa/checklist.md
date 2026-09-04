# Release checklist

## Security and configuration

- [ ] Gateway binds to `127.0.0.1`, not all interfaces.
- [ ] Upstream URL uses a loopback host.
- [ ] Bearer token contains at least 16 characters.
- [ ] `.env`, Allure data, coverage data, and browser artifacts are ignored.
- [ ] No real tokens, prompts, private paths, or stack traces appear in output.
- [ ] Only configured models and backends reach the upstream.

## API behavior

- [ ] `GET /health` returns `200` and a request ID.
- [ ] `GET /ready` confirms the configured backend, or returns neutral `503`.
- [ ] Missing/invalid authentication returns a neutral `401`.
- [ ] Incorrect media type and malformed JSON are rejected.
- [ ] Oversized requests return `413` before proxying.
- [ ] Valid non-streaming requests preserve the contract.
- [ ] Valid streaming requests preserve SSE content type and `[DONE]`.
- [ ] Upstream timeouts/network/HTTP errors become safe `502` responses.
- [ ] Upstream streams are closed after completion.
- [ ] Interrupted or malformed SSE emits a neutral terminal SSE error, never
  backend details.
- [ ] Chunked oversized input stops reading before proxying.
- [ ] Concurrent requests remain isolated; graceful and forced-stop restart
  checks pass against the fake backend.

## UI and reports

- [ ] QA console health state is visible.
- [ ] Successful Chromium scenario displays the assistant response.
- [ ] Invalid token scenario displays a readable error.
- [ ] LLM evaluation emits JSON and Markdown reports.
- [ ] Allure contains environment, feature, story, and severity metadata.
- [ ] GitHub Pages shows the latest 79-test report and trend history.

## Delivery

- [ ] `uv run pytest ... --cov-fail-under=90` passes.
- [ ] Package build succeeds.
- [ ] Git worktree contains no unintended artifacts.
- [ ] GitHub Actions completes both test and Pages deployment jobs.
- [ ] README metrics, screenshots, links, and release notes are current.
