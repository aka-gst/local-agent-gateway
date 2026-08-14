FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.12-slim
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8642
CMD [".venv/bin/uvicorn", "local_agent_gateway.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8642", "--no-access-log"]
