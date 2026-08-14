# Requirements traceability matrix

| ID | Requirement | Automated evidence |
|---|---|---|
| SEC-01 | All chat requests require a valid bearer token | `test_invalid_bearer_is_rejected_without_sensitive_output`, browser negative test |
| SEC-02 | Only allowlisted backends and models may be proxied | disallowed backend/model API tests |
| SEC-03 | Upstream must remain on loopback | `test_upstream_must_be_loopback` |
| SEC-04 | Failures must not reveal sensitive values | connection, timeout, HTTP, invalid-JSON, and log-safety tests |
| API-01 | Health is public and traceable | `test_health_is_public_and_has_request_id` |
| API-02 | Invalid content and oversized requests are rejected | parameterized payload tests and middleware boundary test |
| API-03 | Valid JSON requests preserve the OpenAI-compatible contract | `test_allowed_request_is_forwarded_without_client_auth_or_backend` |
| STR-01 | SSE streaming is forwarded and closed | mock streaming contract test |
| STR-02 | Streaming works across real HTTP processes | `test_streaming_round_trip_over_real_http` |
| OBS-01 | Safe request IDs are preserved; unsafe values are replaced | forwarding and unsafe-ID tests |
| UI-01 | User can submit a valid request in Chromium | `test_demo_success` |
| UI-02 | UI explains an authentication failure | `test_demo_rejects_invalid_token` |
| EVAL-01 | Required concepts and forbidden disclosures are scored | evaluator unit tests and golden dataset |
| EVAL-02 | Reports are available as JSON and Markdown | evaluator CLI test |
| OPS-01 | CLI binds only to fixed loopback host and port | `test_cli_binds_only_to_loopback` |
| OPS-02 | CI blocks coverage below 90% and publishes Allure | `.github/workflows/quality.yml` |
