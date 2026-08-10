FROM ghcr.io/astral-sh/uv:0.7.19-python3.12-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy dependency metadata first so dependency installation stays cached when
# only application source changes. The client manifest is required because it
# is a member of the uv workspace, but client dependencies are not installed.
COPY pyproject.toml uv.lock ./
COPY client/pyproject.toml client/pyproject.toml
COPY cloud/pyproject.toml cloud/pyproject.toml
COPY shared/pyproject.toml shared/pyproject.toml

RUN uv sync --frozen --no-dev --package dcs-copilot-cloud --no-install-workspace

COPY cloud/dcs_copilot_cloud cloud/dcs_copilot_cloud
COPY shared/dcs_copilot_protocol shared/dcs_copilot_protocol

RUN uv sync --frozen --no-dev --package dcs-copilot-cloud \
    && groupadd --system dcs-copilot \
    && useradd --system --create-home --gid dcs-copilot dcs-copilot

USER dcs-copilot
WORKDIR /app/cloud

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD python -c "import json, urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)); raise SystemExit(0 if data.get('status') == 'ok' and data.get('ai_inference') is True else 1)"

CMD ["dcs-copilot-cloud"]
