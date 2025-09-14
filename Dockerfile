# syntax=docker/dockerfile:1.6

# Minimal Python image
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/home/appuser/.local/bin:$PATH"

# System deps for building wheels if needed
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        bash \
    && rm -rf /var/lib/apt/lists/*

# Create user and workdir
RUN useradd -m -u 10001 appuser
WORKDIR /app

# Copy only requirements first for better layer caching
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy the rest of the project
COPY src ./src
COPY README.md ./
COPY run.sh ./
# Create runtime dirs and set permissions
RUN chmod +x run.sh \
    && mkdir -p logs data \
    && chown -R appuser:appuser /app

USER appuser

# Expose no ports (bot uses Telegram long polling outbound)
# HEALTHCHECK can be added if using webhooks

# The bot reads configuration from environment variables (.env can be passed via --env-file)
CMD ["./run.sh"]
