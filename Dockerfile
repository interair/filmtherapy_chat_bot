# Stage 1: Build
FROM python:3.14-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc python3-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir --prefer-binary -r requirements.txt

# Stage 2: Final
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    PYTHONPATH="/app" \
    APP_PROFILE_STARTUP=0

WORKDIR /app
RUN useradd -m -u 10001 appuser && mkdir -p logs data && chown -R appuser:appuser /app

# Copy installed packages from builder
COPY --from=builder /root/.local /home/appuser/.local
ENV PATH=/home/appuser/.local/bin:$PATH

COPY src ./src
COPY sitecustomize.py .

# Pre-compile for faster startup
RUN python -m compileall -q /app/src

USER appuser
EXPOSE 8080

CMD ["python", "-m", "src.main"]
