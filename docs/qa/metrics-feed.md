# Published metrics feed

The landing page of aka-gst.ru shows this project as a test run, not as a
marketing block. To keep that honest, the numbers on the page are read from the
same artifacts CI enforced, not retyped into HTML.

## Where it lives

| URL | Produced by | Updated |
|---|---|---|
| `https://aka-gst.github.io/local-agent-gateway/` | `allure-commandline generate` | Every successful push to `main` |
| `https://aka-gst.github.io/local-agent-gateway/qa-metrics.json` | `local-agent-qa-metrics` | Same deployment |
| `https://aka-gst.github.io/local-agent-gateway/qa-metrics-history.json` | `local-agent-qa-metrics` | Same deployment |

Both JSON files are copied into the Allure output directory before the Pages
artifact is uploaded, so a single `deploy-pages` step publishes the report and
the metrics together. A run therefore never serves a report and metrics that
disagree with each other.

GitHub Pages responds with `Access-Control-Allow-Origin: *`, so a static page on
another origin can fetch both files from the browser without a proxy.

## How it is updated

1. `pytest` writes `allure-results/` and `coverage.json`.
2. `local-agent-eval` writes `test-results/llm-evaluation.json`.
3. The workflow downloads the currently published `qa-metrics-history.json`.
4. `local-agent-qa-metrics` merges those inputs with the committed live
   benchmark and writes `test-results/qa-metrics.json` plus an appended
   `test-results/qa-metrics-history.json` (last 20 runs).
5. On a successful push to `main`, both files are copied next to the generated
   Allure HTML and deployed.

Steps 3 and 4 run with `if: always()`, so a failing run still uploads a report
artifact that says which suite failed. Only a green run reaches Pages, which
means the public feed always describes the last known-good state of `main`.

## Report schema

`qa-metrics.json`, schema `aka-gst.qa-metrics/1`:

| Field | Meaning |
|---|---|
| `generated_at` | ISO-8601 UTC timestamp of the run that produced the file |
| `project` | Package name, released version, repository and report URLs |
| `commit.sha` / `commit.short` / `commit.branch` / `commit.run_url` | Provenance of the run |
| `status` | `passed`, `failed`, or `unknown` across tests, coverage, and the deterministic evaluation |
| `headline[]` | Four ready-to-render cards: `tests`, `coverage`, `pass_rate`, `median_latency` |
| `tests` | Totals, per-status counts, wall-clock duration, and a per-suite breakdown by Allure feature |
| `coverage` | Measured percent, the CI threshold, covered and total statements |
| `evaluation.deterministic` | Case count, pass rate, and mean score of the offline golden-response suite |
| `evaluation.live` | The recorded local model benchmark, including its origin and environment |

Each `headline` card carries a raw `value`, a preformatted `display` string, a
`unit`, a per-card `status`, and bilingual `label` and `note` objects
(`{"en": ..., "ru": ...}`). A consumer that only renders `headline` needs no
other knowledge of the schema.

`qa-metrics-history.json`, schema `aka-gst.qa-metrics-history/1`, holds
`entries[]` with `generated_at`, `commit`, `status`, `tests`, `pass_rate`,
`coverage`, and `duration_ms` — enough for a sparkline, small enough to fetch on
every page load.

## Live evaluation numbers

CI has no GPU-backed Ollama, so live-model latency, stability, token, and cost
numbers come from
[`evaluations/benchmarks/qwen3-8b.json`](../../evaluations/benchmarks/qwen3-8b.json),
a committed record of a local run. It is reported under
`evaluation.live` with `source: "recorded-local-run"`, `recorded_at`, and the
full environment and sampling profile, so a reader can tell at a glance which
numbers a machine enforced on every push and which numbers were measured once
on a named machine. Refresh it with:

```bash
uv run local-agent-live-eval evaluations/live_model_cases.json \
  --provider ollama --model qwen3:8b --repetitions 3 \
  --output evaluations/benchmarks/qwen3-8b.json
```

then re-add the `schema`, `id`, `source`, `recorded_at`, `provider`,
`environment`, `profile`, and `notes` fields and drop the per-run `results`
array before committing. The passed-run count is derived from `runs` and
`pass_rate` when it is absent.

## Rules for consumers

- Render `headline` first; treat every other section as optional detail.
- Show `generated_at` and link `commit.run_url`. A metrics feed without a
  visible run date is indistinguishable from a hand-written claim.
- Ship a snapshot of `qa-metrics.json` with the consuming site and use the
  network copy only as a refresh. The page must render with no network access
  to GitHub.
- Never hard-code the numbers themselves. The test count changes whenever a
  test is added; that is the point of the feed.
