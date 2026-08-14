# Changelog

## 0.2.1

- hardened live evaluation with bounded deterministic generation, retries,
  neutral per-run errors, and partial report preservation;
- grounded project-specific evaluation cases to detect hallucinated commands;
- recorded a reproducible 9-run qwen3:8b benchmark on Apple Silicon.

## 0.2.0

- expanded the deterministic suite from 13 to 48 tests;
- raised Python coverage from 78% to 99% with a 90% CI gate;
- added real-HTTP SSE streaming E2E coverage;
- added readable Allure features, stories, severities, environment data, and
  cross-run trend history;
- added a test plan, release checklist, traceability matrix, live-eval guide,
  and regression-oriented defect reports;
- added optional live Ollama/OpenRouter evaluations with pass-rate, stability,
  latency, token, estimated-cost, and prompt-injection gates;
- added a safe Docker image and loopback-published Ollama Compose stack;
- expanded the QA console with SSE streaming, latency, raw response inspection,
  and a browser evaluation suite.

## 0.1.0

- introduced API, browser, and deterministic LLM evaluation tests;
- added coverage, Allure, GitHub Actions, GitHub Pages, and the QA console.
