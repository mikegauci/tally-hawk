# TallyHawk API. Build: docker build -t tallyhawk .
# Run:  docker run -p 8000:8000 --env-file .env tallyhawk
# Migrations (run once per deploy, e.g. as Railway's pre-deploy command): tallyhawk db migrate
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY supabase ./supabase
RUN uv sync --locked --no-dev

RUN useradd --create-home app && mkdir storage && chown app storage
USER app

ENV PATH="/app/.venv/bin:$PATH" PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn tallyhawk.api:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
