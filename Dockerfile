FROM node:22-alpine AS web-build
WORKDIR /build/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt
COPY planning_agent/ ./planning_agent/
COPY scripts/ ./scripts/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY --from=web-build /build/web/dist ./web/dist
RUN mkdir -p /app/data /app/documents /app/outputs && useradd --create-home --uid 10001 planner && chown -R planner:planner /app
USER planner
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD curl -fsS http://127.0.0.1:8000/health/live || exit 1
CMD ["uvicorn", "planning_agent.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--proxy-headers", "--no-server-header"]
