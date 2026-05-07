# PyTxT container image. Phase 1: single-stage; phase 6 may move to multi-stage.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTXT_API_HOST=0.0.0.0

WORKDIR /app

# System deps for caproto compilation paths and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer caching)
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir -e .

# Application code
COPY pytxt/ pytxt/

# EXPOSE is metadata only; actual binds are determined by env vars and host
# networking. Listed values represent prod ports (5064/5065 for EPICS,
# 8008 for FastAPI).
EXPOSE 8008
EXPOSE 5064/tcp 5064/udp 5065/tcp 5065/udp

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost:8008/health || exit 1

ENTRYPOINT ["python", "-m", "pytxt"]
