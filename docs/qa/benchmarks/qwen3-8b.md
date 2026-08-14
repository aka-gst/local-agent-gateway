# qwen3:8b local evaluation benchmark

Date: 2026-08-15  
Environment: Apple Silicon M5, 24 GB unified memory, macOS  
Ollama: 0.32.12  
Model: qwen3:8b, Q4_K_M, 8.2B parameters  
Profile: 3 cases × 3 repetitions, `temperature=0`, `seed=42`,
`max_tokens=256`, `reasoning_effort=none`

## Results

| Metric | Result |
|---|---:|
| Runs | 9 |
| Pass rate | 100% |
| Mean quality score | 0.755 |
| Median latency | 3,483 ms |
| p95 latency | 14,912 ms |
| Prompt tokens | 468 |
| Completion tokens | 1,014 |
| Estimated API cost | $0.00 |
| Stability, all cases | 1.000 |

All three repetitions passed for grounded health guidance, safe token handling,
and prompt-injection canary non-disclosure.

## Findings from the first exploratory run

The first attempt produced two useful defects. A shared Ollama process caused a
transport disconnect that terminated the evaluator, and unbounded default
thinking made short cases take several minutes. Retries, partial failure
records, token limits, deterministic sampling, and disabled reasoning were
added before the recorded run.

An earlier ungrounded health prompt also caused the model to invent systemctl,
Windows Service, and unknown-port instructions. The case was corrected to
provide authoritative project context. This distinguishes grounded-answer
quality from impossible closed-book recall while still rejecting invented
instructions.

## Interpretation

The model is suitable for fast local regression evaluation on this machine.
The p95 includes model warm-up and is much higher than the median, so cold and
warm latency should be separated in a larger future benchmark. Reasoning-enabled
quality is also intentionally out of scope for this fast profile.
