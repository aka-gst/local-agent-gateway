# Live LLM evaluations

The deterministic suite is the default CI gate. The live suite is optional and
targets a real Ollama or OpenRouter model. It measures response-rule pass rate,
token similarity, repeated-output stability, median/p95 latency, token usage,
and estimated cost.

Model text is redacted from the JSON report by default. Add
`--include-responses` only for controlled local debugging; the report directory
is ignored by Git.

## Ollama

```bash
uv run local-agent-live-eval evaluations/live_model_cases.json \
  --provider ollama \
  --model '<exact-name-from-ollama-list>' \
  --repetitions 3
```

Ollama mode rejects non-loopback URLs.

## OpenRouter

Set `OPENROUTER_API_KEY` in the local environment without putting it in shell
history, then run:

```bash
uv run local-agent-live-eval evaluations/live_model_cases.json \
  --provider openrouter \
  --model '<provider/model>' \
  --input-cost-per-million 0 \
  --output-cost-per-million 0 \
  --repetitions 3
```

Supply the current per-million-token rates for the selected model if estimated
cost is needed. The runner never guesses changing provider prices.

## Quality gates

- `--minimum-pass-rate` defaults to `0.8`;
- `--minimum-stability` defaults to `0.3`;
- `--maximum-p95-ms` defaults to `120000`;
- `--maximum-cost-usd` defaults to `1.0`.

The command exits non-zero when any gate fails. The canary case also fails if a
model repeats the synthetic secret after a prompt-injection request.
