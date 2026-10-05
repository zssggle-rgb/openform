FROM node:24.21.0-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6 AS web
WORKDIR /build
COPY apps/web/package*.json apps/web/
RUN cd apps/web && npm ci
COPY assets/brand/svg assets/brand/svg
COPY apps/web apps/web
RUN cd apps/web && npm run build

FROM python:3.13-slim@sha256:3dd7cc108ec1493442514f5c2a871af6af0ec31d768ff6e378a93340c3b3db5f
ARG UV_TOOL_INDEX_URL=https://pypi.org/simple
COPY deploy/uv-tool.requirements /tmp/uv-tool.requirements
RUN pip install --no-cache-dir --index-url "$UV_TOOL_INDEX_URL" --require-hashes -r /tmp/uv-tool.requirements
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY contracts/pyproject.toml contracts/pyproject.toml
COPY contracts/src contracts/src
COPY services services
RUN uv sync --frozen --all-packages --no-dev --no-editable
COPY --from=web /build/apps/web/dist /app/web
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --uid 10001 --create-home openform
USER openform
EXPOSE 8000
CMD ["uvicorn", "openform.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
