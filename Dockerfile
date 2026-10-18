# DealScour: one image serving the API and the built web app (ADR-017).
# Build:  docker compose up --build      (see deploy/README.md)

FROM node:22-alpine AS web
WORKDIR /web
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

FROM python:3.11-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/app ./app
COPY backend/migrations ./migrations
COPY backend/alembic.ini ./alembic.ini
COPY backend/scripts ./scripts
RUN pip install .
COPY --from=web /web/dist ./static
RUN useradd --create-home --uid 10001 dealscour && mkdir -p /data && chown dealscour /data
USER dealscour
ENV DEALSCOUR_DB_PATH=/data/dealscour.db DEALSCOUR_STATIC_DIR=/app/static
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
