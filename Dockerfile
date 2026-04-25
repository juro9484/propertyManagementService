# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js tailwind.config.js postcss.config.js ./
COPY src/ src/
COPY public/ public/
RUN npm run build

# ── Stage 2: Python API server ────────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# System deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Server code
COPY server/ ./server/
COPY pipeline.py ./

# Built frontend from stage 1
COPY --from=frontend /app/dist ./dist/

# Data directory (mounted as volume in production)
RUN mkdir -p /app/data

ENV PYTHONUNBUFFERED=1
WORKDIR /app/server

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
