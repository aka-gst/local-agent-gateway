# Local Agent Gateway

Minimal loopback-only FastAPI gateway between an OpenAI-compatible client and a
local Ollama server.

```text
Open-LLM-VTuber -> http://127.0.0.1:8642/v1 -> Ollama at http://127.0.0.1:11434/v1
```

The gateway exposes a public `GET /health` endpoint. Requests to
`POST /v1/chat/completions` require a bearer token. Both streaming and
non-streaming chat-completion requests are supported.

## Windows PowerShell runbook

Run all commands in PowerShell 7 (`pwsh`). Paths below are relative to the
respective project directories; do not replace them with paths copied from
another user's machine.

### Prerequisites

- Windows 10 22H2 or newer for the current native Ollama Windows application.
- PowerShell 7, Python 3.11 or newer, Ollama, and `uv` available on `PATH`.
- An Ollama model already downloaded locally.
- A separately installed Open-LLM-VTuber checkout with its dependencies synced.
- FFmpeg and any ASR/TTS dependencies required by the selected
  Open-LLM-VTuber configuration.

Verify the commands without displaying configuration or secrets:

```powershell
pwsh --version
python --version
uv --version
ollama --version
ollama list
```

Use the exact model name reported by `ollama list` in both
`GATEWAY_ALLOWED_MODELS` and the Open-LLM-VTuber configuration.

### Prepare the gateway

From the `local-agent-gateway` project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
Copy-Item -LiteralPath .\.env.example -Destination .\.env
```

Edit the untracked `.env` locally. At minimum, set:

```dotenv
GATEWAY_BEARER_TOKEN=<generate-a-unique-token-of-at-least-16-characters>
GATEWAY_ALLOWED_MODELS=<exact-name-from-ollama-list>
```

The defaults restrict the gateway to the `ollama` backend at
`http://127.0.0.1:11434/v1`. Do not weaken the loopback binding.

### Back up and configure Open-LLM-VTuber

Run these commands from the Open-LLM-VTuber project directory. If `conf.yaml`
does not exist, create it using the version-specific procedure in the official
Open-LLM-VTuber Quick Start before continuing.

Create a timestamped local backup without displaying the file:

```powershell
if (-not (Test-Path -LiteralPath .\conf.yaml)) { throw 'conf.yaml was not found' }
$backup = ".\conf.yaml.before-local-agent-gateway.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item -LiteralPath .\conf.yaml -Destination $backup
Write-Host "Backup created: $backup"
```

Edit only the existing settings appropriate to the installed
Open-LLM-VTuber version:

- Select `openai_compatible_llm` as the LLM provider for `basic_memory_agent`.
- Set its `base_url` to `http://127.0.0.1:8642/v1`.
- Set `model` to the exact allowlisted Ollama model name.
- Set `llm_api_key` to the same value as `GATEWAY_BEARER_TOKEN`.
- Leave `organization_id` and `project_id` unset or `null` unless the installed
  Open-LLM-VTuber version explicitly requires them.

Do not replace the entire `conf.yaml` with an example from a different release:
the schema has changed between Open-LLM-VTuber versions.

To roll back, stop Open-LLM-VTuber first, select the intended backup, inspect
only its name and timestamp, and restore it:

```powershell
Get-ChildItem -File .\conf.yaml.before-local-agent-gateway.* |
    Sort-Object LastWriteTime -Descending |
    Select-Object Name, LastWriteTime
$backup = Get-ChildItem -File .\conf.yaml.before-local-agent-gateway.* |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($null -eq $backup) { throw 'No local-agent-gateway backup was found' }
Copy-Item -LiteralPath $backup.FullName -Destination .\conf.yaml -Force
```

### Window layout and startup order

Use three separate PowerShell windows so that each foreground process has its
own logs and can be stopped independently.

#### Window 1: Ollama

Ollama for Windows normally runs in the background and serves its API on port
`11434`. Check it first:

```powershell
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:11434/api/tags
```

If this fails because Ollama is not running, start the Ollama application. Use
`ollama serve` in this window only when intentionally running Ollama as a
foreground server; do not run it alongside an already active tray server.

