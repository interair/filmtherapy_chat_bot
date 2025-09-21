# syntax=docker/dockerfile:1.6

# Minimal Python image
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create user and workdir
RUN useradd -m -u 10001 appuser
WORKDIR /app

# Copy only requirements first for better layer caching
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy the application source
COPY src ./src

# Precompile project bytecode to speed up startup
RUN python -m compileall -q /app/src

# Create runtime dirs and set permissions
RUN mkdir -p logs data \
    && chown -R appuser:appuser /app

USER appuser

# Expose no ports (bot uses Telegram long polling outbound)
# HEALTHCHECK can be added if using webhooks

# The bot reads configuration from environment variables (.env can be passed via --env-file)
CMD ["python", "-m", "src.main"]
