# syntax=docker/dockerfile:1.6

# Use Python 3.12 for better performance
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH="/app" \
    PYTHONSTARTUP="" \
    PYTHONIOENCODING=utf-8

# Create user and workdir in one layer
RUN useradd -m -u 10001 appuser && mkdir -p /app
WORKDIR /app

# Install dependencies with optimizations
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --prefer-binary -r requirements.txt \
    && python -m compileall -q -o 2 /usr/local/lib/python3.12/site-packages \
    && find /usr/local/lib/python3.12/site-packages -name "tests" -type d -exec rm -rf {} + 2>/dev/null || true \
    && find /usr/local/lib/python3.12/site-packages -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Copy source and early logging helper
COPY src ./src
COPY sitecustomize.py ./

# Compile everything and set permissions in one layer
RUN python -m compileall -q -o 2 /app/src /app/sitecustomize.py \
    && mkdir -p logs data \
    && chown -R appuser:appuser /app

USER appuser

# Use exec form and optimize startup
CMD ["python", "-O", "-m", "src.main"]