```powershell
ollama serve
```

#### Window 2: gateway

From the `local-agent-gateway` directory:

```powershell
.\.venv\Scripts\Activate.ps1
local-agent-gateway
```

The supported bind address is fixed to `127.0.0.1:8642`.

#### Window 3: Open-LLM-VTuber

Start this only after the Ollama and gateway health checks pass. From the
Open-LLM-VTuber project directory:

```powershell
uv run run_server.py
```

The default web interface is `http://localhost:12393`. A release with a custom
`system_config.port` must use that configured port instead.

### Health checks

Run these in a fourth PowerShell prompt or in a window not occupied by a
foreground process:

```powershell
$ollama = Invoke-RestMethod -Method Get -Uri http://127.0.0.1:11434/api/tags
if ($null -eq $ollama.models) { throw 'Unexpected Ollama health response' }

$gateway = Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8642/health
if ($gateway.status -ne 'ok') { throw 'Gateway health check failed' }

$vtuber = Invoke-WebRequest -Method Get -Uri http://localhost:12393
if ($vtuber.StatusCode -ne 200) { throw 'Open-LLM-VTuber health check failed' }
```

The gateway health endpoint checks the gateway process itself; the Ollama check
must also pass before an end-to-end request can succeed.

### Smoke tests

First verify that authentication is enforced. PowerShell 7 treats the expected
HTTP error as a response when `-SkipHttpErrorCheck` is used:

```powershell
$unauthorized = Invoke-WebRequest -Method Post `
    -Uri http://127.0.0.1:8642/v1/chat/completions `
    -ContentType 'application/json' `
    -Body '{"model":"not-used-without-auth","messages":[]}' `
    -SkipHttpErrorCheck
if ($unauthorized.StatusCode -ne 401) { throw "Expected 401, got $($unauthorized.StatusCode)" }
```

For an authenticated Ollama round trip, enter the token without echoing it.
Replace only the model placeholder; do not put the token directly in the
command or shell history:

```powershell
$model = '<exact-name-from-ollama-list>'
$secureToken = Read-Host 'Gateway bearer token' -AsSecureString
$tokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $gatewayToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenPointer)
    $headers = @{ Authorization = "Bearer $gatewayToken" }
    $body = @{
        model = $model
        messages = @(@{ role = 'user'; content = 'Reply with exactly: gateway-ok' })
        stream = $false
    } | ConvertTo-Json -Depth 5
    $response = Invoke-RestMethod -Method Post `
        -Uri http://127.0.0.1:8642/v1/chat/completions `
        -Headers $headers -ContentType 'application/json' -Body $body
    if ($null -eq $response.choices) { throw 'Unexpected chat-completion response' }
} finally {
    if ($tokenPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenPointer)
    }
    Remove-Variable gatewayToken, headers -ErrorAction SilentlyContinue
}
```

Finally, send a short message through the Open-LLM-VTuber UI and confirm that a
response is produced while Window 2 records HTTP `200`. This validates the
complete Open-LLM-VTuber -> gateway -> Ollama path.

### Normal shutdown and port release

Stop services in reverse order:

1. Press `Ctrl+C` in Window 3 and wait for Open-LLM-VTuber to exit.
2. Press `Ctrl+C` in Window 2 and wait for the gateway to exit.
3. If Window 1 is running `ollama serve`, press `Ctrl+C` there. If Ollama is the
   tray application, exit it from its tray menu only when it should also stop.

Check the listeners:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 11434, 8642, 12393 `
    -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Ports `8642` and `12393` should no longer be listed. Port `11434` is expected to
remain listed when the Ollama tray application was intentionally left running.
Do not terminate an unknown process by PID; identify and close its owning
application normally.

### Troubleshooting

| Symptom | Class | Check | Fix |
| --- | --- | --- | --- |
| Ollama request cannot connect | Startup or local proxy | Run the `/api/tags` health check; confirm the proxy bypasses `localhost` and `127.0.0.1` | Start the Ollama application, or correct the local proxy bypass |
| `address already in use` on `11434` | Port conflict | Run `Get-NetTCPConnection -State Listen -LocalPort 11434` | Do not start `ollama serve` when the Ollama tray server is already active |
| Gateway fails during startup with a settings error | Configuration | Check that required `GATEWAY_` names exist in `.env` without printing their values | Correct the local `.env`; token length must be at least 16 characters and model allowlist must not be empty |
| Gateway `/health` cannot connect | Startup or port conflict | Check Window 2 and listener `8642` | Start the gateway from its project environment; close the known conflicting application normally |
| Gateway returns `401 unauthorized` | Authentication | Confirm Open-LLM-VTuber uses the same token as the gateway without logging either value | Re-enter the same token in both local configurations and restart both clients of that configuration |
| Gateway returns `400 model not allowed` | Allowlist | Compare the Open-LLM-VTuber model with `ollama list` and `GATEWAY_ALLOWED_MODELS` | Use the exact same model name, including tag and ASCII colon |
| Gateway returns `400 backend not allowed` | Allowlist | Check the client payload and `GATEWAY_ALLOWED_BACKENDS` | Use the default `ollama` backend; do not send a different `backend` value |
| Gateway returns `502 upstream unavailable` | Ollama reachability or timeout | Run the Ollama health check and inspect Window 1 | Start Ollama, bypass the proxy for loopback, or select a model that can respond within the configured timeout |
| Gateway returns `502 upstream error` | Ollama request or model | Run `ollama list`; inspect Ollama logs without copying secrets | Correct the model name or resolve the Ollama-side error |
| Open-LLM-VTuber reports `Error calling the chat endpoint` | Client configuration | Check `base_url`, model, and gateway health; inspect backend logs | Set `base_url` to `http://127.0.0.1:8642/v1`, then correct model or token as indicated |
| Open-LLM-VTuber cannot bind `12393` | Port conflict | Run `Get-NetTCPConnection -State Listen -LocalPort 12393` | Stop the other known Open-LLM-VTuber instance, or use its documented `system_config.port` setting |
| A port remains after `Ctrl+C` | Shutdown | Inspect `OwningProcess` with `Get-NetTCPConnection` | Return to the owning application and close it normally; do not kill an unidentified process |

### Token handling rules

- Generate a unique bearer token of at least 16 characters; do not reuse a
  personal, cloud-provider, or production API key.
- Store it only in the untracked gateway `.env` and the local Open-LLM-VTuber
  `conf.yaml` required by this integration.
- Never put a real token in README files, screenshots, chat messages, test
  fixtures, command arguments, shell history, issue reports, or git commits.
- Do not print `.env` or `conf.yaml` while troubleshooting. Report variable
  names, HTTP status codes, request IDs, and redacted errors instead.
- Treat `conf.yaml` backups as secrets because they contain the same token.
- If a token is exposed, replace it in both configurations, restart the gateway
  and Open-LLM-VTuber, and retire the exposed value.

## Developer test

From the `local-agent-gateway` project directory:

```powershell
uv run pytest -q
```

## Command sources

- Gateway entry point, bind address, endpoints, authentication, forwarding, and
  streaming behavior: this repository's `pyproject.toml`,
  `src/local_agent_gateway/`, and `tests/test_gateway.py`.
- Ollama Windows startup and default API address:
  <https://docs.ollama.com/windows>.
- Ollama model-list health endpoint:
  <https://docs.ollama.com/api/tags>.
- Open-LLM-VTuber prerequisites, `uv` workflow, startup command, and default UI
  port: <https://docs.llmvtuber.com/en/docs/quick-start/>.
- OpenAI-compatible provider names and configuration fields:
  <https://docs.llmvtuber.com/en/docs/user-guide/backend/llm/>.
- Open-LLM-VTuber port and connection troubleshooting:
  <https://docs.llmvtuber.com/en/docs/faq/>.
- `Test-Path`, `Copy-Item`, `Get-ChildItem`, `Get-NetTCPConnection`,
  `Invoke-RestMethod`, and `Invoke-WebRequest` are standard Microsoft PowerShell
  cmdlets. Use `Get-Help <command> -Online` for the documentation matching the
  installed PowerShell version.
